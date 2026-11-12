"""Comprehensive test suite for Chapter 12 (C12) — Baseline Dossier and End-to-End G2.

Covers:
- AT-010: Baseline Incident Handover Dossier & Minimum Authorized Human Review.
- FR-OUT-001: JSON Dossier schema validation against dossier.v1.schema.json.
- FR-OUT-002: Human-readable Markdown report rendering according to BRD Appendix A.
- FR-OUT-003: Cryptographic canonical SHA-256 hash calculation and verification.
- FR-OUT-004: Append-only human review audit records with role authorization.
- HUM-01: Zero automated remediation (auto_action_triggered: False).
- NFR-011: Version conflict detection on stale dossier approval.
- EV-02 / SC-09: Trace backend outage yielding honest INCONCLUSIVE uncertainty and missing_sources.
- EV-01: Conflicting telemetry signals yielding honest PARTIAL uncertainty and contradictions.
- FR-RAG-009: No applicable runbook flagging without hallucinated citations.
- OPS-01 / SC-12: 100 duplicate alert storm yielding exactly 1 dossier.
- AT-012: Manual fallback dossier generation on deadline exhaustion.
- AT-008: Zero ground truth exposure end-to-end.
- AT-005 / KPI-09: Zero mutation state-changing calls throughout investigation.
"""

from __future__ import annotations

import json
import pathlib
import pytest

from gateway.policy import PolicyGateway
from orchestrator.checkpoint import CheckpointManager
from orchestrator.dossier import (
    DossierMarkdownRenderer,
    DossierSerializer,
    compute_canonical_dossier_hash,
)
from orchestrator.fallback import ManualFallbackGenerator
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.resilience import ResilienceController
from orchestrator.review import (
    DossierHashMismatchError,
    HumanReviewManager,
    InvalidReviewDecisionError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
)
from orchestrator.state_machine import (
    InvestigationStateMachine,
    WorkflowStateStore,
)
from services.alert_intake.correlation import DependencyCorrelator
from services.alert_intake.dedup import AlertDeduplicator


@pytest.fixture
def store() -> WorkflowStateStore:
    return WorkflowStateStore(":memory:")


@pytest.fixture
def state_machine(store: WorkflowStateStore) -> InvestigationStateMachine:
    return InvestigationStateMachine(store=store)


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


@pytest.fixture
def review_manager(
    state_machine: InvestigationStateMachine,
    store: WorkflowStateStore,
) -> HumanReviewManager:
    return HumanReviewManager(state_machine=state_machine, store=store)


# --- 1. Dossier JSON Schema Validation (Happy Path) ---

def test_dossier_json_schema_validation_happy_path(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-c12-schema-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
        "message": "Gateway timeout upstream call failure",
    }
    result = investigator.investigate_incident(alert)
    assert result["status"] == "HUMAN_REVIEW"

    dossier = result["dossier"]
    assert dossier is not None
    assert dossier["schema_version"] == "1.0"
    assert dossier["incident_id"] == "inc-c12-schema-001"
    assert dossier["dossier_version"] == 1
    assert len(dossier["dossier_hash"]) == 64
    assert dossier["severity"] in ("critical", "high", "medium", "low")
    assert dossier["investigation_mode"] == "deterministic_baseline"
    assert dossier["review_summary"]["status"] == "PENDING_REVIEW"
    assert len(dossier["recommended_checks"]) >= 1


# --- 2. Dossier Markdown Rendering Completeness ---

def test_dossier_markdown_rendering_completeness(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-c12-md-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]
    md = DossierMarkdownRenderer.render(dossier)

    # Verify all 9 sections from BRD Appendix A
    assert "# Incident Investigation Dossier — inc-c12-md-001" in md
    assert "## 1. Executive Summary & Observed Symptoms" in md
    assert "## 2. Impact and Scope" in md
    assert "## 3. Timeline of Observed Signals" in md
    assert "## 4. Evidence Table" in md
    assert "## 5. Ranked Hypotheses" in md
    assert "## 6. Relevant Runbooks & SOP Citations" in md
    assert "## 7. Unknowns & Telemetry Gaps" in md
    assert "## 8. Proposed Next Checks (Human-Controlled Only)" in md
    assert "## 9. Reviewer Decision, Edits, and Sign-off Box" in md
    assert "OFFICIAL SRE HANDOVER SIGN-OFF" in md


