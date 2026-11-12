"""Unit, contract, and in-process integration tests for Chapter C03."""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.api_gateway.app import create_app as create_gateway_app
from services.auth_service.app import create_app as create_auth_app
from services.common.config import load_service_config
from services.common.telemetry import build_structured_log
from services.ledger_service.app import LedgerStore, create_app as create_ledger_app
from services.notification_service.app import (
    NotificationEventPayload,
    NotificationProcessor,
    create_app as create_notification_app,
)
from services.transaction_service.app import create_app as create_transaction_app
from traffic.generator import (
    build_deterministic_schedule,
    run_traffic_profile,
    validate_target_url,
)

CONTRACTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)


def _load_validator(schema_filename: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / schema_filename).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


class MultiServiceRouter(httpx.AsyncBaseTransport):
    """Routes in-process HTTP calls between the 5 FastAPI ASGI apps by hostname."""

    def __init__(self, apps_by_host: dict[str, Any]) -> None:
        self.transports = {
            host: httpx.ASGITransport(app=app) for host, app in apps_by_host.items()
        }

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        transport = self.transports.get(host)
        if transport is None:
            raise httpx.ConnectError(f"Host '{host}' is unreachable")
        return await transport.handle_async_request(request)


@pytest.fixture()
def lab_harness(tmp_path: pathlib.Path) -> dict[str, Any]:
    """Assemble all 5 FastAPI microservices wired via in-process ASGI transport + SQLite."""
    db_file = tmp_path / "test_ledger.sqlite3"
    db_url = f"sqlite:///{db_file}"

    auth_cfg = load_service_config("auth-service", "auth", [])
    ledger_cfg = load_service_config("ledger-service", "ledger", [])
    ledger_store = LedgerStore(db_url)

    notif_cfg = load_service_config("notification-service", "notification_worker", [])
    # Disable background RabbitMQ thread in unit harness; route queue events directly
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

    published_events: list[dict[str, Any]] = []

    def publish_event_to_notif(event_payload: dict[str, Any]) -> None:
        published_events.append(event_payload)
        notif_proc.process_event(NotificationEventPayload(**event_payload))

    auth_app = create_auth_app(auth_cfg)
    ledger_app = create_ledger_app(ledger_cfg, store=ledger_store)
    notif_app = create_notification_app(notif_cfg, processor=notif_proc)
    tx_app = create_transaction_app(tx_cfg, event_publisher=publish_event_to_notif)
    gw_app = create_gateway_app(gw_cfg)

    router = MultiServiceRouter(
        {
            "api-gateway": gw_app,
            "127.0.0.1": gw_app,
            "localhost": gw_app,
            "auth-service": auth_app,
            "transaction-service": tx_app,
            "ledger-service": ledger_app,
            "notification-service": notif_app,
        }
    )
    shared_client = httpx.AsyncClient(transport=router)
    tx_app.state.http_client = shared_client
    gw_app.state.http_client = shared_client

    return {
        "client": shared_client,
        "db_url": db_url,
        "ledger_store": ledger_store,
        "notif_processor": notif_proc,
        "published_events": published_events,
        "apps": {
            "api-gateway": gw_app,
            "auth-service": auth_app,
            "transaction-service": tx_app,
            "ledger-service": ledger_app,
            "notification-service": notif_app,
        },
    }


