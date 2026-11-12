"""Automated unit, contract, cascade attribution, missing-source, and live Compose tests for C05."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from fault_harness.runner import emergency_stop_all, run_scenario_workflow
from fault_harness.gt_registry import RestrictedGroundTruthRegistry
from observability.alerts import verify_alert_webhook_headers
from observability.backends import (
    create_grafana_app,
    create_loki_app,
    create_otel_collector_app,
    create_prometheus_app,
    create_tempo_app,
)
from observability.client import (
    ObservabilityClient,
    scan_telemetry_for_gt_leakage,
    validate_cross_signal_correlation,
)
from services.api_gateway.app import create_app as create_gateway_app
from services.auth_service.app import create_app as create_auth_app
from services.common.config import load_service_config
from services.common.telemetry import (
    clear_telemetry_buffers,
    clear_telemetry_sinks,
    register_telemetry_sink,
    utc_now_iso,
)
from services.ledger_service.app import LedgerStore, create_app as create_ledger_app
from services.notification_service.app import (
    NotificationEventPayload,
    NotificationProcessor,
    create_app as create_notification_app,
)
from services.transaction_service.app import create_app as create_transaction_app
from tests.test_c03_services import MultiServiceRouter

CONTRACTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)

LIVE_GATEWAY_URL = os.getenv("LIVE_GATEWAY_URL", "http://127.0.0.1:18080")
LIVE_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:19090")
LIVE_LOKI_URL = os.getenv("LOKI_URL", "http://127.0.0.1:13100")
LIVE_TEMPO_URL = os.getenv("TEMPO_URL", "http://127.0.0.1:13200")
LIVE_OTEL_URL = os.getenv("OTEL_URL", "http://127.0.0.1:14318")
LIVE_GRAFANA_URL = os.getenv("GRAFANA_URL", "http://127.0.0.1:13000")


def _load_validator(schema_filename: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / schema_filename).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture()
def c05_lab_harness(tmp_path: pathlib.Path) -> Any:
    """Assemble the 5 synthetic microservices + 5 C05 observability backends in-process."""
    clear_telemetry_buffers()
    clear_telemetry_sinks()

    db_file = tmp_path / "c05_ledger.sqlite3"
    db_url = f"sqlite:///{db_file}"

    auth_cfg = load_service_config("auth-service", "auth", [])
    ledger_cfg = load_service_config("ledger-service", "ledger", ["db-dummy"])
    ledger_store = LedgerStore(db_url)

    notif_cfg = load_service_config("notification-service", "notification_worker", [])
    object.__setattr__(notif_cfg, "rabbitmq_enabled", False)
    notif_proc = NotificationProcessor(notif_cfg)

    tx_cfg = load_service_config(
        "transaction-service",
        "transaction",
        ["ledger-service", "notification-service"],
    )
    object.__setattr__(tx_cfg, "rabbitmq_enabled", False)

    gw_cfg = load_service_config(
        "api-gateway",
        "gateway",
        ["auth-service", "transaction-service"],
    )

    def publish_event_to_notif(event_payload: dict[str, Any]) -> None:
        notif_proc.process_event(NotificationEventPayload(**event_payload))

    auth_app = create_auth_app(auth_cfg)
    ledger_app = create_ledger_app(ledger_cfg, store=ledger_store)
    notif_app = create_notification_app(notif_cfg, processor=notif_proc)
    tx_app = create_transaction_app(tx_cfg, event_publisher=publish_event_to_notif)
    gw_app = create_gateway_app(gw_cfg)

    loki_app = create_loki_app()
    tempo_app = create_tempo_app()
    otel_app = create_otel_collector_app(
        loki_app_ref=loki_app,
        tempo_app_ref=tempo_app,
    )
    prom_app = create_prometheus_app(loki_app_ref=loki_app)
    grafana_app = create_grafana_app()

    def _in_process_otel_sink(signal_kind: str, record: dict[str, Any]) -> None:
        if signal_kind == "log":
            loki_app.state.ingest_records([record])
        elif signal_kind == "span":
            tempo_app.state.ingest_spans([record])

    register_telemetry_sink(_in_process_otel_sink)

    router = MultiServiceRouter(
        {
            "api-gateway": gw_app,
            "127.0.0.1": gw_app,
            "localhost": gw_app,
            "auth-service": auth_app,
            "transaction-service": tx_app,
            "ledger-service": ledger_app,
            "notification-service": notif_app,
            "loki": loki_app,
            "tempo": tempo_app,
            "otel-collector": otel_app,
            "prometheus": prom_app,
            "grafana": grafana_app,
        }
    )
    shared_client = httpx.AsyncClient(transport=router)
    tx_app.state.http_client = shared_client
    gw_app.state.http_client = shared_client
    otel_app.state.http_client = shared_client
    prom_app.state.http_client = shared_client

    obs_client = ObservabilityClient(
        gateway_url="http://api-gateway:8000",
        prometheus_url="http://prometheus:9090",
        loki_url="http://loki:3100",
        tempo_url="http://tempo:3200",
        http_client=shared_client,
    )
    registry = RestrictedGroundTruthRegistry(storage_dir=tmp_path / "restricted_gt")

    yield {
        "client": shared_client,
        "obs_client": obs_client,
        "registry": registry,
        "apps": {
            "api-gateway": gw_app,
            "auth-service": auth_app,
            "transaction-service": tx_app,
            "ledger-service": ledger_app,
            "notification-service": notif_app,
            "loki": loki_app,
            "tempo": tempo_app,
            "otel-collector": otel_app,
            "prometheus": prom_app,
            "grafana": grafana_app,
        },
    }

    clear_telemetry_sinks()


def test_c05_telemetry_correlation_and_schema_compliance(
    c05_lab_harness: dict[str, Any],
) -> None:
    """Verify logs, RED metrics, multi-hop W3C traces, and catalog/edges against C02 contracts (AT-001)."""
    log_validator = _load_validator("telemetry-log.v1.schema.json")
    metric_validator = _load_validator("telemetry-metric.v1.schema.json")
    catalog_validator = _load_validator("service-catalog.v1.schema.json")
    edge_validator = _load_validator("dependency-edge.v1.schema.json")
    trace_req_validator = _load_validator("trace-request.v1.schema.json")
    tool_res_validator = _load_validator("tool-result.v1.schema.json")

    client: httpx.AsyncClient = c05_lab_harness["client"]
    obs_client: ObservabilityClient = c05_lab_harness["obs_client"]

    trace_id = "abcdef0123456789abcdef0123456789"
    corr_id = "corr-c05-trace-0001"
    traceparent = f"00-{trace_id}-1111222233334444-01"

    async def _run() -> None:
        win_start = utc_now_iso()
        resp = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={
                "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
                "X-Correlation-ID": corr_id,
                "traceparent": traceparent,
            },
            json={
                "idempotency_key": "idem-c05-trace-0001",
                "account_id": "SYNTH-ACC-001",
                "counterparty_id": "SYNTH-ACC-002",
                "amount": 250000.0,
                "currency": "IDR",
                "channel": "mobile-sim",
            },
        )
        assert resp.status_code == 201
        win_end = utc_now_iso()

        # 1. Verify Structured Logs in Loki
        logs = await obs_client.fetch_logs(trace_id=trace_id, limit=100)
        assert len(logs) >= 6
        for lg in logs:
            log_validator.validate(lg)

        # 2. Verify RED Metrics in Prometheus (3 metrics x 5 services = 15 records)
        metrics = await obs_client.fetch_red_metrics()
        assert len(metrics) == 15
        for m in metrics:
            metric_validator.validate(m)

        # 3. Verify Distributed Trace in Tempo via tool-result.v1 wrapper
        trace_req = {
            "trace_id": trace_id,
            "service_id": "api-gateway",
            "environment": "lab",
            "start": win_start,
            "end": win_end,
        }
        trace_req_validator.validate(trace_req)
        trace_res = await obs_client.get_trace_summary(trace_req)
        tool_res_validator.validate(trace_res)
        assert trace_res["status"] == "ok"
        assert trace_res["data_quality"] == "complete"
        assert trace_res["error_code"] is None
        assert len(trace_res["records"]) == 1

        trace_record = trace_res["records"][0]
        assert trace_record["trace_id"] == trace_id
        assert trace_record["dependency_hops"] >= 4
        for expected_svc in (
            "api-gateway",
            "auth-service",
            "transaction-service",
            "ledger-service",
            "db-dummy",
            "notification-service",
        ):
            assert expected_svc in trace_record["services_traversed"]

        # 4. Validate cross-signal correlation (BRD §13.3)
        spans = trace_record["spans"]
        corr_report = validate_cross_signal_correlation(
            logs=logs,
            metrics=metrics,
            spans=spans,
            target_trace_id=trace_id,
        )
        assert corr_report["all_timestamps_utc_iso8601"] is True
        assert corr_report["meets_at001_multi_hop_trace"] is True
        assert corr_report["gt_leakage_scan"]["leakage_detected"] is False

        # 5. Validate Service Catalog (6 entries incl. db-dummy) & Observed Dependency Graph (5 edges)
        cat_snap = await obs_client.build_catalog_snapshot(
            logs=logs, metrics=metrics, spans=spans
        )
        assert len(cat_snap["services"]) == 6
        for cat in cat_snap["services"]:
            catalog_validator.validate(cat)
        assert len(cat_snap["dependency_edges"]) == 5
        for edge in cat_snap["dependency_edges"]:
            edge_validator.validate(edge)
            assert edge["source_kind"] == "trace_observed"
            assert edge["freshness_status"] == "fresh"
            assert edge["error_propagation_observed"] is False
        assert cat_snap["cascade_analysis"]["cascade_detected"] is False

    asyncio.run(_run())


def test_c05_alert_evaluation_and_zero_false_positives_on_sc01(
    c05_lab_harness: dict[str, Any],
) -> None:
    """Verify 0 critical false-positive alerts on SC-01 and signed alert-event.v1 on SC-02."""
    alert_validator = _load_validator("alert-event.v1.schema.json")
    client: httpx.AsyncClient = c05_lab_harness["client"]
    obs_client: ObservabilityClient = c05_lab_harness["obs_client"]
    registry: RestrictedGroundTruthRegistry = c05_lab_harness["registry"]

    async def _run() -> None:
        # 1. Run SC-01 normal baseline and verify 0 alerts
        await obs_client.reset_telemetry_backends()
        for app in c05_lab_harness["apps"].values():
            if hasattr(app.state, "metrics"):
                app.state.metrics.reset_samples()

        sc01_summary = await run_scenario_workflow(
            scenario_id="SC-01",
            gateway_url="http://127.0.0.1:8000",
            duration_override_sec=5.0,
            seed_override=20261111,
            registry=registry,
            http_client=client,
        )
        assert sc01_summary["recovered_cleanly"] is True
        sc01_alerts_bundle = await obs_client.evaluate_alerts()
        assert sc01_alerts_bundle["alerts"] == [], (
            f"Expected 0 alerts on SC-01 baseline, got: {sc01_alerts_bundle['alerts']}"
        )

        # 2. Inject SC-02 (http_5xx on transaction-service) and observe during active fault
        await obs_client.reset_telemetry_backends()
        for app in c05_lab_harness["apps"].values():
            if hasattr(app.state, "metrics"):
                app.state.metrics.reset_samples()

        from services.common.fault_control import build_harness_headers

        inject_payload = {
            "fault_id": "flt-c05-sc02",
            "target_service": "transaction-service",
            "fault_mode": "http_5xx",
            "duration_sec": 20.0,
            "delay_ms": 0,
            "error_rate": 1.0,
            "pool_limit": 1,
            "seed": 20261111,
        }
        raw_inject = json.dumps(inject_payload).encode("utf-8")
        r_inj = await client.post(
            "http://api-gateway:8000/_sim/fault/inject",
            content=raw_inject,
            headers=build_harness_headers("SYNTH-HARNESS-CTRL-KEY-C04", raw_inject),
        )
        assert r_inj.status_code == 200

        try:
            for idx in range(3):
                r_probe = await client.post(
                    "http://api-gateway:8000/api/v1/transactions",
                    headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
                    json={
                        "idempotency_key": f"idem-c05-sc02-{idx}",
                        "account_id": "SYNTH-ACC-001",
                        "counterparty_id": "SYNTH-ACC-002",
                        "amount": 10000.0,
                        "currency": "IDR",
                    },
                )
                assert r_probe.status_code >= 500

            sc02_alerts_bundle = await obs_client.evaluate_alerts()
            alerts = sc02_alerts_bundle["alerts"]
            assert len(alerts) >= 1
            for alert in alerts:
                alert_validator.validate(alert)

            tx_alerts = [
                a
                for a in alerts
                if a["service_id"] == "transaction-service"
                and a["alert_type"] == "high_error_rate"
            ]
            assert len(tx_alerts) == 1
            assert tx_alerts[0]["error_code"] == "ERR_TX_INTERNAL_EXCEPTION"
            assert tx_alerts[0]["trace_id"] is not None

            # Verify signed webhook headers for C10 Alert Intake
            for item in sc02_alerts_bundle["signed_deliveries"]:
                raw_bytes = json.dumps(
                    item["alert"], separators=(",", ":"), sort_keys=True
                ).encode("utf-8")
                assert verify_alert_webhook_headers(item["webhook_headers"], raw_bytes)
        finally:
            await emergency_stop_all(
                gateway_url="http://127.0.0.1:8000", http_client=client
            )

    asyncio.run(_run())


def test_c05_dependency_cascade_attribution_sc03_and_sc04(
    c05_lab_harness: dict[str, Any],
) -> None:
    """Verify observed dependency graph and cascade attribution for SC-03 (DB latency) and SC-04 (dependency down) (AT-016)."""
    edge_validator = _load_validator("dependency-edge.v1.schema.json")
    alert_validator = _load_validator("alert-event.v1.schema.json")
    client: httpx.AsyncClient = c05_lab_harness["client"]
    obs_client: ObservabilityClient = c05_lab_harness["obs_client"]

    from services.common.fault_control import build_harness_headers

    async def _run_cascade_case(
        fault_mode: str,
        delay_ms: int,
        expected_alert_type: str,
    ) -> None:
        await obs_client.reset_telemetry_backends()
        for app in c05_lab_harness["apps"].values():
            if hasattr(app.state, "metrics"):
                app.state.metrics.reset_samples()

        inject_payload = {
            "fault_id": f"flt-c05-{fault_mode}",
            "target_service": "ledger-service",
            "fault_mode": fault_mode,
            "duration_sec": 20.0,
            "delay_ms": delay_ms,
            "error_rate": 1.0,
            "pool_limit": 1,
            "seed": 20261111,
        }
        raw_inject = json.dumps(inject_payload).encode("utf-8")
        r_inj = await client.post(
            "http://api-gateway:8000/_sim/fault/inject",
            content=raw_inject,
            headers=build_harness_headers("SYNTH-HARNESS-CTRL-KEY-C04", raw_inject),
        )
        assert r_inj.status_code == 200

        try:
            for idx in range(2):
                await client.post(
                    "http://api-gateway:8000/api/v1/transactions",
                    headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
                    json={
                        "idempotency_key": f"idem-c05-{fault_mode}-{idx}",
                        "account_id": "SYNTH-ACC-001",
                        "counterparty_id": "SYNTH-ACC-002",
                        "amount": 50000.0,
                        "currency": "IDR",
                    },
                )

            snapshot = await obs_client.build_catalog_snapshot()
            for edge in snapshot["dependency_edges"]:
                edge_validator.validate(edge)

            edge_map = {e["edge_id"]: e for e in snapshot["dependency_edges"]}
            assert edge_map["edge-ledger-db"]["error_propagation_observed"] is True
            assert edge_map["edge-tx-ledger"]["error_propagation_observed"] is True
            assert edge_map["edge-gw-tx"]["error_propagation_observed"] is True
            assert edge_map["edge-gw-auth"]["error_propagation_observed"] is False

            cascade = snapshot["cascade_analysis"]
            assert cascade["cascade_detected"] is True
            assert cascade["origin_dependency_id"] == "db-dummy"
            assert cascade["primary_fault_service_id"] == "ledger-service"
            assert cascade["upstream_impacted_services"] == [
                "transaction-service",
                "api-gateway",
            ]

            alerts_bundle = await obs_client.evaluate_alerts()
            alerts = alerts_bundle["alerts"]
            assert len(alerts) >= 1
            for a in alerts:
                alert_validator.validate(a)
            assert any(
                a["service_id"] == "ledger-service"
                and a["alert_type"] == expected_alert_type
                for a in alerts
            )
        finally:
            await emergency_stop_all(
                gateway_url="http://127.0.0.1:8000", http_client=client
            )

    async def _run() -> None:
        # SC-03: DB Latency on ledger-service (350ms > 250ms SLO threshold)
        await _run_cascade_case(
            fault_mode="db_latency",
            delay_ms=350,
            expected_alert_type="high_latency_p95",
        )
        # SC-04: Dependency unavailable on ledger-service
        await _run_cascade_case(
            fault_mode="dependency_unavailable",
            delay_ms=0,
            expected_alert_type="dependency_unavailable",
        )

    asyncio.run(_run())


def test_c05_missing_trace_source_sc09_reversible_outage(
    c05_lab_harness: dict[str, Any],
) -> None:
    """Verify SC-09 missing trace backend returns SOURCE_UNAVAILABLE without fabricated spans and recovers cleanly (EV-02, AT-009)."""
    tool_res_validator = _load_validator("tool-result.v1.schema.json")
    client: httpx.AsyncClient = c05_lab_harness["client"]
    obs_client: ObservabilityClient = c05_lab_harness["obs_client"]

    async def _run() -> None:
        # 1. Generate a real trace while Tempo is healthy
        trace_id = "99998888777766665555444433332222"
        win_start = utc_now_iso()
        resp = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={
                "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
                "X-Correlation-ID": "corr-sc09-test-01",
                "traceparent": f"00-{trace_id}-1234567890abcdef-01",
            },
            json={
                "idempotency_key": "idem-c05-sc09-01",
                "account_id": "SYNTH-ACC-001",
                "counterparty_id": "SYNTH-ACC-002",
                "amount": 95000.0,
                "currency": "IDR",
            },
        )
        assert resp.status_code == 201
        win_end = utc_now_iso()

        trace_req = {
            "trace_id": trace_id,
            "service_id": "api-gateway",
            "environment": "lab",
            "start": win_start,
            "end": win_end,
        }

        # 2. Activate SC-09 Tempo outage
        outage_res = await obs_client.set_tempo_outage(
            True, reason="SC-09_trace_backend_outage"
        )
        assert outage_res["status"] == "OUTAGE_ACTIVE"

        try:
            unavailable_res = await obs_client.get_trace_summary(trace_req)
            tool_res_validator.validate(unavailable_res)
            assert unavailable_res["tool_name"] == "get_trace_summary"
            assert unavailable_res["status"] == "unavailable"
            assert unavailable_res["data_quality"] == "unavailable"
            assert unavailable_res["error_code"] == "SOURCE_UNAVAILABLE"
            assert unavailable_res["records"] == []
            assert unavailable_res["sanitized"] is True

            # Verify logs and metrics remain available while Tempo is down
            logs = await obs_client.fetch_logs(trace_id=trace_id)
            metrics = await obs_client.fetch_red_metrics()
            assert len(logs) >= 4
            assert len(metrics) == 15
        finally:
            # 3. Recover Tempo and verify trace query works again
            rec_res = await obs_client.set_tempo_outage(False, reason="operator_reset")
            assert rec_res["status"] == "RECOVERED"

        recovered_trace = await obs_client.get_trace_summary(trace_req)
        tool_res_validator.validate(recovered_trace)
        assert recovered_trace["status"] == "ok"
        assert recovered_trace["data_quality"] == "complete"
        assert recovered_trace["error_code"] is None
        assert len(recovered_trace["records"]) == 1
        assert recovered_trace["records"][0]["trace_id"] == trace_id

    asyncio.run(_run())


def test_c05_otel_collector_strips_forbidden_gt_fields_and_zero_leakage(
    c05_lab_harness: dict[str, Any],
) -> None:
    """Verify OTel Collector processor strips forbidden GT attributes and all signals pass AT-008 leakage scan."""
    client: httpx.AsyncClient = c05_lab_harness["client"]
    obs_client: ObservabilityClient = c05_lab_harness["obs_client"]

    async def _run() -> None:
        await obs_client.reset_telemetry_backends()
        # Push a log record containing forbidden ground-truth attributes to OTel Collector
        poisoned_log = {
            "schema_version": "1.0",
            "timestamp": utc_now_iso(),
            "severity": "INFO",
            "service.name": "api-gateway",
            "service_id": "api-gateway",
            "environment": "lab",
            "instance_id": "api-gateway-lab-01",
            "build_version": "0.1.0-sim",
            "event_type": "test.sanitizer.check",
            "correlation_id": "corr-sanitize-check-01",
            "trace_id": "11112222333344445555666677778888",
            "span_id": "1111222233334444",
            "trace_absent_reason": None,
            "error_code": None,
            "message": "Normal synthetic transaction log entry",
            "sanitized": True,
            "scenario_id": "SC-04",
            "ground_truth": "ledger-service",
            "expected_root_cause_services": ["ledger-service"],
            "split_id": "holdout",
        }
        r_push = await client.post(
            "http://otel-collector:4318/v1/logs",
            json={"records": [poisoned_log]},
        )
        assert r_push.status_code == 200

        stored_logs = await obs_client.fetch_logs(
            correlation_id="corr-sanitize-check-01"
        )
        assert len(stored_logs) == 1
        for forbidden_key in (
            "scenario_id",
            "ground_truth",
            "expected_root_cause_services",
            "split_id",
        ):
            assert forbidden_key not in stored_logs[0]

        scan_res = scan_telemetry_for_gt_leakage(stored_logs)
        assert scan_res["leakage_detected"] is False

    asyncio.run(_run())


def test_live_docker_compose_c05_observability_stack() -> None:
    """Verify the live 12-container Docker Compose stack, GT mount isolation, and end-to-end telemetry."""
    try:
        r_gw = httpx.get(f"{LIVE_GATEWAY_URL}/healthz", timeout=2.5)
        r_prom = httpx.get(f"{LIVE_PROMETHEUS_URL}/-/ready", timeout=2.5)
        if r_gw.status_code != 200 or r_prom.status_code != 200:
            pytest.skip("Live C05 Docker Compose observability stack is not running")
    except httpx.HTTPError:
        pytest.skip("Live C05 Docker Compose observability stack is not reachable")

    # 1. Verify container filesystem GT isolation on all 5 observability containers
    for container_name in (
        "sre-sim-otel-collector",
        "sre-sim-prometheus",
        "sre-sim-loki",
        "sre-sim-tempo",
        "sre-sim-grafana",
    ):
        proc = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-c",
                "test ! -d /app/fault_harness && test ! -d /app/restricted",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"GT isolation violated in {container_name}: /app/fault_harness or /app/restricted exists!"
        )

    # 2. Verify live OTel Collector, Prometheus, Loki, Tempo, and Grafana endpoints
    async def _run_live() -> None:
        obs_client = ObservabilityClient(
            gateway_url=LIVE_GATEWAY_URL,
            prometheus_url=LIVE_PROMETHEUS_URL,
            loki_url=LIVE_LOKI_URL,
            tempo_url=LIVE_TEMPO_URL,
        )
        trace_id = "abcdef99887766554433221100fedcba"
        corr_id = "corr-live-c05-e2e-01"
        win_start = utc_now_iso()

        async with httpx.AsyncClient(timeout=4.0) as ac:
            # Verify Grafana datasources & dashboard
            r_ds = await ac.get(f"{LIVE_GRAFANA_URL}/api/datasources")
            assert r_ds.status_code == 200
            assert len(r_ds.json()) == 3
            r_dash = await ac.get(
                f"{LIVE_GRAFANA_URL}/api/dashboards/uid/sre-sim-overview-v1"
            )
            assert r_dash.status_code == 200

            # Send live transaction through API Gateway
            r_tx = await ac.post(
                f"{LIVE_GATEWAY_URL}/api/v1/transactions",
                headers={
                    "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
                    "X-Correlation-ID": corr_id,
                    "traceparent": f"00-{trace_id}-0102030405060708-01",
                },
                json={
                    "idempotency_key": f"idem-live-c05-{ utc_now_iso() }",
                    "account_id": "SYNTH-ACC-001",
                    "counterparty_id": "SYNTH-ACC-002",
                    "amount": 175000.0,
                    "currency": "IDR",
                    "channel": "mobile-sim",
                },
            )
            assert r_tx.status_code in (200, 201)

            # Poll briefly (up to 2.5s) for background OTel shipper to flush over HTTP to otel-collector -> loki/tempo
            logs: list[dict[str, Any]] = []
            for _ in range(15):
                logs = await obs_client.fetch_logs(trace_id=trace_id)
                if len(logs) >= 4:
                    break
                await asyncio.sleep(0.15)
            win_end = utc_now_iso()

            # Check Prometheus targets (all 5 up) and RED metrics (15 records)
            r_targets = await ac.get(f"{LIVE_PROMETHEUS_URL}/api/v1/targets")
            assert r_targets.status_code == 200
            active_targets = r_targets.json()["data"]["activeTargets"]
            assert len(active_targets) == 5
            assert all(t["health"] == "up" for t in active_targets)

            metrics = await obs_client.fetch_red_metrics()
            assert len(metrics) == 15
            assert len(logs) >= 4

            trace_req = {
                "trace_id": trace_id,
                "service_id": "api-gateway",
                "environment": "lab",
                "start": win_start,
                "end": win_end,
            }
            trace_res = await obs_client.get_trace_summary(trace_req)
            assert trace_res["status"] == "ok"
            assert trace_res["records"][0]["dependency_hops"] >= 3

            # Test live SC-09 Tempo outage and recovery
            await obs_client.set_tempo_outage(True, reason="SC-09_live_check")
            try:
                unavail = await obs_client.get_trace_summary(trace_req)
                assert unavail["status"] == "unavailable"
                assert unavail["error_code"] == "SOURCE_UNAVAILABLE"
                assert unavail["records"] == []
            finally:
                await obs_client.set_tempo_outage(False, reason="SC-09_live_recover")

            rec = await obs_client.get_trace_summary(trace_req)
            assert rec["status"] == "ok"

    asyncio.run(_run_live())
