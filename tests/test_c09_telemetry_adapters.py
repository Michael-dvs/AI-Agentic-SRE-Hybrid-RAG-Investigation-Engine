"""Chapter C09 Automated Verification Suite — Read-Only Telemetry Adapters (C09, MCP-01, MCP-02, EV-02, SEC-03, AT-005, AT-008, AT-009, AT-012, SC-09, ADR-S05, ADR-S07)."""

from __future__ import annotations

import datetime
import json
import pathlib
import tempfile
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from starlette.testclient import TestClient

from gateway import (
    GatewayPolicyConfig,
    PolicyGateway,
    SYNTHETIC_BEARER_TOKENS,
    SecurityAuditLogger,
    ToolDispatcher,
)
from gateway.adapters import (
    ApmAdapter,
    CatalogAdapter,
    LogsAdapter,
    MetricsAdapter,
    TelemetryResponseEnvelope,
    TracesAdapter,
    validate_time_window,
)
from gateway.adapters.base import parse_iso8601_utc
from observability.backends import (
    create_loki_app,
    create_prometheus_app,
    create_tempo_app,
)
from observability.client import scan_telemetry_for_gt_leakage

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "evidence" / "c02-20261109T070500Z" / "C02" / "contracts"

# Load schema validators
_TOOL_RESULT_SCHEMA = json.loads((_CONTRACTS_DIR / "tool-result.v1.schema.json").read_text(encoding="utf-8"))
_AUDIT_SCHEMA = json.loads((_CONTRACTS_DIR / "audit-event.v1.schema.json").read_text(encoding="utf-8"))

_TOOL_RESULT_VALIDATOR = Draft202012Validator(_TOOL_RESULT_SCHEMA, format_checker=FormatChecker())
_AUDIT_VALIDATOR = Draft202012Validator(_AUDIT_SCHEMA, format_checker=FormatChecker())

_VALID_COORD_TOKEN = "sre-sim-coord-token-secret-2026"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def telemetry_fixture():
    """Build in-process FastAPI backends for Prometheus, Loki, and Tempo."""
    prom_app = create_prometheus_app()
    loki_app = create_loki_app()
    tempo_app = create_tempo_app()

    prom_client = TestClient(prom_app)
    loki_client = TestClient(loki_app)
    tempo_client = TestClient(tempo_app)

    # Seed baseline RED metrics
    now_epoch = datetime.datetime.now(datetime.timezone.utc).timestamp()

    # Seed baseline spans in tempo
    tempo_app.state.ingest_spans([
        {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7",
            "parent_span_id": None,
            "service_id": "api-gateway",
            "service.name": "api-gateway",
            "operation": "HTTP POST /transactions",
            "duration_ms": 324.5,
            "status_code": "ERROR",
            "start_time": "2026-11-12T00:01:00Z",
            "end_time": "2026-11-12T00:01:00.324Z",
            "attributes": {
                "http.route": "/transactions",
                "auth.token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID19GZyQ",
            },
        },
        {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "5fb397be34d23b0f",
            "parent_span_id": "00f067aa0ba902b7",
            "service_id": "transaction-service",
            "service.name": "transaction-service",
            "operation": "ProcessTransaction",
            "duration_ms": 280.0,
            "status_code": "ERROR",
            "start_time": "2026-11-12T00:01:00.010Z",
            "end_time": "2026-11-12T00:01:00.290Z",
            "attributes": {"client.card_pan": "4111-2222-3333-4444"},
        },
    ])

    metrics_adapter = MetricsAdapter(client=prom_client)
    logs_adapter = LogsAdapter(client=loki_client)
    traces_adapter = TracesAdapter(client=tempo_client)
    catalog_adapter = CatalogAdapter()
    apm_adapter = ApmAdapter()

    return {
        "prom_app": prom_app,
        "loki_app": loki_app,
        "tempo_app": tempo_app,
        "prom_client": prom_client,
        "loki_client": loki_client,
        "tempo_client": tempo_client,
        "metrics_adapter": metrics_adapter,
        "logs_adapter": logs_adapter,
        "traces_adapter": traces_adapter,
        "catalog_adapter": catalog_adapter,
        "apm_adapter": apm_adapter,
    }


