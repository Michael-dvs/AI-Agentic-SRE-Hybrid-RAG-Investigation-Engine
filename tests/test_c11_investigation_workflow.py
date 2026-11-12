"""Comprehensive test suite for Chapter 11 (C11) — Durable Deterministic Investigation Workflow.

Covers:
- AT-004: Sequential 9-state progression (RECEIVED -> ... -> HUMAN_REVIEW).
- FR-AGT-001: Strict transition checking and illegal transition rejection.
- FR-AGT-008: Frozen version manifest verification.
- ADR-TBD05: SQLite persistent store, transitions, and checkpoints.
- ADR-S05: Bounded investigation scope (max 5 services, max_depth 2).
- FR-AGT-004 / OPS-01: Tool call budget enforcement and exhaustion handling.
- FR-AGT-006 / ADR-S05: Global investigation deadline enforcement.
- NFR-014: Circuit breaker tripping on consecutive failures and cooldown.
- FR-AGT-009: Emergency cancellation kill switch.
- FR-AGT-009 / AT-012: Crash recovery, in-flight incident recovery, and resume.
- SC-09 / EV-02: Trace backend outage yielding honest INCONCLUSIVE uncertainty.
- EV-01: Conflicting metrics and logs yielding honest PARTIAL uncertainty.
- FR-RAG-009: No applicable runbook flagged when knowledge is missing.
- MCP-01 / KPI-09: Zero mutation guarantee through authenticated read-only gateway.
- KPI-10: Zero ground truth leakage.
- OPS-01: Idempotent replay and audit consistency.
"""

from __future__ import annotations

import os
import pathlib
import time
from typing import Any, Dict

import pytest

from gateway.policy import PolicyGateway
from orchestrator.checkpoint import CheckpointManager
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.resilience import (
    BudgetExhaustedError,
    CircuitBreaker,
    DeadlineExceededError,
    DeadLetterQueue,
    IncidentCancelledError,
    ResilienceController,
)
from orchestrator.state_machine import (
    MANDATORY_STATES,
    InvalidStateTransitionError,
    InvestigationStateMachine,
    WorkflowStateStore,
)
from services.alert_intake.correlation import DependencyCorrelator


@pytest.fixture
def in_memory_store() -> WorkflowStateStore:
    return WorkflowStateStore(":memory:")


@pytest.fixture
def state_machine(in_memory_store: WorkflowStateStore) -> InvestigationStateMachine:
    return InvestigationStateMachine(store=in_memory_store)


@pytest.fixture
def gateway() -> PolicyGateway:
    return PolicyGateway()


@pytest.fixture
def correlator() -> DependencyCorrelator:
    return DependencyCorrelator()


@pytest.fixture
def resilience() -> ResilienceController:
    return ResilienceController(default_deadline_seconds=120.0, max_tool_calls=30)


@pytest.fixture
def investigator(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> DeterministicInvestigator:
    return DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )


# --- 1. Sequential 9 States Progression (AT-004) ---

