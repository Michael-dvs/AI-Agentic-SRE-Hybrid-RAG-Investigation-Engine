"""P0-02 Regression Suite — Human Review Approval Semantics, State Safety, Auditability & Integration.

Covers all required scenarios in P0-02 Section 10:
- Group A (A1-A8): Approval semantics across SUPPORTED, PARTIAL, INCONCLUSIVE, UNSUPPORTED, CONTRADICTED, NO_APPLICABLE_RUNBOOK.
- Group B (B1-B5): REJECT, CORRECT (preserving AI findings & immutable evidence), ESCALATE, and audit context.
- Group C (C1-C6): Unauthorized reviewer, invalid lifecycle transitions, duplicate/concurrent approval, conflicting finalized decisions, stale version, invalid dossiers.
- Group D (D1-D6): AI-actor rejection, zero auto-remediation, Policy Gateway preservation, GT isolation, RULE-007, fail-closed audit integrity.
- Group E (E1-E7): CLI/TUI parity, SQLite persistence, dossier.v1 schema validation, DummyTicketManager, Evaluator gating, P0-01 preservation, HandoverExporter.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import pathlib
from typing import Any, Dict

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from evaluator.runner import EvaluationBlocked, join_dev
from gateway.audit import SecurityAuditLogger
from gateway.policy import PolicyGateway
from observability.audit_chain import AuditHashChain, AuditWriteError, verify_chain_integrity
from orchestrator.claim_validator_contract import ClaimValidator, HypothesisStatus
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer, compute_canonical_dossier_hash
from orchestrator.handover import HandoverExporter, verify_ground_truth_isolation
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.llm_investigator import LLMInvestigator, LLMRunLedger
from orchestrator.llm_provider import ProviderReply, ReplayProvider
from orchestrator.review import (
    AuthorizedReviewManager,
    DossierHashMismatchError,
    InvalidDossierError,
    ReviewError,
    ReviewStateConflictError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
    build_human_correction_payload,
)
from orchestrator.state_machine import (
    InvalidStateTransitionError,
    InvestigationStateMachine,
    WorkflowStateStore,
    utc_now_z,
)
from orchestrator.ticketing import DummyTicketManager, InvalidDossierStateError
from orchestrator.usability_console import ReviewActionController
from scripts.review_console import run_review_action


def _make_dossier(
    incident_id: str,
    *,
    support_status: str = "PARTIAL",
    validation_status: str | None = None,
    supporting_ids: list[str] | None = None,
    contradicting_ids: list[str] | None = None,
    with_sop: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ev_log = {
        "evidence_id": f"ev-{incident_id}-001",
        "tool_name": "search_error_logs",
        "service_id": "api-gateway",
        "source_ref": "loki",
        "observed_at": "2026-11-23T03:44:28Z",
        "data_quality": "complete",
        "sanitized": True,
        "records": [
            {
                "service_id": "api-gateway",
                "status_code": 503,
                "error_code": "ERR_DEPENDENCY_UNAVAILABLE",
                "message": "ERR_DEPENDENCY_UNAVAILABLE: Downstream dependency refused connection",
            }
        ],
    }
    ev_rate = {
        "evidence_id": f"ev-{incident_id}-002",
        "tool_name": "get_service_metrics",
        "service_id": "api-gateway",
        "source_ref": "prometheus",
        "observed_at": "2026-11-23T03:44:28Z",
        "data_quality": "complete",
        "sanitized": True,
        "records": [
            {"service_id": "api-gateway", "metric_enum": "request_rate", "value": 0.4833},
        ],
    }
    sup = [ev_log["evidence_id"]] if supporting_ids is None else list(supporting_ids)
    con = [] if contradicting_ids is None else list(contradicting_ids)
    val_stat = validation_status or support_status
    cit = (
        [
            {
                "chunk_id": "chk-gw-001",
                "document_id": "SOP-GW-001",
                "service_id": "api-gateway",
                "environment": "lab",
                "status": "approved",
                "title": "Dependency errors",
                "effective_from": "2026-11-01T00:00:00Z", "effective_to": None,
                "content_hash": "a" * 64, "score": 0.03, "score_type": "rrf_fusion", "source_branch": "hybrid",
                "document_version": "1.0.0",
                "section_path": "/dependency-errors",
                "source_uri": "kb://sop/sop-gw-001.md",
                "applicability_verified": True,
                "sanitized_excerpt": "Inspect downstream service health before manual intervention.",
                "sanitized": True,
            }
        ]
        if with_sop
        else []
    )
    context: dict[str, Any] = {
        "incident_id": incident_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-23T03:44:14Z",
        "priority": "high",
        "investigation_scope": ["api-gateway", "transaction-service"],
        "query_window": {"start": "2026-11-23T03:39:14Z", "end": "2026-11-23T03:45:14Z"},
        "evidence_items": [ev_log, ev_rate],
        "runbook_citations": cit,
        "sop_availability": "APPLICABLE_SOP_FOUND" if with_sop else "NO_APPLICABLE_RUNBOOK",
        "no_applicable_runbook": not with_sop,
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "title": "api-gateway downstream dependency failure",
                "description": "Downstream dependency refused connection causing 503.",
                "status": support_status,
                "validation_status": val_stat,
                "supporting_evidence_ids": sup,
                "contradicting_evidence_ids": con,
                "unknowns": ["Downstream instance restart state unknown."],
            }
        ],
        "unknowns": [
            "Downstream instance restart state unknown.",
            "api-gateway rate limit configuration values unavailable.",
        ],
        "validation_reports": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "status": val_stat,
                "reason_codes": ["NO_APPLICABLE_RUNBOOK"] if not with_sop else ["CLAIM_CORROBORATED"],
                "claims": [],
                "contradictions": [],
                "unknowns": ["Downstream instance restart state unknown."],
                "supporting_evidence_ids": sup,
                "contradicting_evidence_ids": con,
                "rejected_sop_citations": [],
                "valid_sop_citations": cit,
            }
        ],
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "model_version": "synthetic-replay",
            "prompt_version": "prompt-p0-02",
            "tool_schema_version": "1.0",
            "kb_version": "kb-idx-20261111-v1",
        },
    }
    dossier = DossierSerializer.serialize(context, revision=1, investigation_mode="agentic_llm")
    return dossier, context


def _setup_review_env(
    tmp_path: pathlib.Path,
    incident_id: str,
    *,
    support_status: str = "PARTIAL",
    validation_status: str | None = None,
    supporting_ids: list[str] | None = None,
    contradicting_ids: list[str] | None = None,
    with_sop: bool = False,
    initial_state: str = "HUMAN_REVIEW",
) -> tuple[WorkflowStateStore, InvestigationStateMachine, AuditHashChain, AuthorizedReviewManager, dict[str, Any]]:
    store = WorkflowStateStore(str(tmp_path / f"{incident_id}.db"))
    sm = InvestigationStateMachine(store=store)
    audit = AuditHashChain(log_path=tmp_path / f"{incident_id}-audit.jsonl")
    rm = AuthorizedReviewManager(state_machine=sm, store=store, audit_chain=audit)
    dossier, ctx = _make_dossier(
        incident_id,
        support_status=support_status,
        validation_status=validation_status,
        supporting_ids=supporting_ids,
        contradicting_ids=contradicting_ids,
        with_sop=with_sop,
    )
    store.create_incident(
        incident_id=incident_id,
        service_id="api-gateway",
        environment="lab",
        initial_state=initial_state,
        status="ACTIVE",
    )
    store.save_checkpoint(incident_id, initial_state, ctx)
    store.save_dossier(
        incident_id=incident_id,
        dossier_version=1,
        dossier_hash=dossier["dossier_hash"],
        dossier_json=dossier,
        dossier_markdown=DossierMarkdownRenderer.render(dossier),
    )
    return store, sm, audit, rm, dossier


# ==============================================================================
# GROUP A — Approval Semantics (A1-A8)
# ==============================================================================


@pytest.mark.parametrize(
    ("case_id", "support_status", "validation_status", "sup_ids", "con_ids", "with_sop", "expected_val"),
    [
        ("a1-supported", "SUPPORTED", "SUPPORTED", ["ev-inc-a1-supported-001"], [], True, "SUPPORTED"),
        ("a2-partial", "PARTIAL", "PARTIAL", ["ev-inc-a2-partial-001"], [], True, "PARTIAL"),
        ("a3-inconclusive", "INCONCLUSIVE", "INCONCLUSIVE", [], [], False, "INCONCLUSIVE"),
        ("a4-unsupported", "INCONCLUSIVE", "UNSUPPORTED", [], [], False, "UNSUPPORTED"),
        ("a5-contradicted", "INCONCLUSIVE", "CONTRADICTED", [], ["ev-inc-a5-contradicted-002"], False, "CONTRADICTED"),
        ("a6-no-sop", "PARTIAL", "PARTIAL", ["ev-inc-a6-no-sop-001"], [], False, "PARTIAL"),
    ],
)
def test_group_a_approve_semantics_preserve_diagnosis_and_uncertainty(
    tmp_path: pathlib.Path,
    case_id: str,
    support_status: str,
    validation_status: str,
    sup_ids: list[str],
    con_ids: list[str],
    with_sop: bool,
    expected_val: str,
) -> None:
    """A1-A8: APPROVE accepts dossier handover without verifying unconfirmed diagnosis or enabling remediation."""
    inc_id = f"inc-{case_id}"
    store, _, audit, rm, dossier = _setup_review_env(
        tmp_path,
        inc_id,
        support_status=support_status,
        validation_status=validation_status,
        supporting_ids=sup_ids,
        contradicting_ids=con_ids,
        with_sop=with_sop,
    )
    try:
        orig_hyp = copy.deepcopy(dossier["hypotheses"])
        orig_unknowns = copy.deepcopy(dossier["unknowns"])
        orig_missing = copy.deepcopy(dossier["missing_sources"])
        orig_evidence = copy.deepcopy(dossier["evidence"])

        res = rm.approve(
            incident_id=inc_id,
            dossier_dict=dossier,
            reviewer_ref="sre_lead_maria",
            reviewer_role="L2_SRE",
        )
        updated = res["updated_dossier"]
        sem = res["approval_semantics"]
        rev_ev = res["review_event"]

        # Lifecycle & review status vs diagnostic status
        assert updated["review_summary"]["status"] == "APPROVED"
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert sem["dossier_review_status"] == "APPROVED"
        assert sem["dossier_accepted_for_handover"] is True
        assert sem["closure_meaning"] == "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED"
        assert sem["diagnosis_verified"] is False
        assert sem["root_cause_proven"] is False
        assert sem["remediation_authorized"] is False
        assert sem["auto_action_triggered"] is False
        assert sem["has_applicable_runbook"] is with_sop
        assert sem["diagnostic_validation_statuses"][f"hyp-{inc_id}-001"] == expected_val

        # Original diagnostic fields & uncertainty preserved verbatim (never upgraded to VERIFIED)
        assert updated["hypotheses"] == orig_hyp
        assert updated["hypotheses"][0]["support_status"] == support_status
        assert updated["unknowns"] == orig_unknowns
        assert updated["missing_sources"] == orig_missing
        assert updated["evidence"] == orig_evidence
        assert "VERIFIED" not in json.dumps(updated["hypotheses"]).upper()
        assert "VERIFIED" not in json.dumps(updated["review_summary"]).upper()

        # A8: Zero auto-execution
        assert rev_ev["auto_action_triggered"] is False
        assert all(c["auto_execution_allowed"] is False for c in updated["recommended_checks"])
        assert all(c["requires_human_approval"] is True for c in updated["recommended_checks"])

        # Audit chain valid
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


# ==============================================================================
# GROUP B — Other Review Decisions (B1-B5)
# ==============================================================================


def test_group_b1_reject_prevents_approval_and_closure(tmp_path: pathlib.Path) -> None:
    """B1: REJECT records rejection without handover approval, CLOSED state, or ticket creation."""
    inc_id = "inc-b1-reject"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        res = rm.reject(
            incident_id=inc_id,
            dossier_dict=dossier,
            reviewer_ref="sre_maya",
            reviewer_role="L2_SRE",
            rationale="Evidence does not isolate upstream dependency cause.",
        )
        assert res["review_event"]["decision"] == "reject"
        assert res["review_event"]["auto_action_triggered"] is False
        assert res["updated_dossier"]["review_summary"]["status"] == "REJECTED"
        assert res["approval_semantics"]["dossier_accepted_for_handover"] is False
        inc = store.get_incident(inc_id)
        assert inc["current_state"] == "REJECTED"
        assert inc["status"] == "REJECTED"

        tm = DummyTicketManager(storage_path=tmp_path / "tickets.json")
        with pytest.raises(InvalidDossierStateError):
            tm.create_ticket_from_dossier(res["updated_dossier"])

        assert any(e["action"] == "HUMAN_REVIEW_DECISION" for e in audit.events)
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


def test_group_b2_b3_correct_preserves_original_ai_findings_and_evidence(tmp_path: pathlib.Path) -> None:
    """B2 & B3: CORRECT preserves v1, keeps original AI hypotheses inside v2, and protects telemetry/SOP."""
    inc_id = "inc-b2-correct"
    store, _, audit, rm, dossier_v1 = _setup_review_env(tmp_path, inc_id, with_sop=True)
    try:
        orig_evidence = copy.deepcopy(dossier_v1["evidence"])
        orig_sops = copy.deepcopy(dossier_v1["sop_citations"])
        orig_ai_hyp = copy.deepcopy(dossier_v1["hypotheses"][0])

        correction = build_human_correction_payload(
            dossier_v1,
            "Corrected candidate: ledger-service connection pool timeout triggered gateway 503.",
            reviewer_ref="sre_dan",
            reviewer_role="L2_SRE",
        )
        res = rm.correct(
            incident_id=inc_id,
            dossier_dict=dossier_v1,
            reviewer_ref="sre_dan",
            reviewer_role="L2_SRE",
            rationale="Adding candidate explanation while retaining AI telemetry findings.",
            corrections={
                **correction,
                "evidence": [],  # Attempted overwrite must be ignored
                "sop_citations": [],  # Attempted overwrite must be ignored
                "alert_received_at": "2099-01-01T00:00:00Z",  # Must be ignored
                "unknowns": ["Human note: verify ledger pool max_connections."],
            },
        )
        v2 = res["new_dossier_revision"]
        assert v2 is not None
        assert v2["dossier_version"] == 2
        assert v2["review_summary"]["status"] == "PENDING_REVIEW"
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"

        # Evidence & citations & alert time cannot be silently overwritten
        assert v2["evidence"] == orig_evidence
        assert v2["sop_citations"] == orig_sops
        assert v2["alert_received_at"] == dossier_v1["alert_received_at"]

        # Human correction is rank 1 INCONCLUSIVE (not SUPPORTED/VERIFIED without evidence)
        assert v2["hypotheses"][0]["support_status"] == "INCONCLUSIVE"
        assert "[Human Correction by sre_dan (L2_SRE)]" in v2["hypotheses"][0]["reason_summary"]

        # Original AI hypothesis preserved at rank 2 with original evidence & status
        assert len(v2["hypotheses"]) == 2
        assert v2["hypotheses"][1]["statement"] == orig_ai_hyp["statement"]
        assert v2["hypotheses"][1]["support_status"] == orig_ai_hyp["support_status"]
        assert v2["hypotheses"][1]["supporting_evidence_ids"] == orig_ai_hyp["supporting_evidence_ids"]
        assert "[Original AI Finding]" in v2["hypotheses"][1]["reason_summary"]

        # Unknowns merged rather than wiped
        assert any("Downstream instance" in u for u in v2["unknowns"])
        assert any("ledger pool max_connections" in u for u in v2["unknowns"])

        # Schema valid & audited
        Draft202012Validator(DossierSerializer.get_schema(), format_checker=FormatChecker()).validate(v2)
        assert any(e["action"] == "HUMAN_REVIEW_DECISION" for e in audit.events)
    finally:
        store.close()


def test_group_b4_b5_escalate_and_all_decisions_audit_context(tmp_path: pathlib.Path) -> None:
    """B4 & B5: ESCALATE routes to MANUAL_TRIAGE_REQUIRED without resolution; all decisions emit schema-valid audit."""
    inc_id = "inc-b4-escalate"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        res = rm.escalate(
            incident_id=inc_id,
            dossier_dict=dossier,
            reviewer_ref="sre_l1_nina",
            reviewer_role="L1_SRE",
            rationale="Missing runbook and inconclusive trace require L2 incident commander.",
            escalation_target="L2_INCIDENT_COMMANDER",
        )
        ev = res["review_event"]
        assert ev["decision"] == "escalate_manual"
        assert ev["escalation_target"] == "L2_INCIDENT_COMMANDER"
        assert ev["auto_action_triggered"] is False
        assert res["updated_dossier"]["review_summary"]["status"] == "MANUAL_TRIAGE"
        assert res["approval_semantics"]["dossier_accepted_for_handover"] is False
        assert store.get_incident(inc_id)["current_state"] == "MANUAL_TRIAGE_REQUIRED"
        assert store.get_incident(inc_id)["status"] == "MANUAL_TRIAGE_REQUIRED"

        # Audit entry contains incident, target version, hash integrity
        assert len(audit.events) == 1
        aud = audit.events[0]
        assert aud["incident_id"] == inc_id
        assert aud["target_ref"] == f"{inc_id}:v1"
        assert aud["action"] == "HUMAN_REVIEW_DECISION"
        assert aud["result_code"] == "ALLOW"
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


# ==============================================================================
# GROUP C — Invalid & Unauthorized Actions (C1-C6)
# ==============================================================================


def test_group_c1_unauthorized_reviewer_denied_and_audited(tmp_path: pathlib.Path) -> None:
    """C1: Unauthorized role is denied before DB write and recorded as DENY in audit."""
    inc_id = "inc-c1-unauth"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(
                incident_id=inc_id,
                dossier_dict=dossier,
                reviewer_ref="guest_user",
                reviewer_role="GUEST",
            )
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
        assert audit.events[-1]["reason_code"] == "FORBIDDEN_SCOPE"
    finally:
        store.close()


@pytest.mark.parametrize("bad_state", ["RECEIVED", "HYPOTHESES", "VALIDATED", "DRAFTED"])
def test_group_c2_incomplete_lifecycle_state_rejected(tmp_path: pathlib.Path, bad_state: str) -> None:
    """C2: Review decisions in incomplete lifecycle states are rejected before any DB mutation."""
    inc_id = f"inc-c2-{bad_state.lower()}"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id, initial_state=bad_state)
    try:
        with pytest.raises(ReviewStateConflictError):
            rm.approve(
                incident_id=inc_id,
                dossier_dict=dossier,
                reviewer_ref="sre_lead_alex",
                reviewer_role="L2_SRE",
            )
        assert store.get_incident(inc_id)["current_state"] == bad_state
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
    finally:
        store.close()


def test_group_c3_duplicate_and_concurrent_approval_blocked(tmp_path: pathlib.Path) -> None:
    """C3: Duplicate or concurrent APPROVE cannot double-finalize or duplicate side effects."""
    inc_id = "inc-c3-dup"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        def _attempt(idx: int) -> str:
            try:
                rm.approve(
                    incident_id=inc_id,
                    dossier_dict=dossier,
                    reviewer_ref=f"sre_reviewer_{idx}",
                    reviewer_role="L2_SRE",
                )
                return "OK"
            except (ReviewStateConflictError, StaleDossierVersionError):
                return "REJECTED"

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(_attempt, range(4)))

        assert outcomes.count("OK") == 1
        assert outcomes.count("REJECTED") == 3
        assert len(store.get_reviews(inc_id)) == 1
        closure_events = [e for e in audit.events if e["action"] == "WORKFLOW_TRANSITION" and e["result_code"] == "ALLOW"]
        assert len(closure_events) == 1
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


@pytest.mark.parametrize(
    ("first_action", "second_action"),
    [
        ("approve", "reject"),
        ("approve", "edit"),
        ("approve", "escalate_manual"),
        ("reject", "approve"),
        ("reject", "edit"),
        ("reject", "escalate_manual"),
        ("escalate_manual", "approve"),
        ("escalate_manual", "reject"),
        ("escalate_manual", "edit"),
    ],
)
def test_group_c4_conflicting_finalized_decisions_rejected(
    tmp_path: pathlib.Path,
    first_action: str,
    second_action: str,
) -> None:
    """C4: Conflicting decisions after finalization are rejected both by ReviewManager and StateMachine."""
    inc_id = f"inc-c4-{first_action[:3]}-{second_action[:3]}"
    store, sm, _, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        rm.submit_review(
            incident_id=inc_id,
            dossier_dict=dossier,
            reviewer_ref="sre_first",
            reviewer_role="L2_SRE",
            decision=first_action,
            rationale=f"First finalizing decision: {first_action}",
        )
        latest = store.get_dossier(inc_id)["dossier_json"]
        with pytest.raises(ReviewStateConflictError):
            rm.submit_review(
                incident_id=inc_id,
                dossier_dict=latest,
                reviewer_ref="sre_second",
                reviewer_role="L2_SRE",
                decision=second_action,
                rationale=f"Conflicting second decision: {second_action}",
            )
        assert len(store.get_reviews(inc_id)) == 1
        if first_action != "approve":
            with pytest.raises(InvalidStateTransitionError):
                sm.transition(inc_id, "CLOSED", idempotency_key=f"illegal-{inc_id}")
        else:
            with pytest.raises(InvalidStateTransitionError):
                sm.transition(inc_id, "REJECTED", idempotency_key=f"illegal-{inc_id}")
    finally:
        store.close()


def test_group_c5_stale_review_rejected(tmp_path: pathlib.Path) -> None:
    """C5: Stale v1 submission after v2 edit is rejected with VERSION_CONFLICT."""
    inc_id = "inc-c5-stale"
    store, _, audit, rm, dossier_v1 = _setup_review_env(tmp_path, inc_id)
    try:
        rm.correct(
            incident_id=inc_id,
            dossier_dict=dossier_v1,
            reviewer_ref="sre_editor",
            reviewer_role="L2_SRE",
            rationale="Generating v2 revision.",
        )
        with pytest.raises(StaleDossierVersionError) as exc_info:
            rm.approve(
                incident_id=inc_id,
                dossier_dict=dossier_v1,
                reviewer_ref="sre_approver",
                reviewer_role="LEAD_SRE",
            )
        assert exc_info.value.code == "VERSION_CONFLICT"
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert audit.events[-1]["result_code"] == "DENY"
        assert audit.events[-1]["reason_code"] == "VERSION_CONFLICT"
    finally:
        store.close()


def test_group_c6_invalid_dossiers_cannot_be_finalized(tmp_path: pathlib.Path) -> None:
    """C6: Tampered hash, missing hash, mismatched incident ID, empty hypotheses, VERIFIED, or auto_exec are rejected."""
    inc_id = "inc-c6-invalid"
    store, _, _, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        tampered = copy.deepcopy(dossier)
        tampered["severity"] = "low"
        with pytest.raises(DossierHashMismatchError):
            rm.approve(inc_id, tampered, "sre_alex", "L2_SRE")

        missing_hash = copy.deepcopy(dossier)
        del missing_hash["dossier_hash"]
        with pytest.raises(InvalidDossierError):
            rm.approve(inc_id, missing_hash, "sre_alex", "L2_SRE")

        wrong_inc = copy.deepcopy(dossier)
        wrong_inc["incident_id"] = "inc-other-service"
        wrong_inc["dossier_hash"] = compute_canonical_dossier_hash(wrong_inc)
        with pytest.raises(InvalidDossierError):
            rm.approve(inc_id, wrong_inc, "sre_alex", "L2_SRE")

        empty_hyps = copy.deepcopy(dossier)
        empty_hyps["hypotheses"] = []
        empty_hyps["dossier_hash"] = compute_canonical_dossier_hash(empty_hyps)
        with pytest.raises(InvalidDossierError):
            rm.approve(inc_id, empty_hyps, "sre_alex", "L2_SRE")

        verified_hyp = copy.deepcopy(dossier)
        verified_hyp["hypotheses"][0]["support_status"] = "VERIFIED"
        verified_hyp["dossier_hash"] = compute_canonical_dossier_hash(verified_hyp)
        with pytest.raises(InvalidDossierError, match="RULE-007"):
            rm.approve(inc_id, verified_hyp, "sre_alex", "L2_SRE")

        auto_exec = copy.deepcopy(dossier)
        auto_exec["recommended_checks"][0]["auto_execution_allowed"] = True
        auto_exec["dossier_hash"] = compute_canonical_dossier_hash(auto_exec)
        with pytest.raises(InvalidDossierError, match="INV-01"):
            rm.approve(inc_id, auto_exec, "sre_alex", "L2_SRE")

        short_rat = copy.deepcopy(dossier)
        with pytest.raises(ReviewError):
            rm.approve(inc_id, short_rat, "sre_alex", "L2_SRE", rationale="ok")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
    finally:
        store.close()


# ==============================================================================
# GROUP D — Security Invariants (D1-D6)
# ==============================================================================


@pytest.mark.parametrize(
    "ai_actor",
    ["principal_investigator", "ai_agent_01", "llm_investigator", "auto_remediator", "bot-reviewer"],
)
def test_group_d1_ai_actors_cannot_submit_review_decisions(tmp_path: pathlib.Path, ai_actor: str) -> None:
    """D1: Automated/AI identities cannot approve, reject, correct, or escalate."""
    inc_id = "inc-d1-ai-actor"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        for decision in ("approve", "reject", "edit", "escalate_manual"):
            with pytest.raises(UnauthorizedReviewerError):
                rm.submit_review(
                    incident_id=inc_id,
                    dossier_dict=dossier,
                    reviewer_ref=ai_actor,
                    reviewer_role="L2_SRE",
                    decision=decision,
                    rationale="Automated actor attempting review bypass.",
                )
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert all(e["result_code"] == "DENY" for e in audit.events)
    finally:
        store.close()


def test_group_d2_d3_zero_remediation_and_policy_gateway_intact(tmp_path: pathlib.Path) -> None:
    """D2 & D3: Review actions trigger zero remediation and Policy Gateway remains read-only."""
    gateway = PolicyGateway()
    gw_res = gateway.execute_tool(
        tool_name="restart_service",
        arguments={"service_id": "api-gateway"},
        token="Bearer sre-sim-coord-token-secret-2026",
        incident_id="inc-d3-gateway",
    )
    assert gw_res["status"] == "rejected"
    assert gw_res["error_code"] == "TOOL_NOT_ALLOWED"

    inc_id = "inc-d2-zero-rem"
    store, _, _, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        res = rm.approve(inc_id, dossier, "sre_human", "L2_SRE")
        assert res["review_event"]["auto_action_triggered"] is False
        assert res["approval_semantics"]["remediation_authorized"] is False
    finally:
        store.close()


def test_group_d4_d5_gt_isolation_and_rule007_enforced_on_corrections(tmp_path: pathlib.Path) -> None:
    """D4 & D5: Ground truth injections and VERIFIED claims in human corrections are rejected."""
    inc_id = "inc-d4-gt"
    store, _, _, rm, dossier = _setup_review_env(tmp_path, inc_id)
    try:
        with pytest.raises(InvalidDossierError, match="Ground Truth"):
            rm.correct(
                incident_id=inc_id,
                dossier_dict=dossier,
                reviewer_ref="sre_human",
                reviewer_role="L2_SRE",
                rationale="Attempting to inject restricted GT field.",
                corrections={"ground_truth": {"fault": "injected"}},
            )
        with pytest.raises(InvalidDossierError, match="RULE-007"):
            build_human_correction_payload(dossier, "VERIFIED root cause is DB outage", "sre_human", "L2_SRE")
        assert store.get_latest_dossier_version(inc_id) == 1
    finally:
        store.close()


def test_group_d6_audit_failure_prevents_finalization_fail_closed(tmp_path: pathlib.Path) -> None:
    """D6: If required audit persistence fails, review is NOT persisted or finalized."""
    inc_id = "inc-d6-audit-fail"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id)

    def _boom(**kwargs: Any) -> dict[str, Any]:
        raise AuditWriteError("Simulated audit disk failure")

    audit.record_event = _boom  # type: ignore[method-assign]
    try:
        with pytest.raises(AuditWriteError):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_dossier(inc_id)["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
    finally:
        store.close()


# ==============================================================================
# GROUP E — Integration (E1-E7)
# ==============================================================================


@pytest.mark.parametrize("action", ["APPROVE", "REJECT", "CORRECT", "ESCALATE"])
def test_group_e1_e2_e3_cli_and_tui_consistent_semantics_and_persistence(
    tmp_path: pathlib.Path,
    action: str,
) -> None:
    """E1-E3: CLI (run_review_action) and TUI (ReviewActionController) produce consistent semantics, state, and valid dossier.v1."""
    inc_cli = f"inc-e1-cli-{action.lower()}"
    inc_tui = f"inc-e1-tui-{action.lower()}"
    store_cli, _, audit_cli, _, dos_cli = _setup_review_env(tmp_path, inc_cli)
    store_tui, _, _, _, dos_tui = _setup_review_env(tmp_path, inc_tui)
    try:
        cli_res = run_review_action(
            dos_cli,
            action,
            reviewer_ref="sre_operator",
            reviewer_role="L2_SRE",
            rationale=f"CLI executing {action} decision.",
            store=store_cli,
            corrected_hypothesis="Human candidate via CLI." if action == "CORRECT" else None,
            escalation_target="L2_ONCALL" if action == "ESCALATE" else None,
            audit_chain=audit_cli,
            handover_root=tmp_path / "cli_handover",
            ticket_storage_path=tmp_path / "cli_tickets.json",
        )

        tui_ctrl = ReviewActionController(
            store_tui,
            audit_path=tmp_path / f"tui-{action.lower()}-audit.jsonl",
            handover_root=tmp_path / "tui_handover",
        )
        tui_res = tui_ctrl.apply(
            dos_tui,
            action,
            reviewer_ref="sre_operator",
            reviewer_role="L2_SRE",
            rationale=f"TUI executing {action} decision.",
            corrected_hypothesis="Human candidate via TUI." if action == "CORRECT" else None,
            escalation_target="L2_ONCALL" if action == "ESCALATE" else None,
        )

        cli_sem = cli_res["approval_semantics"]
        tui_sem = tui_res["approval_semantics"]
        assert cli_sem["dossier_review_status"] == tui_sem["dossier_review_status"]
        assert cli_sem["resulting_lifecycle_state"] == tui_sem["resulting_lifecycle_state"]
        assert cli_sem["diagnosis_verified"] is tui_sem["diagnosis_verified"] is False
        assert cli_sem["remediation_authorized"] is tui_sem["remediation_authorized"] is False
        assert store_cli.get_incident(inc_cli)["current_state"] == store_tui.get_incident(inc_tui)["current_state"]

        latest_tui = store_tui.get_dossier(inc_tui)["dossier_json"]
        Draft202012Validator(DossierSerializer.get_schema(), format_checker=FormatChecker()).validate(latest_tui)
    finally:
        store_cli.close()
        store_tui.close()


def test_group_e4_e5_e7_ticketing_evaluator_gating_and_handover(tmp_path: pathlib.Path) -> None:
    """E4, E5, E7: Evaluator blocked until APPROVE->CLOSED with bound closure audit; ticketing & handover enforce semantics."""
    inc_id = "inc-e5-eval"
    store, _, audit, rm, dossier = _setup_review_env(tmp_path, inc_id, support_status="PARTIAL", with_sop=False)
    dev_dir = tmp_path / "dev_gt"
    out_dir = tmp_path / "eval_out"
    run_dir = tmp_path / "runtime"
    for p in (dev_dir, out_dir, run_dir):
        p.mkdir(mode=0o700)
    gt_file = dev_dir / "run-e5.json"
    gt_file.write_text(json.dumps({"run_id": "run-e5", "incident_id": inc_id, "split_id": "dev", "cause": "downstream"}))
    gt_file.chmod(0o600)

    try:
        # E5: Premature evaluation blocked while in HUMAN_REVIEW
        with pytest.raises(EvaluationBlocked, match="PREMATURE_EVALUATION_BLOCKED"):
            join_dev(
                store=store,
                audit_events=list(audit.events),
                trusted_audit_head=audit.last_event_hash or ("0" * 64),
                incident_id=inc_id,
                run_id="run-e5",
                dev_source_dir=dev_dir,
                output_dir=out_dir,
                runtime_dir=run_dir,
            )

        # E4: Ticket blocked before APPROVE
        tm = DummyTicketManager(storage_path=tmp_path / "tickets.json")
        with pytest.raises(InvalidDossierStateError):
            tm.create_ticket_from_dossier(dossier)

        # APPROVE -> CLOSED -> Evaluator unlocked, Ticket created, Handover exported
        app_res = rm.approve(inc_id, dossier, "sre_lead_alex", "LEAD_SRE")
        approved_dossier = app_res["updated_dossier"]

        ticket = tm.create_ticket_from_dossier(approved_dossier)
        assert ticket["diagnosis_support_status"] == "PARTIAL"
        assert ticket["diagnosis_verified"] is False
        assert ticket["remediation_authorized"] is False
        assert ticket["has_applicable_sop"] is False
        assert ticket["auto_action_triggered"] is False

        exported = HandoverExporter(export_root=tmp_path / "handover").export_handover_package(
            incident_id=inc_id,
            dossier_dict=approved_dossier,
            review_history=rm.get_review_history(inc_id),
        )
        md_text = exported["markdown"].read_text(encoding="utf-8")
        assert "Diagnosis Verified:" in md_text
        assert "handover acceptance only" in md_text
        assert verify_ground_truth_isolation(json.loads(exported["json"].read_text(encoding="utf-8")))[0] is True

        joined_path = join_dev(
            store=store,
            audit_events=list(audit.events),
            trusted_audit_head=audit.last_event_hash,
            incident_id=inc_id,
            run_id="run-e5",
            dev_source_dir=dev_dir,
            output_dir=out_dir,
            runtime_dir=run_dir,
        )
        assert joined_path.exists()
    finally:
        store.close()


def test_group_e6_p0_01_and_p0_02_end_to_end_preservation(tmp_path: pathlib.Path) -> None:
    """E6: Full investigation (P0-01) -> Human APPROVE (P0-02) preserves UNSUPPORTED/CONTRADICTED & partial findings."""
    inc_id = "inc-e6-p01-p02"

    class Correlator:
        def build_impact_graph(self, **kwargs: Any) -> dict[str, Any]:
            return {"upstream_callers": [], "downstream_dependencies": [], "edges": []}

    class GatewayDispatcher:
        def dispatch(self, tool_name: str, arguments: dict[str, Any], **kwargs: Any) -> tuple[dict[str, Any], str, Any, str]:
            if tool_name == "retrieve_runbooks":
                return {"citations": []}, "ok", None, "synthetic-kb"
            if tool_name == "get_service_metrics":
                metric = arguments["metric_enum"]
                val = 0.4833 if metric == "request_rate" else 0.31
                return {
                    "records": [
                        {"service_id": "api-gateway", "metric_enum": metric, "value": val},
                        {"service_id": "api-gateway", "metric_enum": metric, "value": val},
                    ]
                }, "ok", None, "synthetic-prometheus"
            if tool_name == "search_error_logs":
                return {
                    "records": [
                        {
                            "service_id": "api-gateway",
                            "status_code": 503,
                            "error_code": "ERR_DEPENDENCY_UNAVAILABLE",
                            "message": "ERR_DEPENDENCY_UNAVAILABLE: Downstream dependency on transaction-service refused connection",
                        }
                    ]
                }, "ok", None, "synthetic-loki"
            return {
                "records": [{"service_id": "api-gateway", "span_id": "4d6de2bc32063db7", "duration_ms": 17.2, "status_code": "OK"}]
            }, "ok", None, "synthetic-tempo"

    candidate = {
        "primary_hypothesis": {
            "summary": "api-gateway degraded due to downstream transaction-service connection failures",
            "diagnosis": "Downstream dependency on transaction-service refused connection causing 503 ERR_DEPENDENCY_UNAVAILABLE.",
            "confidence": "MEDIUM",
            "estimated_root_cause": "transaction-service is refusing connections.",
        },
        "alternative_hypotheses": [
            {
                "summary": "api-gateway rate limiting or configuration change causing reduced request acceptance",
                "diagnosis": "Internal rate limiting thresholds blocking legitimate requests.",
                "confidence": "LOW",
                "estimated_root_cause": "Misconfigured rate limit threshold.",
                "supporting_evidence_ids": [f"ev-{inc_id}-002"],
                "contradicting_evidence_ids": [],
            },
            {
                "summary": "upstream client traffic surge overwhelming api-gateway capacity",
                "diagnosis": "Sudden increase in client request rate exceeding api-gateway capacity.",
                "confidence": "LOW",
                "estimated_root_cause": "Client traffic surge.",
                "supporting_evidence_ids": [f"ev-{inc_id}-001"],
                "contradicting_evidence_ids": [],
            },
        ],
        "supporting_evidence_ids": [f"ev-{inc_id}-002"],
        "contradicting_evidence_ids": [],
        "unknowns": ["api-gateway rate limit configuration values"],
    }

    provider = ReplayProvider([ProviderReply(json.dumps(candidate), 120, 80, "synthetic-replay")])
    ledger = LLMRunLedger(tmp_path / "usage.sqlite3")
    sec_audit = SecurityAuditLogger(tmp_path / "sec-audit.jsonl")
    review_audit = AuditHashChain(log_path=tmp_path / "review-audit.jsonl")
    llm = LLMInvestigator(provider, ledger, sec_audit, artifact_dir=tmp_path / "io")
    store = WorkflowStateStore(str(tmp_path / "state.db"))
    try:
        sm = InvestigationStateMachine(store)
        inv = DeterministicInvestigator(
            sm,
            PolicyGateway(dispatcher=GatewayDispatcher(), audit_logger=sec_audit),
            correlator=Correlator(),
            llm_investigator=llm,
        )
        inv_res = inv.investigate_incident({
            "incident_id": inc_id,
            "service_id": "api-gateway",
            "environment": "lab",
            "event_time": utc_now_z(),
        })
        assert inv_res["status"] == "HUMAN_REVIEW"
        dossier = inv_res["dossier"]

        rm = AuthorizedReviewManager(state_machine=sm, store=store, audit_chain=review_audit)
        app_res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        closed_dossier = app_res["updated_dossier"]
        sem = app_res["approval_semantics"]

        # P0-01 findings remain intact after P0-02 APPROVE
        assert closed_dossier["review_summary"]["status"] == "APPROVED"
        assert closed_dossier["hypotheses"][0]["support_status"] == "PARTIAL"
        assert closed_dossier["hypotheses"][1]["support_status"] == "INCONCLUSIVE"
        assert closed_dossier["hypotheses"][1]["supporting_evidence_ids"] == []
        assert closed_dossier["hypotheses"][2]["support_status"] == "INCONCLUSIVE"
        assert closed_dossier["hypotheses"][2]["supporting_evidence_ids"] == []
        assert sem["diagnostic_validation_statuses"][closed_dossier["hypotheses"][1]["hypothesis_id"]] == "UNSUPPORTED"
        assert sem["diagnostic_validation_statuses"][closed_dossier["hypotheses"][2]["hypothesis_id"]] == "CONTRADICTED"
        assert sem["has_applicable_runbook"] is False
        assert sem["diagnosis_verified"] is False
        assert sem["remediation_authorized"] is False
        assert "VERIFIED" not in json.dumps(closed_dossier).upper()
    finally:
        ledger.close()
        store.close()