# ---------------------------------------------------------------------------
# Test Cases (Minimum 15 Cases)
# ---------------------------------------------------------------------------

def test_get_metrics_success(telemetry_fixture: dict[str, Any]) -> None:
    """1. test_get_metrics_success: Valid query returns RED metrics with correct envelope."""
    adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]
    start_z = "2026-11-12T00:00:00Z"
    end_z = "2026-11-12T00:10:00Z"

    env = adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "sim_red_request_rate_rps",
        "start": start_z,
        "end": end_z,
        "step": "15s",
        "max_points": 100,
    })

    assert isinstance(env, TelemetryResponseEnvelope)
    assert env.status == "ok"
    assert env.tool_name == "get_service_metrics"
    assert env.source_ref.startswith("prometheus:")
    assert env.data_quality == "complete"
    assert env.truncated is False
    assert env.sanitized is True
    assert env.error_code is None
    assert env.query_window["start"] == start_z
    assert env.query_window["end"] == end_z
    assert env.query_window["duration_seconds"] == 600.0


def test_dispatcher_preserves_empty_metric_results(telemetry_fixture: dict[str, Any]) -> None:
    dispatcher = ToolDispatcher(metrics_adapter=telemetry_fixture["metrics_adapter"])
    result, status, error, _ = dispatcher.dispatch(
        "get_service_metrics",
        {
            "service_id": "api-gateway",
            "metric_name": "error_rate",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:05:00Z",
        },
    )
    assert status == "ok"
    assert error is None
    assert result["records"] == []
    assert result["data"] == []


def test_get_metrics_window_exceeded(telemetry_fixture: dict[str, Any]) -> None:
    """2. test_get_metrics_window_exceeded: Query with 7200s window strictly rejected with WINDOW_EXCEEDED (MCP-02)."""
    adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]
    start_z = "2026-11-12T00:00:00Z"
    end_z = "2026-11-12T02:00:00Z"  # 7200s > 3600s

    env = adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "error_rate",
        "start": start_z,
        "end": end_z,
        "max_points": 100,
    })

    assert env.status == "rejected"
    assert env.error_code == "WINDOW_EXCEEDED"
    assert env.data_quality == "unavailable"
    assert env.data is None
    # Verify no silent clamping
    assert env.query_window.get("duration_seconds", 0.0) == 0.0


def test_get_metrics_invalid_metric_rejected(telemetry_fixture: dict[str, Any]) -> None:
    """3. test_get_metrics_invalid_metric_rejected: Metric outside allowlist is strictly rejected."""
    adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]

    env = adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "arbitrary_custom_metric_injection",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
        "max_points": 50,
    })

    assert env.status == "rejected"
    assert env.error_code == "TOOL_NOT_ALLOWED"
    assert env.data_quality == "unavailable"
    assert env.data is None


def test_get_logs_sanitizes_secrets(telemetry_fixture: dict[str, Any]) -> None:
    """4. test_get_logs_sanitizes_secrets: Logs containing synthetic JWT/PAN/credential are redacted by SEC-03."""
    loki_app = telemetry_fixture["loki_app"]
    adapter: LogsAdapter = telemetry_fixture["logs_adapter"]

    # Ingest log containing synthetic secrets
    loki_app.state.ingest_records([
        {
            "timestamp": "2026-11-12T00:01:00Z",
            "service_id": "auth-service",
            "service.name": "auth-service",
            "severity": "ERROR",
            "error_code": "AUTH_FAILED",
            "message": (
                "Failed authentication for Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID19GZyQ "
                "using password='SuperSecretPassword123' and credit card 4111-2222-3333-4444"
            ),
        }
    ])

    env = adapter.execute({
        "service_id": "auth-service",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
        "severity": "ERROR",
        "max_hits": 10,
    })

    assert env.status == "ok"
    assert env.sanitized is True
    assert len(env.data) >= 1

    clean_msg = env.data[0]["message"]
    assert "SuperSecretPassword123" not in clean_msg
    assert "4111-2222-3333-4444" not in clean_msg
    assert "eyJhbGci" not in clean_msg
    assert "[REDACTED:SEC-03:JWT]" in clean_msg
    assert "[REDACTED:SEC-03:CREDENTIAL]" in clean_msg
    assert "[REDACTED:SEC-03:CARD_PAN]" in clean_msg