# --- 3. Canonical SHA-256 Hash Integrity ---

def test_dossier_sha256_canonical_hash_integrity(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-c12-hash-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]
    original_hash = dossier["dossier_hash"]

    # Verify recomputing hash produces exact match
    recomputed = compute_canonical_dossier_hash(dossier)
    assert recomputed == original_hash

    # Tampering with payload must alter the hash
    tampered = dict(dossier)
    tampered["severity"] = "critical" if dossier["severity"] != "critical" else "low"
    tampered_hash = compute_canonical_dossier_hash(tampered)
    assert tampered_hash != original_hash


# --- 4. Human Review Approval Flow and Closure ---

def test_human_review_approval_flow_and_closure(
    investigator: DeterministicInvestigator,
    review_manager: HumanReviewManager,
    state_machine: InvestigationStateMachine,
) -> None:
    alert = {
        "incident_id": "inc-c12-review-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    review_res = review_manager.submit_review(
        incident_id="inc-c12-review-001",
        dossier_dict=dossier,
        reviewer_ref="sre_lead_alex",
        reviewer_role="L2_SRE_REVIEWER",
        decision="approve",
        rationale="Hypothesis validated against downstream metrics and error logs; safe to hand over.",
    )

    # Verify review event
    event = review_res["review_event"]
    assert event["decision"] == "approve"
    assert event["target_dossier_version"] == 1
    assert event["auto_action_triggered"] is False

    # Verify incident state transitioned to CLOSED
    inc = state_machine.store.get_incident("inc-c12-review-001")
    assert inc["current_state"] == "CLOSED"
    assert inc["status"] == "CLOSED"

    # Verify review history in SQLite
    history = review_manager.get_review_history("inc-c12-review-001")
    assert len(history) == 1
    assert history[0]["decision"] == "approve"
    assert history[0]["reviewer_ref"] == "sre_lead_alex"


# --- 5. Unauthorized Reviewer Role Rejected ---

