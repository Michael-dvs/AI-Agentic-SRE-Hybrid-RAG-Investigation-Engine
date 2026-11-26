"""Authorized Human Review Manager enforcing append-only decision audit, version-bound approval, and HUM-01 (C12, C16, FR-OUT-004, HUM-01, NFR-011)."""

from __future__ import annotations

import copy
import datetime
import json
import logging
import pathlib
import re
import threading
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from jsonschema import Draft202012Validator, FormatChecker

from observability.audit_chain import compute_request_fingerprint, verify_chain_integrity
from orchestrator.dossier import (
    DossierMarkdownRenderer,
    DossierSerializer,
    compute_canonical_dossier_hash,
)
from orchestrator.handover import verify_ground_truth_isolation
from orchestrator.state_machine import (
    TERMINAL_STATES,
    InvalidStateTransitionError,
    InvestigationStateMachine,
    WorkflowStateStore,
    utc_now_z,
)

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
    """Raised when an unapproved or unauthorized role/actor attempts to submit a review."""

    def __init__(self, role: str, message: Optional[str] = None) -> None:
        super().__init__(
            message or f"UNAUTHORIZED: Unauthorized reviewer role: {role!r}",
            code="FORBIDDEN_SCOPE",
        )
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


class InvalidDossierError(ReviewError):
    """Raised when a dossier or edit payload fails structural, safety, or provenance checks."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_DOSSIER")


class ReviewStateConflictError(ReviewError, InvalidStateTransitionError):
    """Raised when a review action conflicts with lifecycle state or prior finalization."""

    def __init__(self, message: str, code: str = "INVALID_STATE_TRANSITION") -> None:
        ReviewError.__init__(self, message, code=code)
        self.code = code


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

_VALID_HUMAN_REVIEWER_REF_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._@-]{2,127}$")
_FORBIDDEN_AI_REVIEWER_REFS: Set[str] = {
    "principal_intake",
    "principal_investigator",
    "principal_tool_gateway",
    "principal_kb_ingestor",
    "principal_fault_harness",
    "principal_evaluator",
    "principal_reviewer",
    "principal:investigator-coord",
    "principal:mcp-policy-gateway",
    "principal:operator-harness",
    "principal:offline-evaluator",
    "principal:alert-intake",
    "principal:kb-ingestion",
    "principal:human-reviewer",
}
_FORBIDDEN_PREFIXES = ("principal_", "principal:", "cmp-", "svc:", "service:")
_FORBIDDEN_AI_ACTOR_PATTERN = re.compile(
    r"^(?:ai|llm|agent|auto|bot|system|orchestrator)(?:[-_ ].*)?$",
    re.IGNORECASE,
)
_FORBIDDEN_AI_SYSTEM_TOKENS: Set[str] = {
    "ai",
    "llm",
    "agent",
    "agentic",
    "auto",
    "automated",
    "autonomous",
    "bot",
    "system",
    "sys",
    "orchestrator",
    "investigator",
    "gateway",
    "harness",
    "evaluator",
    "ingestor",
    "daemon",
    "cron",
    "worker",
    "svc",
    "machine",
    "model",
    "gpt",
    "claude",
    "gemini",
    "ollama",
    "openrouter",
    "nemotron",
    "copilot",
    "watchdog",
    "watcher",
    "pipeline",
}
_FORBIDDEN_ANONYMOUS_TOKENS: Set[str] = {
    "anonymous",
    "unknown",
    "guest",
    "nobody",
    "null",
    "none",
    "unauthenticated",
}
_VERIFIED_PATTERN = re.compile(r"\bVERIFIED\b", re.IGNORECASE)

_PRIVILEGE_ESCALATION_EDIT_FIELDS: Set[str] = {
    "reviewer_ref",
    "reviewer_role",
    "allowed_roles",
    "role",
    "roles",
    "permissions",
    "is_admin",
    "authenticated",
    "auth_context",
    "approval_semantics",
    "authorization_context",
    "auto_action_triggered",
    "auto_execution_allowed",
    "remediation_authorized",
    "diagnosis_verified",
    "root_cause_proven",
    "current_state",
    "terminal_state",
    "closure_meaning",
}
_EDITABLE_DOSSIER_FIELDS: Set[str] = {
    "hypotheses",
    "unknowns",
    "impact_summary",
    "recommended_checks",
}

_PROTECTED_DOSSIER_FIELDS: Set[str] = {
    "schema_version",
    "incident_id",
    "service_id",
    "environment",
    "alert_received_at",
    "window_start",
    "window_end",
    "investigation_mode",
    "evidence",
    "evidence_items",
    "missing_sources",
    "sop_citations",
    "telemetry_summary",
    "signals_timeline",
    "telemetry_citations",
    "source_telemetry",
    "reproducibility",
    "timeline",
}


def _status_str(val: Any, default: str = "INCONCLUSIVE") -> str:
    if val is None:
        return default
    return str(val.value if hasattr(val, "value") else val)


def build_human_correction_payload(
    dossier: Dict[str, Any],
    corrected_statement: str,
    reviewer_ref: str,
    reviewer_role: str,
) -> Dict[str, Any]:
    """Build a schema-compliant human correction payload without fabricating evidence or VERIFIED claims."""
    statement = " ".join((corrected_statement or "").split())
    if len(statement) < 5:
        raise InvalidDossierError("Corrected hypothesis statement must be at least 5 characters.")
    if _VERIFIED_PATTERN.search(statement):
        raise InvalidDossierError("RULE-007 Violation: Human correction text cannot claim 'VERIFIED' without formal validation.")

    inc_id = str(dossier.get("incident_id", "inc-unknown"))
    if not inc_id.startswith("inc-"):
        inc_id = f"inc-{inc_id}"
    next_rev = int(dossier.get("dossier_version", 1)) + 1

    return {
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{inc_id}-human-v{next_rev:02d}",
                "statement": statement[:2048],
                "status": "INCONCLUSIVE",
                "supporting_evidence_ids": [],
                "refuting_evidence_ids": [],
                "reason_summary": (
                    f"[Human Correction by {reviewer_ref} ({reviewer_role})] "
                    "Candidate hypothesis proposed during human review; requires supporting telemetry evidence and renewed review."
                ),
                "unknowns": [
                    "Human-authored correction has not been verified against automated telemetry evidence."
                ],
            }
        ]
    }


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
        reviewer_directory: Optional[Mapping[str, Any]] = None,
        require_registered_reviewer: bool = False,
        require_authenticated_context: bool = False,
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
        self.reviewer_directory: Optional[Dict[str, Set[str]]] = None
        if reviewer_directory is not None:
            normalized_dir: Dict[str, Set[str]] = {}
            for ref, raw_roles in reviewer_directory.items():
                if isinstance(raw_roles, str):
                    role_list = [raw_roles]
                else:
                    role_list = list(raw_roles or [])
                expanded: Set[str] = set()
                for role_item in role_list:
                    r_str = str(role_item)
                    expanded.add(r_str)
                    if r_str in ROLE_SCHEMA_MAP:
                        expanded.add(ROLE_SCHEMA_MAP[r_str])
                normalized_dir[str(ref).strip()] = expanded
            self.reviewer_directory = normalized_dir
        self.require_registered_reviewer = bool(require_registered_reviewer)
        self.require_authenticated_context = bool(require_authenticated_context)
        self._lock = threading.RLock()

    def _audit_sink(self) -> Any:
        return self.audit_chain or self.audit_logger

    def _record_denied_audit(
        self,
        *,
        incident_id: str,
        target_version: Optional[int],
        reason_code: str,
        decision: str,
        reviewer_ref: str,
        reviewer_role: str,
        detail: str,
    ) -> None:
        audit_sink = self._audit_sink()
        if not (audit_sink and hasattr(audit_sink, "record_event")):
            return
        allowed_codes = {"FORBIDDEN_SCOPE", "VERSION_CONFLICT", "SCHEMA_INVALID"}
        safe_code = reason_code if reason_code in allowed_codes else "SCHEMA_INVALID"
        ver_str = str(target_version) if target_version is not None else "1"
        try:
            audit_sink.record_event(
                actor_ref="principal_reviewer",
                action="HUMAN_REVIEW_DECISION",
                target_ref=f"{incident_id}:v{ver_str}",
                result_code="DENY",
                reason_code=safe_code,
                request_payload={
                    "incident_id": incident_id,
                    "attempted_decision": str(decision)[:64],
                    "reviewer_ref": str(reviewer_ref or "UNSPECIFIED")[:128],
                    "reviewer_role": str(reviewer_role or "UNSPECIFIED")[:64],
                    "detail": detail[:256],
                },
                incident_id=incident_id,
                target_version=ver_str,
            )
        except Exception as exc:
            _LOG.warning("Failed to record denied review audit event: %s", exc)

    def _record_compensating_audit(
        self,
        *,
        audit_sink: Any,
        incident_id: str,
        target_version: int,
        review_event_id: str,
        prior_audit_event_ids: List[str],
        error: BaseException,
    ) -> Optional[Dict[str, Any]]:
        """Append an immutable compensating ERROR audit record if SQLite commit failed after ALLOW audit."""
        if not (audit_sink and hasattr(audit_sink, "record_event")):
            return None
        try:
            return audit_sink.record_event(
                actor_ref="principal_reviewer",
                action="HUMAN_REVIEW_DECISION",
                target_ref=f"{incident_id}:v{target_version}",
                result_code="ERROR",
                reason_code="SOURCE_UNAVAILABLE",
                request_payload={
                    "incident_id": incident_id,
                    "review_event_id": review_event_id,
                    "phase": "POST_AUDIT_PERSISTENCE_FAILED_DB_ROLLED_BACK",
                    "prior_audit_event_ids": prior_audit_event_ids,
                    "error_type": type(error).__name__,
                    "detail": str(error)[:256],
                    "db_rolled_back": True,
                },
                incident_id=incident_id,
                target_version=str(target_version),
                evidence_refs=[review_event_id, *prior_audit_event_ids],
            )
        except Exception as comp_exc:
            _LOG.critical(
                "AUDIT_RECONCILIATION_REQUIRED: Failed to append compensating ERROR audit for %s (%s): %s",
                incident_id,
                review_event_id,
                comp_exc,
            )
            return None

    def _authorize_reviewer(
        self,
        *,
        incident_id: str,
        target_version: int,
        decision: Any,
        reviewer_ref: Any,
        reviewer_role: Any,
        auth_context: Any = None,
    ) -> Dict[str, Any]:
        """Enforce PoC reviewer identity/role boundary without falsely claiming human authentication."""
        def _deny(role_val: Any, ref_val: str, detail: str, msg: Optional[str] = None) -> None:
            safe_role = str(role_val) if isinstance(role_val, str) and role_val.strip() else "UNSPECIFIED"
            self._record_denied_audit(
                incident_id=incident_id,
                target_version=target_version,
                reason_code="FORBIDDEN_SCOPE",
                decision=str(decision),
                reviewer_ref=ref_val,
                reviewer_role=safe_role,
                detail=detail,
            )
            raise UnauthorizedReviewerError(safe_role, message=msg)

        if not isinstance(reviewer_ref, str):
            _deny(
                reviewer_role,
                type(reviewer_ref).__name__,
                "Malformed non-string reviewer_ref rejected.",
                msg="UNAUTHORIZED: reviewer_ref must be a non-empty human operator string.",
            )

        if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in reviewer_ref):
            cleaned_preview = "".join(ch if ch >= " " and ch != "\x7f" else "?" for ch in reviewer_ref)[:64]
            _deny(
                reviewer_role,
                cleaned_preview or "UNSPECIFIED",
                "Malformed reviewer_ref containing whitespace or control characters rejected.",
                msg="UNAUTHORIZED: Malformed reviewer_ref cannot contain whitespace or control characters.",
            )

        cleaned_ref = reviewer_ref.strip()
        lowered_ref = cleaned_ref.lower()
        tokens = [t for t in re.split(r"[-_.:/@]+", lowered_ref) if t]

        if not _VALID_HUMAN_REVIEWER_REF_PATTERN.match(cleaned_ref):
            _deny(
                reviewer_role,
                cleaned_ref[:64] or "UNSPECIFIED",
                f"Malformed reviewer_ref format rejected: {cleaned_ref[:64]!r}",
                msg=f"UNAUTHORIZED: Malformed human reviewer identifier {cleaned_ref[:64]!r}.",
            )

        if (
            lowered_ref in _FORBIDDEN_AI_REVIEWER_REFS
            or lowered_ref.startswith(_FORBIDDEN_PREFIXES)
            or _FORBIDDEN_AI_ACTOR_PATTERN.match(cleaned_ref)
            or any(tok in _FORBIDDEN_AI_SYSTEM_TOKENS for tok in tokens)
        ):
            _LOG.warning("AI/automated or system reviewer actor rejected: %r", cleaned_ref)
            _deny(
                reviewer_role,
                cleaned_ref,
                "Automated/AI/system reviewer identity is forbidden from making review decisions.",
                msg=f"UNAUTHORIZED: Human reviewer identity required; actor {cleaned_ref!r} is forbidden.",
            )

        if not isinstance(reviewer_role, str) or not reviewer_role or reviewer_role not in ALLOWED_REVIEWER_ROLES:
            _LOG.warning("Unauthorized review attempt by %s with role %r", cleaned_ref, reviewer_role)
            _deny(
                reviewer_role,
                cleaned_ref,
                f"Unauthorized reviewer role: {reviewer_role!r}",
            )

        if any(tok in _FORBIDDEN_ANONYMOUS_TOKENS for tok in tokens):
            _LOG.warning("Anonymous or unattributed reviewer actor rejected: %r", cleaned_ref)
            _deny(
                reviewer_role,
                cleaned_ref,
                "Anonymous/unknown/guest reviewer identity is forbidden from making review decisions.",
                msg=f"UNAUTHORIZED: Human reviewer identity required; actor {cleaned_ref!r} is forbidden.",
            )

        principal_verified = False
        principal_actor_ref: Optional[str] = None
        if auth_context is not None or self.require_authenticated_context:
            ctx_actor = getattr(auth_context, "actor_ref", None) if auth_context is not None else None
            if ctx_actor != "principal_reviewer":
                _deny(
                    reviewer_role,
                    cleaned_ref,
                    f"Authenticated context actor_ref={ctx_actor!r} is not authorized as principal_reviewer.",
                    msg=f"UNAUTHORIZED: Scoped principal {ctx_actor!r} cannot submit human review decisions.",
                )
            principal_verified = True
            principal_actor_ref = "principal_reviewer"

        if self.reviewer_directory is not None or self.require_registered_reviewer:
            directory = self.reviewer_directory or {}
            allowed_for_ref = directory.get(cleaned_ref)
            schema_role = ROLE_SCHEMA_MAP.get(reviewer_role, reviewer_role)
            if allowed_for_ref is None or (
                reviewer_role not in allowed_for_ref and schema_role not in allowed_for_ref
            ):
                _deny(
                    reviewer_role,
                    cleaned_ref,
                    f"Reviewer {cleaned_ref!r} not authorized in directory for role {reviewer_role!r}.",
                    msg=f"UNAUTHORIZED: Reviewer {cleaned_ref!r} is not registered or lacks role {reviewer_role!r}.",
                )

        return {
            "identity_mode": (
                "SCOPED_PRINCIPAL_CONTEXT_WITH_LOCAL_REF"
                if principal_verified
                else "POC_CALLER_ASSERTED_UNAUTHENTICATED"
            ),
            "principal_context_verified": principal_verified,
            "human_identity_authenticated": False,
            "directory_role_verified": self.reviewer_directory is not None,
            "principal_actor_ref": principal_actor_ref,
            "claimed_reviewer_ref": cleaned_ref,
            "claimed_reviewer_role": reviewer_role,
            "effective_schema_role": ROLE_SCHEMA_MAP.get(reviewer_role, reviewer_role),
            "trust_boundary_note": (
                "Local PoC trust boundary: reviewer_ref is a local operator identifier, not SSO/OIDC-authenticated."
            ),
        }

    def _extract_validation_statuses(
        self,
        incident_id: str,
        dossier: Dict[str, Any],
    ) -> Dict[str, str]:
        statuses: Dict[str, str] = {}
        try:
            checkpoint = self.store.get_checkpoint(incident_id)
        except Exception:
            checkpoint = None
        if isinstance(checkpoint, dict):
            ctx = checkpoint.get("context") or {}
            for report in ctx.get("validation_reports") or []:
                if isinstance(report, dict) and report.get("hypothesis_id"):
                    statuses[str(report["hypothesis_id"])] = _status_str(report.get("status"))
            for hyp in ctx.get("hypotheses") or []:
                if isinstance(hyp, dict) and hyp.get("hypothesis_id") and hyp.get("validation_status"):
                    statuses.setdefault(
                        str(hyp["hypothesis_id"]),
                        _status_str(hyp.get("validation_status")),
                    )
        for hyp in dossier.get("hypotheses") or []:
            if isinstance(hyp, dict) and hyp.get("hypothesis_id"):
                statuses.setdefault(
                    str(hyp["hypothesis_id"]),
                    _status_str(hyp.get("support_status") or hyp.get("status")),
                )
        return statuses

    @staticmethod
    def _build_approval_semantics(
        *,
        canonical_decision: str,
        summary_status: str,
        updated_dossier: Dict[str, Any],
        diagnostic_validation_statuses: Dict[str, str],
        previous_state: str,
        authorization_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        hyp_support_statuses = {
            str(h.get("hypothesis_id", f"hyp-{idx}")): _status_str(h.get("support_status") or h.get("status"))
            for idx, h in enumerate(updated_dossier.get("hypotheses") or [], start=1)
            if isinstance(h, dict)
        }
        missing_sources = updated_dossier.get("missing_sources") or []
        missing_source_codes = [
            str(ms.get("error_code"))
            for ms in missing_sources
            if isinstance(ms, dict) and ms.get("error_code")
        ]
        sop_citations = updated_dossier.get("sop_citations") or []
        has_applicable_runbook = bool(sop_citations) and "NO_APPLICABLE_RUNBOOK" not in missing_source_codes

        if canonical_decision == "approve":
            resulting_state = "CLOSED"
            closure_meaning = "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED"
        elif canonical_decision == "reject":
            resulting_state = "REJECTED"
            closure_meaning = "DOSSIER_REJECTED"
        elif canonical_decision == "escalate_manual":
            resulting_state = "MANUAL_TRIAGE_REQUIRED"
            closure_meaning = "ESCALATED_FOR_MANUAL_TRIAGE"
        else:
            resulting_state = "HUMAN_REVIEW"
            closure_meaning = "REVISION_PENDING_RENEWED_REVIEW"

        payload: Dict[str, Any] = {
            "dossier_review_status": summary_status,
            "dossier_accepted_for_handover": canonical_decision == "approve",
            "hypothesis_support_statuses": hyp_support_statuses,
            "diagnostic_validation_statuses": diagnostic_validation_statuses,
            "diagnosis_verified": False,
            "root_cause_proven": False,
            "technical_incident_resolved": False,
            "remediation_authorized": False,
            "sop_compliance_confirmed": False,
            "auto_action_triggered": False,
            "has_applicable_runbook": has_applicable_runbook,
            "missing_source_codes": missing_source_codes,
            "unknowns_count": len(updated_dossier.get("unknowns") or []),
            "previous_lifecycle_state": previous_state,
            "resulting_lifecycle_state": resulting_state,
            "closure_meaning": closure_meaning,
        }
        if authorization_context is not None:
            payload["authorization_context"] = authorization_context
        return payload

    @staticmethod
    def _merge_human_edit_context(
        *,
        base_dossier: Dict[str, Any],
        edited_dossier_data: Optional[Dict[str, Any]],
        reviewer_ref: str,
        reviewer_role: str,
    ) -> Dict[str, Any]:
        edit_ctx = copy.deepcopy(base_dossier)
        if not edited_dossier_data:
            return edit_ctx

        original_hypotheses = copy.deepcopy(base_dossier.get("hypotheses") or [])
        original_unknowns = list(base_dossier.get("unknowns") or [])

        for k, v in edited_dossier_data.items():
            if (
                k in _PROTECTED_DOSSIER_FIELDS
                or k in ("review_summary", "dossier_hash", "dossier_version")
                or k not in _EDITABLE_DOSSIER_FIELDS
            ):
                continue
            if k == "hypotheses" and isinstance(v, list):
                merged_hyps: List[Dict[str, Any]] = []
                edited_statements: Set[str] = set()
                seen_ids: Set[str] = set()
                human_prefix = f"[Human Correction by {reviewer_ref} ({reviewer_role})]"

                for idx, item in enumerate(v, start=1):
                    if not isinstance(item, dict):
                        continue
                    h_copy = copy.deepcopy(item)
                    stmt = str(h_copy.get("statement") or h_copy.get("title") or "").strip()
                    if stmt:
                        edited_statements.add(stmt.lower())
                    sup_ids = list(h_copy.get("supporting_evidence_ids") or [])
                    raw_stat = _status_str(h_copy.get("status") or h_copy.get("support_status"), "INCONCLUSIVE").upper()
                    if raw_stat == "SUPPORTED" and not sup_ids:
                        raw_stat = "INCONCLUSIVE"
                    h_copy["status"] = raw_stat
                    h_copy.pop("support_status", None)

                    reason = str(h_copy.get("reason_summary") or h_copy.get("description") or "Human-authored candidate hypothesis.").strip()
                    if not reason.startswith("[Human Correction"):
                        reason = f"{human_prefix} {reason}"
                    h_copy["reason_summary"] = reason
                    h_copy.pop("description", None)

                    hid = str(h_copy.get("hypothesis_id") or f"hyp-{base_dossier.get('incident_id', 'unknown')}-human-{idx:02d}")
                    if hid in seen_ids:
                        hid = f"{hid}-human-{idx:02d}"
                    seen_ids.add(hid)
                    h_copy["hypothesis_id"] = hid
                    merged_hyps.append(h_copy)

                for orig in original_hypotheses:
                    if len(merged_hyps) >= 10:
                        break
                    if not isinstance(orig, dict):
                        continue
                    orig_stmt = str(orig.get("statement") or "").strip()
                    if orig_stmt and orig_stmt.lower() in edited_statements:
                        continue
                    orig_copy = copy.deepcopy(orig)
                    orig_stat = _status_str(orig_copy.get("support_status") or orig_copy.get("status"), "INCONCLUSIVE").upper()
                    orig_copy["status"] = orig_stat
                    orig_copy.pop("support_status", None)
                    orig_reason = str(orig_copy.get("reason_summary") or "Original AI candidate finding.").strip()
                    if not orig_reason.startswith("[Original AI Finding]"):
                        orig_reason = f"[Original AI Finding] {orig_reason}"
                    orig_copy["reason_summary"] = orig_reason
                    orig_id = str(orig_copy.get("hypothesis_id") or f"hyp-orig-{len(merged_hyps) + 1:02d}")
                    if orig_id in seen_ids:
                        orig_id = f"{orig_id}-ai-orig"
                    seen_ids.add(orig_id)
                    orig_copy["hypothesis_id"] = orig_id
                    merged_hyps.append(orig_copy)

                if merged_hyps:
                    edit_ctx["hypotheses"] = merged_hyps[:10]
            elif k == "unknowns" and isinstance(v, list):
                combined_unknowns = list(dict.fromkeys([*original_unknowns, *[str(u) for u in v if isinstance(u, str)]]))
                edit_ctx["unknowns"] = combined_unknowns
            else:
                edit_ctx[k] = copy.deepcopy(v)

        return edit_ctx

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
        auth_context: Any = None,
    ) -> Dict[str, Any]:
        """Submit an authorized human review decision on a specific dossier revision."""
        formatted_inc_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"

        with self._lock:
            raw_version_hint = 1
            if isinstance(target_version, int) and not isinstance(target_version, bool):
                raw_version_hint = target_version
            elif isinstance(revision_number, int) and not isinstance(revision_number, bool):
                raw_version_hint = revision_number
            elif (
                isinstance(dossier_dict, dict)
                and isinstance(dossier_dict.get("dossier_version"), int)
                and not isinstance(dossier_dict.get("dossier_version"), bool)
            ):
                raw_version_hint = int(dossier_dict["dossier_version"])

            # 1. Authorize Human Actor, Role & PoC Trust Boundary (INV-05)
            auth_meta = self._authorize_reviewer(
                incident_id=formatted_inc_id,
                target_version=raw_version_hint,
                decision=decision,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
                auth_context=auth_context,
            )
            cleaned_ref = auth_meta["claimed_reviewer_ref"]

            # 2. Validate and Normalize Decision enum
            if not isinstance(decision, str) or decision not in DECISION_MAP:
                self._record_denied_audit(
                    incident_id=formatted_inc_id,
                    target_version=raw_version_hint,
                    reason_code="SCHEMA_INVALID",
                    decision=str(decision),
                    reviewer_ref=cleaned_ref,
                    reviewer_role=reviewer_role,
                    detail=f"Invalid review decision: {decision!r}",
                )
                raise InvalidReviewDecisionError(str(decision))
            canonical_decision = DECISION_MAP[decision]

            # 3. Validate Dossier Structure, Safety & Cryptographic Hash Integrity (before any mutation)
            if not isinstance(dossier_dict, dict):
                raise InvalidDossierError("Dossier payload must be a dictionary.")

            dossier_inc_raw = str(dossier_dict.get("incident_id") or "")
            dossier_inc_id = dossier_inc_raw if dossier_inc_raw.startswith("inc-") else f"inc-{dossier_inc_raw}"
            if not dossier_inc_raw or dossier_inc_id != formatted_inc_id:
                self._record_denied_audit(
                    incident_id=formatted_inc_id,
                    target_version=raw_version_hint,
                    reason_code="SCHEMA_INVALID",
                    decision=canonical_decision,
                    reviewer_ref=cleaned_ref,
                    reviewer_role=reviewer_role,
                    detail=f"Dossier incident_id {dossier_inc_raw!r} does not match {formatted_inc_id!r}",
                )
                raise InvalidDossierError(
                    f"Dossier incident_id {dossier_inc_raw!r} does not match {formatted_inc_id!r}."
                )

            raw_version = dossier_dict.get("dossier_version")
            if type(raw_version) is not int or raw_version < 1:
                raise InvalidDossierError(f"Invalid dossier_version: {raw_version!r}")

            requested_version = target_version if target_version is not None else revision_number
            effective_target_version = requested_version if requested_version is not None else raw_version
            if type(effective_target_version) is not int or effective_target_version < 1:
                raise InvalidDossierError(f"Invalid target_version: {effective_target_version!r}")

            given_hash = dossier_dict.get("dossier_hash")
            if not isinstance(given_hash, str) or not given_hash.strip():
                self._record_denied_audit(
                    incident_id=formatted_inc_id,
                    target_version=effective_target_version,
                    reason_code="SCHEMA_INVALID",
                    decision=canonical_decision,
                    reviewer_ref=cleaned_ref,
                    reviewer_role=reviewer_role,
                    detail="Dossier missing canonical SHA-256 dossier_hash.",
                )
                raise InvalidDossierError("Dossier missing required canonical SHA-256 dossier_hash.")

            computed_hash = compute_canonical_dossier_hash(dossier_dict)
            if computed_hash != given_hash:
                self._record_denied_audit(
                    incident_id=formatted_inc_id,
                    target_version=effective_target_version,
                    reason_code="SCHEMA_INVALID",
                    decision=canonical_decision,
                    reviewer_ref=cleaned_ref,
                    reviewer_role=reviewer_role,
                    detail="Dossier hash mismatch.",
                )
                raise DossierHashMismatchError(expected_hash=given_hash, actual_hash=computed_hash)

            hyps = dossier_dict.get("hypotheses")
            legacy_hyps = (
                (dossier_dict.get("root_cause_analysis") or {}).get("ranked_hypotheses")
                if isinstance(dossier_dict.get("root_cause_analysis"), dict)
                else None
            )
            effective_hyps = hyps if isinstance(hyps, list) else legacy_hyps
            if not isinstance(effective_hyps, list) or not effective_hyps:
                raise InvalidDossierError("Dossier must contain at least one hypothesis.")
            for h in effective_hyps:
                if not isinstance(h, dict):
                    raise InvalidDossierError("Dossier hypothesis entries must be objects.")
                h_stat = _status_str(h.get("support_status") or h.get("evaluation_status") or h.get("status"), "").upper()
                if h_stat == "VERIFIED":
                    raise InvalidDossierError("RULE-007 Violation: Dossier contains forbidden 'VERIFIED' hypothesis status.")

            for chk in dossier_dict.get("recommended_checks") or []:
                if isinstance(chk, dict) and chk.get("auto_execution_allowed") is True:
                    raise InvalidDossierError("INV-01 Violation: Dossier check cannot allow auto_execution_allowed=True.")

            # 4. Validate Rationale & Correction Payload Safety (including privilege-escalation rejection)
            cleaned_rationale = " ".join((rationale or "").split())
            if len(cleaned_rationale) < 5:
                raise ReviewError("Review rationale must be at least 5 characters.", code="INVALID_RATIONALE")

            if edited_dossier_data is not None:
                if not isinstance(edited_dossier_data, dict):
                    raise InvalidDossierError("edited_dossier_data must be a dictionary.")
                priv_fields = sorted(set(edited_dossier_data.keys()) & _PRIVILEGE_ESCALATION_EDIT_FIELDS)
                if priv_fields:
                    self._record_denied_audit(
                        incident_id=formatted_inc_id,
                        target_version=effective_target_version,
                        reason_code="FORBIDDEN_SCOPE",
                        decision=canonical_decision,
                        reviewer_ref=cleaned_ref,
                        reviewer_role=reviewer_role,
                        detail=f"Forbidden privilege/control fields in edited_dossier_data: {priv_fields}",
                    )
                    raise UnauthorizedReviewerError(
                        reviewer_role,
                        message=f"UNAUTHORIZED: Privilege escalation or control-field override in edited_dossier_data is forbidden: {priv_fields}",
                    )
                if canonical_decision == "edit":
                    gt_clean, gt_violations = verify_ground_truth_isolation(edited_dossier_data)
                    if not gt_clean:
                        raise InvalidDossierError(f"INV-04 Ground Truth isolation violation in correction: {gt_violations}")
                    edited_hyps = edited_dossier_data.get("hypotheses")
                    if edited_hyps is not None:
                        if not isinstance(edited_hyps, list):
                            raise InvalidDossierError("Corrected hypotheses must be a list.")
                        for eh in edited_hyps:
                            if not isinstance(eh, dict):
                                raise InvalidDossierError("Corrected hypothesis entry must be an object.")
                            eh_stat = _status_str(eh.get("status") or eh.get("support_status"), "").upper()
                            if eh_stat == "VERIFIED":
                                raise InvalidDossierError("RULE-007 Violation: Corrected hypothesis status cannot be 'VERIFIED'.")
                            for text_field in ("statement", "title", "reason_summary", "description"):
                                if _VERIFIED_PATTERN.search(str(eh.get(text_field) or "")):
                                    raise InvalidDossierError("RULE-007 Violation: Corrected hypothesis text cannot claim 'VERIFIED'.")
                    edited_checks = edited_dossier_data.get("recommended_checks")
                    if edited_checks is not None:
                        if not isinstance(edited_checks, list):
                            raise InvalidDossierError("Corrected recommended_checks must be a list.")
                        for chk in edited_checks:
                            if not isinstance(chk, dict):
                                raise InvalidDossierError("Corrected recommended_checks entries must be objects.")
                            if chk.get("auto_execution_allowed") is True or chk.get("requires_human_approval") is False:
                                self._record_denied_audit(
                                    incident_id=formatted_inc_id,
                                    target_version=effective_target_version,
                                    reason_code="SCHEMA_INVALID",
                                    decision=canonical_decision,
                                    reviewer_ref=cleaned_ref,
                                    reviewer_role=reviewer_role,
                                    detail="INV-01 Violation: Edited check cannot enable auto_execution_allowed or waive human approval.",
                                )
                                raise InvalidDossierError(
                                    "INV-01 Violation: Corrected check cannot allow auto_execution_allowed=True or requires_human_approval=False."
                                )

            # 5–8. Atomic SQLite Transaction (BEGIN IMMEDIATE) + Fail-Closed Audit + Compensation
            audit_sink = self._audit_sink()
            recorded_audit_events: List[Dict[str, Any]] = []
            pending_error: Optional[BaseException] = None
            pending_denied_kwargs: Optional[Dict[str, Any]] = None
            review_event: Optional[Dict[str, Any]] = None
            updated_dossier: Optional[Dict[str, Any]] = None
            new_dossier_version_record: Optional[Dict[str, Any]] = None
            approval_semantics: Optional[Dict[str, Any]] = None
            event_id = f"rev-{uuid.uuid4().hex[:16]}"

            try:
                with self.store.transaction(immediate=True):
                    # Authoritative DB reads inside BEGIN IMMEDIATE write transaction
                    latest_version = self.store.get_latest_dossier_version(formatted_inc_id)
                    existing_incident = self.store.get_incident(formatted_inc_id)
                    stored_dossier = self.store.get_dossier(formatted_inc_id, version=effective_target_version)
                    prior_reviews = self.store.get_reviews(formatted_inc_id)

                    if requested_version is not None and requested_version != raw_version:
                        if latest_version > requested_version:
                            pending_denied_kwargs = {
                                "incident_id": formatted_inc_id,
                                "target_version": requested_version,
                                "reason_code": "VERSION_CONFLICT",
                                "decision": canonical_decision,
                                "reviewer_ref": cleaned_ref,
                                "reviewer_role": reviewer_role,
                                "detail": f"Target version v{requested_version} superseded by v{latest_version}.",
                            }
                            pending_error = StaleDossierVersionError(requested_version, latest_version)
                        else:
                            pending_error = InvalidDossierError(
                                f"Target version v{requested_version} does not match dossier payload version v{raw_version}."
                            )
                    elif latest_version > effective_target_version or (
                        latest_version > 0 and effective_target_version > latest_version
                    ):
                        _LOG.warning(
                            "Stale review attempt on %s: target v%d != latest v%d",
                            formatted_inc_id,
                            effective_target_version,
                            latest_version,
                        )
                        pending_denied_kwargs = {
                            "incident_id": formatted_inc_id,
                            "target_version": effective_target_version,
                            "reason_code": "VERSION_CONFLICT",
                            "decision": canonical_decision,
                            "reviewer_ref": cleaned_ref,
                            "reviewer_role": reviewer_role,
                            "detail": f"Target version v{effective_target_version} conflicts with latest v{latest_version}.",
                        }
                        pending_error = StaleDossierVersionError(
                            target_version=effective_target_version,
                            latest_version=latest_version,
                        )
                    elif existing_incident is not None and existing_incident["current_state"] != "HUMAN_REVIEW":
                        cur_state = existing_incident["current_state"]
                        is_finalized = cur_state in (TERMINAL_STATES | {"CLOSED"})
                        err_code = "ALREADY_FINALIZED" if is_finalized else "INVALID_STATE_TRANSITION"
                        pending_denied_kwargs = {
                            "incident_id": formatted_inc_id,
                            "target_version": effective_target_version,
                            "reason_code": "VERSION_CONFLICT" if is_finalized else "FORBIDDEN_SCOPE",
                            "decision": canonical_decision,
                            "reviewer_ref": cleaned_ref,
                            "reviewer_role": reviewer_role,
                            "detail": f"Cannot execute review decision {canonical_decision!r} in lifecycle state {cur_state!r}.",
                        }
                        pending_error = ReviewStateConflictError(
                            f"Cannot execute {canonical_decision!r} on {formatted_inc_id}: incident is in state {cur_state!r} (expected 'HUMAN_REVIEW').",
                            code=err_code,
                        )
                    else:
                        def _is_finalized_review_summary(doc_obj: Mapping[str, Any] | None) -> tuple[bool, str]:
                            rev_sum = (doc_obj or {}).get("review_summary")
                            rev_sum = rev_sum if isinstance(rev_sum, Mapping) else {}
                            status_val = str(rev_sum.get("status", "PENDING_REVIEW")).upper()
                            if status_val in ("APPROVED", "REJECTED", "EDITED"):
                                return True, status_val
                            if status_val == "MANUAL_TRIAGE":
                                # Unreviewed manual_fallback drafts enter HUMAN_REVIEW with status="MANUAL_TRIAGE"
                                # and null review markers; human ESCALATE sets latest_review_event_id and reviewed_by.
                                has_human_marker = bool(
                                    rev_sum.get("latest_review_event_id")
                                    or rev_sum.get("reviewed_by")
                                    or rev_sum.get("reviewed_at")
                                )
                                return has_human_marker, status_val
                            return False, status_val

                        input_finalized, dossier_review_status = _is_finalized_review_summary(dossier_dict)
                        stored_finalized, stored_status = (
                            _is_finalized_review_summary(stored_dossier.get("dossier_json") or {})
                            if stored_dossier is not None
                            else (False, "PENDING_REVIEW")
                        )

                        if input_finalized:
                            pending_denied_kwargs = {
                                "incident_id": formatted_inc_id,
                                "target_version": effective_target_version,
                                "reason_code": "VERSION_CONFLICT",
                                "decision": canonical_decision,
                                "reviewer_ref": cleaned_ref,
                                "reviewer_role": reviewer_role,
                                "detail": f"Dossier revision already finalized with status {dossier_review_status!r}.",
                            }
                            pending_error = ReviewStateConflictError(
                                f"Dossier v{effective_target_version} for {formatted_inc_id} is already finalized ({dossier_review_status}).",
                                code="ALREADY_FINALIZED",
                            )
                        elif stored_finalized:
                            pending_denied_kwargs = {
                                "incident_id": formatted_inc_id,
                                "target_version": effective_target_version,
                                "reason_code": "VERSION_CONFLICT",
                                "decision": canonical_decision,
                                "reviewer_ref": cleaned_ref,
                                "reviewer_role": reviewer_role,
                                "detail": f"Persisted dossier v{effective_target_version} already has status {stored_status!r}.",
                            }
                            pending_error = ReviewStateConflictError(
                                f"Dossier v{effective_target_version} for {formatted_inc_id} is already finalized ({stored_status}).",
                                code="ALREADY_FINALIZED",
                            )
                        else:
                            finalizing_prior = [
                                r
                                for r in prior_reviews
                                if r.get("decision") in ("approve", "reject", "escalate_manual")
                            ]
                            if finalizing_prior:
                                pending_denied_kwargs = {
                                    "incident_id": formatted_inc_id,
                                    "target_version": effective_target_version,
                                    "reason_code": "VERSION_CONFLICT",
                                    "decision": canonical_decision,
                                    "reviewer_ref": cleaned_ref,
                                    "reviewer_role": reviewer_role,
                                    "detail": f"Conflicting decision after prior finalizing decision {finalizing_prior[-1].get('decision')!r}.",
                                }
                                pending_error = ReviewStateConflictError(
                                    f"Incident {formatted_inc_id} already has a finalized review decision ({finalizing_prior[-1].get('decision')}).",
                                    code="ALREADY_FINALIZED",
                                )
                            elif canonical_decision == "edit":
                                same_ver_edits = [
                                    r
                                    for r in prior_reviews
                                    if r.get("decision") == "edit"
                                    and r.get("target_dossier_version") == effective_target_version
                                ]
                                if same_ver_edits:
                                    pending_denied_kwargs = {
                                        "incident_id": formatted_inc_id,
                                        "target_version": effective_target_version,
                                        "reason_code": "VERSION_CONFLICT",
                                        "decision": canonical_decision,
                                        "reviewer_ref": cleaned_ref,
                                        "reviewer_role": reviewer_role,
                                        "detail": f"Concurrent edit conflict: dossier v{effective_target_version} was already edited.",
                                    }
                                    pending_error = ReviewStateConflictError(
                                        f"Dossier v{effective_target_version} for {formatted_inc_id} was already edited.",
                                        code="VERSION_CONFLICT",
                                    )

                    if pending_error is None:
                        # 6. Build Canonical Review Event & Updated Dossier In Memory
                        now = utc_now_z()
                        edited_version: Optional[int] = (
                            effective_target_version + 1 if canonical_decision == "edit" else None
                        )
                        schema_role = ROLE_SCHEMA_MAP.get(reviewer_role, reviewer_role)

                        review_event = {
                            "schema_version": "1.0",
                            "review_event_id": event_id,
                            "incident_id": formatted_inc_id,
                            "target_dossier_version": effective_target_version,
                            "target_dossier_hash": given_hash,
                            "reviewer_ref": cleaned_ref,
                            "reviewer_role": schema_role,
                            "reviewed_at": now,
                            "decision": canonical_decision,
                            "rationale": cleaned_rationale[:2048],
                            "edited_dossier_version": edited_version,
                            "escalation_target": escalation_target,
                            "auto_action_triggered": False,  # Strict HUM-01 Enforcement
                        }

                        if _REVIEW_VALIDATOR is not None:
                            errors = list(_REVIEW_VALIDATOR.iter_errors(review_event))
                            if errors:
                                err_msg = "; ".join(f"{e.json_path}: {e.message}" for e in errors)
                                raise ValueError(f"Review event failed schema validation: {err_msg}")

                        summary_status = {
                            "approve": "APPROVED",
                            "reject": "REJECTED",
                            "edit": "EDITED",
                            "escalate_manual": "MANUAL_TRIAGE",
                        }[canonical_decision]

                        updated_dossier = copy.deepcopy(dossier_dict)
                        updated_dossier["review_summary"] = {
                            "status": summary_status,
                            "latest_review_event_id": event_id,
                            "reviewed_by": f"{cleaned_ref} ({reviewer_role})",
                            "reviewed_at": now,
                        }
                        updated_hash = compute_canonical_dossier_hash(updated_dossier)
                        updated_dossier["dossier_hash"] = updated_hash
                        updated_md = DossierMarkdownRenderer.render(updated_dossier)

                        new_md: Optional[str] = None
                        if canonical_decision == "edit":
                            edit_ctx = self._merge_human_edit_context(
                                base_dossier=updated_dossier,
                                edited_dossier_data=edited_dossier_data,
                                reviewer_ref=cleaned_ref,
                                reviewer_role=reviewer_role,
                            )
                            edit_ctx["review_summary"] = {
                                "status": "PENDING_REVIEW",
                                "latest_review_event_id": None,
                                "reviewed_by": None,
                                "reviewed_at": None,
                            }
                            new_rev = effective_target_version + 1
                            new_dossier_version_record = DossierSerializer.serialize(
                                edit_ctx,
                                revision=new_rev,
                                investigation_mode=str(
                                    updated_dossier.get("investigation_mode") or "deterministic_baseline"
                                ),
                            )
                            new_md = DossierMarkdownRenderer.render(new_dossier_version_record)

                        diagnostic_validation_statuses = self._extract_validation_statuses(
                            formatted_inc_id, updated_dossier
                        )
                        approval_semantics = self._build_approval_semantics(
                            canonical_decision=canonical_decision,
                            summary_status=summary_status,
                            updated_dossier=updated_dossier,
                            diagnostic_validation_statuses=diagnostic_validation_statuses,
                            previous_state="HUMAN_REVIEW",
                            authorization_context=auth_meta,
                        )

                        # 7. Stage SQLite Persistence Inside Uncommitted Transaction (rolled back on any error)
                        if existing_incident is None:
                            self.store.create_incident(
                                incident_id=formatted_inc_id,
                                service_id=updated_dossier.get("service_id"),
                                environment=updated_dossier.get("environment"),
                                initial_state="HUMAN_REVIEW",
                                status="ACTIVE",
                            )

                        self.store.record_review(review_event)
                        self.store.save_dossier(
                            incident_id=formatted_inc_id,
                            dossier_version=effective_target_version,
                            dossier_hash=updated_hash,
                            dossier_json=updated_dossier,
                            dossier_markdown=updated_md,
                            allow_overwrite=True,
                        )

                        if canonical_decision == "approve":
                            self.sm.transition(
                                incident_id=formatted_inc_id,
                                to_state="CLOSED",
                                idempotency_key=f"idem-{formatted_inc_id}-closed-{event_id}",
                                reason_code="OK",
                                terminal_outcome="CLOSED_APPROVED",
                                reason=f"Dossier v{effective_target_version} approved for handover by {cleaned_ref}: {cleaned_rationale}",
                                input_data={"review_event_id": event_id, "approval_semantics": approval_semantics},
                                output_data={
                                    "status": "CLOSED_APPROVED",
                                    "closure_meaning": "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED",
                                },
                            )
                        elif canonical_decision == "reject":
                            self.sm.transition(
                                incident_id=formatted_inc_id,
                                to_state="REJECTED",
                                idempotency_key=f"idem-{formatted_inc_id}-rejected-{event_id}",
                                reason_code="OK",
                                terminal_outcome="TERMINATED_REJECTED",
                                reason=f"Rejected by {cleaned_ref}: {cleaned_rationale}",
                                input_data={"review_event_id": event_id},
                                output_data={"status": "TERMINATED_REJECTED"},
                            )
                        elif canonical_decision == "escalate_manual":
                            self.sm.transition(
                                incident_id=formatted_inc_id,
                                to_state="MANUAL_TRIAGE_REQUIRED",
                                idempotency_key=f"idem-{formatted_inc_id}-escalated-{event_id}",
                                reason_code="OK",
                                terminal_outcome="TERMINATED_MANUAL_TRIAGE",
                                reason=f"Escalated to manual triage ({escalation_target}): {cleaned_rationale}",
                                input_data={"review_event_id": event_id, "escalation_target": escalation_target},
                                output_data={"status": "TERMINATED_MANUAL_TRIAGE"},
                            )
                        elif (
                            canonical_decision == "edit"
                            and new_dossier_version_record is not None
                            and new_md is not None
                        ):
                            self.store.save_dossier(
                                incident_id=formatted_inc_id,
                                dossier_version=new_dossier_version_record["dossier_version"],
                                dossier_hash=new_dossier_version_record["dossier_hash"],
                                dossier_json=new_dossier_version_record,
                                dossier_markdown=new_md,
                                allow_overwrite=False,
                            )
                            _LOG.info(
                                "Created new dossier revision v%d for %s",
                                new_dossier_version_record["dossier_version"],
                                formatted_inc_id,
                            )

                        # 8. Fail-Closed Audit Write AFTER SQLite Staging, BEFORE COMMIT
                        if audit_sink and hasattr(audit_sink, "record_event"):
                            decision_audit = audit_sink.record_event(
                                actor_ref="principal_reviewer",
                                action="HUMAN_REVIEW_DECISION",
                                target_ref=f"{formatted_inc_id}:v{effective_target_version}",
                                result_code="ALLOW",
                                reason_code="OK",
                                request_payload={
                                    "review_event": review_event,
                                    "approval_semantics": approval_semantics,
                                    "authorization_context": auth_meta,
                                },
                                incident_id=formatted_inc_id,
                                target_version=str(effective_target_version),
                                evidence_refs=[event_id, f"dossier:{updated_hash[:16]}"],
                            )
                            recorded_audit_events.append(decision_audit)

                            if canonical_decision == "approve":
                                # Exact _closure_payload required by evaluator/runner.py (C17 offline evaluation gate)
                                closure_payload = {
                                    "incident_id": formatted_inc_id,
                                    "dossier_version": effective_target_version,
                                    "dossier_hash": updated_hash,
                                    "terminal_state": "CLOSED",
                                }
                                closure_audit = audit_sink.record_event(
                                    actor_ref="principal_reviewer",
                                    action="WORKFLOW_TRANSITION",
                                    target_ref=f"{formatted_inc_id}:v{effective_target_version}",
                                    result_code="ALLOW",
                                    reason_code="OK",
                                    request_payload=closure_payload,
                                    incident_id=formatted_inc_id,
                                    target_version=str(effective_target_version),
                                )
                                recorded_audit_events.append(closure_audit)

            except BaseException as exc:
                if recorded_audit_events:
                    self._record_compensating_audit(
                        audit_sink=audit_sink,
                        incident_id=formatted_inc_id,
                        target_version=effective_target_version,
                        review_event_id=event_id,
                        prior_audit_event_ids=[
                            str(ev.get("audit_event_id", ""))
                            for ev in recorded_audit_events
                            if ev.get("audit_event_id")
                        ],
                        error=exc,
                    )
                raise

            if pending_error is not None:
                if pending_denied_kwargs is not None:
                    self._record_denied_audit(**pending_denied_kwargs)
                raise pending_error

            return {
                "review_event": review_event,
                "updated_dossier": updated_dossier,
                "new_dossier_revision": new_dossier_version_record,
                "approval_semantics": approval_semantics,
                "authorization_context": auth_meta,
                "audit_events": recorded_audit_events,
            }

    def approve(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str = "Dossier accepted for handover by human reviewer (administrative acceptance; does not verify unconfirmed root cause or authorize remediation).",
        target_version: Optional[int] = None,
        auth_context: Any = None,
    ) -> Dict[str, Any]:
        """Convenience method to approve an incident dossier revision for handover."""
        return self.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision="approve",
            rationale=rationale,
            target_version=target_version,
            auth_context=auth_context,
        )

    def reject(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str,
        target_version: Optional[int] = None,
        auth_context: Any = None,
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
            auth_context=auth_context,
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
        auth_context: Any = None,
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
            auth_context=auth_context,
        )

    def escalate(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        reviewer_ref: str,
        reviewer_role: str,
        rationale: str,
        escalation_target: Optional[str] = "SRE_LEAD_ONCALL",
        target_version: Optional[int] = None,
        auth_context: Any = None,
    ) -> Dict[str, Any]:
        """Convenience method to escalate an incident dossier for manual triage."""
        return self.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
            decision="escalate_manual",
            rationale=rationale,
            escalation_target=escalation_target,
            target_version=target_version,
            auth_context=auth_context,
        )

    def get_review_history(self, incident_id: str) -> List[Dict[str, Any]]:
        """Retrieve chronological history of all review events for an incident."""
        formatted_inc_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
        return self.store.get_reviews(formatted_inc_id)


def reconcile_review_audit(
    store: WorkflowStateStore,
    audit_events: Sequence[Mapping[str, Any]],
    incident_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcile independent JSONL audit events against persisted SQLite review & closure state."""
    events_list = [dict(ev) for ev in audit_events]
    chain_valid, chain_violations = verify_chain_integrity(events_list)

    filter_inc: Optional[str] = None
    if incident_id is not None:
        filter_inc = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"

    def _norm_inc(inc_val: Any, target_ref: Any) -> str:
        raw = str(inc_val or "").strip()
        if not raw and isinstance(target_ref, str) and target_ref:
            raw = target_ref.split(":", 1)[0].strip()
        if not raw:
            return ""
        return raw if raw.startswith("inc-") else f"inc-{raw}"

    compensated_audit_event_ids: Set[str] = set()
    for ev in events_list:
        if ev.get("action") == "HUMAN_REVIEW_DECISION" and ev.get("result_code") == "ERROR":
            for ref in ev.get("evidence_refs") or []:
                if isinstance(ref, str) and not ref.startswith("rev-"):
                    compensated_audit_event_ids.add(ref)

    compensated_rollbacks: List[Dict[str, Any]] = []
    unreconciled_orphans: List[Dict[str, Any]] = []
    unaudited_db_reviews: List[Dict[str, Any]] = []
    audited_review_ids: Set[str] = set()
    audit_seen_incidents: Set[str] = set()

    for ev in events_list:
        ev_inc = _norm_inc(ev.get("incident_id"), ev.get("target_ref"))
        if filter_inc is not None and ev_inc != filter_inc:
            continue
        if ev_inc:
            audit_seen_incidents.add(ev_inc)

        ev_id = str(ev.get("audit_event_id") or "")
        action = ev.get("action")
        result_code = ev.get("result_code")

        if action == "HUMAN_REVIEW_DECISION" and result_code == "ALLOW":
            ref_list = ev.get("evidence_refs") or []
            rev_ref = next((str(x) for x in ref_list if isinstance(x, str) and x.startswith("rev-")), None)
            if ev_id in compensated_audit_event_ids:
                compensated_rollbacks.append({
                    "audit_event_id": ev_id,
                    "incident_id": ev_inc,
                    "review_event_id": rev_ref,
                    "action": "HUMAN_REVIEW_DECISION",
                    "status": "COMPENSATED_DB_ROLLBACK",
                })
                continue
            db_reviews = store.get_reviews(ev_inc) if ev_inc else []
            if rev_ref and any(r.get("review_event_id") == rev_ref for r in db_reviews):
                audited_review_ids.add(rev_ref)
            else:
                unreconciled_orphans.append({
                    "audit_event_id": ev_id,
                    "incident_id": ev_inc,
                    "review_event_id": rev_ref,
                    "action": "HUMAN_REVIEW_DECISION",
                    "status": "ORPHANED_AUDIT_WITHOUT_DB_COMMIT",
                })
        elif (
            action == "WORKFLOW_TRANSITION"
            and ev.get("actor_ref") == "principal_reviewer"
            and result_code == "ALLOW"
        ):
            if ev_id in compensated_audit_event_ids:
                compensated_rollbacks.append({
                    "audit_event_id": ev_id,
                    "incident_id": ev_inc,
                    "action": "WORKFLOW_TRANSITION",
                    "status": "COMPENSATED_DB_ROLLBACK",
                })
                continue
            inc_row = store.get_incident(ev_inc) if ev_inc else None
            dossier_rec = store.get_dossier(ev_inc) if ev_inc else None
            matches_closed = False
            if inc_row and inc_row.get("current_state") == "CLOSED" and dossier_rec:
                fp = compute_request_fingerprint({
                    "incident_id": ev_inc,
                    "dossier_version": dossier_rec["dossier_version"],
                    "dossier_hash": dossier_rec["dossier_hash"],
                    "terminal_state": "CLOSED",
                })
                matches_closed = (ev.get("request_fingerprint") == fp)
            if not matches_closed:
                unreconciled_orphans.append({
                    "audit_event_id": ev_id,
                    "incident_id": ev_inc,
                    "action": "WORKFLOW_TRANSITION",
                    "status": "ORPHANED_CLOSURE_AUDIT_WITHOUT_CLOSED_DB",
                })

    if filter_inc is not None:
        incidents_to_check = [filter_inc]
    else:
        store_inc_ids = {str(row["incident_id"]) for row in store.list_incidents()}
        incidents_to_check = sorted(store_inc_ids | audit_seen_incidents)

    for check_inc in incidents_to_check:
        for db_rev in store.get_reviews(check_inc):
            rev_id = str(db_rev.get("review_event_id") or "")
            if rev_id not in audited_review_ids:
                unaudited_db_reviews.append({
                    "incident_id": check_inc,
                    "review_event_id": rev_id,
                    "decision": db_rev.get("decision"),
                    "status": "DB_REVIEW_MISSING_ALLOW_AUDIT",
                })

    return {
        "chain_valid": chain_valid,
        "chain_violations": chain_violations,
        "consistent": bool(chain_valid and not unreconciled_orphans and not unaudited_db_reviews),
        "compensated_rollbacks": compensated_rollbacks,
        "unreconciled_orphans": unreconciled_orphans,
        "unaudited_db_reviews": unaudited_db_reviews,
    }


# Backward-compatibility alias
HumanReviewManager = AuthorizedReviewManager