def test_get_logs_truncated_at_max_hits(telemetry_fixture: dict[str, Any]) -> None:
    """5. test_get_logs_truncated_at_max_hits: Results > 500 hits truncated at 500 with truncated: true."""
    loki_app = telemetry_fixture["loki_app"]
    adapter: LogsAdapter = telemetry_fixture["logs_adapter"]

    # Ingest 600 records into Loki
    large_records = [
        {
            "timestamp": f"2026-11-12T00:0{i%10}:00Z",
            "service_id": "transaction-service",
            "service.name": "transaction-service",
            "severity": "ERROR",
            "error_code": "ERR_SPIKE",
            "message": f"Log error spike entry #{i}",
        }
        for i in range(600)
    ]
    loki_app.state.ingest_records(large_records)

    env = adapter.execute({
        "service_id": "transaction-service",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:10:00Z",
        "severity": "ERROR",
        "max_hits": 500,
    })

    assert env.status == "ok"
    assert len(env.data) == 500
    assert env.truncated is True


def test_get_trace_summary_success(telemetry_fixture: dict[str, Any]) -> None:
    """6. test_get_trace_summary_success: Valid trace from Tempo summarized and sanitized correctly."""
    adapter: TracesAdapter = telemetry_fixture["traces_adapter"]
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"

    env = adapter.execute({"trace_id": trace_id, "service_id": "api-gateway"})

    assert env.status == "ok"
    assert env.tool_name == "get_trace_summary"
    assert env.data_quality == "complete"
    assert env.error_code is None
    assert len(env.data) >= 1

    span = env.data[0]
    assert span["span_id"] == "00f067aa0ba902b7"
    assert span["service_name"] == "api-gateway"
    assert span["operation"] == "HTTP POST /transactions"
    assert span["duration_ms"] == 324.5
    assert span["status_code"] == "ERROR"
    assert span["error"] is True

    # Attributes sanitized
    attr_str = json.dumps(span["attributes"])
    assert "eyJhbGci" not in attr_str
    assert "[REDACTED:SEC-03:JWT]" in attr_str


def test_get_trace_summary_source_unavailable(telemetry_fixture: dict[str, Any]) -> None:
    """7. test_get_trace_summary_source_unavailable: Tempo outage returns SOURCE_UNAVAILABLE and data=None (EV-02, SC-09)."""
    tempo_app = telemetry_fixture["tempo_app"]
    adapter: TracesAdapter = telemetry_fixture["traces_adapter"]

    # Trigger Tempo outage mode (SC-09)
    tempo_app.state.outage_state["unavailable"] = True
    tempo_app.state.outage_state["reason"] = "SC-09_trace_backend_outage"

    env = adapter.execute({"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"})

    assert env.status == "unavailable"
    assert env.error_code == "SOURCE_UNAVAILABLE"
    assert env.data_quality == "unavailable"
    assert env.data is None  # DILARANG merekayasa span kosong atau durasi 0

    # Recover Tempo
    tempo_app.state.outage_state["unavailable"] = False


def test_get_dependencies_depth_enforced(telemetry_fixture: dict[str, Any]) -> None:
    """8. test_get_dependencies_depth_enforced: Dependency query enforces max_depth <= 3."""
    adapter: CatalogAdapter = telemetry_fixture["catalog_adapter"]

    # Case A: Valid max_depth (2) -> ALLOW
    env_valid = adapter.execute({"service_id": "api-gateway", "max_depth": 2})
    assert env_valid.status == "ok"
    assert len(env_valid.data) > 0
    assert any(e["source"] == "api-gateway" for e in env_valid.data)

    # Case B: Exceeds max_depth (4 > 3) -> REJECT with LIMIT_EXCEEDED
    env_exceeded = adapter.execute({"service_id": "api-gateway", "max_depth": 4})
    assert env_exceeded.status == "rejected"
    assert env_exceeded.error_code == "LIMIT_EXCEEDED"
    assert env_exceeded.data is None