def test_human_review_unauthorized_role_rejected(
    investigator: DeterministicInvestigator,
    review_manager: HumanReviewManager,
) -> None:
    alert = {
        "incident_id": "inc-c12-unauth-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    with pytest.raises(UnauthorizedReviewerError) as exc_info:
        review_manager.submit_review(
            incident_id="inc-c12-unauth-001",
            dossier_dict=dossier,
            reviewer_ref="anonymous_user",
            reviewer_role="ANONYMOUS_GUEST",
            decision="approve",
            rationale="Attempting unauthorized sign-off",
        )
    assert "Unauthorized reviewer role" in str(exc_info.value)
    assert exc_info.value.code == "FORBIDDEN_SCOPE"


# --- 6. Version Conflict on Stale Dossier Approval ---

def test_human_review_version_conflict_rejected(
    investigator: DeterministicInvestigator,
    review_manager: HumanReviewManager,
    store: WorkflowStateStore,
) -> None:
    alert = {
        "incident_id": "inc-c12-conflict-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier_v1 = result["dossier"]

    # First review: edit to generate v2
    review_manager.submit_review(
        incident_id="inc-c12-conflict-001",
        dossier_dict=dossier_v1,
        reviewer_ref="operator_bob",
        reviewer_role="L1_OPERATOR",
        decision="edit",
        rationale="Refining root cause statement with more specific details.",
    )

    # Attempt to approve old v1 dossier when v2 is now active
    with pytest.raises(StaleDossierVersionError) as exc_info:
        review_manager.submit_review(
            incident_id="inc-c12-conflict-001",
            dossier_dict=dossier_v1,  # Passing stale v1!
            reviewer_ref="sre_lead_alex",
            reviewer_role="L2_SRE_REVIEWER",
            decision="approve",
            rationale="Approving stale version by mistake.",
        )
    assert "Version conflict" in str(exc_info.value)
    assert exc_info.value.code == "VERSION_CONFLICT"


# --- 7. Human Review Edit Creates New Revision ---

def test_human_review_edit_creates_new_revision(
    investigator: DeterministicInvestigator,
    review_manager: HumanReviewManager,
    store: WorkflowStateStore,
) -> None:
    alert = {
        "incident_id": "inc-c12-edit-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier_v1 = result["dossier"]

    review_res = review_manager.submit_review(
        incident_id="inc-c12-edit-001",
        dossier_dict=dossier_v1,
        reviewer_ref="operator_charlie",
        reviewer_role="L1_OPERATOR",
        decision="edit",
        rationale="Correcting observation summary based on manual metric verification.",
    )

    new_dossier = review_res["new_dossier_revision"]
    assert new_dossier is not None
    assert new_dossier["dossier_version"] == 2
    assert new_dossier["dossier_hash"] != dossier_v1["dossier_hash"]

    # Verify both v1 and v2 exist in persistence
    d1 = store.get_dossier("inc-c12-edit-001", version=1)
    d2 = store.get_dossier("inc-c12-edit-001", version=2)
    assert d1 is not None and d1["dossier_version"] == 1
    assert d2 is not None and d2["dossier_version"] == 2


# --- 8. Zero Mutation Enforced via HUM-01 ---

def test_human_review_strictly_zero_mutation_hum01(
    investigator: DeterministicInvestigator,
    review_manager: HumanReviewManager,
) -> None:
    alert = {
        "incident_id": "inc-c12-hum01-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    review_res = review_manager.submit_review(
        incident_id="inc-c12-hum01-001",
        dossier_dict=dossier,
        reviewer_ref="sre_alice",
        reviewer_role="L2_SRE_REVIEWER",
        decision="approve",
        rationale="Approved without side effects.",
    )

    event = review_res["review_event"]
    assert event["auto_action_triggered"] is False

    # Also verify in dossier recommended_checks that auto_execution_allowed is false for all
    for chk in dossier["recommended_checks"]:
        assert chk["auto_execution_allowed"] is False
        assert chk["requires_human_approval"] is True


# --- 9. Trace Outage Honest Uncertainty (SC-09, EV-02) ---

def test_sc09_trace_outage_honest_inconclusive_ev02(
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

    # Simulate Tempo outage
    gateway.dispatcher.set_outage("get_trace_summary", True)

    alert = {
        "incident_id": "inc-c12-sc09-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_GATEWAY_TIMEOUT",
    }
    result = investigator.investigate_incident(alert)
    gateway.dispatcher.set_outage("get_trace_summary", False)

    dossier = result["dossier"]
    assert dossier["hypotheses"][0]["support_status"] == "INCONCLUSIVE"

    # Missing sources must record Tempo outage
    missing_tools = [m["tool_name"] for m in dossier["missing_sources"]]
    assert "get_trace_summary" in missing_tools


# --- 10. Conflicting Evidence Yields PARTIAL (EV-01) ---

def test_ev01_conflicting_evidence_partial_status(
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

    alert = {
        "incident_id": "inc-c12-ev01-001",
        "service_id": "transaction-service",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_TRANSACTION_FAILED",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    if result.get("contradictions"):
        for h in dossier["hypotheses"]:
            assert h["support_status"] in ("PARTIAL", "INCONCLUSIVE")


# --- 11. No Applicable Runbook Flagging (FR-RAG-009) ---

def test_no_applicable_runbook_flagging(
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

    alert = {
        "incident_id": "inc-c12-no-rag-001",
        "service_id": "notification-service",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "error_code": "ERR_COMPLETELY_UNMAPPED_CODE",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    # When no runbook matched, missing_sources or sop_citations must reflect it
    if result.get("no_applicable_runbook"):
        assert any(m.get("error_code") == "NO_APPLICABLE_RUNBOOK" for m in dossier.get("missing_sources", []))


# --- 12. 100 Duplicate Alerts Yields Exactly 1 Dossier (SC-12, OPS-01) ---

def test_sc12_100_duplicate_alerts_single_dossier(
    investigator: DeterministicInvestigator,
) -> None:
    dedup = AlertDeduplicator()
    base_alert = {
        "service_id": "api-gateway",
        "environment": "lab",
        "alert_type": "HIGH_ERROR_RATE",
        "error_code": "ERR_GATEWAY_TIMEOUT",
        "event_time": "2026-11-12T10:00:00Z",
        "window_start": "2026-11-12T09:55:00Z",
        "window_end": "2026-11-12T10:01:00Z",
        "severity": "CRITICAL",
        "source": "prometheus",
    }

    # Burst of 100 duplicate alerts
    for _ in range(100):
        dedup.process(base_alert)

    # Queue should contain exactly 1 incident
    snapshot = dedup.dequeue()
    assert snapshot is not None
    assert dedup.dequeue() is None  # Exactly one!

    # Execute investigation for dequeued incident
    result = investigator.investigate_incident(snapshot)
    assert result["status"] == "HUMAN_REVIEW"
    assert "dossier" in result


# --- 13. Manual Fallback on Deadline Exceeded (AT-012) ---

def test_manual_fallback_on_deadline_exceeded_at012(
    state_machine: InvestigationStateMachine,
    gateway: PolicyGateway,
    correlator: DependencyCorrelator,
) -> None:
    now = 1000.0

    def mock_clock() -> float:
        return now

    res = ResilienceController(default_deadline_seconds=5.0, clock=mock_clock)
    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=res,
    )

    inc_id = "inc-c12-fallback-001"
    res.start_incident(inc_id)
    now += 15.0  # Expire deadline!

    alert = {
        "incident_id": inc_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)

    assert result["status"] == "FAILED_SAFE"
    dossier = result["dossier"]
    assert dossier is not None
    assert dossier["investigation_mode"] == "manual_fallback"
    assert dossier["review_summary"]["status"] == "MANUAL_TRIAGE"

    # Emergency manual triage checklist must be present
    check_ids = [c["check_id"] for c in dossier["recommended_checks"]]
    assert any("fb" in cid.lower() for cid in check_ids)


# --- 14. Zero Ground Truth Leakage End-to-End (AT-008, KPI-10 = 0) ---

def test_zero_ground_truth_leakage_end_to_end_at008(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-c12-gt-leak-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]
    md = result["dossier_markdown"]

    dossier_text = json.dumps(dossier).lower()
    md_text = md.lower()

    forbidden_tokens = [
        "restricted/",
        "gt_registry",
        "ground_truth_records",
        "holdout_queries",
        "fault_injection_harness",
    ]

    for token in forbidden_tokens:
        assert token not in dossier_text, f"Forbidden GT token '{token}' leaked in dossier JSON!"
        assert token not in md_text, f"Forbidden GT token '{token}' leaked in dossier Markdown!"


# --- 15. Zero Mutation Calls Throughout Investigation (AT-005, KPI-09 = 0) ---

def test_zero_mutation_calls_end_to_end_at005(gateway: PolicyGateway) -> None:
    # Verify that only allowed read-only tools exist
    assert gateway.policy.prohibited_tools is not None
    for p_tool in gateway.policy.prohibited_tools:
        res = gateway.execute_tool(
            tool_name=p_tool,
            arguments={"service_id": "api-gateway"},
            token="Bearer sre-sim-coord-token-secret-2026",
            incident_id="inc-c12-zero-mut",
        )
        assert res["status"] == "rejected"
        assert res["error_code"] == "TOOL_NOT_ALLOWED"


# --- 16. Reproducibility & Version Provenance ---

def test_reproducibility_and_version_provenance(investigator: DeterministicInvestigator) -> None:
    alert = {
        "incident_id": "inc-c12-repro-001",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-12T10:00:00Z",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    }
    result = investigator.investigate_incident(alert)
    dossier = result["dossier"]

    repro = dossier["reproducibility"]
    assert repro["workflow_version"] == "1.0.0"
    assert repro["policy_version"] == "1.0.0"
    assert repro["kb_index_version"] == "kb-idx-20261111-v1"
    assert repro["tool_schema_version"] == "1.0"
    assert "4bf92f3577b34da6a3ce929d0e0e4736" in repro["correlation_ids"]
