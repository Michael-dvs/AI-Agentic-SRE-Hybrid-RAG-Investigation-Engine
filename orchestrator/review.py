"""Authorized Human Review Manager enforcing append-only decision audit, version-bound approval, and HUM-01 (C12, C16, FR-OUT-004, HUM-01, NFR-011)."""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
import uuid
from typing import Any, Dict, List, Optional, Set

from jsonschema import Draft202012Validator, FormatChecker

from orchestrator.dossier import (
    DossierMarkdownRenderer,
    DossierSerializer,
    compute_canonical_dossier_hash,
)
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore, utc_now_z

_LOG = logging.getLogger(__name__)

# Path to canonical review contract schema
_CONTRACT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)
_REVIEW_SCHEMA_PATH = _CONTRACT_DIR / "review-event.v1.schema.json"
_REVIEW_VALIDATOR: Draft202012Validator | None = None
if _REVIEW_SCHEMA_PATH.exists():
    try:
        _schema = json.loads(_REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
        _REVIEW_VALIDATOR = Draft202012Validator(_schema, format_checker=FormatChecker())
    except Exception:
        _REVIEW_VALIDATOR = None


class ReviewError(Exception):
    """Base exception for human review processing."""

    def __init__(self, message: str, code: str = "REVIEW_ERROR") -> None:
        super().__init__(message)
        self.code = code


class UnauthorizedReviewerError(ReviewError):
    """Raised when an unapproved or unauthorized role attempts to submit a review."""

    def __init__(self, role: str) -> None:
        super().__init__(f"UNAUTHORIZED: Unauthorized reviewer role: {role!r}", code="FORBIDDEN_SCOPE")
        self.role = role


class StaleDossierVersionError(ReviewError):
    """Raised when an approval is attempted on a stale/superseded dossier version (VERSION_CONFLICT)."""

    def __init__(self, target_version: int, latest_version: int) -> None:
        super().__init__(
            f"Version conflict (VERSION_CONFLICT): target dossier version v{target_version} is superseded by latest v{latest_version}",
            code="VERSION_CONFLICT",
        )
        self.target_version = target_version
        self.latest_version = latest_version


class InvalidReviewDecisionError(ReviewError):
    """Raised when an unrecognized decision string is provided."""

    def __init__(self, decision: str) -> None:
        super().__init__(f"Invalid review decision: {decision!r}", code="INVALID_DECISION")
        self.decision = decision


class DossierHashMismatchError(ReviewError):
    """Raised when the dossier payload does not match its cryptographic SHA-256 hash."""

    def __init__(self, expected_hash: str, actual_hash: str) -> None:
        super().__init__(
            f"Dossier hash mismatch: payload hash {actual_hash} != {expected_hash}",
            code="HASH_MISMATCH",
        )


ALLOWED_REVIEWER_ROLES: Set[str] = {
    "L1_OPERATOR",
    "L2_SRE_REVIEWER",
    "PROJECT_OWNER_LAB",
    "L1_SRE",
    "L2_SRE",
    "LEAD_SRE",
}

# Mapping extended roles to canonical contract schema roles for review-event validation
ROLE_SCHEMA_MAP: Dict[str, str] = {
    "L1_SRE": "L1_OPERATOR",
    "L2_SRE": "L2_SRE_REVIEWER",
    "LEAD_SRE": "PROJECT_OWNER_LAB",
    "L1_OPERATOR": "L1_OPERATOR",
    "L2_SRE_REVIEWER": "L2_SRE_REVIEWER",
    "PROJECT_OWNER_LAB": "PROJECT_OWNER_LAB",
}

DECISION_MAP: Dict[str, str] = {
    "approve": "approve",
    "APPROVE": "approve",
    "reject": "reject",
    "REJECT": "reject",
    "edit": "edit",
    "EDIT": "edit",
    "correct": "edit",
    "CORRECT": "edit",
    "escalate": "escalate_manual",
    "ESCALATE": "escalate_manual",
    "escalate_manual": "escalate_manual",
    "ESCALATE_MANUAL": "escalate_manual",
}

ALLOWED_DECISIONS: Set[str] = set(DECISION_MAP.keys())


class AuthorizedReviewManager:
    """Manages append-only authorized human reviews, enforcing HUM-01 zero auto-remediation,

    version-bound approval, and cryptographic audit hashing (C12, C16, FR-OUT-004, HUM-01, NFR-011).
    """

    def __init__(
        self,
        state_machine: Optional[InvestigationStateMachine] = None,
        store: Optional[WorkflowStateStore] = None,
        audit_logger: Any = None,
        audit_chain: Any = None,
    ) -> None:
        if state_machine is None:
            self.store = store or WorkflowStateStore(":memory:")
            self.sm = InvestigationStateMachine(store=self.store)
        else:
            self.sm = state_machine
            self.store = store or state_machine.store
        self.audit_logger = audit_logger
        self.audit_chain = audit_chain or (
            audit_logger if hasattr(audit_logger, "last_event_hash") else None
        )

    def submit_review(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        decision: str,
        rationale: str,
        edited_dossier_data: Optional[Dict[str, Any]] = None,
        escalation_target: Optional[str] = None,
        target_version: Optional[int] = None,
        revision_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Submit an authorized human review decision on a specific dossier revision."""
        formatted_inc_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"

        # 1. Authorize Role (Rule check)
        if not reviewer_role or reviewer_role not in ALLOWED_REVIEWER_ROLES:
            _LOG.warning("Unauthorized review attempt by %s with role %s", reviewer_ref, reviewer_role)
            raise UnauthorizedReviewerError(reviewer_role or "UNSPECIFIED")

        # 2. Validate and Normalize Decision enum
        if decision not in DECISION_MAP:
            raise InvalidReviewDecisionError(decision)
        canonical_decision = DECISION_MAP[decision]

        # 3. Cryptographic Hash Integrity Check
        computed_hash = compute_canonical_dossier_hash(dossier_dict)
        given_hash = dossier_dict.get("dossier_hash", "")
        if given_hash and computed_hash != given_hash:
            raise DossierHashMismatchError(expected_hash=given_hash, actual_hash=computed_hash)
        elif not given_hash:
            given_hash = computed_hash
            dossier_dict["dossier_hash"] = given_hash

        # 4. Version Conflict Check (Detect stale approvals)
        effective_target_version = target_version or revision_number or int(dossier_dict.get("dossier_version", 1))
        latest_version = self.store.get_latest_dossier_version(formatted_inc_id)
        if latest_version > effective_target_version:
            _LOG.warning(
                "Stale review attempt on %s: target v%d < latest v%d",
                formatted_inc_id,
                effective_target_version,
                latest_version,
            )
            raise StaleDossierVersionError(
                target_version=effective_target_version,
                latest_version=latest_version,
            )

        # Ensure incident exists in state store if not present (e.g. CLI review session)
        if not self.store.get_incident(formatted_inc_id):
            self.store.create_incident(
                incident_id=formatted_inc_id,
                initial_state="HUMAN_REVIEW",
                status="ACTIVE",
            )

        # 5. Build canonical review event
        now = utc_now_z()
        event_id = f"rev-{uuid.uuid4().hex[:16]}"
        edited_version: Optional[int] = effective_target_version + 1 if canonical_decision == "edit" else None

        schema_role = ROLE_SCHEMA_MAP.get(reviewer_role, reviewer_role)

        review_event = {
            "schema_version": "1.0",
            "review_event_id": event_id,
            "incident_id": formatted_inc_id,
            "target_dossier_version": effective_target_version,
            "target_dossier_hash": given_hash,
            "reviewer_ref": reviewer_ref,
            "reviewer_role": schema_role,
            "reviewed_at": now,
            "decision": canonical_decision,
            "rationale": (rationale or "Review action recorded")[:2048],
            "edited_dossier_version": edited_version,
            "escalation_target": escalation_target,
            "auto_action_triggered": False,  # Strict HUM-01 Enforcement: Never trigger auto remediation!
        }

        # 6. Validate against review-event contract
        if _REVIEW_VALIDATOR is not None:
            errors = list(_REVIEW_VALIDATOR.iter_errors(review_event))
            if errors:
                err_msg = "; ".join(f"{e.json_path}: {e.message}" for e in errors)
                raise ValueError(f"Review event failed schema validation: {err_msg}")

        # 7. Record append-only review in SQLite
        self.store.record_review(review_event)

        # 8. Update dossier review summary & persist
        updated_dossier = dict(dossier_dict)
        summary_status = "PENDING_REVIEW"

        if canonical_decision == "approve":
            summary_status = "APPROVED"
        elif canonical_decision == "reject":
            summary_status = "REJECTED"
        elif canonical_decision == "edit":
            summary_status = "EDITED"
        elif canonical_decision == "escalate_manual":
            summary_status = "MANUAL_TRIAGE"

        updated_dossier["review_summary"] = {
            "status": summary_status,
            "latest_review_event_id": event_id,
            "reviewed_by": f"{reviewer_ref} ({reviewer_role})",
            "reviewed_at": now,
        }

        # Re-compute hash and re-save current dossier version
        updated_hash = compute_canonical_dossier_hash(updated_dossier)
        updated_dossier["dossier_hash"] = updated_hash
        updated_md = DossierMarkdownRenderer.render(updated_dossier)
        self.store.save_dossier(
            incident_id=formatted_inc_id,
            dossier_version=effective_target_version,
            dossier_hash=updated_hash,
            dossier_json=updated_dossier,
            dossier_markdown=updated_md,
        )

        # 9. Handle Decision Outcomes & State Machine Transitions
        new_dossier_version_record: Optional[Dict[str, Any]] = None

        if canonical_decision == "approve":
            # Transition state machine to CLOSED
            self.sm.transition(
                incident_id=formatted_inc_id,
                to_state="CLOSED",
                idempotency_key=f"idem-{formatted_inc_id}-closed",
                reason_code="OK",
                terminal_outcome="CLOSED_APPROVED",
                reason=f"Approved by {reviewer_ref}: {rationale}",
                input_data={"review_event_id": event_id},
                output_data={"status": "CLOSED_APPROVED"},
            )

            # Record cryptographic sign-off event in AuditHashChain if available (schema-conformant)
            audit_sink = self.audit_chain or self.audit_logger
            if audit_sink and hasattr(audit_sink, "record_event"):
                try:
                    audit_sink.record_event(
                        actor_ref="principal_reviewer",
                        action="HUMAN_REVIEW_DECISION",
                        target_ref=f"{formatted_inc_id}:v{effective_target_version}",
                        result_code="ALLOW",
                        reason_code="OK",
                        request_payload=review_event,
                        incident_id=formatted_inc_id,
                        target_version=str(effective_target_version),
                    )
                except Exception as e:
                    _LOG.warning("Failed to record sign-off audit event: %s", e)

        elif canonical_decision == "reject":
            # Transition state machine to REJECTED terminal state
            self.sm.transition(
                incident_id=formatted_inc_id,
                to_state="REJECTED",
                idempotency_key=f"idem-{formatted_inc_id}-rejected",
                reason_code="OK",
                terminal_outcome="TERMINATED_REJECTED",
                reason=f"Rejected by {reviewer_ref}: {rationale}",
                input_data={"review_event_id": event_id},
                output_data={"status": "TERMINATED_REJECTED"},
            )

        elif canonical_decision == "escalate_manual":
            # Transition state machine to MANUAL_TRIAGE_REQUIRED
            self.sm.transition(
                incident_id=formatted_inc_id,
                to_state="MANUAL_TRIAGE_REQUIRED",
                idempotency_key=f"idem-{formatted_inc_id}-escalated",
                reason_code="OK",
                terminal_outcome="TERMINATED_MANUAL_TRIAGE",
                reason=f"Escalated to manual triage ({escalation_target}): {rationale}",
                input_data={"review_event_id": event_id},
                output_data={"status": "TERMINATED_MANUAL_TRIAGE"},
            )

        elif canonical_decision == "edit":
            # Create a new revision N+1 append-only without modifying raw telemetry data
            edit_ctx = dict(updated_dossier)
            if edited_dossier_data:
                # Merge user corrections while strictly safeguarding raw telemetry
                protected_fields = {
                    "telemetry_summary",
                    "signals_timeline",
                    "evidence_items",
                    "telemetry_citations",
                    "source_telemetry",
                }
                for k, v in edited_dossier_data.items():
                    if k not in protected_fields:
                        edit_ctx[k] = v

            # Reset review summary for the new revision
            edit_ctx["review_summary"] = {
                "status": "PENDING_REVIEW",
                "latest_review_event_id": None,
                "reviewed_by": None,
                "reviewed_at": None,
            }
            new_rev = effective_target_version + 1
            new_dossier_version_record = DossierSerializer.serialize(edit_ctx, revision=new_rev)
            new_md = DossierMarkdownRenderer.render(new_dossier_version_record)
            self.store.save_dossier(
                incident_id=formatted_inc_id,
                dossier_version=new_rev,
                dossier_hash=new_dossier_version_record["dossier_hash"],
                dossier_json=new_dossier_version_record,
                dossier_markdown=new_md,
            )
            _LOG.info("Created new dossier revision v%d for %s", new_rev, formatted_inc_id)

        # 10. Audit event logging if logger available and not already recorded above
        if self.audit_logger and canonical_decision != "approve":
            try:
                self.audit_logger.record_event(
                    actor_ref=reviewer_ref,
                    action="HUMAN_REVIEW_DECISION",
                    target_ref=formatted_inc_id,
                    result_code="ALLOW",
                    reason_code=canonical_decision.upper(),
                    request_payload=review_event,
                    incident_id=formatted_inc_id,
                )
            except Exception as e:
                _LOG.warning("Audit logger failed to record review: %s", e)

        return {
            "review_event": review_event,
            "updated_dossier": updated_dossier,
            "new_dossier_revision": new_dossier_version_record,
        }

    def approve(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str = "Dossier hypotheses and evidence verified by human reviewer.",
        target_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Convenience method to approve an incident dossier revision."""
        return self.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision="approve",
            rationale=rationale,
            target_version=target_version,
        )

    def reject(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str,
        target_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Convenience method to reject an incident dossier revision."""
        return self.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision="reject",
            rationale=rationale,
            target_version=target_version,
        )

    def correct(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str,
        corrections: Optional[Dict[str, Any]] = None,
        target_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Convenience method to correct/edit an incident dossier revision."""
        return self.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision="edit",
            rationale=rationale,
            edited_dossier_data=corrections,
            target_version=target_version,
        )

    def get_review_history(self, incident_id: str) -> List[Dict[str, Any]]:
        """Retrieve chronological history of all review events for an incident."""
        formatted_inc_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
        return self.store.get_reviews(formatted_inc_id)


# Backward-compatibility alias
HumanReviewManager = AuthorizedReviewManager