def test_apm_health_unsupported_disposition(telemetry_fixture: dict[str, Any]) -> None:
    """9. test_apm_health_unsupported_disposition: APM tool returns honest UNSUPPORTED_SOURCE under ADR-S07."""
    adapter: ApmAdapter = telemetry_fixture["apm_adapter"]

    env = adapter.execute({"service_id": "api-gateway"})

    assert env.status == "unavailable"
    assert env.tool_name == "get_apm_health"
    assert env.source_ref == "apm:unsupported"
    assert env.data_quality == "unavailable"
    assert env.error_code == "UNSUPPORTED_SOURCE"
    assert env.data is None  # Dilarang mengarang APM palsu


def test_mutation_attempts_blocked(telemetry_fixture: dict[str, Any]) -> None:
    """10. test_mutation_attempts_blocked: Write/restart/deploy/scale/shell/SQL strictly rejected with TOOL_NOT_ALLOWED."""
    metrics_adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]
    catalog_adapter: CatalogAdapter = telemetry_fixture["catalog_adapter"]

    mutation_attempts = [
        {"service_id": "api-gateway", "action": "restart_service"},
        {"service_id": "api-gateway", "metric_name": "error_rate", "sql": "DROP TABLE transactions;"},
        {"service_id": "transaction-service", "command": "deploy_patch v2"},
        {"service_id": "ledger-service", "action": "scale_deployment", "replicas": 5},
    ]

    for attempt in mutation_attempts:
        env = metrics_adapter.execute(attempt)
        assert env.status == "rejected"
        assert env.error_code == "TOOL_NOT_ALLOWED"

    # Direct mutation on catalog adapter
    env_cat = catalog_adapter.execute({"service_id": "api-gateway", "write": True})
    assert env_cat.status == "rejected"
    assert env_cat.error_code == "TOOL_NOT_ALLOWED"


def test_zero_ground_truth_leak(telemetry_fixture: dict[str, Any]) -> None:
    """11. test_zero_ground_truth_leak: Verification of zero ground-truth access in adapters (AT-008, KPI-10 = 0)."""
    # A. Static check: adapters must not import or open files in restricted/
    adapters_dir = _REPO_ROOT / "gateway" / "adapters"
    for py_file in adapters_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "restricted/" not in content, f"{py_file.name} references restricted/ path"
        assert "from restricted" not in content, f"{py_file.name} imports from restricted"
        assert "import restricted" not in content, f"{py_file.name} imports restricted"

    # B. Parameter rejection check
    metrics_adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]
    gt_attacks = [
        {"service_id": "api-gateway", "metric_name": "error_rate", "path": "restricted/gt_registry/records.jsonl"},
        {"service_id": "api-gateway", "metric_name": "error_rate", "table": "ground_truth"},
        {"service_id": "api-gateway", "metric_name": "error_rate", "scenario_id": "SC-01"},
    ]
    for atk in gt_attacks:
        env = metrics_adapter.execute(atk)
        assert env.status == "rejected"
        assert env.error_code == "FORBIDDEN_SCOPE"

    # C. Payload leakage scan
    logs_adapter: LogsAdapter = telemetry_fixture["logs_adapter"]
    env_logs = logs_adapter.execute({
        "service_id": "api-gateway",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
    })
    scan = scan_telemetry_for_gt_leakage(env_logs.to_dict())
    assert scan["leakage_detected"] is False, f"Ground truth token leaked: {scan['matched_forbidden_tokens']}"


