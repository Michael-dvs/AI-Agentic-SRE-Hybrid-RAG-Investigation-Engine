"""Test Suite for Chapter 16 (C16 — Human Review, Version-Bound Approval, Handover Export, and Dummy Ticketing).

Requirements & Acceptance Tests:
- HUM-01: Zero automated remediation, critical recommendations require human sign-off, auto_action_triggered: false.
- AT-010: Readability of dossier, authorized approve/reject/edit decisions, append-only persistence.
- AT-017: Dummy ITSM ticket creation strictly gated on APPROVED dossier revision (ADR-S07).
- FR-OUT-005 & RULE-002: Ground truth isolation in exported handover demo pack.
- NFR-011: Append-only corrections (revision N+1) without raw telemetry data mutation.
"""

from __future__ import annotations

import json
import pathlib
import pytest
from typing import Any, Dict

from gateway.policy import PolicyGateway
from observability.audit_chain import AuditHashChain, verify_chain_integrity
from orchestrator.dossier import compute_canonical_dossier_hash
from orchestrator.handover import (
    HandoverExporter,
    sanitize_data_recursively,
    verify_ground_truth_isolation,
)
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.resilience import ResilienceController
from orchestrator.review import (
    AuthorizedReviewManager,
    DossierHashMismatchError,
    HumanReviewManager,
    InvalidReviewDecisionError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
)
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from orchestrator.ticketing import DummyTicketManager, InvalidDossierStateError
from scripts.review_console import display_dossier_summary, run_review_action
from services.alert_intake.correlation import DependencyCorrelator


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
def audit_chain(tmp_path: pathlib.Path) -> AuditHashChain:
    log_file = tmp_path / "c16_audit_chain.jsonl"
    return AuditHashChain(log_path=log_file)


@pytest.fixture
def review_manager(
    state_machine: InvestigationStateMachine,
    store: WorkflowStateStore,
    audit_chain: AuditHashChain,
) -> AuthorizedReviewManager:
    return AuthorizedReviewManager(
        state_machine=state_machine,
        store=store,
        audit_chain=audit_chain,
    )


def _generate_test_dossier(investigator: DeterministicInvestigator, incident_id: str) -> Dict[str, Any]:
    alert = {
        "incident_id": incident_id,
        "service_id": "auth-service",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "priority": "high",
        "message": "Elevated 500 error rate on auth-service /verify endpoint",
    }
    result = investigator.investigate_incident(alert)
    return result["dossier"]


# ==============================================================================
# 1. HUM-01: Zero Auto-Remediation & Review Hold
# ==============================================================================

def test_hum01_zero_auto_remediation(
    investigator: DeterministicInvestigator,
    state_machine: InvestigationStateMachine,
) -> None:
    """HUM-01: Dossier newly created is held at HUMAN_REVIEW and 0 auto remediation actions triggered."""
    inc_id = "inc-c16-hum01-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    # 1. State machine is in HUMAN_REVIEW
    inc = state_machine.store.get_incident(inc_id)
    assert inc["current_state"] == "HUMAN_REVIEW"
    assert inc["status"] in ("HUMAN_REVIEW", "OPEN", "ACTIVE")

    # 2. Dossier review status is pending
    review_summary = dossier.get("review_summary", {})
    assert review_summary.get("status") == "PENDING_REVIEW"

    # 3. No auto actions in dossier: all recommended checks require human approval and disallow auto-execution
    rec_checks = dossier.get("recommended_checks", [])
    assert len(rec_checks) >= 1
    assert all(chk.get("requires_human_approval") is True for chk in rec_checks)
    assert all(chk.get("auto_execution_allowed") is False for chk in rec_checks)

    # 4. Strict check that illegal state machine transitions are rejected
    with pytest.raises(Exception):
        state_machine.transition(
            incident_id=inc_id,
            to_state="RECEIVED",
            idempotency_key="illegal-backward-transition",
            reason="Illegal bypass",
        )


# ==============================================================================
# 2. AT-010: Unauthorized Reviewer Rejected
# ==============================================================================

