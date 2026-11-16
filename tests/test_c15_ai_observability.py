"""Unit & Integration tests for Sanitized AI Observability Tracer and Outage Resilience (C15, ADR-S06, OPS-02, AT-012, NFR-005, NFR-018, SEC-03)."""

from __future__ import annotations

import json
import pathlib
import pytest

from gateway.audit import SecurityAuditLogger
from gateway.policy import PolicyGateway
from observability.ai_tracer import SanitizedAITracer, strip_hidden_cot
from observability.cost_tracker import CostAndResourceTracker
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore


class MockCorrelator:
    def build_impact_graph(self, **kwargs):
        return {"upstream_callers": [], "downstream_dependencies": [], "edges": []}


class MockDispatcher:
    def dispatch(self, tool_name, arguments, **kwargs):
        if tool_name == "retrieve_runbooks":
            return {"citations": []}, "ok", None, "synthetic-kb"
        if tool_name == "get_service_metrics":
            records = [{"service_id": "auth-service", "metric_enum": arguments.get("metric_enum"), "value": 0.05}]
        elif tool_name == "search_error_logs":
            records = [{"service_id": "auth-service", "status_code": 500, "message": "auth failure"}]
        else:
            records = [{"service_id": "auth-service", "span_id": "abcdef0123456789", "duration_ms": 15, "status_code": "OK"}]
        return {"records": records}, "ok", None, "synthetic-telemetry"


def create_test_investigator(tmp_path, *, simulate_tracer_outage: bool = False):
    audit_file = tmp_path / "security_audit.jsonl"
    tracer_file = tmp_path / "ai_traces.jsonl"

    audit_logger = SecurityAuditLogger(audit_file)
    gateway = PolicyGateway(audit_logger=audit_logger)
    gateway.dispatcher = MockDispatcher()

    store = WorkflowStateStore(":memory:")
    sm = InvestigationStateMachine(store=store)

    tracer = SanitizedAITracer(sink_path=tracer_file, simulate_outage=simulate_tracer_outage)
    cost_tracker = CostAndResourceTracker()

    investigator = DeterministicInvestigator(
        state_machine=sm,
        gateway=gateway,
        correlator=MockCorrelator(),
        ai_tracer=tracer,
        cost_tracker=cost_tracker,
    )
    return investigator, audit_logger, tracer, audit_file, tracer_file


def test_ai_tracer_lifecycle_and_end_to_end_correlation(tmp_path):
    investigator, audit_logger, tracer, audit_file, tracer_file = create_test_investigator(tmp_path)

    incident_id = "inc-c15-trace-test"
    alert = {
        "incident_id": incident_id,
        "correlation_id": "corr-c15-001",
        "service_id": "auth-service",
        "environment": "lab",
        "error_code": "ERR_AUTH_FAIL",
    }

    result = investigator.investigate_incident(alert)
    assert result["status"] == "HUMAN_REVIEW"
    assert result["correlation_id"] == "corr-c15-001"
    assert "metrics" in result

    # 1. Verify AI trace session was recorded
    traces = tracer.export_traces()
    assert len(traces) == 1
    trace = traces[0]
    assert trace["incident_id"] == incident_id
    assert trace["correlation_id"] == "corr-c15-001"
    assert trace["outcome"] == "COMPLETED"

    # Verify state spans exist
    span_names = [s["name"] for s in trace["spans"]]
    assert "state.received" in span_names
    assert "state.correlated" in span_names
    assert "state.evidence_collected" in span_names
    assert "state.retrieved" in span_names
    assert "state.hypotheses" in span_names
    assert "state.validated" in span_names
    assert "state.drafted" in span_names
    assert "state.human_review" in span_names

    # 2. Verify Security Audit log was recorded independently
    assert audit_file.exists()
    audit_events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(audit_events) > 0

    # 3. Verify cross-sink correlation by incident_id (NFR-005, NFR-018)
    for ev in audit_events:
        assert ev["incident_id"] == incident_id

    # 4. Verify file export of traces
    assert tracer_file.exists()
    disk_spans = [json.loads(line) for line in tracer_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(disk_spans) == len(trace["spans"])


def test_ai_tracer_blocks_hidden_chain_of_thought_and_think_tags():
    raw_payload = {
        "summary": "High latency detected",
        "diagnosis": "<think>This is internal model reasoning that must NOT be stored.</think>External diagnosis text.",
        "analysis_tag": "<analysis>Hidden scratchpad steps</analysis>Final decision",
        "chain_of_thought": "Sensitive intermediate token progression",
        "raw_thinking": "Forbidden step",
    }

    cleaned = strip_hidden_cot(raw_payload)

    assert "<think>" not in cleaned["diagnosis"]
    assert "[REDACTED:COT]" in cleaned["diagnosis"]
    assert "External diagnosis text" in cleaned["diagnosis"]
    assert "<analysis>" not in cleaned["analysis_tag"]
    assert "[REDACTED:COT]" in cleaned["analysis_tag"]
    assert "chain_of_thought" not in cleaned
    assert "raw_thinking" not in cleaned


def test_ai_tracer_outage_does_not_disrupt_investigation_and_preserves_audit(tmp_path):
    """OPS-02 & AT-012: Simulate AI observability sink outage.

    Investigation MUST finish successfully to HUMAN_REVIEW, produce a valid dossier,
    and the independent security audit sink MUST remain 100% intact.
    """
    investigator, audit_logger, tracer, audit_file, tracer_file = create_test_investigator(
        tmp_path, simulate_tracer_outage=True
    )

    incident_id = "inc-c15-outage-test"
    alert = {
        "incident_id": incident_id,
        "service_id": "auth-service",
        "environment": "lab",
        "error_code": "ERR_DATABASE_DOWN",
    }

    # Execute with dead AI tracer sink
    result = investigator.investigate_incident(alert)

    # 1. Investigation finishes cleanly without disruption
    assert result["status"] == "HUMAN_REVIEW"
    assert "dossier" in result
    assert "dossier_markdown" in result
    assert tracer.dropped_spans_count > 0

    # 2. Independent Security Audit log remains completely intact and verified
    assert audit_file.exists()
    audit_events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(audit_events) > 0

    from observability.audit_chain import verify_chain_integrity
    is_valid, violations = verify_chain_integrity(audit_events)
    assert is_valid is True
    assert len(violations) == 0