def test_audit_chain_intact(tmp_path: pathlib.Path, telemetry_fixture: dict[str, Any]) -> None:
    """12. test_audit_chain_intact: Every adapter invocation logged with SHA-256 cryptographic hash chaining."""
    audit_file = tmp_path / "c09_audit.jsonl"
    logger = SecurityAuditLogger(log_path=audit_file)
    gw = PolicyGateway(audit_logger=logger)

    # Perform sequence of 4 calls: 2 ALLOW, 1 DENY (prohibited tool), 1 DENY (window exceeded)
    now_z = "2026-11-12T00:05:00Z"
    start_z = "2026-11-12T00:00:00Z"

    gw.execute_tool("get_service_metrics", {"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": start_z, "end": now_z, "max_points": 50}, token=_VALID_COORD_TOKEN, incident_id="inc-c09-01")
    gw.execute_tool("search_error_logs", {"service_id": "api-gateway", "environment": "lab", "start": start_z, "end": now_z, "error_code": "ERR_TEST", "max_hits": 50}, token=_VALID_COORD_TOKEN, incident_id="inc-c09-01")
    gw.execute_tool("restart_service", {"service_id": "api-gateway"}, token=_VALID_COORD_TOKEN, incident_id="inc-c09-01")
    gw.execute_tool("get_service_metrics", {"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": start_z, "end": "2026-11-12T02:00:00Z", "max_points": 50}, token=_VALID_COORD_TOKEN, incident_id="inc-c09-01")

    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4

    events = [json.loads(line) for line in lines]
    for idx, ev in enumerate(events):
        # Validate schema compliance against audit-event.v1
        errors = list(_AUDIT_VALIDATOR.iter_errors(ev))
        assert not errors, f"Event {idx} schema violation: {[e.message for e in errors]}"

        # Validate hash chaining
        if idx == 0:
            assert ev["prev_event_hash"] is None
        else:
            assert ev["prev_event_hash"] == events[idx - 1]["event_hash"]
        assert len(ev["event_hash"]) == 64


def test_invalid_time_range_rejected(telemetry_fixture: dict[str, Any]) -> None:
    """13. test_invalid_time_range_rejected: Start >= end strictly rejected with INVALID_TIME_RANGE."""
    adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]

    # Start after end (inverted)
    env = adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "error_rate",
        "start": "2026-11-12T00:10:00Z",
        "end": "2026-11-12T00:05:00Z",
    })
    assert env.status == "rejected"
    assert env.error_code == "INVALID_TIME_RANGE"

    # Start equals end
    env_equal = adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "error_rate",
        "start": "2026-11-12T00:05:00Z",
        "end": "2026-11-12T00:05:00Z",
    })
    assert env_equal.status == "rejected"
    assert env_equal.error_code == "INVALID_TIME_RANGE"


def test_get_metrics_source_unavailable_timeout() -> None:
    """14. test_get_metrics_source_unavailable_timeout: Unreachable Prometheus returns SOURCE_UNAVAILABLE."""
    # Point to closed port
    dead_adapter = MetricsAdapter(base_url="http://127.0.0.1:59999", timeout_seconds=0.5)

    env = dead_adapter.execute({
        "service_id": "api-gateway",
        "metric_name": "error_rate",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
    })

    assert env.status == "unavailable"
    assert env.error_code == "SOURCE_UNAVAILABLE"
    assert env.data_quality == "unavailable"
    assert env.data is None


def test_get_logs_source_unavailable() -> None:
    """15. test_get_logs_source_unavailable: Unreachable Loki returns SOURCE_UNAVAILABLE."""
    dead_adapter = LogsAdapter(base_url="http://127.0.0.1:59999", timeout_seconds=0.5)

    env = dead_adapter.execute({
        "service_id": "api-gateway",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
    })

    assert env.status == "unavailable"
    assert env.error_code == "SOURCE_UNAVAILABLE"
    assert env.data_quality == "unavailable"
    assert env.data is None


def test_invalid_trace_id_format_rejected(telemetry_fixture: dict[str, Any]) -> None:
    """16. test_invalid_trace_id_format_rejected: Non-hex or invalid length trace_id rejected with SCHEMA_INVALID."""
    adapter: TracesAdapter = telemetry_fixture["traces_adapter"]

    invalid_trace_ids = [
        "short-id",
        "not-a-hex-string-at-all-1234567890",
        "00000000000000000000000000000000",  # all zeroes prohibited
        "4bf92f3577b34da6a3ce929d0e0e47361",  # 33 chars
    ]

    for tid in invalid_trace_ids:
        env = adapter.execute({"trace_id": tid})
        assert env.status == "rejected"
        assert env.error_code == "SCHEMA_INVALID"