def test_c02_contracts_compliance_for_all_five_services(
    lab_harness: dict[str, Any],
) -> None:
    """Verify catalog, RED metrics, structured logs, and dependency edges against C02 schemas."""
    catalog_validator = _load_validator("service-catalog.v1.schema.json")
    metric_validator = _load_validator("telemetry-metric.v1.schema.json")
    log_validator = _load_validator("telemetry-log.v1.schema.json")
    edge_validator = _load_validator("dependency-edge.v1.schema.json")

    client: httpx.AsyncClient = lab_harness["client"]

    async def _run() -> None:
        topo_resp = await client.get("http://api-gateway:8000/api/v1/topology")
        assert topo_resp.status_code == 200
        topo = topo_resp.json()
        assert len(topo["services"]) == 5
        for cat in topo["services"]:
            catalog_validator.validate(cat)
        for edge in topo["dependency_edges"]:
            edge_validator.validate(edge)

        for host in [
            "api-gateway",
            "auth-service",
            "transaction-service",
            "ledger-service",
            "notification-service",
        ]:
            r_live = await client.get(f"http://{host}:8000/health/live")
            assert r_live.status_code == 200
            r_ready = await client.get(f"http://{host}:8000/health/ready")
            assert r_ready.status_code == 200
            r_met = await client.get(f"http://{host}:8000/metrics?format=json")
            assert r_met.status_code == 200
            metrics_list = r_met.json()
            assert len(metrics_list) == 3
            for m in metrics_list:
                metric_validator.validate(m)

    asyncio.run(_run())

    for app in lab_harness["apps"].values():
        cfg = app.state.config
        log_entry = build_structured_log(
            config=cfg,
            severity="INFO",
            event_type="service.startup.verified",
            message="Verified structured log contract compliance for C03",
            correlation_id="corr-contract-test-001",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
        log_validator.validate(log_entry)


def test_end_to_end_sync_and_async_transaction_flow(
    lab_harness: dict[str, Any],
) -> None:
    """Verify Gateway -> Auth -> Transaction -> Ledger -> DB and Transaction -> Queue -> Notification."""
    client: httpx.AsyncClient = lab_harness["client"]
    trace_id = "abcdef0123456789abcdef0123456789"
    traceparent = f"00-{trace_id}-1122334455667788-01"
    corr_id = "corr-e2e-test-0001"

    async def _run() -> None:
        resp = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={
                "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
                "X-Correlation-ID": corr_id,
                "traceparent": traceparent,
            },
            json={
                "idempotency_key": "idem-e2e-0001",
                "account_id": "SYNTH-ACC-001",
                "counterparty_id": "SYNTH-ACC-002",
                "amount": 150000.0,
                "currency": "IDR",
                "channel": "mobile-sim",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["idempotent_replay"] is False
        assert data["correlation_id"] == corr_id
        assert data["trace_id"] == trace_id
        assert data["status"] == "COMMITTED"
        tx_id = data["transaction_id"]

        # Verify read via Gateway (includes Ledger record + async Notification record)
        get_resp = await client.get(
            f"http://api-gateway:8000/api/v1/transactions/{tx_id}",
            headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
        )
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["transaction_id"] == tx_id
        assert fetched["amount"] == 150000.0
        assert fetched["notification"] is not None
        assert fetched["notification"]["delivery_status"] == "DELIVERED_ACKED"
        assert fetched["notification"]["correlation_id"] == corr_id
        assert fetched["notification"]["trace_id"] == trace_id

    asyncio.run(_run())


def test_idempotency_and_duplicate_prevention(lab_harness: dict[str, Any]) -> None:
    """Verify duplicate idempotency_key returns existing record and conflicting payload returns 409."""
    client: httpx.AsyncClient = lab_harness["client"]
    notif_proc: NotificationProcessor = lab_harness["notif_processor"]

    async def _run() -> None:
        payload = {
            "idempotency_key": "idem-dup-check-001",
            "account_id": "SYNTH-ACC-001",
            "counterparty_id": "SYNTH-ACC-003",
            "amount": 250.0,
            "currency": "USD",
            "channel": "web-sim",
        }
        r1 = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json=payload,
        )
        assert r1.status_code == 201
        tx_id = r1.json()["transaction_id"]

        # Replay identical request -> 200 OK with idempotent_replay=True
        r2 = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json=payload,
        )
        assert r2.status_code == 200
        assert r2.json()["idempotent_replay"] is True
        assert r2.json()["transaction_id"] == tx_id
        assert notif_proc.processed_count == 1

        # Replay same idempotency_key with different amount -> 409 Conflict
        conflicting = {**payload, "amount": 999.0}
        r3 = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json=conflicting,
        )
        assert r3.status_code == 409
        assert r3.json()["error_code"] == "ERR_IDEMPOTENCY_KEY_CONFLICT"

        # Verify Ledger only has 1 row
        ledger_list = await client.get("http://ledger-service:8000/internal/ledger/entries")
        assert ledger_list.status_code == 200
        assert ledger_list.json()["total_count"] == 1

    asyncio.run(_run())


