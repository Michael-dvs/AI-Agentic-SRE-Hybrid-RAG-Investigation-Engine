"""Unit & Integration tests for Latency, Token Accounting, and Shadow Cost Accounting (C15, AT-015, KPI-07, KPI-14, NFR-007, NFR-008, NFR-013)."""

from __future__ import annotations

import pytest

from observability.cost_tracker import CostAndResourceTracker, IncidentCostProfile, DEFAULT_RATES


def test_incident_cost_profile_latency_and_shadow_cost_calculation():
    incident_id = "inc-cost-001"
    rates = {
        "prompt_token_per_1k": 0.00015,
        "completion_token_per_1k": 0.00060,
        "embedding_token_per_1k": 0.00002,
        "tool_call_unit_cost": 0.00005,
    }
    profile = IncidentCostProfile(incident_id, rates=rates)

    # Record durations and calls
    profile.record_state_duration("RECEIVED", 12.5)
    profile.record_state_duration("CORRELATED", 45.0)
    profile.record_retrieval_latency(85.3)
    profile.record_tokens(prompt=2000, completion=500)
    profile.record_embedding_tokens(1000)
    profile.record_tool_call(count=4)

    # Expected shadow cost:
    # prompt: (2000 / 1000) * 0.00015 = 0.00030
    # completion: (500 / 1000) * 0.00060 = 0.00030
    # embedding: (1000 / 1000) * 0.00002 = 0.00002
    # tool calls: 4 * 0.00005 = 0.00020
    # total = 0.00082 USD
    computed_cost = profile.compute_shadow_cost_usd()
    assert computed_cost == 0.00082

    summary = profile.finish(outcome="COMPLETED")
    assert summary["incident_id"] == incident_id
    assert summary["outcome"] == "COMPLETED"
    assert summary["latency"]["retrieval_latency_ms"] == 85.3
    assert summary["latency"]["state_durations_ms"]["RECEIVED"] == 12.5
    assert summary["latency"]["kpi_07_under_120s"] is True
    assert summary["tokens"]["total_tokens"] == 3500
    assert summary["calls"]["tool_calls_count"] == 4
    assert summary["shadow_cost"]["actual_billed_lab_cost_usd"] == 0.00
    assert summary["resource_usage"]["memory_ceiling_8gib_ok"] is True


def test_tracker_aggregates_multiple_runs_including_failed_runs():
    """AT-015: Shadow cost and tokens MUST be accounted for failed/timeout runs as well."""
    tracker = CostAndResourceTracker()

    # Run 1: Completed
    p1 = tracker.start_incident("inc-001")
    p1.record_tokens(1000, 200)
    p1.record_tool_call(2)
    tracker.finish_incident("inc-001", outcome="COMPLETED")

    # Run 2: Aborted / Failed safe (deadline exceeded or circuit open)
    p2 = tracker.start_incident("inc-002")
    p2.record_tokens(1500, 0)  # Input consumed before failure
    p2.record_tool_call(3)
    tracker.finish_incident("inc-002", outcome="TERMINATED_FAILED_SAFE")

    summary = tracker.export_summary()
    assert summary["total_incidents_tracked"] == 2
    assert summary["total_tokens_consumed"] == (1000 + 200 + 1500)
    assert summary["total_shadow_cost_usd"] > 0.0
    assert summary["actual_billed_lab_cost_usd"] == 0.00
    assert summary["kpi_07_p95_met"] is True


def test_tracker_integration_in_investigator(tmp_path):
    from gateway.audit import SecurityAuditLogger
    from gateway.policy import PolicyGateway
    from orchestrator.investigator import DeterministicInvestigator
    from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore

    class QuickDispatcher:
        def dispatch(self, tool_name, arguments, **kwargs):
            if tool_name == "retrieve_runbooks":
                return {"citations": []}, "ok", None, "synthetic-kb"
            return {"records": []}, "ok", None, "synthetic-telemetry"

    audit_logger = SecurityAuditLogger(tmp_path / "audit.jsonl")
    gw = PolicyGateway(audit_logger=audit_logger)
    gw.dispatcher = QuickDispatcher()
    sm = InvestigationStateMachine(store=WorkflowStateStore(":memory:"))

    cost_tracker = CostAndResourceTracker()
    investigator = DeterministicInvestigator(
        state_machine=sm,
        gateway=gw,
        cost_tracker=cost_tracker,
    )

    incident_id = "inc-cost-integration"
    res = investigator.investigate_incident({
        "incident_id": incident_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "error_code": "ERR_NONE",
    })

    assert "metrics" in res
    metrics = res["metrics"]
    assert metrics["incident_id"] == incident_id
    assert metrics["latency"]["intake_to_dossier_duration_ms"] > 0.0
    assert metrics["latency"]["kpi_07_under_120s"] is True
    assert metrics["resource_usage"]["peak_rss_mb"] > 0.0
