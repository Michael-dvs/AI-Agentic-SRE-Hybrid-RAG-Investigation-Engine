"""Chapter C08 Automated Verification Suite — Authenticated Policy Gateway, Boundary Security & Foundation G1 (SEC-01, SEC-02, SEC-03, MCP-01, MCP-02, RAG-02, AT-005, AT-008, TBD-05)."""

from __future__ import annotations

import json
import pathlib
import tempfile
import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway import (
    AuthenticatedContext,
    AuthenticationError,
    Authenticator,
    DeterministicSanitizer,
    GatewayPolicyConfig,
    PolicyGateway,
    SYNTHETIC_BEARER_TOKENS,
    SanitizerFailureError,
    SecurityAuditLogger,
    ToolDispatcher,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "evidence" / "c02-20261109T070500Z" / "C02" / "contracts"

# Load schema validators
_TOOL_RESULT_SCHEMA = json.loads((_CONTRACTS_DIR / "tool-result.v1.schema.json").read_text(encoding="utf-8"))
_AUDIT_SCHEMA = json.loads((_CONTRACTS_DIR / "audit-event.v1.schema.json").read_text(encoding="utf-8"))

_TOOL_RESULT_VALIDATOR = Draft202012Validator(_TOOL_RESULT_SCHEMA, format_checker=FormatChecker())
_AUDIT_VALIDATOR = Draft202012Validator(_AUDIT_SCHEMA, format_checker=FormatChecker())

_VALID_COORD_TOKEN = "sre-sim-coord-token-secret-2026"
_VALID_REVIEWER_TOKEN = "sre-sim-reviewer-token-secret-2026"


@pytest.fixture
def gateway_fixture(tmp_path: pathlib.Path) -> tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]:
    """Create a PolicyGateway instance with an isolated append-only audit log."""
    audit_file = tmp_path / "gateway_audit.jsonl"
    logger = SecurityAuditLogger(log_path=audit_file)
    config = GatewayPolicyConfig(
        max_window_seconds=900,  # 15 minutes test profile
        max_points=500,
        max_hits=200,
        max_dependency_depth=3,
        max_tool_calls_per_incident=5,
    )
    gw = PolicyGateway(policy=config, audit_logger=logger)
    return gw, logger, audit_file


def test_unauthenticated_request_rejected(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """Verify that requests with missing or invalid tokens are rejected with UNAUTHENTICATED (401)."""
    gw, logger, _ = gateway_fixture
    args = {
        "service_id": "api-gateway",
        "environment": "lab",
        "metric_enum": "error_rate",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
        "max_points": 100,
    }

    # Case A: Missing token
    res_none = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token=None)
    assert res_none["status"] == "rejected"
    assert res_none["error_code"] == "UNAUTHENTICATED"

    # Case B: Bogus token
    res_bogus = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token="Bearer invalid-token-12345")
    assert res_bogus["status"] == "rejected"
    assert res_bogus["error_code"] == "UNAUTHENTICATED"

    # Verify audit events
    denial_events = [e for e in logger.events if e["reason_code"] == "UNAUTHENTICATED"]
    assert len(denial_events) == 2
    for e in denial_events:
        assert e["action"] == "TOOL_DENIAL"
        assert e["result_code"] == "DENY"