def test_notification_bounded_retries_and_idempotency(
    lab_harness: dict[str, Any],
) -> None:
    """Verify bounded retries (retry on transient failure, DLQ after max retries) and deduplication."""
    notif_proc: NotificationProcessor = lab_harness["notif_processor"]

    # 1. Transient failure that succeeds on retry #2
    evt_transient = NotificationEventPayload(
        event_id="evt-retry-once-001",
        transaction_id="tx-retry-once-001",
        idempotency_key="idem-retry-once-001",
        account_id="SYNTH-ACC-001",
        counterparty_id="SYNTH-ACC-002",
        amount=50000.0,
        currency="IDR",
        channel="fail-once-sim",
        correlation_id="corr-retry-once-001",
        trace_id="11112222333344445555666677778888",
    )
    out1 = notif_proc.process_event(evt_transient)
    assert out1["status"] == "RETRY_SCHEDULED"
    assert out1["acknowledged"] is False

    out2 = notif_proc.process_event(evt_transient)
    assert out2["status"] == "DELIVERED_ACKED"
    assert out2["acknowledged"] is True

    # Duplicate delivery after success -> DUPLICATE_IGNORED
    out3 = notif_proc.process_event(evt_transient)
    assert out3["status"] == "DUPLICATE_IGNORED"
    assert out3["idempotent_replay"] is True

    # 2. Persistent failure exceeding MAX_RETRIES=3 -> moves to DLQ
    evt_dlq = NotificationEventPayload(
        event_id="evt-dlq-001",
        transaction_id="tx-dlq-001",
        idempotency_key="idem-dlq-001",
        account_id="SYNTH-ACC-001",
        counterparty_id="SYNTH-ACC-002",
        amount=75000.0,
        currency="IDR",
        channel="fail-dlq-sim",
        correlation_id="corr-dlq-001",
        trace_id="88887777666655554444333322221111",
    )
    for attempt in range(1, 4):
        res = notif_proc.process_event(evt_dlq)
        assert res["status"] == "RETRY_SCHEDULED"
        assert res["retry_count"] == attempt

    res_final = notif_proc.process_event(evt_dlq)
    assert res_final["status"] == "DEAD_LETTERED"
    assert res_final["acknowledged"] is True
    assert notif_proc.dlq_count == 1


def test_invalid_inputs_and_auth_rejections(lab_harness: dict[str, Any]) -> None:
    """Verify 401/403 auth errors and 400/422 payload validation errors."""
    client: httpx.AsyncClient = lab_harness["client"]

    async def _run() -> None:
        valid_body = {
            "idempotency_key": "idem-auth-test-01",
            "account_id": "SYNTH-ACC-001",
            "counterparty_id": "SYNTH-ACC-002",
            "amount": 100.0,
            "currency": "SGD",
        }
        # Missing token -> 401
        r_no_tok = await client.post(
            "http://api-gateway:8000/api/v1/transactions", json=valid_body
        )
        assert r_no_tok.status_code == 401
        assert r_no_tok.json()["error_code"] == "ERR_AUTH_MISSING_TOKEN"

        # Expired token -> 401
        r_exp = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-EXPIRED-001"},
            json=valid_body,
        )
        assert r_exp.status_code == 401
        assert r_exp.json()["error_code"] == "ERR_AUTH_TOKEN_EXPIRED"

        # Read-only token attempting write -> 403
        r_scope = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
            json=valid_body,
        )
        assert r_scope.status_code == 403
        assert r_scope.json()["error_code"] == "ERR_AUTH_INSUFFICIENT_SCOPE"

        # Negative amount -> 422
        r_invalid = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json={**valid_body, "amount": -50.0},
        )
        assert r_invalid.status_code == 422
        assert r_invalid.json()["error_code"] == "ERR_INVALID_PAYLOAD"

        # Same source and counterparty account -> 400
        r_same = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json={**valid_body, "counterparty_id": "SYNTH-ACC-001"},
        )
        assert r_same.status_code == 400
        assert r_same.json()["error_code"] == "ERR_SAME_ACCOUNT_TRANSFER"

    asyncio.run(_run())


