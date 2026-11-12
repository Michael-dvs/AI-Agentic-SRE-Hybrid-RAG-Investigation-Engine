"""Automated unit, security-boundary, workflow, and live Compose tests for Chapter C04."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import subprocess
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from fault_harness.gt_registry import (
    FORBIDDEN_RUNTIME_PRINCIPALS,
    GroundTruthAccessDeniedError,
    GroundTruthImmutabilityError,
    RestrictedGroundTruthRegistry,
)
from fault_harness.runner import (
    emergency_stop_all,
    run_scenario_workflow,
    scan_for_gt_leakage,
)
from fault_harness.scenarios import (
    SCENARIO_CATALOG,
    get_public_scenario_manifest,
    get_restricted_oracle,
)
from services.api_gateway.app import create_app as create_gateway_app
from services.auth_service.app import create_app as create_auth_app
from services.common.config import load_service_config
from services.common.fault_control import build_harness_headers
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
HARNESS_TOKEN = os.getenv("HARNESS_CONTROL_TOKEN", "SYNTH-HARNESS-CTRL-KEY-C04")
EVALUATOR_TOKEN = os.getenv("EVALUATOR_CONTROL_TOKEN", "SYNTH-EVALUATOR-KEY-C04")


def _load_validator(schema_filename: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / schema_filename).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture()
def c04_lab_harness(tmp_path: pathlib.Path) -> dict[str, Any]:
    """Assemble all 5 FastAPI microservices with C04 fault control wired in-process."""
    db_file = tmp_path / "c04_ledger.sqlite3"
    db_url = f"sqlite:///{db_file}"

    auth_cfg = load_service_config("auth-service", "auth", [])
    ledger_cfg = load_service_config("ledger-service", "ledger", [])
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

    gt_dir = tmp_path / "restricted_gt"
    registry = RestrictedGroundTruthRegistry(storage_dir=gt_dir)

    return {
        "client": shared_client,
        "registry": registry,
        "gt_dir": gt_dir,
        "ledger_store": ledger_store,
        "notif_processor": notif_proc,
        "apps": {
            "api-gateway": gw_app,
            "auth-service": auth_app,
            "transaction-service": tx_app,
            "ledger-service": ledger_app,
            "notification-service": notif_app,
        },
    }


def test_scenario_catalog_public_vs_restricted_separation() -> None:
    """Verify 14 scenarios exist, public manifest excludes restricted oracle fields, and principal checks work."""
    manifest = get_public_scenario_manifest()
    assert manifest["total_scenarios"] == 14
    scenario_ids = [s["scenario_id"] for s in manifest["scenarios"]]
    assert scenario_ids == [f"SC-{i:02d}" for i in range(1, 15)]
    assert manifest["c04_active_service_scenarios"] == [
        f"SC-{i:02d}" for i in range(1, 9)
    ]

    # Public manifest must not contain restricted oracle fields (split_id, expected_root_cause_services, etc.)
    serialized_public = json.dumps(manifest)
    for forbidden_field in (
        "split_id",
        "expected_root_cause_services",
        "expected_fault_types",
        "expected_relevant_chunk_ids",
        "split_freeze_hash",
    ):
        assert forbidden_field not in serialized_public

    # Operator and evaluator can read restricted oracle
    op_oracle = get_restricted_oracle("SC-04", "principal:operator-harness")
    eval_oracle = get_restricted_oracle("SC-04", "principal:offline-evaluator")
    assert op_oracle.expected_root_cause_services == ["ledger-service"]
    assert eval_oracle.expected_fault_types == ["dependency_unavailable"]
    assert op_oracle.split_id == "dev"

    # All investigator/runtime principals must be denied
    for bad_principal in FORBIDDEN_RUNTIME_PRINCIPALS:
        with pytest.raises(PermissionError, match="forbidden from accessing restricted scenario oracle"):
            get_restricted_oracle("SC-04", bad_principal)


def test_restricted_gt_registry_immutability_and_access_control(
    tmp_path: pathlib.Path,
) -> None:
    """Verify pre-onset freeze, file permissions, immutability, access denials, and post-CLOSED join (AT-008)."""
    eval_validator = _load_validator("evaluation-manifest.v1.schema.json")
    gt_dir = tmp_path / "restricted_gt"
    registry = RestrictedGroundTruthRegistry(storage_dir=gt_dir)

    # Check directory permissions (0o700) and file permissions (0o600)
    assert (gt_dir.stat().st_mode & 0o777) == 0o700
    assert (registry.records_file.stat().st_mode & 0o777) == 0o600

    # Freeze ground truth before fault onset
    frozen = registry.freeze_ground_truth(
        run_id="run-test-sc04-001",
        incident_id="inc-test-sc04-001",
        scenario_id="SC-04",
        fault_seed=20261110,
        injected_parameters=[
            {
                "fault_id": "flt-test-01",
                "target_service": "ledger-service",
                "fault_mode": "dependency_unavailable",
                "duration_sec": 15.0,
            }
        ],
        caller_principal="principal:operator-harness",
        caller_token=HARNESS_TOKEN,
    )
    assert len(frozen["record_sha256"]) == 64

    # Second freeze attempt for same run_id must fail (immutability guarantee)
    with pytest.raises(GroundTruthImmutabilityError, match="already frozen and immutable"):
        registry.freeze_ground_truth(
            run_id="run-test-sc04-001",
            incident_id="inc-test-sc04-001",
            scenario_id="SC-04",
            fault_seed=20261110,
            injected_parameters=[],
            caller_principal="principal:operator-harness",
            caller_token=HARNESS_TOKEN,
        )

    # Record lifecycle outcome
    outcome = registry.record_execution_outcome(
        run_id="run-test-sc04-001",
        fault_onset_at="2026-11-10T09:00:01Z",
        fault_end_at="2026-11-10T09:00:05Z",
        injection_outcome="INJECTED_AND_OBSERVED",
        recovery_outcome="RECOVERED_VERIFIED",
        leakage_detected=False,
        evidence_refs=["evidence/c04/run-test-sc04-001"],
        caller_principal="principal:operator-harness",
        caller_token=HARNESS_TOKEN,
    )
    assert outcome["recovery_outcome"] == "RECOVERED_VERIFIED"

    dummy_hash = hashlib.sha256(b"closed-dossier-v1").hexdigest()

    # Every runtime/investigator principal must be denied across registry methods
    for principal in sorted(FORBIDDEN_RUNTIME_PRINCIPALS):
        with pytest.raises(GroundTruthAccessDeniedError) as exc_info:
            registry.read_for_offline_evaluation(
                run_id="run-test-sc04-001",
                caller_principal=principal,
                caller_token=EVALUATOR_TOKEN,
                investigation_status="CLOSED",
                closed_dossier_version=1,
                closed_dossier_hash=dummy_hash,
            )
        assert exc_info.value.error_code == "ERR_FORBIDDEN_PRINCIPAL"

    # Offline evaluator must be denied if investigation_status != CLOSED
    with pytest.raises(GroundTruthAccessDeniedError) as exc_info:
        registry.read_for_offline_evaluation(
            run_id="run-test-sc04-001",
            caller_principal="principal:offline-evaluator",
            caller_token=EVALUATOR_TOKEN,
            investigation_status="HUMAN_REVIEW",
            closed_dossier_version=1,
            closed_dossier_hash=dummy_hash,
        )
    assert exc_info.value.error_code == "ERR_INVESTIGATION_NOT_CLOSED"

    # Offline evaluator succeeds once investigation_status == CLOSED and validates against C02 schema
    joined = registry.read_for_offline_evaluation(
        run_id="run-test-sc04-001",
        caller_principal="principal:offline-evaluator",
        caller_token=EVALUATOR_TOKEN,
        investigation_status="CLOSED",
        closed_dossier_version=1,
        closed_dossier_hash=dummy_hash,
    )
    eval_manifest = joined["evaluation_manifest"]
    eval_validator.validate(eval_manifest)
    assert eval_manifest["expected_root_cause_services"] == ["ledger-service"]
    assert eval_manifest["required_terminal_state"] == "CLOSED"

    # Verify audit log recorded all denials and approvals
    audit_events = registry.list_audit_events()
    deny_events = [e for e in audit_events if e["decision"] == "DENY"]
    assert len(deny_events) == len(FORBIDDEN_RUNTIME_PRINCIPALS) + 2


def test_fault_control_endpoint_security_and_limits(
    c04_lab_harness: dict[str, Any],
) -> None:
    """Verify principal enforcement, HMAC check, forbidden GT fields, duration/concurrency caps, and TTL expiry."""
    client: httpx.AsyncClient = c04_lab_harness["client"]

    async def _run() -> None:
        valid_payload = {
            "fault_id": "flt-sec-01",
            "target_service": "transaction-service",
            "fault_mode": "http_5xx",
            "duration_sec": 15.0,
            "delay_ms": 0,
            "error_rate": 1.0,
            "pool_limit": 1,
            "seed": 20261110,
        }
        body_bytes = json.dumps(valid_payload).encode("utf-8")

        # 1. Unauthenticated / missing headers -> 403
        r_unauth = await client.post(
            "http://api-gateway/_sim/fault/inject", content=body_bytes
        )
        assert r_unauth.status_code == 403
        assert r_unauth.json()["error_code"] == "ERR_FAULT_CONTROL_FORBIDDEN"

        # 2. All 5 forbidden runtime principals -> 403
        for principal in sorted(FORBIDDEN_RUNTIME_PRINCIPALS):
            headers = build_harness_headers(HARNESS_TOKEN, body_bytes, principal_id=principal)
            r_forbid = await client.post(
                "http://api-gateway/_sim/fault/inject",
                content=body_bytes,
                headers=headers,
            )
            assert r_forbid.status_code == 403
            assert r_forbid.json()["error_code"] == "ERR_FAULT_CONTROL_FORBIDDEN"

        # 3. Invalid HMAC signature -> 403
        bad_sig_headers = build_harness_headers(HARNESS_TOKEN, body_bytes)
        bad_sig_headers["X-Harness-Signature"] = "0" * 64
        r_badsig = await client.post(
            "http://api-gateway/_sim/fault/inject",
            content=body_bytes,
            headers=bad_sig_headers,
        )
        assert r_badsig.status_code == 403

        # 4. Payload containing forbidden ground-truth fields -> 422 ERR_FORBIDDEN_GROUND_TRUTH_FIELD
        for gt_key in ("scenario_id", "ground_truth", "expected_root_cause", "split_id"):
            bad_payload = dict(valid_payload)
            bad_payload[gt_key] = "SC-02"
            bad_bytes = json.dumps(bad_payload).encode("utf-8")
            r_gt = await client.post(
                "http://api-gateway/_sim/fault/inject",
                content=bad_bytes,
                headers=build_harness_headers(HARNESS_TOKEN, bad_bytes),
            )
            assert r_gt.status_code == 422
            assert r_gt.json()["error_code"] == "ERR_FORBIDDEN_GROUND_TRUTH_FIELD"

        # 5. Unallowlisted target service -> 400 ERR_INVALID_FAULT_TARGET
        bad_target_payload = dict(valid_payload, target_service="external-payment-service")
        bt_bytes = json.dumps(bad_target_payload).encode("utf-8")
        r_bt = await client.post(
            "http://api-gateway/_sim/fault/inject",
            content=bt_bytes,
            headers=build_harness_headers(HARNESS_TOKEN, bt_bytes),
        )
        assert r_bt.status_code == 400
        assert r_bt.json()["error_code"] == "ERR_INVALID_FAULT_TARGET"

        # 6. Duration > 120s -> 422 validation error
        long_payload = dict(valid_payload, duration_sec=300.0)
        long_bytes = json.dumps(long_payload).encode("utf-8")
        r_long = await client.post(
            "http://api-gateway/_sim/fault/inject",
            content=long_bytes,
            headers=build_harness_headers(HARNESS_TOKEN, long_bytes),
        )
        assert r_long.status_code == 422

        # 7. Concurrency cap (max 2 active faults per service; 3rd must fail with 429)
        for idx in (1, 2):
            p = dict(valid_payload, fault_id=f"flt-conc-{idx}")
            b = json.dumps(p).encode("utf-8")
            r_ok = await client.post(
                "http://api-gateway/_sim/fault/inject",
                content=b,
                headers=build_harness_headers(HARNESS_TOKEN, b),
            )
            assert r_ok.status_code == 200

        p3 = dict(valid_payload, fault_id="flt-conc-3")
        b3 = json.dumps(p3).encode("utf-8")
        r_conc = await client.post(
            "http://api-gateway/_sim/fault/inject",
            content=b3,
            headers=build_harness_headers(HARNESS_TOKEN, b3),
        )
        assert r_conc.status_code == 429
        assert r_conc.json()["error_code"] == "ERR_FAULT_CONCURRENCY_LIMIT"

        # Reset cleanup
        stop_res = await emergency_stop_all(
            gateway_url="http://127.0.0.1:8000", http_client=client
        )
        assert stop_res["recovered_cleanly"] is True

        # 8. Automatic TTL expiration check (1.0s fault on api-gateway expires automatically)
        ttl_payload = dict(
            valid_payload,
            fault_id="flt-ttl-1",
            target_service="api-gateway",
            duration_sec=1.0,
        )
        ttl_bytes = json.dumps(ttl_payload).encode("utf-8")
        r_ttl = await client.post(
            "http://api-gateway/_sim/fault/inject",
            content=ttl_bytes,
            headers=build_harness_headers(HARNESS_TOKEN, ttl_bytes),
        )
        assert r_ttl.status_code == 200
        await asyncio.sleep(1.15)
        status_resp = await client.get(
            "http://api-gateway/_sim/fault/status",
            headers=build_harness_headers(HARNESS_TOKEN, b""),
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["active_fault_count"] == 0

    asyncio.run(_run())


def test_external_target_url_rejected_by_runner(
    c04_lab_harness: dict[str, Any],
) -> None:
    """Verify RULE-009 blocks non-localhost target URLs in fault runner."""
    with pytest.raises(ValueError, match="Rejected external target host"):
        asyncio.run(
            run_scenario_workflow(
                scenario_id="SC-01",
                gateway_url="https://api.production-bank.example.com",
                registry=c04_lab_harness["registry"],
                http_client=c04_lab_harness["client"],
            )
        )


def test_all_eight_core_scenarios_and_recipe_hooks_in_process(
    c04_lab_harness: dict[str, Any],
) -> None:
    """Execute SC-01 through SC-08 plus recipe hooks SC-09, SC-11, SC-14 through the 8-step workflow."""
    client: httpx.AsyncClient = c04_lab_harness["client"]
    registry: RestrictedGroundTruthRegistry = c04_lab_harness["registry"]

    async def _run() -> None:
        for idx, scenario_id in enumerate(
            [
                "SC-01",
                "SC-02",
                "SC-03",
                "SC-04",
                "SC-05",
                "SC-06",
                "SC-07",
                "SC-08",
                "SC-09",
                "SC-11",
                "SC-14",
            ],
            start=1,
        ):
            summary = await run_scenario_workflow(
                scenario_id=scenario_id,
                gateway_url="http://127.0.0.1:8000",
                duration_override_sec=6.0,
                seed_override=20261110 + idx,
                registry=registry,
                http_client=client,
            )
            assert summary["recovered_cleanly"] is True, (
                f"Scenario {scenario_id} failed recovery: {json.dumps(summary, indent=2)}"
            )
            assert summary["leakage_scan"]["leakage_detected"] is False
            assert summary["workflow_steps_completed"] == [
                "validate",
                "baseline_check",
                "inject",
                "observe",
                "stop",
                "recover",
                "verify",
                "record",
            ]

            # Assert specific expected symptoms during observation window
            probes = summary["observed_probes"]
            if scenario_id == "SC-01":
                assert all(p["status_code"] in (200, 201) for p in probes)
            elif scenario_id in ("SC-02", "SC-04", "SC-05"):
                assert all(p["status_code"] >= 500 for p in probes)
            elif scenario_id == "SC-03":
                assert all(p["latency_ms"] >= 50.0 for p in probes)
            elif scenario_id in ("SC-06", "SC-08"):
                assert all(p["status_code"] == 403 for p in probes)
            elif scenario_id == "SC-07":
                assert summary["observed_notification_queue"]["consumer_lag_active"] is True
                assert summary["observed_notification_queue"]["backlog_depth"] >= 2

    asyncio.run(_run())


def test_live_docker_compose_c04_isolation_and_fault_recovery(
    tmp_path: pathlib.Path,
) -> None:
    """Verify container filesystem GT isolation and live C04 fault injection + recovery on Docker Compose."""
    try:
        resp = httpx.get(f"{LIVE_GATEWAY_URL}/healthz", timeout=3.0)
        if resp.status_code != 200:
            pytest.skip("Live Docker Compose stack is not healthy on LIVE_GATEWAY_URL")
    except httpx.HTTPError:
        pytest.skip("Live Docker Compose stack is not reachable on LIVE_GATEWAY_URL")

    # 1. Verify container filesystem isolation: neither /app/fault_harness nor /app/restricted exists in containers
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "sre-sim-api-gateway",
            "sh",
            "-c",
            "test ! -d /app/fault_harness && test ! -d /app/restricted",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        "Container filesystem isolation violated: /app/fault_harness or /app/restricted found in container!"
    )

    # 2. Run SC-02 (HTTP 5xx), SC-04 (Dependency Cascade), and SC-07 (Queue Consumer Lag) against live Compose
    registry = RestrictedGroundTruthRegistry(storage_dir=tmp_path / "live_gt")

    async def _run_live() -> None:
        for sc_id in ("SC-02", "SC-04", "SC-07"):
            summary = await run_scenario_workflow(
                scenario_id=sc_id,
                gateway_url=LIVE_GATEWAY_URL,
                duration_override_sec=6.0,
                seed_override=20261110,
                registry=registry,
            )
            assert summary["recovered_cleanly"] is True
            assert summary["leakage_scan"]["leakage_detected"] is False

        # Verify emergency stop on live stack
        stop_res = await emergency_stop_all(gateway_url=LIVE_GATEWAY_URL)
        assert stop_res["recovered_cleanly"] is True

    asyncio.run(_run_live())