def test_at010_unauthorized_review_rejected(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    state_machine: InvestigationStateMachine,
) -> None:
    """AT-010: Reviewer without valid authorized role is rejected with UNAUTHORIZED / FORBIDDEN_SCOPE."""
    inc_id = "inc-c16-unauth-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    # Attempt sign-off by guest/unauthorized actor
    with pytest.raises(UnauthorizedReviewerError) as exc_info:
        review_manager.submit_review(
            incident_id=inc_id,
            dossier_dict=dossier,
            reviewer_ref="anonymous_intruder",
            reviewer_role="ANONYMOUS_GUEST",
            decision="APPROVE",
            rationale="Attempting unauthorized closure",
        )

    assert "UNAUTHORIZED" in str(exc_info.value) or exc_info.value.code in ("UNAUTHORIZED", "FORBIDDEN_SCOPE")

    # State machine remains in HUMAN_REVIEW
    inc = state_machine.store.get_incident(inc_id)
    assert inc["current_state"] == "HUMAN_REVIEW"


# ==============================================================================
# 3. AT-010: Rejection Flow
# ==============================================================================

def test_at010_rejection_flow(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    state_machine: InvestigationStateMachine,
) -> None:
    """AT-010: Reviewer rejects dossier, status transitions to REJECTED with rationale."""
    inc_id = "inc-c16-reject-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    review_res = review_manager.submit_review(
        incident_id=inc_id,
        dossier_dict=dossier,
        reviewer_ref="sre_lead_sarah",
        reviewer_role="L2_SRE",
        decision="REJECT",
        rationale="Investigation failed to check downstream database pool metrics.",
    )

    ev = review_res["review_event"]
    assert ev["decision"] == "reject"
    assert ev["auto_action_triggered"] is False
    assert "downstream database" in ev["rationale"]

    # Incident state machine is in REJECTED
    inc = state_machine.store.get_incident(inc_id)
    assert inc["current_state"] == "REJECTED"

    # History contains rejection
    history = review_manager.get_review_history(inc_id)
    assert len(history) == 1
    assert history[0]["decision"] == "reject"


# ==============================================================================
# 4. AT-010 & NFR-011: Correction Creates New Revision (Append-Only)
# ==============================================================================