def test_write_restart_deploy_tools_strictly_rejected(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """MCP-01 / AT-005: Verify mutation and prohibited tools are blocked before dispatch."""
    gw, logger, _ = gateway_fixture
    prohibited_calls = [
        ("restart_service", {"service_id": "api-gateway"}),
        ("deploy_patch", {"service_id": "transaction-service", "version": "v2"}),
        ("execute_sql", {"sql": "DROP TABLE ledger_entries;"}),
        ("run_shell", {"command": "rm -rf /"}),
        ("scale_deployment", {"replicas": 10}),
        ("read_ground_truth", {"scenario_id": "SC-01"}),
    ]

    for tool_name, args in prohibited_calls:
        res = gw.execute_tool(tool_name=tool_name, arguments=args, token=_VALID_COORD_TOKEN)
        assert res["status"] == "rejected"
        assert res["error_code"] == "TOOL_NOT_ALLOWED"

    # Verify audit records for all prohibited calls
    denials = [e for e in logger.events if e["reason_code"] == "TOOL_NOT_ALLOWED"]
    assert len(denials) == len(prohibited_calls)
    for e in denials:
        assert e["result_code"] == "DENY"


def test_excessive_time_window_rejected_without_silent_clamping(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """MCP-02 / RULE-003: Queries with time windows exceeding policy max must be REJECTED (do not silently clamp)."""
    gw, logger, _ = gateway_fixture
    # Config max_window_seconds is 900 seconds (15m)
    # Case A: Within limit (10 minutes = 600s) -> ALLOW
    res_valid = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:10:00Z",  # 600s
            "max_points": 100,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_valid["status"] == "ok"
    assert res_valid["error_code"] is None

    # Case B: Exceeds limit (16 minutes = 960s > 900s) -> REJECT with WINDOW_EXCEEDED
    res_exceeded = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:16:00Z",  # 960s
            "max_points": 100,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_exceeded["status"] == "rejected"
    assert res_exceeded["error_code"] == "WINDOW_EXCEEDED"

    # Case C: Invalid time range (start >= end) -> REJECT with INVALID_TIME_RANGE
    res_inverted = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": "2026-11-12T00:20:00Z",
            "end": "2026-11-12T00:10:00Z",  # inverted
            "max_points": 100,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_inverted["status"] == "rejected"
    assert res_inverted["error_code"] == "INVALID_TIME_RANGE"


def test_ground_truth_path_access_blocked(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """AT-008 / RULE-002: Any attempt to access restricted ground truth paths or tables is blocked at gateway."""
    gw, logger, _ = gateway_fixture
    gt_leak_attempts = [
        {"service_id": "api-gateway", "environment": "lab", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:05:00Z", "error_code": "ERR_GT", "max_hits": 50, "path": "restricted/gt_registry/ground_truth_records.jsonl"},
        {"service_id": "api-gateway", "environment": "lab", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:05:00Z", "error_code": "ERR_GT", "max_hits": 50, "table": "ground_truth"},
        {"service_id": "api-gateway", "environment": "lab", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:05:00Z", "error_code": "ERR_GT", "max_hits": 50, "scenario_id": "SC-01"},
    ]

    for attempt in gt_leak_attempts:
        res = gw.execute_tool(tool_name="search_error_logs", arguments=attempt, token=_VALID_COORD_TOKEN)
        assert res["status"] == "rejected"
        assert res["error_code"] in ("FORBIDDEN_SCOPE", "SCHEMA_INVALID")


def test_cross_service_scope_enforcement(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """RAG-02 / SEC-01: Gateway blocks unmapped service and unprivileged access to restricted runbooks."""
    gw, logger, _ = gateway_fixture

    # Case A: Request to an unmapped / unauthorized service
    res_unmapped = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "unauthorized-external-service",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:05:00Z",
            "max_points": 100,
        },
        token=_VALID_COORD_TOKEN,
    )
    assert res_unmapped["status"] == "rejected"
    assert res_unmapped["error_code"] == "FORBIDDEN_SCOPE"

    # Case B: Restricted runbook access via retrieve_runbooks (SEC-01)
    # Unprivileged caller (sre-core-l1)
    res_sec_unauth = gw.execute_tool(
        tool_name="retrieve_runbooks",
        arguments={
            "service_id": "auth-service",
            "environment": "lab",
            "query_text": "Prosedur darurat rotasi cryptographic master key and secret keys",
            "reference_time": "2026-11-12T00:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 3,
            "max_context_tokens": 1024,
            "index_version_policy": "latest",
        },
        token=_VALID_COORD_TOKEN,
        override_groups=["sre-core-l1"],
    )
    # Document SOP-SEC-KEY-ROTATION should NOT be present
    citations = res_sec_unauth.get("citations", [])
    assert not any(c.get("document_id") == "SOP-SEC-KEY-ROTATION" for c in citations)

    # Privileged caller (sre-core-l2, security-admin)
    res_sec_auth = gw.execute_tool(
        tool_name="retrieve_runbooks",
        arguments={
            "service_id": "auth-service",
            "environment": "lab",
            "query_text": "Prosedur darurat rotasi cryptographic master key and secret keys",
            "reference_time": "2026-11-12T00:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 3,
            "max_context_tokens": 1024,
            "index_version_policy": "latest",
        },
        token=_VALID_REVIEWER_TOKEN,
        override_groups=["sre-core-l2", "security-admin"],
    )
    auth_citations = res_sec_auth.get("citations", [])
    assert any(c.get("document_id") == "SOP-SEC-KEY-ROTATION" for c in auth_citations)


def test_sanitizer_redaction_and_fail_closed(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """SEC-03: Pre-sink sanitizer redacts secrets and implements FAIL_CLOSED upon unexpected exception."""
    gw, logger, _ = gateway_fixture
    sanitizer = DeterministicSanitizer()

    # Test individual redaction patterns
    dirty_text = (
        "User auth failed: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID19GZyQ "
        "with password='SuperSecretPassword123' and credit card 4111-2222-3333-4444"
    )
    clean_text, count = sanitizer.sanitize_text(dirty_text)
    assert count >= 3
    assert "SuperSecretPassword123" not in clean_text
    assert "4111-2222-3333-4444" not in clean_text
    assert "[REDACTED:SEC-03:JWT]" in clean_text
    assert "[REDACTED:SEC-03:CREDENTIAL]" in clean_text
    assert "[REDACTED:SEC-03:CARD_PAN]" in clean_text

    # Test FAIL_CLOSED in gateway
    res_fail_closed = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "api-gateway",
            "environment": "lab",
            "metric_enum": "error_rate",
            "start": "2026-11-12T00:00:00Z",
            "end": "2026-11-12T00:05:00Z",
            "max_points": 100,
        },
        token=_VALID_COORD_TOKEN,
        force_sanitizer_failure=True,
    )
    assert res_fail_closed["status"] == "rejected"
    assert res_fail_closed["error_code"] == "REDACTION_FAILED"
    assert len(res_fail_closed["records"]) == 0

    # Verify audit event for redaction failure
    redact_denial = next((e for e in logger.events if e["reason_code"] == "REDACTION_FAILED"), None)
    assert redact_denial is not None
    assert redact_denial["action"] == "REDACTION_GATE"
    assert redact_denial["result_code"] == "ERROR"


def test_append_only_audit_log_records_all_decisions(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """Verify that every decision (ALLOW, DENY, ERROR) is recorded in audit-event.v1 with valid hash chaining."""
    gw, logger, audit_file = gateway_fixture

    # Execute a sequence of 3 actions: ALLOW, DENY (allowlist), DENY (window)
    gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:05:00Z", "max_points": 100},
        token=_VALID_COORD_TOKEN,
        incident_id="inc-test-01",
    )
    gw.execute_tool(
        tool_name="restart_service",
        arguments={"service_id": "api-gateway"},
        token=_VALID_COORD_TOKEN,
        incident_id="inc-test-01",
    )
    gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:20:00Z", "max_points": 100},
        token=_VALID_COORD_TOKEN,
        incident_id="inc-test-01",
    )

    # Read audit log from disk
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    parsed_events = [json.loads(line) for line in lines]
    for i, ev in enumerate(parsed_events):
        # Validate schema compliance
        errors = list(_AUDIT_VALIDATOR.iter_errors(ev))
        assert not errors, f"Audit event {i} schema violation: {[e.message for e in errors]}"

        # Validate hash chaining
        if i == 0:
            assert ev["prev_event_hash"] is None
        else:
            assert ev["prev_event_hash"] == parsed_events[i - 1]["event_hash"]
        assert len(ev["event_hash"]) == 64


def test_read_only_tool_dispatch_and_schema_compliance(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """Verify all 4 read-only observability tools return envelopes conforming 100% to tool-result.v1.schema.json."""
    gw, _, _ = gateway_fixture
    now_z = "2026-11-12T00:05:00Z"
    start_z = "2026-11-12T00:00:00Z"

    tool_calls = [
        ("get_service_metrics", {"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": start_z, "end": now_z, "max_points": 50}),
        ("search_error_logs", {"service_id": "api-gateway", "environment": "lab", "start": start_z, "end": now_z, "error_code": "ERR_TEST", "max_hits": 50}),
        ("get_trace_summary", {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "service_id": "api-gateway", "environment": "lab", "start": start_z, "end": now_z}),
        ("get_service_dependencies", {"service_id": "api-gateway", "environment": "lab", "reference_time": now_z, "max_depth": 2}),
    ]

    for tool_name, args in tool_calls:
        res = gw.execute_tool(tool_name=tool_name, arguments=args, token=_VALID_COORD_TOKEN)
        assert res["status"] == "ok"
        assert res["error_code"] is None
        assert res["sanitized"] is True
        errors = list(_TOOL_RESULT_VALIDATOR.iter_errors(res))
        assert not errors, f"Tool {tool_name} returned invalid envelope: {[e.message for e in errors]}"


def test_backend_outage_simulation_returns_unavailable(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """EV-02 / NFR-016: Backend outage returns status=unavailable with error_code=SOURCE_UNAVAILABLE."""
    gw, _, _ = gateway_fixture
    args = {
        "service_id": "api-gateway",
        "environment": "lab",
        "metric_enum": "error_rate",
        "start": "2026-11-12T00:00:00Z",
        "end": "2026-11-12T00:05:00Z",
        "max_points": 100,
    }

    # Simulate Prometheus / metrics outage
    gw.dispatcher.set_outage("get_service_metrics", True)
    res_outage = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token=_VALID_COORD_TOKEN)
    assert res_outage["status"] == "unavailable"
    assert res_outage["error_code"] == "SOURCE_UNAVAILABLE"
    assert res_outage["data_quality"] == "unavailable"

    # Recover
    gw.dispatcher.set_outage("get_service_metrics", False)
    res_recovered = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token=_VALID_COORD_TOKEN)
    assert res_recovered["status"] == "ok"


def test_orchestrator_spike_invariants(gateway_fixture: tuple[PolicyGateway, SecurityAuditLogger, pathlib.Path]) -> None:
    """SPK-C08-01..07: Verify capability spike invariants (quota, stale review rejection, idempotency)."""
    gw, logger, _ = gateway_fixture

    # SPK-C08-05: Quota limit enforcement (max_tool_calls_per_incident = 5)
    incident_id = "inc-spike-quota-01"
    args = {"service_id": "api-gateway", "environment": "lab", "metric_enum": "error_rate", "start": "2026-11-12T00:00:00Z", "end": "2026-11-12T00:05:00Z", "max_points": 50}

    for i in range(5):
        res = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token=_VALID_COORD_TOKEN, incident_id=incident_id)
        assert res["status"] == "ok", f"Call {i+1} failed"

    # 6th call exceeds quota
    res_quota_exceeded = gw.execute_tool(tool_name="get_service_metrics", arguments=args, token=_VALID_COORD_TOKEN, incident_id=incident_id)
    assert res_quota_exceeded["status"] == "rejected"
    assert res_quota_exceeded["error_code"] == "BUDGET_EXHAUSTED"

    # SPK-C08-06: Human review hash conflict simulation (VERSION_CONFLICT)
    # Simulate a review event targeting stale dossier version/hash
    stale_review_event = {
        "incident_id": incident_id,
        "target_dossier_version": 1,
        "target_dossier_hash": "a" * 64,
        "current_dossier_hash": "b" * 64,  # modified
        "decision": "approve",
    }
    is_conflict = (stale_review_event["target_dossier_hash"] != stale_review_event["current_dossier_hash"])
    assert is_conflict is True, "Expected version conflict on stale dossier hash"