def test_unknown_service_id_rejected(telemetry_fixture: dict[str, Any]) -> None:
    """17. test_unknown_service_id_rejected: Unregistered service_id rejected with SERVICE_NOT_FOUND."""
    metrics_adapter: MetricsAdapter = telemetry_fixture["metrics_adapter"]
    catalog_adapter: CatalogAdapter = telemetry_fixture["catalog_adapter"]

    env_m = metrics_adapter.execute({
        "service_id": "non-existent-payment-svc",
        "metric_name": "error_rate",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
    })
    assert env_m.status == "rejected"
    assert env_m.error_code == "SERVICE_NOT_FOUND"

    env_c = catalog_adapter.execute({"service_id": "non-existent-payment-svc", "max_depth": 2})
    assert env_c.status == "rejected"
    assert env_c.error_code == "SERVICE_NOT_FOUND"


def test_logs_logql_injection_blocked(telemetry_fixture: dict[str, Any]) -> None:
    """18. test_logs_logql_injection_blocked: Free LogQL expressions rejected with SCHEMA_INVALID."""
    adapter: LogsAdapter = telemetry_fixture["logs_adapter"]

    injections = [
        '{service_id="api-gateway"} |= "error"',
        'error" | json | status="500',
        'rate({app="sim"}[5m])',
    ]

    for inj in injections:
        env = adapter.execute({
            "service_id": "api-gateway",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:05:00Z",
            "search_query": inj,
        })
        assert env.status == "rejected"
        assert env.error_code == "SCHEMA_INVALID"


def test_all_adapter_envelopes_conformance(telemetry_fixture: dict[str, Any]) -> None:
    """19. test_all_adapter_envelopes_conformance: All adapters produce envelopes conforming to standard metadata."""
    now_z = "2026-11-12T00:05:00Z"
    start_z = "2026-11-12T00:00:00Z"

    adapters = [
        ("get_service_metrics", telemetry_fixture["metrics_adapter"], {"service_id": "api-gateway", "metric_name": "error_rate", "start": start_z, "end": now_z}),
        ("search_error_logs", telemetry_fixture["logs_adapter"], {"service_id": "api-gateway", "start": start_z, "end": now_z, "error_code": "ERR_TEST"}),
        ("get_trace_summary", telemetry_fixture["traces_adapter"], {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"}),
        ("get_service_dependencies", telemetry_fixture["catalog_adapter"], {"service_id": "api-gateway", "max_depth": 2}),
        ("get_apm_health", telemetry_fixture["apm_adapter"], {"service_id": "api-gateway"}),
    ]

    for tool_name, adapter, args in adapters:
        env = adapter.execute(args)
        assert isinstance(env, TelemetryResponseEnvelope)
        assert env.tool_name == tool_name
        assert env.source_ref is not None
        assert env.observed_at.endswith("Z")
        assert "start" in env.query_window
        assert "end" in env.query_window
        assert env.data_quality in ("complete", "partial", "unavailable")
        assert isinstance(env.truncated, bool)
        assert env.sanitized is True

        # Test dictionary conversion
        d = env.to_dict()
        assert d["tool_name"] == tool_name
        assert "data" in d

        # Test contract envelope conversion
        c = env.to_contract_envelope()
        assert c["schema_version"] == "1.0"
        assert c["sanitized"] is True


def test_gateway_dispatch_integration(telemetry_fixture: dict[str, Any]) -> None:
    """20. test_gateway_dispatch_integration: PolicyGateway seamlessly dispatches to adapters and validates output."""
    gw = PolicyGateway()
    now_z = "2026-11-12T00:05:00Z"
    start_z = "2026-11-12T00:00:00Z"

    # Query metrics via gateway
    res_m = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": start_z,
            "end": now_z,
            "max_points": 50,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_m["status"] == "ok"
    assert res_m["tool_name"] == "get_service_metrics"
    assert res_m["sanitized"] is True
    errors = list(_TOOL_RESULT_VALIDATOR.iter_errors(res_m))
    assert not errors, f"Envelope validation errors: {[e.message for e in errors]}"

    # Query dependencies via gateway
    res_d = gw.execute_tool(
        tool_name="get_service_dependencies",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "reference_time": now_z,
            "max_depth": 2,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_d["status"] == "ok"
    assert res_d["tool_name"] == "get_service_dependencies"
    errors = list(_TOOL_RESULT_VALIDATOR.iter_errors(res_d))
    assert not errors, f"Envelope validation errors: {[e.message for e in errors]}"