def test_at010_correction_creates_new_revision(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    store: WorkflowStateStore,
) -> None:
    """AT-010 & NFR-011: Reviewer corrects hypothesis, creating revision v2 while v1 remains intact."""
    inc_id = "inc-c16-edit-001"
    dossier_v1 = _generate_test_dossier(investigator, inc_id)
    hash_v1 = dossier_v1["dossier_hash"]

    corrected_statement = "Database connection pool exhaustion on auth-db replica"
    corrections = {
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{inc_id}-001",
                "statement": corrected_statement,
                "status": "SUPPORTED",
            }
        ]
    }

    review_res = review_manager.submit_review(
        incident_id=inc_id,
        dossier_dict=dossier_v1,
        reviewer_ref="sre_expert_dan",
        reviewer_role="L2_SRE",
        decision="CORRECT",
        rationale="Refined root cause hypothesis based on secondary database replica connection stats.",
        edited_dossier_data=corrections,
    )

    # Revision 2 is generated
    dossier_v2 = review_res["new_dossier_revision"]
    assert dossier_v2 is not None
    assert dossier_v2["dossier_version"] == 2
    assert dossier_v2["dossier_hash"] != hash_v1
    assert dossier_v2["hypotheses"][0]["statement"] == corrected_statement

    # Both v1 and v2 are preserved append-only in the store
    stored_v1 = store.get_dossier(inc_id, version=1)
    stored_v2 = store.get_dossier(inc_id, version=2)
    assert stored_v1 is not None and stored_v1["dossier_version"] == 1
    assert stored_v2 is not None and stored_v2["dossier_version"] == 2
    assert stored_v1["dossier_hash"] != stored_v2["dossier_hash"]
    assert stored_v1["dossier_json"]["review_summary"]["status"] == "EDITED"
    assert stored_v2["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"


# ==============================================================================
# 5. Version-Bound Approval Conflict Guard
# ==============================================================================

def test_version_conflict_guard(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
) -> None:
    """Attempting to approve a stale/superseded revision v1 when v2 is active raises VERSION_CONFLICT."""
    inc_id = "inc-c16-conflict-001"
    dossier_v1 = _generate_test_dossier(investigator, inc_id)

    # Reviewer corrects to create v2
    review_manager.submit_review(
        incident_id=inc_id,
        dossier_dict=dossier_v1,
        reviewer_ref="sre_alice",
        reviewer_role="L1_SRE",
        decision="CORRECT",
        rationale="Updating observation scope.",
    )

    # Attempt to approve stale v1
    with pytest.raises(StaleDossierVersionError) as exc_info:
        review_manager.submit_review(
            incident_id=inc_id,
            dossier_dict=dossier_v1,  # Passing v1
            reviewer_ref="sre_lead_alex",
            reviewer_role="LEAD_SRE",
            decision="APPROVE",
            rationale="Accidentally signing stale revision.",
        )

    assert exc_info.value.code == "VERSION_CONFLICT"
    assert "VERSION_CONFLICT" in str(exc_info.value) or "Version conflict" in str(exc_info.value)


# ==============================================================================
# 6. Approval Seals Dossier and Audits to SHA-256 Chain
# ==============================================================================

def test_approval_seals_and_audits(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    state_machine: InvestigationStateMachine,
    audit_chain: AuditHashChain,
) -> None:
    """Approval transitions incident to CLOSED and cryptographically records event into AuditHashChain."""
    inc_id = "inc-c16-approve-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    review_res = review_manager.approve(
        incident_id=inc_id,
        dossier_dict=dossier,
        reviewer_ref="sre_lead_marcus",
        reviewer_role="LEAD_SRE",
        rationale="Telemetry evidence and runbook citations fully verified.",
    )

    # 1. State machine transitioned to CLOSED
    inc = state_machine.store.get_incident(inc_id)
    assert inc["current_state"] == "CLOSED"
    assert inc["status"] in ("CLOSED", "CLOSED_APPROVED")

    # 2. auto_action_triggered is false
    assert review_res["review_event"]["auto_action_triggered"] is False

    # 3. Audit hash chain contains sign-off event
    signoff_events = [e for e in audit_chain.events if e.get("action") == "HUMAN_REVIEW_DECISION"]
    assert len(signoff_events) >= 1
    signoff = signoff_events[0]
    assert signoff["actor_ref"] == "principal_reviewer"
    assert signoff["result_code"] == "ALLOW"
    assert signoff["reason_code"] == "OK"
    assert len(signoff["request_fingerprint"]) == 64

    # 4. Verify cryptographic integrity of the audit chain
    is_valid, violations = verify_chain_integrity(audit_chain.events)
    assert is_valid is True, f"Audit chain compromised: {violations}"


# ==============================================================================
# 7. AT-017 & ADR-S07: Dummy Ticket Creation Guard
# ==============================================================================

def test_at017_ticket_creation_guard(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    tmp_path: pathlib.Path,
) -> None:
    """AT-017: Ticket creation is strictly forbidden on non-approved dossiers, succeeds only after APPROVE."""
    inc_id = "inc-c16-ticket-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    ticket_file = tmp_path / "tickets.json"
    tm = DummyTicketManager(storage_path=ticket_file)

    # 1. Attempt ticket creation on PENDING_REVIEW dossier -> Rejected
    with pytest.raises(InvalidDossierStateError) as exc_info:
        tm.create_ticket_from_dossier(dossier)
    assert exc_info.value.code == "INVALID_DOSSIER_STATE"

    # 2. Reject the dossier and attempt ticket creation -> Rejected
    review_manager.reject(
        incident_id=inc_id,
        dossier_dict=dossier,
        reviewer_ref="sre_bob",
        reviewer_role="L2_SRE",
        rationale="Rejected due to incomplete metrics.",
    )
    rejected_dossier = dict(dossier)
    rejected_dossier["review_summary"] = {"status": "REJECTED"}
    with pytest.raises(InvalidDossierStateError) as exc_info:
        tm.create_ticket_from_dossier(rejected_dossier)
    assert exc_info.value.code == "INVALID_DOSSIER_STATE"

    # 3. Create fresh incident and approve it -> Ticket creation succeeds
    inc_id_2 = "inc-c16-ticket-002"
    dossier_2 = _generate_test_dossier(investigator, inc_id_2)
    app_res = review_manager.approve(
        incident_id=inc_id_2,
        dossier_dict=dossier_2,
        reviewer_ref="sre_lead_alex",
        reviewer_role="LEAD_SRE",
        rationale="Sign-off verified, ready for ITSM handover.",
    )

    ticket = tm.create_ticket_from_dossier(app_res["updated_dossier"])
    assert ticket["ticket_id"].startswith("TICK-")
    assert ticket["incident_id"] == inc_id_2
    assert ticket["revision_number"] == 1
    assert "sre_lead_alex" in ticket["approved_by"]
    assert ticket["primary_hypothesis"] is not None
    assert isinstance(ticket["sop_references"], list)
    assert ticket["auto_action_triggered"] is False

    # Persisted to disk
    assert ticket_file.exists()
    saved_tickets = tm.list_tickets(inc_id_2)
    assert len(saved_tickets) == 1
    assert saved_tickets[0]["ticket_id"] == ticket["ticket_id"]