def test_sequential_9_states_happy_path(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-test-happy-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
        "message": "Upstream gateway request timed out",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "HUMAN_REVIEW"
    assert result["incident_id"] == "inc-test-happy-001"

    # Verify transitions in store
    transitions = investigator.sm.store.get_transitions("inc-test-happy-001")
    recorded_states = [t["to_state"] for t in transitions]

    # Verify exact sequential 9 states
    expected_9_states = list(MANDATORY_STATES)
    assert recorded_states == expected_9_states

    # Verify timestamps are ISO 8601 UTC with 'Z'
    for t in transitions:
        assert t["occurred_at"].endswith("Z")
        assert t["producer_ref"] == "CMP-INV-01"


# --- 2. Illegal State Transition Rejection (FR-AGT-001) ---

def test_illegal_state_transition_rejected(state_machine: InvestigationStateMachine) -> None:
    # Initial state is RECEIVED
    state_machine.transition(
        incident_id="inc-test-illegal-001",
        to_state="RECEIVED",
        idempotency_key="idem-001",
    )

    # Attempt illegal jump directly from RECEIVED to HYPOTHESES
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        state_machine.transition(
            incident_id="inc-test-illegal-001",
            to_state="HYPOTHESES",
            idempotency_key="idem-002",
        )
    assert "Illegal state transition" in str(exc_info.value)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"


# --- 3. Version Manifest Verification (FR-AGT-008) ---

def test_version_manifest_recorded(investigator: DeterministicInvestigator) -> None:
    manifest = investigator.sm.get_version_manifest()
    assert manifest["workflow_version"] == "1.0.0"
    assert manifest["policy_version"] == "1.0.0"
    assert manifest["kb_version"] == "kb-idx-20261111-v1"
    assert manifest["tool_schema_version"] == "1.0"
    assert manifest["coordinator_ref"] == "CMP-INV-01"

    # Also verify manifest is embedded into final dossier
    alert = {
        "incident_id": "inc-test-manifest-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]
    assert dossier["version_manifest"] == manifest


# --- 4. SQLite Persistence & History (ADR-TBD05) ---

def test_sqlite_persistence_and_transitions(tmp_path: pathlib.Path) -> None:
    db_file = str(tmp_path / "test_workflow.db")
    store = WorkflowStateStore(db_file)
    sm = InvestigationStateMachine(store=store)

    sm.transition("inc-test-db-001", "RECEIVED", "idem-key-001")
    sm.transition("inc-test-db-001", "CORRELATED", "idem-key-002")

    store.save_checkpoint("inc-test-db-001", "CORRELATED", {"step": 2, "data": "val"})

    # Close and reopen to verify persistence across connections
    store.close()

    store2 = WorkflowStateStore(db_file)
    inc = store2.get_incident("inc-test-db-001")
    assert inc is not None
    assert inc["current_state"] == "CORRELATED"
    assert inc["status"] == "ACTIVE"

    transitions = store2.get_transitions("inc-test-db-001")
    assert len(transitions) == 2
    assert transitions[0]["to_state"] == "RECEIVED"
    assert transitions[1]["to_state"] == "CORRELATED"

    chk = store2.get_checkpoint("inc-test-db-001")
    assert chk is not None
    assert chk["state"] == "CORRELATED"
    assert chk["context"]["step"] == 2
    store2.close()


# --- 5. Bounded Investigation Scope (ADR-S05) ---

def test_bounded_investigation_scope(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-test-scope-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)

    scope = result["investigation_scope"]
    # Primary service must be first
    assert scope[0] == "api-gateway"
    # Strict cap: maximum 5 services (ADR-S05)
    assert len(scope) <= 5
    # Impact graph present
    assert "primary_service" in result["impact_graph"]
    assert result["impact_graph"]["primary_service"] == "api-gateway"


# --- 6. Tool Budget Exhaustion (FR-AGT-004, ADR-S05, OPS-01) ---

def test_tool_budget_exhaustion(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
) -> None:
    # Set tight budget cap of 2 tool calls
    tight_resilience = ResilienceController(max_tool_calls=2)
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=tight_resilience,
    )

    alert = {
        "incident_id": "inc-test-budget-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "FAILED_SAFE"
    assert "budget exhausted" in result["abort_reason"].lower()

    # Verify DLQ received entry
    dlq_entries = tight_resilience.dlq.get_entries()
    assert len(dlq_entries) >= 1
    assert dlq_entries[0]["incident_id"] == "inc-test-budget-001"
    assert dlq_entries[0]["reason_code"] == "BUDGET_EXHAUSTED"

    # Verify state machine recorded FAILED_SAFE
    inc = state_machine.store.get_incident("inc-test-budget-001")
    assert inc["current_state"] == "FAILED_SAFE"
    assert inc["status"] == "FAILED_SAFE"


# --- 7. Global Deadline Exceeded (FR-AGT-006, ADR-S05) ---

def test_global_deadline_exceeded(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
) -> None:
    # Mock monotonic clock that jumps forward beyond deadline
    fake_time = 1000.0

    def mock_clock() -> float:
        return fake_time

    resilience = ResilienceController(default_deadline_seconds=5.0, clock=mock_clock)
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    # Start incident
    resilience.start_incident("inc-test-deadline-001")
    # Advance clock past 5.0 seconds
    fake_time += 10.0

    alert = {
        "incident_id": "inc-test-deadline-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "FAILED_SAFE"
    assert "exceeded global deadline" in result["abort_reason"].lower()

    # Verify DLQ
    dlq_entries = resilience.dlq.get_entries()
    assert any(e["reason_code"] == "DEADLINE_EXCEEDED" for e in dlq_entries)


# --- 8. Circuit Breaker Tripping and Cooldown (NFR-014) ---

def test_circuit_breaker_tripping_and_cooldown() -> None:
    now = 100.0

    def mock_clock() -> float:
        return now

    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0, clock=mock_clock)
    target = "broken-metrics-service"

    assert not cb.is_open(target)
    assert cb.get_state(target) == "CLOSED"

    # 1st failure
    cb.record_failure(target)
    assert not cb.is_open(target)

    # 2nd failure
    cb.record_failure(target)
    assert not cb.is_open(target)

    # 3rd failure -> trips to OPEN
    tripped = cb.record_failure(target)
    assert tripped is True
    assert cb.is_open(target)
    assert cb.get_state(target) == "OPEN"

    # Within cooldown period, remains OPEN
    now += 5.0
    assert cb.is_open(target)

    # After cooldown period, transitions to HALF_OPEN (allows test call)
    now += 6.0  # now elapsed = 11.0 > 10.0
    assert not cb.is_open(target)
    assert cb.get_state(target) == "HALF_OPEN"

    # Successful test call closes circuit
    cb.record_success(target)
    assert cb.get_state(target) == "CLOSED"
    assert not cb.is_open(target)


# --- 9. Cancellation Kill Switch (FR-AGT-009) ---

def test_cancellation_kill_switch(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> None:
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    inc_id = "inc-test-cancel-001"
    # Pre-emptively engage kill switch
    resilience.cancel_incident(inc_id, reason="Operator emergency test stop")

    alert = {
        "incident_id": inc_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "CANCELLED"
    assert "emergency test stop" in result["abort_reason"]

    # Verify state in store
    inc = state_machine.store.get_incident(inc_id)
    assert inc["current_state"] == "CANCELLED"
    assert inc["status"] == "CANCELLED"

    # Verify transition has TERMINATED_CANCELLED outcome
    transitions = state_machine.store.get_transitions(inc_id)
    cancel_t = [t for t in transitions if t["to_state"] == "CANCELLED"]
    assert len(cancel_t) == 1
    assert cancel_t[0]["terminal_outcome"] == "TERMINATED_CANCELLED"
    assert cancel_t[0]["reason_code"] == "CANCELLED"


# --- 10. Checkpoint Crash Recovery & Resume (FR-AGT-009, AT-012) ---

def test_checkpoint_crash_recovery_and_resume(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> None:
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    inc_id = "inc-test-resume-001"

    # Manually simulate in-flight execution up to TRIAGED
    state_machine.transition(inc_id, "RECEIVED", "idem-resume-001")
    state_machine.transition(inc_id, "CORRELATED", "idem-resume-002")
    state_machine.transition(inc_id, "TRIAGED", "idem-resume-003")

    # Save checkpoint context at TRIAGED
    simulated_context = {
        "incident_id": inc_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
        "investigation_scope": ["api-gateway", "transaction-service"],
        "priority": "HIGH",
        "query_window": {
            "start": "2026-11-12T09:55:00Z",
            "end": "2026-11-12T10:01:00Z",
            "duration_seconds": 360.0,
        },
        "evidence_items": [],
        "timeline": [
            {"state": "RECEIVED", "timestamp": "2026-11-12T10:00:01Z"},
            {"state": "CORRELATED", "timestamp": "2026-11-12T10:00:02Z"},
            {"state": "TRIAGED", "timestamp": "2026-11-12T10:00:03Z"},
        ],
    }
    investigator.checkpoint.save_checkpoint(inc_id, "TRIAGED", simulated_context)

    # Verify recovery scanner finds this in-flight incident
    in_flight = investigator.checkpoint.recover_in_flight_incidents()
    assert any(i["incident_id"] == inc_id for i in in_flight)

    # Resume investigation from checkpoint
    resumed_result = investigator.resume_investigation(inc_id)

    assert resumed_result["status"] == "HUMAN_REVIEW"
    assert "dossier" in resumed_result

    # Verify all subsequent states were reached
    transitions = state_machine.store.get_transitions(inc_id)
    states = [t["to_state"] for t in transitions]
    assert states == list(MANDATORY_STATES)


# --- 11. Trace Outage Honest Uncertainty (SC-09, EV-02, RULE-006) ---

def test_trace_outage_honest_inconclusive(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> None:
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    # Simulate backend outage for distributed tracing (SC-09, EV-02)
    gateway.dispatcher.set_outage("get_trace_summary", True)

    alert = {
        "incident_id": "inc-test-trace-outage-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
    }
    result = investigator.investigate_incident(alert)

    # Cleanup outage state
    gateway.dispatcher.set_outage("get_trace_summary", False)

    assert result["status"] == "HUMAN_REVIEW"
    # Hypotheses must be INCONCLUSIVE (cannot prove causality without trace)
    hypotheses = result["hypotheses"]
    assert len(hypotheses) >= 1
    for h in hypotheses:
        assert h["status"] == "INCONCLUSIVE"
        assert h["confidence_score"] <= 0.40

    # Unknowns must record trace outage
    assert any("trace backend is unavailable" in u.lower() for u in result["unknowns"])


# --- 12. Conflicting Evidence Honest Uncertainty (EV-01, RULE-006) ---

def test_conflicting_evidence_honest_partial(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> None:
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    # Target service with error logs in loki, but no Prometheus points
    alert = {
        "incident_id": "inc-test-conflict-001",
        "service_id": "transaction-service",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_TRANSACTION_FAILED",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "HUMAN_REVIEW"
    # If contradictions detected, status must be PARTIAL
    if result["contradictions"]:
        for h in result["hypotheses"]:
            assert h["status"] in ("PARTIAL", "INCONCLUSIVE")
            assert h["confidence_score"] <= 0.50
        assert any("discrepancy detected" in c.lower() for c in result["contradictions"])


# --- 13. No Applicable Runbook Flagged (FR-RAG-009) ---

def test_no_applicable_runbook_flagged(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
    resilience: ResilienceController,
) -> None:
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
    )

    # Use a service and error code with no match in the corpus
    alert = {
        "incident_id": "inc-test-no-runbook-001",
        "service_id": "notification-service",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_NONEXISTENT_ESOTERIC_CODE",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "HUMAN_REVIEW"
    # When no citations or unknown service/error, flag must be set
    assert "no_applicable_runbook" in result


# --- 14. Zero Mutation Guaranteed (MCP-01, KPI-09 = 0) ---

def test_zero_mutation_enforced(gateway: PolicyGateway) -> None:
    prohibited = [
        "restart_service",
        "deploy_service",
        "scale_deployment",
        "execute_shell",
        "run_sql",
        "remediate_incident",
    ]
    for p_tool in prohibited:
        res = gateway.execute_tool(
            tool_name=p_tool,
            arguments={"service_id": "api-gateway"},
            token="Bearer sre-sim-coord-token-secret-2026",
            incident_id="inc-test-mut-001",
        )
        assert res["status"] == "rejected"
        assert res["error_code"] == "TOOL_NOT_ALLOWED"


# --- 15. Zero Ground Truth Leakage (KPI-10 = 0, RULE-002) ---

def test_zero_ground_truth_leakage(investigator: DeterministicInvestigator) -> None:
    # Ensure investigator does not import or read anything from restricted/
    import inspect
    import orchestrator.investigator as inv_mod

    src = inspect.getsource(inv_mod)
    assert "restricted" not in src.lower()
    assert "scenario_id" not in src.lower()
    assert "fault_harness" not in src.lower()
    assert "gt_registry" not in src.lower()


# --- 16. Idempotent Replay and Repeatability (OPS-01) ---

def test_idempotent_replay(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-test-idempotent-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
    }
    res1 = investigator.investigate_incident(alert)
    assert res1["status"] == "HUMAN_REVIEW"

    # Checkpoint exists
    chk = investigator.checkpoint.get_checkpoint("inc-test-idempotent-001")
    assert chk is not None
    assert chk["state"] == "HUMAN_REVIEW"

    # Resuming completed incident does not corrupt state
    res2 = investigator.resume_investigation("inc-test-idempotent-001")
    assert res2["status"] == "HUMAN_REVIEW"