def test_dependency_failure_responses_and_persistence(
    lab_harness: dict[str, Any],
) -> None:
    """Verify explicit 503 responses when DB/Ledger fails and persistence across store re-instantiation."""
    client: httpx.AsyncClient = lab_harness["client"]
    ledger_store: LedgerStore = lab_harness["ledger_store"]

    async def _run() -> None:
        # 1. Simulate PostgreSQL/DB outage on ledger-service
        ledger_store.force_unavailable = True
        try:
            r_ready = await client.get("http://ledger-service:8000/health/ready")
            assert r_ready.status_code == 503
            assert r_ready.json()["error_code"] == "ERR_DEPENDENCY_UNAVAILABLE"

            r_tx = await client.post(
                "http://api-gateway:8000/api/v1/transactions",
                headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
                json={
                    "idempotency_key": "idem-db-down-001",
                    "account_id": "SYNTH-ACC-001",
                    "counterparty_id": "SYNTH-ACC-002",
                    "amount": 500.0,
                    "currency": "IDR",
                },
            )
            assert r_tx.status_code == 503
            assert r_tx.json()["error_code"] == "ERR_LEDGER_UPSTREAM_UNAVAILABLE"
        finally:
            ledger_store.force_unavailable = False

        # 2. Recover and persist transaction, then verify new LedgerStore instance reads persisted row
        r_ok = await client.post(
            "http://api-gateway:8000/api/v1/transactions",
            headers={"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"},
            json={
                "idempotency_key": "idem-persist-001",
                "account_id": "SYNTH-ACC-001",
                "counterparty_id": "SYNTH-ACC-002",
                "amount": 777.0,
                "currency": "USD",
            },
        )
        assert r_ok.status_code == 201
        tx_id = r_ok.json()["transaction_id"]

        restarted_store = LedgerStore(lab_harness["db_url"])
        persisted = restarted_store.get_by_transaction_id(tx_id)
        assert persisted is not None
        assert persisted["idempotency_key"] == "idem-persist-001"
        assert persisted["amount"] == 777.0

    asyncio.run(_run())


def test_deterministic_traffic_generator_and_external_target_rejection(
    lab_harness: dict[str, Any],
) -> None:
    """Verify deterministic schedule generation and RULE-009 external target rejection."""
    s1, hash1 = build_deterministic_schedule("normal", seed=20261109, count_override=5)
    s2, hash2 = build_deterministic_schedule("normal", seed=20261109, count_override=5)
    assert hash1 == hash2
    assert s1 == s2

    _, spike_hash = build_deterministic_schedule("spike", seed=20261109, count_override=5)
    assert spike_hash != hash1

    # External targets MUST be rejected
    for forbidden_url in [
        "https://example.com/api",
        "http://10.0.0.15:8080",
        "http://production-bank.internal:8000",
        "ftp://localhost:8000",
    ]:
        with pytest.raises(ValueError, match="Rejected"):
            validate_target_url(forbidden_url)

    # Execute traffic generator in-process against lab_harness
    client: httpx.AsyncClient = lab_harness["client"]
    summary = asyncio.run(
        run_traffic_profile(
            target_url="http://api-gateway:8000",
            profile="normal",
            seed=20261109,
            count_override=6,
            http_client=client,
        )
    )
    assert summary["planned_requests"] == 6
    assert summary["completed_requests"] == 6
    assert summary["success_count"] == 6
    assert summary["error_count"] == 0
    assert summary["schedule_sha256"] == build_deterministic_schedule(
        "normal", seed=20261109, count_override=6
    )[1]