# ==============================================================================
# 8. FR-OUT-005 & RULE-002: Handover Export Ground-Truth Isolation
# ==============================================================================

def test_handover_export_isolation(
    investigator: DeterministicInvestigator,
    review_manager: AuthorizedReviewManager,
    tmp_path: pathlib.Path,
) -> None:
    """FR-OUT-005: Handover export produces 3 artifacts and strips ground truth attributes."""
    inc_id = "inc-c16-export-001"
    dossier = _generate_test_dossier(investigator, inc_id)

    # Intentionally inject ground truth leakage markers into test payload
    dossier["scenario_id"] = "SC-02-auth-token-failure"
    dossier["expected_root_cause"] = "Token verification timeout"
    dossier["ground_truth"] = {"recipe_id": "RC-99", "restricted_path": "restricted/gt_registry/sc02.json"}
    if "impact_summary" in dossier:
        dossier["impact_summary"]["internal_gt_leak"] = "Evaluated against restricted/gt_registry/gold.json"
    dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)

    # Approve dossier
    app_res = review_manager.approve(
        incident_id=inc_id,
        dossier_dict=dossier,
        reviewer_ref="sre_reviewer",
        reviewer_role="L2_SRE",
    )

    export_dir = tmp_path / "handover"
    exporter = HandoverExporter(export_root=export_dir)
    history = review_manager.get_review_history(inc_id)

    exported = exporter.export_handover_package(
        incident_id=inc_id,
        dossier_dict=app_res["updated_dossier"],
        review_history=history,
    )

    # 1. All 3 artifacts exist
    assert exported["json"].exists()
    assert exported["markdown"].exists()
    assert exported["html"].exists()

    # 2. Read dossier_final.json and verify isolation
    final_json = json.loads(exported["json"].read_text(encoding="utf-8"))
    is_clean, violations = verify_ground_truth_isolation(final_json)
    assert is_clean is True, f"Ground truth leaked into final JSON: {violations}"
    assert "scenario_id" not in final_json
    assert "expected_root_cause" not in final_json
    assert "ground_truth" not in final_json

    # 3. Read Markdown and HTML to verify no raw leakage of restricted paths
    md_text = exported["markdown"].read_text(encoding="utf-8")
    assert "restricted/gt_registry/" not in md_text
    assert "scenario_id" not in md_text

    html_text = exported["html"].read_text(encoding="utf-8")
    assert "restricted/gt_registry/" not in html_text
    assert "Zero Auto-Remediation" in html_text


# ==============================================================================
# 9. Review Console Non-Interactive CLI Flow
# ==============================================================================

def test_review_console_cli_execution(
    investigator: DeterministicInvestigator,
    tmp_path: pathlib.Path,
) -> None:
    """CLI review console executes actions cleanly without interactive prompts."""
    inc_id = "inc-c16-console-001"
    dossier = _generate_test_dossier(investigator, inc_id)
    dossier_file = tmp_path / "dossier.json"
    dossier_file.write_text(json.dumps(dossier, indent=2), encoding="utf-8")

    # Test summary display output
    display_dossier_summary(dossier)

    # Test automated execution
    res = run_review_action(
        dossier=dossier,
        action="APPROVE",
        reviewer_ref="sre_alex",
        reviewer_role="L2_SRE",
        rationale="Approved via non-interactive console test.",
        export_handover=True,
        create_ticket=True,
    )

    assert res["action"] == "APPROVE"
    assert res["incident_id"] == inc_id
    assert "handover_export" in res["artifacts"]
    assert "ticket" in res["artifacts"]
    assert res["artifacts"]["ticket"]["auto_action_triggered"] is False
