"""Authoritative snapshot reader, view-models, terminal safety sanitization, and design tokens (P2-06).

Separates domain state access, view-model construction, and semantic formatting from
Rich widget rendering so TUI (`SREDashboard`) and CLI (`scripts/review_console.py`)
present identical, contract-faithful operational semantics without duplicating business logic.

Non-negotiable invariants enforced here:
- Zero auto-remediation (INV-01) and RULE-007 (never emit or imply VERIFIED diagnosis).
- WorkflowStateStore + AuthorizedReviewManager remain the sole authoritative domain sources (INV-03).
- Confidence scores are never recalculated, altered, or fabricated in the presentation layer (INV-08).
- Evidence freshness and historical relevance defer strictly to P1-05 `evidence_lineage` (INV-07).
- Untrusted log/SOP/LLM text is stripped of ANSI/OSC/DCS/C0/C1/BiDi control sequences and
  scrubbed against SEC-03 and Ground Truth leakage before reaching any terminal surface (INV-11, INV-13, INV-17).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import sqlite3
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from rich.cells import cell_len, set_cell_size
from rich.style import Style

from gateway.sanitizer import DeterministicSanitizer
from orchestrator.confidence import DEFAULT_SCORING_CONFIG, confidence_label_for_score
from orchestrator.dossier import DossierSerializer
from orchestrator.evidence_lineage import (
    DEFAULT_TEMPORAL_POLICY,
    INTEGRITY_SEMANTICS_NOTE,
    compute_evidence_content_hash,
    evaluate_evidence_temporal_validity,
    verify_evidence_integrity_and_scope,
)
from orchestrator.handover import DISALLOWED_GT_KEYS, DISALLOWED_STRING_PATTERNS
from orchestrator.review import (
    ALLOWED_REVIEWER_ROLES,
    ROLE_SCHEMA_MAP,
    _FORBIDDEN_AI_ACTOR_PATTERN,
    _FORBIDDEN_AI_REVIEWER_REFS,
    _FORBIDDEN_AI_SYSTEM_TOKENS,
    _FORBIDDEN_ANONYMOUS_TOKENS,
    _FORBIDDEN_PREFIXES,
    _VALID_HUMAN_REVIEWER_REF_PATTERN,
)
from orchestrator.state_machine import (
    MANDATORY_STATES,
    TERMINAL_STATES,
    WorkflowStateStore,
    utc_now_z,
)
from orchestrator.verification_plan import (
    SOP_GAPS,
    availability_text,
    hypothesis_label,
    sop_document_keys,
)


# ---------------------------------------------------------------------------
# Lifecycle & Triage Ordering Constants
# ---------------------------------------------------------------------------

ACTIVE_LIFECYCLE_STATES: frozenset[str] = frozenset(MANDATORY_STATES)
ARCHIVED_LIFECYCLE_STATES: frozenset[str] = frozenset(
    set(TERMINAL_STATES) | {"CLOSED", "REJECTED", "MANUAL_TRIAGE_REQUIRED", "FAILED_SAFE", "CANCELLED", "LEARNED"}
)

SEVERITY_PRIORITY_ORDER: Dict[str, int] = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "UNKNOWN": 4,
}

# Short non-color ASCII tags so severity/state never rely solely on color (AC-08, E09)
SEVERITY_ASCII_BADGE: Dict[str, str] = {
    "CRITICAL": "[CRIT]",
    "HIGH": "[HIGH]",
    "MEDIUM": "[MED]",
    "LOW": "[LOW]",
    "UNKNOWN": "[UNK]",
}

CALIBRATION_LIMITATION_NOTE = (
    "Heuristic support score [5%-85% cap], uncalibrated (not an empirical probability; "
    "does not prove or confirm root cause)."
)

ADMINISTRATIVE_CLOSURE_SHORT = (
    "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED "
    "(diagnosis_verified=False, technical_resolved=False, sop_compliance_confirmed=False, remediation_authorized=False)"
)

REVIEW_ACTION_SEMANTICS: Dict[str, Dict[str, str]] = {
    "APPROVE": {
        "label": "Accept Dossier for Handover (APPROVE)",
        "resulting_state": "CLOSED (Administrative Handover Only)",
        "summary": (
            "Accepts this dossier revision for administrative handover closure and exports sanitized handover "
            "artifacts. Does NOT establish verified root cause (diagnosis_verified=False), resolve the live "
            "technical incident (technical_resolved=False), confirm SOP compliance, or trigger remediation "
            "(auto_action_triggered=False)."
        ),
    },
    "REJECT": {
        "label": "Reject Dossier Findings (REJECT)",
        "resulting_state": "REJECTED (Manual Investigation Required)",
        "summary": (
            "Marks this dossier revision REJECTED in the append-only audit trail while preserving all original "
            "telemetry evidence and AI candidate findings intact for auditability. Zero automated actions run."
        ),
    },
    "CORRECT": {
        "label": "Propose Human Hypothesis Correction (CORRECT)",
        "resulting_state": "HUMAN_REVIEW (Spawns Revision vN+1 Pending Renewed Review)",
        "summary": (
            "Appends a new dossier revision v(N+1) with your human-authored candidate hypothesis while preserving "
            "original AI findings as [Original AI Finding]. Cannot assign VERIFIED status, inflate confidence to "
            "100%, or fabricate supporting telemetry evidence."
        ),
    },
    "ESCALATE": {
        "label": "Escalate to Human Triage (ESCALATE)",
        "resulting_state": "MANUAL_TRIAGE_REQUIRED (Locked from Further Dossier Sign-Off)",
        "summary": (
            "Routes the incident to human incident-commander triage (MANUAL_TRIAGE_REQUIRED). Records escalation "
            "target in the local PoC review log only; no external production paging or ITSM system is contacted."
        ),
    },
}


# ---------------------------------------------------------------------------
# Terminal Escape / Control / DLP / Ground-Truth Sanitization (INV-11, INV-13, INV-17)
# ---------------------------------------------------------------------------

_DISPLAY_SANITIZER = DeterministicSanitizer()

# Match ANSI CSI, OSC, DCS/APC/PM, and 2-byte ESC sequences
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[P^_X][^\x1b]*(?:\x1b\\|$)"
    r"|\x1b[@-Z\\-_]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
)

# Unicode BiDi overrides/isolates and invisible zero-width formatting characters
_UNSAFE_UNICODE_CONTROL_CHARS: frozenset[str] = frozenset(
    {
        "\u061c",  # Arabic Letter Mark
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\u202a",  # LRE
        "\u202b",  # RLE
        "\u202c",  # PDF
        "\u202d",  # LRO
        "\u202e",  # RLO
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
        "\ufeff",  # BOM
    }
)


# Match key=value Ground Truth / holdout / scenario assignments so values are scrubbed too
_GT_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:ground_truth|scenario_id|holdout_label|expected_root_cause|fault_injection_id)"
    r"\s*[:=]\s*[^\s,;\]})]+"
)

# Prevent untrusted log/SOP/LLM strings from spoofing RULE-007 VERIFIED status in UI
_UNTRUSTED_VERIFIED_SPOOF_RE = re.compile(r"\bVERIFIED\b")


def sanitize_terminal_text(
    value: Any,
    *,
    max_chars: int = 240,
    allow_newlines: bool = False,
    empty_placeholder: str = "-",
) -> str:
    """Sanitize dynamic text for safe terminal display.

    1. Strips ANSI CSI/OSC/DCS escape sequences and terminal control codes.
    2. Strips Unicode BiDi overrides and zero-width spoofing codepoints.
    3. Scrubs SEC-03 credentials/PII via DeterministicSanitizer.
    4. Scrubs restricted Ground Truth key/values and substrings (RULE-002 / INV-11)
       and neutralizes spoofed uppercase VERIFIED tokens in untrusted text (INV-02 / INV-17).
    5. Normalizes whitespace and bounds length using ASCII '...' (no font-missing glyphs).
    """
    if value is None:
        return empty_placeholder
    raw = str(value)
    if not raw:
        return empty_placeholder

    # 1. Strip terminal escape sequences first so split escapes cannot hide secrets
    no_ansi = _ANSI_ESCAPE_RE.sub("", raw)
    no_ansi = no_ansi.replace("\r\n", "\n").replace("\r", " ").replace("\t", " ")

    # 2. Strip C0/C1 control characters and BiDi overrides
    cleaned_chars: list[str] = []
    for ch in no_ansi:
        if ch in _UNSAFE_UNICODE_CONTROL_CHARS:
            continue
        code = ord(ch)
        if ch == "\n" and allow_newlines:
            cleaned_chars.append("\n")
            continue
        if code < 32 or code == 127 or (0x80 <= code <= 0x9F):
            cleaned_chars.append(" ")
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)

    # 3. Apply SEC-03 deterministic credential/PII redaction
    sanitized, _ = _DISPLAY_SANITIZER.sanitize_text(cleaned)

    # 4. Scrub prohibited Ground Truth key=value assignments and markers + spoofed VERIFIED badges
    sanitized = _GT_KEY_VALUE_RE.sub("[REDACTED_GT_FIELD]", sanitized)
    for pat in DISALLOWED_STRING_PATTERNS:
        sanitized = pat.sub("[REDACTED_GT_FIELD]", sanitized)
    sanitized = _UNTRUSTED_VERIFIED_SPOOF_RE.sub("[untrusted:verified]", sanitized)

    if allow_newlines:
        lines = [" ".join(line.split()) for line in sanitized.split("\n")]
        normalized = "\n".join(line for line in lines if line)
    else:
        normalized = " ".join(sanitized.split())

    if not normalized:
        return empty_placeholder

    if max_chars > 0 and len(normalized) > max_chars:
        if max_chars <= 3:
            return normalized[:max_chars]
        return f"{normalized[: max_chars - 3].rstrip()}..."
    return normalized


def compact_identifier(identifier: Any, *, max_cells: int = 28) -> str:
    """Preserve both prefix and unique tail when shortening long incident/evidence IDs."""
    clean = sanitize_terminal_text(identifier, max_chars=256, empty_placeholder="unknown")
    if max_cells <= 0 or cell_len(clean) <= max_cells:
        return clean
    if max_cells <= 10:
        return set_cell_size(clean, max(1, max_cells - 3)) + "..."
    tail_len = min(10, max(4, (max_cells - 3) // 2))
    head_len = max(3, max_cells - 3 - tail_len)
    head = set_cell_size(clean, head_len).rstrip()
    tail = clean[-tail_len:]
    candidate = f"{head}...{tail}"
    if cell_len(candidate) <= max_cells:
        return candidate
    return set_cell_size(clean, max_cells - 3) + "..."


def cell_width_truncate(text: str, max_cells: int) -> str:
    """Truncate text accurately by terminal display cell width (CJK/wide-glyph safe)."""
    if max_cells <= 0:
        return ""
    if cell_len(text) <= max_cells:
        return text
    if max_cells <= 3:
        return set_cell_size(text, max_cells)
    return set_cell_size(text, max_cells - 3).rstrip() + "..."


# ---------------------------------------------------------------------------
# Centralized Contrast-Verified Design Tokens (Work Package C1-C3, WCAG AA >= 4.5:1)
# ---------------------------------------------------------------------------

# Every hex color below is verified >= 4.5:1 against #292929, #1e1e1e, and #14181f
# via WCAG 2.x relative luminance formula (and >= 3.0:1 for structural borders).
# Palette discipline (antislop R-29):
# - Neutrals: #f8fafc (primary text), #cbd5e1 (secondary labels), #94a3b8 (muted borders)
# - Core semantic colors (3): #fca5a5 (error/critical), #fde047 (warning/unconfirmed), #86efac (infra healthy ONLY)
# - Deliberate focus/corroboration accent (1 family): #38bdf8 (active focus) / #67e8f9 (corroborated observation)

@dataclasses.dataclass(frozen=True)
class ConsoleDesignTokens:
    """Centralized terminal-native visual tokens with monochrome fallback."""

    monochrome: bool = False

    @property
    def primary(self) -> Style:
        return Style(bold=False) if self.monochrome else Style(color="#f8fafc")

    @property
    def primary_bold(self) -> Style:
        return Style(bold=True) if self.monochrome else Style(color="#f8fafc", bold=True)

    @property
    def secondary(self) -> Style:
        return Style() if self.monochrome else Style(color="#cbd5e1")

    @property
    def muted(self) -> Style:
        return Style() if self.monochrome else Style(color="#94a3b8")

    @property
    def border_inactive(self) -> Style | str:
        return "" if self.monochrome else "#94a3b8"

    @property
    def border_focused(self) -> Style | str:
        return "bold" if self.monochrome else "bold #38bdf8"

    @property
    def border_modal(self) -> Style | str:
        return "bold" if self.monochrome else "bold #fde047"

    @property
    def accent(self) -> Style:
        return Style(bold=True) if self.monochrome else Style(color="#38bdf8", bold=True)

    @property
    def selected_row(self) -> Style:
        return Style(bold=True, reverse=True) if self.monochrome else Style(color="#38bdf8", bold=True)

    @property
    def selected_nav(self) -> Style:
        return Style(bold=True, reverse=True) if self.monochrome else Style(color="#0f172a", bgcolor="#38bdf8", bold=True)

    @property
    def warning(self) -> Style:
        return Style(bold=True) if self.monochrome else Style(color="#fde047", bold=True)

    @property
    def warning_soft(self) -> Style:
        return Style() if self.monochrome else Style(color="#fde047")

    @property
    def critical(self) -> Style:
        return Style(bold=True) if self.monochrome else Style(color="#fca5a5", bold=True)

    @property
    def infra_healthy(self) -> Style:
        """Reserved strictly for infrastructure/connectivity status, NEVER confidence or CLOSED diagnosis."""
        return Style(bold=True) if self.monochrome else Style(color="#86efac", bold=True)

    @property
    def corroborated(self) -> Style:
        """Informational cyan for SUPPORTED observations (distinct from green so it never implies VERIFIED)."""
        return Style(bold=True) if self.monochrome else Style(color="#67e8f9", bold=True)

    @property
    def disabled(self) -> Style:
        return Style() if self.monochrome else Style(color="#94a3b8")

    def severity_style(self, severity: str) -> Style:
        sev = severity.upper()
        if sev in ("CRITICAL", "HIGH"):
            return self.critical
        if sev == "MEDIUM":
            return self.warning
        return self.secondary

    def support_style(self, support_label: str) -> Style:
        sup = support_label.upper()
        if sup == "SUPPORTED":
            return self.corroborated
        if sup in ("PARTIAL", "INCONCLUSIVE"):
            return self.warning_soft
        if sup in ("CONTRADICTED", "UNSUPPORTED"):
            return self.critical
        return self.secondary


TOKENS_COLOR = ConsoleDesignTokens(monochrome=False)
TOKENS_MONO = ConsoleDesignTokens(monochrome=True)


def tokens_for_console(console: Any) -> ConsoleDesignTokens:
    """Select color or monochrome tokens based on Rich Console capabilities."""
    if console is None or getattr(console, "color_system", None) is None or getattr(console, "no_color", False):
        return TOKENS_MONO
    return TOKENS_COLOR


# ---------------------------------------------------------------------------
# View-Model Dataclasses
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class LifecycleStageVM:
    stage: str
    status: str  # "COMPLETED" | "CURRENT" | "PENDING" | "ABORTED"
    occurred_at: str = ""
    reason_code: str = ""


@dataclasses.dataclass(frozen=True)
class HypothesisItemVM:
    rank: int
    hypothesis_id: str
    statement: str
    support_label: str
    origin_kind: str  # "AI_CANDIDATE" | "HUMAN_CORRECTION" | "ORIGINAL_AI_FINDING"
    confidence_score: Optional[float]
    confidence_band: str
    confidence_display: str
    is_unvalidated_prior: bool
    supporting_ids: Tuple[str, ...]
    contradicting_ids: Tuple[str, ...]
    excluded_supporting: Tuple[Dict[str, str], ...]
    partial_supporting_ids: Tuple[str, ...]
    reason_summary: str
    confidence_rationale: str
    main_uncertainty: str


@dataclasses.dataclass(frozen=True)
class EvidenceItemVM:
    evidence_id: str
    tool_name: str
    source_system: str
    source_ref: str
    service_id: str
    environment: str
    observation_kind: str
    value_and_unit: str
    aggregation: str
    observed_at: str
    query_window_str: str
    collected_at: str
    temporal_classification: str
    temporal_badge: str
    data_quality: str
    truncated: bool
    sampling_note: str
    disposition: str  # "ACCEPTED_SUPPORT" | "CONTRADICTING" | "CONTEXTUAL" | "REJECTED"
    associated_hypotheses: Tuple[str, ...]
    limitations: Tuple[str, ...]
    integrity_ok: bool
    integrity_code: str
    content_hash_short: str
    summary: str


@dataclasses.dataclass(frozen=True)
class UnresolvedEvidenceRefVM:
    hypothesis_id: str
    hypothesis_rank: int
    evidence_id: str
    role: str


@dataclasses.dataclass(frozen=True)
class SOPCitationVM:
    doc_id: str
    version: str
    section_path: str
    chunk_id: str
    source_uri: str
    excerpt: str
    retrieval_score_note: str


@dataclasses.dataclass(frozen=True)
class ManualCheckVM:
    index: int
    check_id: str
    status: str  # Always "NOT_PERFORMED" unless an authorized backend field exists
    provenance_tag: str
    risk_level: str
    related_sop_doc_id: str
    description: str
    requires_human_approval: bool
    auto_execution_allowed: bool


@dataclasses.dataclass(frozen=True)
class RAGTransparencyVM:
    availability_code: str
    availability_banner: str
    availability_explanation: str
    competing_sop_warning: str
    delivery_recorded: bool
    retrieved_count: Optional[int]
    eligible_count: Optional[int]
    delivered_to_llm_count: Optional[int]
    omitted_count: Optional[int]
    omitted_reasons: Tuple[str, ...]
    compaction_rung: str
    delivery_summary: str
    citations: Tuple[SOPCitationVM, ...]
    manual_checks: Tuple[ManualCheckVM, ...]


@dataclasses.dataclass(frozen=True)
class ReviewEligibilityVM:
    eligible: bool
    lock_code: str  # "" when eligible, otherwise reason code
    lock_message: str
    lifecycle_state: str
    dossier_review_status: str
    closure_display: str
    target_version: int
    target_hash: str
    reviewer_ref: str
    reviewer_role: str
    reviewer_authorized: bool
    reviewer_auth_reason: str
    identity_mode: str
    identity_disclosure: str


@dataclasses.dataclass(frozen=True)
class IncidentDetailVM:
    incident_id: str
    severity: str
    severity_badge: str
    primary_service: str
    environment: str
    affected_services: Tuple[str, ...]
    lifecycle_state: str
    lifecycle_display: str
    dossier_available: bool
    dossier_version: int
    latest_dossier_version: int
    dossier_hash: str
    revision_history_note: str
    incident_time_display: str
    incident_time_compact: str
    alert_received_at: str
    investigation_started_at: str
    dossier_ready_at: str
    duration_display: str
    tool_calls_used: Optional[int]
    investigation_mode: str
    mode_badge: str
    mode_headline: str
    provider_name: str
    model_version: str
    prompt_version: str
    token_usage_display: str
    fallback_reason: str
    observed_symptoms: str
    error_budget_impact: str
    topology_flow: str
    cascade_summary: str
    topology_uncertainty: str
    stages: Tuple[LifecycleStageVM, ...]
    completed_stage_count: int
    hypotheses: Tuple[HypothesisItemVM, ...]
    ranking_note: str
    evidence_items: Tuple[EvidenceItemVM, ...]
    unresolved_evidence_refs: Tuple[UnresolvedEvidenceRefVM, ...]
    missing_sources: Tuple[Dict[str, str], ...]
    unknowns: Tuple[str, ...]
    rag: RAGTransparencyVM
    review_eligibility: ReviewEligibilityVM
    review_history: Tuple[Dict[str, Any], ...]
    consistency_warnings: Tuple[str, ...]
    raw_incident: Dict[str, Any]
    raw_dossier: Optional[Dict[str, Any]]


@dataclasses.dataclass(frozen=True)
class DashboardSnapshot:
    """Consistent atomic snapshot of operational domain state."""

    generation: int
    fetched_at_utc: str
    fetched_at_local: str
    store_connected: bool
    is_stale_last_known: bool
    refresh_error: str
    environments: Tuple[str, ...]
    active_entries: Tuple[IncidentDetailVM, ...]
    archived_entries: Tuple[IncidentDetailVM, ...]
    in_progress_count: int
    awaiting_review_count: int
    archived_count: int
    by_incident_id: Dict[str, IncidentDetailVM]


# ---------------------------------------------------------------------------
# Reviewer Eligibility Pre-Check (Mirrors AuthorizedReviewManager without mutating state)
# ---------------------------------------------------------------------------

def check_reviewer_actor_format(
    reviewer_ref: Any,
    reviewer_role: Any,
    *,
    reviewer_directory: Optional[Mapping[str, Any]] = None,
    require_registered_reviewer: bool = False,
) -> Tuple[bool, str]:
    """Read-only eligibility check matching AuthorizedReviewManager rules."""
    if not isinstance(reviewer_ref, str) or not reviewer_ref.strip():
        return False, "Reviewer identifier is empty."
    if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in reviewer_ref):
        return False, "Reviewer identifier contains invalid whitespace or control characters."
    cleaned_ref = reviewer_ref.strip()
    lowered_ref = cleaned_ref.lower()
    tokens = [t for t in re.split(r"[-_.:/@]+", lowered_ref) if t]
    if not _VALID_HUMAN_REVIEWER_REF_PATTERN.match(cleaned_ref):
        return False, f"Malformed human reviewer identifier {cleaned_ref[:48]!r}."
    if (
        lowered_ref in _FORBIDDEN_AI_REVIEWER_REFS
        or lowered_ref.startswith(_FORBIDDEN_PREFIXES)
        or _FORBIDDEN_AI_ACTOR_PATTERN.match(cleaned_ref)
        or any(tok in _FORBIDDEN_AI_SYSTEM_TOKENS for tok in tokens)
    ):
        return False, f"Automated/AI actor {cleaned_ref!r} cannot submit human reviews."
    if any(tok in _FORBIDDEN_ANONYMOUS_TOKENS for tok in tokens):
        return False, f"Anonymous/guest actor {cleaned_ref!r} cannot submit human reviews."
    if not isinstance(reviewer_role, str) or reviewer_role not in ALLOWED_REVIEWER_ROLES:
        return False, f"Role {reviewer_role!r} is not an authorized human reviewer role."
    if reviewer_directory is not None or require_registered_reviewer:
        directory = reviewer_directory or {}
        allowed = directory.get(cleaned_ref)
        schema_role = ROLE_SCHEMA_MAP.get(reviewer_role, reviewer_role)
        if allowed is None:
            return False, f"Reviewer {cleaned_ref!r} is not registered in reviewer directory."
        allowed_set = {allowed} if isinstance(allowed, str) else set(allowed)
        if reviewer_role not in allowed_set and schema_role not in allowed_set:
            return False, f"Reviewer {cleaned_ref!r} lacks directory role {reviewer_role!r}."
    return True, "Authorized local human reviewer role."


# ---------------------------------------------------------------------------
# Timestamp & Provenance Helpers
# ---------------------------------------------------------------------------

def _parse_iso_dt(raw_ts: Any) -> Optional[dt.datetime]:
    if not raw_ts or not isinstance(raw_ts, str):
        return None
    cleaned = raw_ts.strip()
    if not cleaned:
        return None
    try:
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except Exception:
        return None


def format_local_timestamp(raw_ts: Any, *, compact: bool = False) -> str:
    parsed = _parse_iso_dt(raw_ts)
    if parsed is None:
        return sanitize_terminal_text(raw_ts, max_chars=16, empty_placeholder="-")
    local_dt = parsed.astimezone()
    return local_dt.strftime("%H:%M:%S" if compact else "%m-%d %H:%M:%S")


def _infer_source_system(tool_name: str, source_ref: str) -> str:
    sref = source_ref.lower()
    for prefix in ("prometheus", "loki", "tempo", "catalog", "apm"):
        if sref.startswith(prefix):
            return prefix
    mapping = {
        "get_service_metrics": "prometheus",
        "search_error_logs": "loki",
        "get_trace_summary": "tempo",
        "get_service_dependencies": "service-catalog",
        "get_apm_health": "apm",
    }
    return mapping.get(tool_name, "unavailable")


def _temporal_badge_for_classification(
    classification: str,
    data_quality: str,
    truncated: bool,
    *,
    fresh_for_current: bool = False,
) -> str:
    cls_upper = str(classification or "").upper()
    if data_quality == "unavailable" or cls_upper == "SOURCE_UNAVAILABLE":
        base = "[SOURCE_UNAVAILABLE]"
    elif cls_upper in ("FRESH_FOR_CURRENT_STATE", "FRESH_FOR_CURRENT_ASSESSMENT"):
        base = "[CURRENT_FRESH]"
    elif cls_upper == "TEMPORALLY_RELEVANT":
        base = "[CURRENT_FRESH]" if fresh_for_current else "[HISTORICAL_VALID]"
    elif cls_upper in ("HISTORICAL_INCIDENT_WINDOW_VALID", "WITHIN_INCIDENT_WINDOW", "HISTORICAL_BUT_RELEVANT"):
        base = "[HISTORICAL_VALID]"
    elif cls_upper in ("STALE_FOR_CURRENT_STATE", "STALE_FOR_CURRENT_ASSESSMENT"):
        base = "[STALE_CURRENT]"
    elif cls_upper == "CLOCK_SKEW_SUSPECTED":
        base = "[CLOCK_SKEW]"
    elif cls_upper == "OUTSIDE_INCIDENT_WINDOW":
        base = "[OUTSIDE_WINDOW]"
    elif cls_upper in ("TIMESTAMP_MISSING", "TIMESTAMP_INVALID", "CLOCK_SKEW_EXCEEDED", "TEMPORAL_VALIDITY_UNKNOWN"):
        base = f"[{cls_upper}]"
    else:
        base = "[TIME_UNASSESSED]"

    if data_quality == "partial" or truncated:
        return f"{base}[PARTIAL]"
    return base


# ---------------------------------------------------------------------------
# Shared View-Model Construction (Used by Both TUI and CLI)
# ---------------------------------------------------------------------------

def build_incident_detail_vm(
    *,
    incident: Optional[Mapping[str, Any]],
    dossier: Optional[Mapping[str, Any]],
    dossier_versions: Sequence[Mapping[str, Any]] = (),
    checkpoint: Optional[Mapping[str, Any]] = None,
    transitions: Sequence[Mapping[str, Any]] = (),
    reviews: Sequence[Mapping[str, Any]] = (),
    llm_run: Optional[Mapping[str, Any]] = None,
    reviewer_ref: str = "sre_reviewer",
    reviewer_role: str = "L2_SRE",
    reviewer_directory: Optional[Mapping[str, Any]] = None,
    require_registered_reviewer: bool = False,
    require_authenticated_context: bool = False,
) -> IncidentDetailVM:
    """Construct a complete, sanitized, consistency-checked IncidentDetailVM."""
    inc_dict = dict(incident) if isinstance(incident, Mapping) else {}
    dos_dict = dict(dossier) if isinstance(dossier, Mapping) else None
    chk_ctx = (
        dict(checkpoint.get("context"))
        if isinstance(checkpoint, Mapping) and isinstance(checkpoint.get("context"), Mapping)
        else {}
    )
    consistency_warnings: list[str] = []

    raw_inc_id = (
        (dos_dict or {}).get("incident_id")
        or inc_dict.get("incident_id")
        or chk_ctx.get("incident_id")
        or "inc-unknown"
    )
    incident_id = sanitize_terminal_text(raw_inc_id, max_chars=128, empty_placeholder="inc-unknown")

    raw_sev = str(
        (dos_dict or {}).get("severity")
        or chk_ctx.get("priority")
        or chk_ctx.get("severity")
        or ((dos_dict or {}).get("impact_summary") or {}).get("severity")
        or "unknown"
    ).strip().upper()
    if raw_sev not in SEVERITY_PRIORITY_ORDER:
        raw_sev = "UNKNOWN"
    severity_badge = f"{SEVERITY_ASCII_BADGE[raw_sev]} {raw_sev}"

    primary_service = sanitize_terminal_text(
        (dos_dict or {}).get("service_id")
        or inc_dict.get("service_id")
        or chk_ctx.get("service_id")
        or "unknown",
        max_chars=80,
    )
    environment = sanitize_terminal_text(
        (dos_dict or {}).get("environment")
        or inc_dict.get("environment")
        or chk_ctx.get("environment")
        or "unknown",
        max_chars=40,
    )

    impact = (dos_dict or {}).get("impact_summary")
    impact = impact if isinstance(impact, Mapping) else {}
    raw_services = (
        impact.get("affected_services")
        or (dos_dict or {}).get("investigation_scope")
        or chk_ctx.get("investigation_scope")
        or [primary_service]
    )
    if isinstance(raw_services, Sequence) and not isinstance(raw_services, (str, bytes)):
        affected_services = tuple(
            sanitize_terminal_text(s, max_chars=80) for s in raw_services if s
        ) or (primary_service,)
    else:
        affected_services = (primary_service,)

    # Authoritative lifecycle state resolution
    review_summary = (dos_dict or {}).get("review_summary")
    review_summary = review_summary if isinstance(review_summary, Mapping) else {}
    dossier_review_status = sanitize_terminal_text(
        review_summary.get("status") or ("PENDING_REVIEW" if dos_dict else "NOT_GENERATED"),
        max_chars=40,
    ).upper()
    has_human_review_marker = bool(
        review_summary.get("latest_review_event_id")
        or review_summary.get("reviewed_by")
        or review_summary.get("reviewed_at")
    )

    if inc_dict.get("current_state"):
        lifecycle_state = sanitize_terminal_text(inc_dict["current_state"], max_chars=40).upper()
    elif dos_dict is not None:
        # Standalone CLI dossier inspection without a state DB
        if dossier_review_status == "APPROVED":
            lifecycle_state = "CLOSED"
        elif dossier_review_status == "REJECTED":
            lifecycle_state = "REJECTED"
        elif dossier_review_status == "MANUAL_TRIAGE" and has_human_review_marker:
            lifecycle_state = "MANUAL_TRIAGE_REQUIRED"
        else:
            lifecycle_state = "HUMAN_REVIEW"
    elif isinstance(checkpoint, Mapping) and checkpoint.get("state"):
        lifecycle_state = sanitize_terminal_text(checkpoint["state"], max_chars=40).upper()
    else:
        lifecycle_state = "UNKNOWN"

    finalizing_reviews = [
        dict(r)
        for r in reviews
        if isinstance(r, Mapping) and str(r.get("decision") or "").lower() in ("approve", "reject", "escalate_manual")
    ]
    if lifecycle_state == "HUMAN_REVIEW" and finalizing_reviews:
        consistency_warnings.append(
            f"State notice: review record {finalizing_reviews[-1].get('decision')} already exists; actions locked."
        )
    if lifecycle_state == "CLOSED" and dossier_review_status == "PENDING_REVIEW" and dos_dict is not None:
        consistency_warnings.append(
            "State notice: workflow state is CLOSED while dossier review_summary shows PENDING_REVIEW; treating as finalized."
        )

    if lifecycle_state == "MANUAL_TRIAGE_REQUIRED":
        lifecycle_display = "ESCALATED (MANUAL_TRIAGE_REQUIRED)"
    elif lifecycle_state == "CLOSED":
        lifecycle_display = "CLOSED (Admin Handover)"
    elif lifecycle_state in MANDATORY_STATES and lifecycle_state != "HUMAN_REVIEW":
        stage_idx = MANDATORY_STATES.index(lifecycle_state) + 1
        lifecycle_display = f"{lifecycle_state} [Running {stage_idx}/9]"
    else:
        lifecycle_display = lifecycle_state

    # Revision metadata
    dossier_available = dos_dict is not None
    dossier_version = int(dos_dict.get("dossier_version", 1)) if dos_dict and isinstance(dos_dict.get("dossier_version"), int) else (1 if dos_dict else 0)
    latest_ver = max(
        [dossier_version]
        + [int(v.get("dossier_version", 0)) for v in dossier_versions if isinstance(v, Mapping) and isinstance(v.get("dossier_version"), int)]
    )
    dossier_hash = sanitize_terminal_text((dos_dict or {}).get("dossier_hash") or "", max_chars=80, empty_placeholder="unavailable")
    if len(dossier_versions) > 1 or dossier_version > 1:
        revision_history_note = f"Revision v{dossier_version} of {max(latest_ver, len(dossier_versions))} (append-only human correction history preserved)"
    elif dossier_available:
        revision_history_note = f"Revision v{dossier_version} (initial dossier)"
    else:
        revision_history_note = "Dossier not yet generated (investigation has not reached DRAFTED/HUMAN_REVIEW)"

    # Timestamps & Duration
    window_map = (dos_dict or {}).get("incident_window")
    window_map = window_map if isinstance(window_map, Mapping) else {}
    raw_primary_ts = (
        window_map.get("start")
        or (dos_dict or {}).get("window_start")
        or (dos_dict or {}).get("alert_received_at")
        or (dos_dict or {}).get("event_time")
        or chk_ctx.get("event_time")
        or inc_dict.get("created_at")
        or inc_dict.get("updated_at")
    )
    incident_time_display = format_local_timestamp(raw_primary_ts, compact=False)
    incident_time_compact = format_local_timestamp(raw_primary_ts, compact=True)
    alert_received_at = sanitize_terminal_text(
        (dos_dict or {}).get("alert_received_at") or chk_ctx.get("event_time") or inc_dict.get("created_at"),
        max_chars=40,
    )
    first_transition_ts = transitions[0].get("occurred_at") if transitions else inc_dict.get("created_at")
    investigation_started_at = sanitize_terminal_text(first_transition_ts, max_chars=40)
    dossier_ready_at = sanitize_terminal_text((dos_dict or {}).get("dossier_ready_at"), max_chars=40)

    duration_display = "unavailable"
    t_start = _parse_iso_dt(first_transition_ts)
    t_end = _parse_iso_dt(
        (dos_dict or {}).get("dossier_ready_at")
        or (transitions[-1].get("occurred_at") if transitions else None)
        or inc_dict.get("updated_at")
    )
    if t_start and t_end and t_end >= t_start:
        secs = (t_end - t_start).total_seconds()
        duration_display = f"{secs:.2f}s" if secs < 60 else f"{int(secs // 60)}m {int(secs % 60)}s"

    # Tool usage count (only when genuinely recorded, never invented)
    tool_calls_used: Optional[int] = None
    if isinstance(chk_ctx.get("tool_calls_used"), int):
        tool_calls_used = int(chk_ctx["tool_calls_used"])
    elif dos_dict and isinstance(dos_dict.get("timeline"), list):
        tool_events = [
            t for t in dos_dict["timeline"]
            if isinstance(t, Mapping) and str(t.get("event_type") or "").upper() in ("TOOL_CALL", "TELEMETRY_COLLECTION")
        ]
        if tool_events:
            tool_calls_used = len(tool_events)

    # Investigation Mode, Runtime Model & Token Provenance (Work Package G2, G3)
    repro = (dos_dict or {}).get("reproducibility")
    repro = repro if isinstance(repro, Mapping) else {}
    inv_mode = str(
        (dos_dict or {}).get("investigation_mode")
        or chk_ctx.get("investigation_mode")
        or ("in_progress" if not dos_dict and lifecycle_state in MANDATORY_STATES else "deterministic_baseline")
    ).lower()
    model_ver = sanitize_terminal_text(
        repro.get("model_version")
        or (llm_run or {}).get("model")
        or ("pending" if inv_mode == "in_progress" else "deterministic_rule_engine_v1"),
        max_chars=80,
    )
    provider_name = sanitize_terminal_text(
        repro.get("provider")
        or (llm_run or {}).get("provider")
        or ("openrouter" if inv_mode == "agentic_llm" else "local-rule-engine"),
        max_chars=48,
    )
    prompt_ver = sanitize_terminal_text(
        repro.get("prompt_version") or "deterministic_baseline_rules_v1",
        max_chars=40,
    )

    in_tok = repro.get("input_tokens")
    out_tok = repro.get("output_tokens")
    tot_tok = repro.get("total_tokens")
    if inv_mode == "agentic_llm" and tot_tok is None and isinstance(llm_run, Mapping):
        rep_in = llm_run.get("input_reported")
        rep_out = llm_run.get("output_reported")
        if rep_in is not None or rep_out is not None:
            in_tok = int(rep_in or 0)
            out_tok = int(rep_out or 0)
            tot_tok = in_tok + out_tok

    fallback_reason = ""
    if inv_mode == "agentic_llm":
        mode_badge = "AI LLM"
        mode_headline = "AI MODEL (ONLINE)"
        token_usage_display = (
            f"in={in_tok}, out={out_tok}, total={tot_tok}"
            if tot_tok is not None
            else "Token counts not reported by provider"
        )
    elif inv_mode == "manual_fallback":
        reason_code = repro.get("llm_reason") or (llm_run or {}).get("error_code")
        if not reason_code and dos_dict:
            for unk in dos_dict.get("unknowns") or []:
                m = re.search(r"LLM synthesis unavailable \(([^)]+)\)", str(unk))
                if m:
                    reason_code = m.group(1)
                    break
        fallback_reason = sanitize_terminal_text(reason_code or "UNAVAILABLE", max_chars=64)
        mode_badge = "FALLBACK"
        mode_headline = f"MANUAL FALLBACK ({fallback_reason})"
        token_usage_display = "0 tokens (LLM unavailable; deterministic fallback active)"
    elif inv_mode == "in_progress":
        mode_badge = "RUNNING"
        mode_headline = f"INVESTIGATION IN PROGRESS ({lifecycle_state})"
        token_usage_display = "Pending completion"
    else:
        mode_badge = "OFFLINE"
        mode_headline = "OFFLINE DETERMINISTIC (NO AI MODEL)"
        token_usage_display = "0 tokens (Offline Rule Engine)"

    # Observed Symptoms & Topology Context
    observed_symptoms = sanitize_terminal_text(
        impact.get("observed_symptoms")
        or (dos_dict or {}).get("message")
        or chk_ctx.get("message")
        or ("Investigation in progress; symptom summary pending." if not dos_dict else "No symptoms recorded."),
        max_chars=420,
    )
    error_budget_impact = sanitize_terminal_text(impact.get("error_budget_impact") or "", max_chars=80, empty_placeholder="")
    impact_graph = chk_ctx.get("impact_graph") if isinstance(chk_ctx.get("impact_graph"), Mapping) else {}
    upstreams = impact_graph.get("upstream_callers") if isinstance(impact_graph.get("upstream_callers"), list) else []
    downstreams = impact_graph.get("downstream_dependencies") if isinstance(impact_graph.get("downstream_dependencies"), list) else []
    if upstreams or downstreams:
        up_str = ", ".join(sanitize_terminal_text(x, max_chars=48) for x in upstreams) if upstreams else "-"
        down_str = ", ".join(sanitize_terminal_text(x, max_chars=48) for x in downstreams) if downstreams else "-"
        topology_flow = f"[{up_str}] -> {primary_service} -> [{down_str}]"
    else:
        topology_flow = ""

    v_reports = chk_ctx.get("validation_reports")
    v_meta = v_reports[0] if isinstance(v_reports, list) and v_reports and isinstance(v_reports[0], Mapping) else {}
    origin_svc = v_meta.get("origin_service")
    is_cascade = v_meta.get("is_cascade")
    reason_codes = v_meta.get("reason_codes") if isinstance(v_meta.get("reason_codes"), list) else []
    if origin_svc or is_cascade is not None or reason_codes:
        flags = ", ".join(sanitize_terminal_text(rc, max_chars=40) for rc in reason_codes) if reason_codes else "-"
        cascade_summary = (
            f"origin={sanitize_terminal_text(origin_svc or primary_service, max_chars=48)} | "
            f"is_cascade={bool(is_cascade)} | flags={flags}"
        )
    else:
        cascade_summary = ""
    topology_uncertainty = sanitize_terminal_text(impact_graph.get("uncertainty") or "", max_chars=240, empty_placeholder="")

    # 9-State Lifecycle Stages (Work Package G1)
    transition_by_to: Dict[str, Mapping[str, Any]] = {}
    for tr in transitions:
        if isinstance(tr, Mapping) and tr.get("to_state"):
            transition_by_to[str(tr["to_state"]).upper()] = tr

    cur_idx = MANDATORY_STATES.index(lifecycle_state) if lifecycle_state in MANDATORY_STATES else (
        len(MANDATORY_STATES) if lifecycle_state in ("CLOSED", "LEARNED") else -1
    )
    stages_out: list[LifecycleStageVM] = []
    completed_count = 0
    for idx_s, st_name in enumerate(MANDATORY_STATES):
        tr_row = transition_by_to.get(st_name)
        occ = format_local_timestamp(tr_row.get("occurred_at"), compact=True) if tr_row else ""
        rcode = sanitize_terminal_text(tr_row.get("reason_code") or "", max_chars=32, empty_placeholder="") if tr_row else ""
        if lifecycle_state in ("CLOSED", "LEARNED"):
            st_status = "COMPLETED"
            completed_count += 1
        elif lifecycle_state in ("REJECTED", "MANUAL_TRIAGE_REQUIRED") and dos_dict is not None:
            st_status = "COMPLETED"
            completed_count += 1
        elif cur_idx >= 0:
            if idx_s < cur_idx or (idx_s == cur_idx and st_name == "HUMAN_REVIEW" and dos_dict is not None):
                st_status = "COMPLETED" if idx_s < cur_idx else "CURRENT"
                if idx_s < cur_idx:
                    completed_count += 1
            elif idx_s == cur_idx:
                st_status = "CURRENT"
            else:
                st_status = "PENDING"
        elif tr_row is not None:
            st_status = "COMPLETED"
            completed_count += 1
        elif lifecycle_state in ("FAILED_SAFE", "CANCELLED"):
            st_status = "ABORTED" if not any(s.status == "ABORTED" for s in stages_out) else "PENDING"
        else:
            st_status = "PENDING"
        stages_out.append(LifecycleStageVM(stage=st_name, status=st_status, occurred_at=occ, reason_code=rcode))

    # Hypotheses & Confidence (Work Package H1-H5: never invent or recalculate confidence)
    chk_hyp_map: Dict[str, Mapping[str, Any]] = {}
    for ch_h in chk_ctx.get("hypotheses") or []:
        if isinstance(ch_h, Mapping) and ch_h.get("hypothesis_id"):
            chk_hyp_map[str(ch_h["hypothesis_id"])] = ch_h

    prior_label_by_rank: Dict[int, str] = {}
    if isinstance(llm_run, Mapping) and llm_run.get("result"):
        try:
            parsed_res = json.loads(llm_run["result"]) if isinstance(llm_run["result"], str) else llm_run["result"]
            cands = (parsed_res or {}).get("candidates") or {}
            prim = cands.get("primary_hypothesis") or {}
            if isinstance(prim, Mapping) and prim.get("confidence"):
                prior_label_by_rank[1] = str(prim["confidence"]).upper()
            for idx_a, alt in enumerate(cands.get("alternative_hypotheses") or [], start=2):
                if isinstance(alt, Mapping) and alt.get("confidence"):
                    prior_label_by_rank[idx_a] = str(alt["confidence"]).upper()
        except Exception:
            pass

    raw_hyps = (
        (dos_dict or {}).get("hypotheses")
        or (((dos_dict or {}).get("root_cause_analysis") or {}).get("ranked_hypotheses") if isinstance((dos_dict or {}).get("root_cause_analysis"), Mapping) else None)
        or chk_ctx.get("hypotheses")
        or []
    )
    unknowns_raw = list((dos_dict or {}).get("unknowns") or chk_ctx.get("unknowns") or [])
    unknowns_clean = tuple(
        sanitize_terminal_text(u, max_chars=360) for u in unknowns_raw if isinstance(u, str) and u.strip()
    )

    hyp_vms: list[HypothesisItemVM] = []
    for idx_h, h in enumerate(raw_hyps, start=1):
        if not isinstance(h, Mapping):
            continue
        rank_num = int(h.get("rank", idx_h)) if isinstance(h.get("rank"), int) else idx_h
        hid = sanitize_terminal_text(h.get("hypothesis_id") or f"hyp-{idx_h:03d}", max_chars=96)
        chk_h = chk_hyp_map.get(hid) or {}
        if not chk_h:
            for cid_k, cid_v in chk_hyp_map.items():
                if cid_k.endswith(f"-{rank_num:03d}"):
                    chk_h = cid_v
                    break

        stmt = sanitize_terminal_text(
            h.get("statement") or h.get("hypothesis_statement") or h.get("title") or h.get("description") or "No statement recorded",
            max_chars=380,
        )
        raw_support = str(hypothesis_label(dict(h))).upper()
        # Enforce RULE-007 in presentation: never display VERIFIED
        if raw_support == "VERIFIED":
            raw_support = "INCONCLUSIVE"
            consistency_warnings.append(f"RULE-007 guard: suppressed invalid VERIFIED label on {hid}.")

        raw_reason = str(h.get("reason_summary") or h.get("description") or "")
        if raw_reason.startswith("[Human Correction"):
            origin_kind = "HUMAN_CORRECTION"
        elif raw_reason.startswith("[Original AI Finding]"):
            origin_kind = "ORIGINAL_AI_FINDING"
        else:
            origin_kind = "AI_CANDIDATE" if inv_mode == "agentic_llm" else "DETERMINISTIC_CANDIDATE"

        conf_val = h.get("confidence_score")
        if conf_val is None:
            conf_val = chk_h.get("confidence_score")

        is_unvalidated_prior = False
        if isinstance(conf_val, (int, float)) and not isinstance(conf_val, bool):
            f_conf = float(conf_val)
            band = confidence_label_for_score(f_conf, DEFAULT_SCORING_CONFIG)
            conf_display = f"{f_conf:.0%} ({band})"
            confidence_score: Optional[float] = f_conf
        else:
            confidence_score = None
            raw_prior = h.get("confidence") or chk_h.get("confidence") or prior_label_by_rank.get(rank_num)
            if raw_prior:
                band = sanitize_terminal_text(raw_prior, max_chars=16).upper()
                conf_display = f"Not scored [prior: {band}, unvalidated]"
                is_unvalidated_prior = True
            else:
                band = "UNSCORED"
                conf_display = "Not scored"

        conf_rationale = sanitize_terminal_text(
            h.get("confidence_rationale") or chk_h.get("confidence_rationale") or "",
            max_chars=360,
            empty_placeholder="",
        )
        breakdown = chk_h.get("confidence_breakdown") if isinstance(chk_h.get("confidence_breakdown"), Mapping) else {}
        excl_raw = breakdown.get("excluded_supporting") or chk_h.get("excluded_supporting") or []
        excl_clean: list[Dict[str, str]] = []
        for ex in excl_raw:
            if isinstance(ex, Mapping):
                excl_clean.append({
                    "evidence_id": sanitize_terminal_text(ex.get("evidence_id"), max_chars=80),
                    "reason": sanitize_terminal_text(ex.get("reason") or ex.get("code"), max_chars=120),
                })
        partial_ids = tuple(
            sanitize_terminal_text(pid, max_chars=80)
            for pid in (breakdown.get("partial_supporting_ids") or chk_h.get("partial_supporting_ids") or [])
            if pid
        )

        sup_ids = tuple(
            sanitize_terminal_text(eid, max_chars=96)
            for eid in (h.get("supporting_evidence_ids") or [])
            if eid
        )
        con_ids = tuple(
            sanitize_terminal_text(eid, max_chars=96)
            for eid in (h.get("contradicting_evidence_ids") or h.get("refuting_evidence_ids") or [])
            if eid
        )
        hyp_unks = h.get("unknowns") if isinstance(h.get("unknowns"), list) else []
        if hyp_unks:
            main_unc = sanitize_terminal_text(hyp_unks[0], max_chars=180)
        elif not sup_ids:
            main_unc = "No accepted supporting telemetry evidence linked."
        elif unknowns_clean:
            main_unc = unknowns_clean[0]
        else:
            main_unc = "Unconfirmed candidate; requires human verification."

        hyp_vms.append(
            HypothesisItemVM(
                rank=rank_num,
                hypothesis_id=hid,
                statement=stmt,
                support_label=raw_support,
                origin_kind=origin_kind,
                confidence_score=confidence_score,
                confidence_band=band,
                confidence_display=conf_display,
                is_unvalidated_prior=is_unvalidated_prior,
                supporting_ids=sup_ids,
                contradicting_ids=con_ids,
                excluded_supporting=tuple(excl_clean),
                partial_supporting_ids=partial_ids,
                reason_summary=sanitize_terminal_text(raw_reason, max_chars=420, empty_placeholder=""),
                confidence_rationale=conf_rationale,
                main_uncertainty=main_unc,
            )
        )

    # Check if persisted historical order differs from P1-04 monotonic support/confidence order
    ranking_note = "Authoritative persisted rank order preserved."
    if len(hyp_vms) > 1:
        top = hyp_vms[0]
        higher_alts = [
            alt for alt in hyp_vms[1:]
            if (alt.confidence_score or 0.0) > (top.confidence_score or 0.0) + 1e-6
        ]
        if higher_alts:
            ranking_note = (
                f"Historical proposal order preserved (INV-16): candidate #{higher_alts[0].rank} "
                f"carries higher heuristic support ({higher_alts[0].confidence_display}) than #1 ({top.confidence_display})."
            )

    # Evidence Lineage, Temporal Validity & Reference Resolution (Work Package I1-I5)
    ev_to_hyps: Dict[str, list[str]] = {}
    excluded_reason_by_eid: Dict[str, list[str]] = {}
    for h_vm in hyp_vms:
        for eid in h_vm.supporting_ids:
            ev_to_hyps.setdefault(eid, []).append(f"#{h_vm.rank} supports")
        for eid in h_vm.contradicting_ids:
            ev_to_hyps.setdefault(eid, []).append(f"#{h_vm.rank} contradicts")
        for ex in h_vm.excluded_supporting:
            excluded_reason_by_eid.setdefault(ex["evidence_id"], []).append(
                f"excluded for #{h_vm.rank}: {ex['reason']}"
            )

    chk_ev_by_id: Dict[str, Mapping[str, Any]] = {}
    for cev in chk_ctx.get("evidence_items") or []:
        if isinstance(cev, Mapping) and cev.get("evidence_id"):
            chk_ev_by_id[str(cev["evidence_id"])] = cev

    dossier_ev_list = (
        (dos_dict or {}).get("evidence")
        or (dos_dict or {}).get("evidence_items")
        or []
    )
    combined_raw_ev: list[Mapping[str, Any]] = []
    seen_eids: set[str] = set()
    for ev in dossier_ev_list:
        if isinstance(ev, Mapping):
            eid_key = str(ev.get("evidence_id") or "")
            if eid_key:
                seen_eids.add(eid_key)
            combined_raw_ev.append(ev)
    # Include rejected/checkpoint-only evidence items (if authorized within same service/env or explicitly rejected)
    # without leaking cross-incident payloads
    for eid_key, cev in chk_ev_by_id.items():
        if eid_key not in seen_eids:
            ev_inc = str(cev.get("incident_id") or incident_id)
            if ev_inc == incident_id:
                seen_eids.add(eid_key)
                combined_raw_ev.append(cev)

    inc_window_ctx = {
        "start": (dos_dict or {}).get("window_start") or (chk_ctx.get("query_window") or {}).get("start"),
        "end": (dos_dict or {}).get("window_end") or (chk_ctx.get("query_window") or {}).get("end"),
    }
    eval_ctx = {
        "incident_id": incident_id,
        "service_id": primary_service,
        "environment": environment,
        "investigation_scope": list(affected_services),
        "query_window": inc_window_ctx if inc_window_ctx["start"] and inc_window_ctx["end"] else None,
    }
    assessment_time = (
        chk_ctx.get("assessment_time")
        or (dos_dict or {}).get("dossier_ready_at")
        or (dos_dict or {}).get("window_end")
    )

    ev_vms: list[EvidenceItemVM] = []
    for raw_ev in combined_raw_ev:
        eid_raw = str(raw_ev.get("evidence_id") or "unknown")
        eid = sanitize_terminal_text(eid_raw, max_chars=96)
        chk_ev = chk_ev_by_id.get(eid_raw) or {}
        merged_ev: Dict[str, Any] = {**dict(chk_ev), **dict(raw_ev)}
        if "records" not in merged_ev and "records" in chk_ev:
            merged_ev["records"] = chk_ev["records"]

        tname = sanitize_terminal_text(merged_ev.get("tool_name") or "source unknown", max_chars=48)
        sref = sanitize_terminal_text(merged_ev.get("source_ref") or "unavailable", max_chars=80)
        src_sys = _infer_source_system(tname, sref)
        ev_svc = sanitize_terminal_text(merged_ev.get("service_id") or primary_service, max_chars=64)
        ev_env = sanitize_terminal_text(merged_ev.get("environment") or environment, max_chars=32)

        # Extract metric/observation details from records if available without fabricating missing fields
        recs = merged_ev.get("records") if isinstance(merged_ev.get("records"), list) else []
        first_rec = recs[0] if recs and isinstance(recs[0], Mapping) else {}
        obs_kind = sanitize_terminal_text(
            first_rec.get("metric_name")
            or first_rec.get("metric_enum")
            or first_rec.get("error_code")
            or first_rec.get("operation")
            or tname,
            max_chars=64,
        )
        if first_rec.get("value") is not None:
            unit_s = sanitize_terminal_text(first_rec.get("unit") or "", max_chars=24, empty_placeholder="")
            val_unit = sanitize_terminal_text(f"{first_rec.get('value')} {unit_s}".strip(), max_chars=48)
        elif recs:
            val_unit = f"{len(recs)} record(s)"
        else:
            val_unit = "unavailable"
        agg_str = sanitize_terminal_text(first_rec.get("aggregation") or "unavailable", max_chars=32)

        obs_at = sanitize_terminal_text(merged_ev.get("observed_at") or "unavailable", max_chars=40)
        col_at = sanitize_terminal_text(merged_ev.get("collected_at") or "not recorded", max_chars=40)
        qw = merged_ev.get("query_window") if isinstance(merged_ev.get("query_window"), Mapping) else {}
        qw_str = (
            f"{sanitize_terminal_text(qw.get('start'), max_chars=32)}..{sanitize_terminal_text(qw.get('end'), max_chars=32)}"
            if qw.get("start") or qw.get("end")
            else "n/a"
        )
        d_qual = sanitize_terminal_text(merged_ev.get("data_quality") or "unknown", max_chars=24)
        is_trunc = bool(merged_ev.get("truncated", False))
        samp = merged_ev.get("sampling") if isinstance(merged_ev.get("sampling"), Mapping) else {}
        samp_note = (
            sanitize_terminal_text(
                f"method={samp.get('method') or 'none'}, returned={samp.get('returned', '-')}",
                max_chars=64,
            )
            if samp
            else ("truncated" if is_trunc else "unsampled")
        )

        # P1-05 Temporal & Integrity evaluation
        integ = verify_evidence_integrity_and_scope(merged_ev, eval_ctx)
        temp_eval = (
            merged_ev["temporal_evaluation"]
            if isinstance(merged_ev.get("temporal_evaluation"), Mapping)
            else evaluate_evidence_temporal_validity(
                merged_ev,
                incident_window=eval_ctx["query_window"],
                assessment_time=assessment_time if isinstance(assessment_time, str) else None,
                purpose="incident_window",
                policy=DEFAULT_TEMPORAL_POLICY,
            )
        )
        temp_cls = str(temp_eval.get("classification") or "UNKNOWN")
        temp_badge = _temporal_badge_for_classification(
            temp_cls,
            d_qual,
            is_trunc,
            fresh_for_current=bool(temp_eval.get("eligible_for_current_state") or temp_eval.get("fresh_for_current_assessment")),
        )

        assoc = tuple(ev_to_hyps.get(eid, []))
        excl_reasons = excluded_reason_by_eid.get(eid, [])
        has_support = any("supports" in x for x in assoc)
        has_contra = any("contradicts" in x for x in assoc)

        if has_support:
            disposition = "ACCEPTED_SUPPORT"
        elif has_contra:
            disposition = "CONTRADICTING"
        elif (
            not integ.get("ok", True)
            or excl_reasons
            or temp_cls in ("OUTSIDE_INCIDENT_WINDOW", "TIMESTAMP_INVALID", "TIMESTAMP_MISSING", "SOURCE_UNAVAILABLE")
        ):
            disposition = "REJECTED"
        else:
            disposition = "CONTEXTUAL"

        lims: list[str] = []
        if not integ.get("ok", True):
            lims.append(f"Integrity/scope violation: {sanitize_terminal_text(integ.get('code'), max_chars=48)}")
        lims.extend(excl_reasons)
        for tlim in temp_eval.get("limitations") or []:
            lims.append(sanitize_terminal_text(tlim, max_chars=160))
        if is_trunc or d_qual == "partial":
            lims.append("Partial/truncated telemetry response; cannot support exhaustive negative claims.")

        raw_hash = str(merged_ev.get("content_hash") or compute_evidence_content_hash(merged_ev))
        summary_raw = merged_ev.get("summary")
        if not summary_raw and first_rec.get("message"):
            summary_raw = first_rec.get("message")
        summary_clean = sanitize_terminal_text(
            summary_raw,
            max_chars=240,
            empty_placeholder="Summary unavailable.",
        )

        ev_vms.append(
            EvidenceItemVM(
                evidence_id=eid,
                tool_name=tname,
                source_system=src_sys,
                source_ref=sref,
                service_id=ev_svc,
                environment=ev_env,
                observation_kind=obs_kind,
                value_and_unit=val_unit,
                aggregation=agg_str,
                observed_at=obs_at,
                query_window_str=qw_str,
                collected_at=col_at,
                temporal_classification=temp_cls,
                temporal_badge=temp_badge,
                data_quality=d_qual,
                truncated=is_trunc,
                sampling_note=samp_note,
                disposition=disposition,
                associated_hypotheses=assoc,
                limitations=tuple(dict.fromkeys(lims)),
                integrity_ok=bool(integ.get("ok", True)),
                integrity_code=sanitize_terminal_text(integ.get("code") or "OK", max_chars=40),
                content_hash_short=sanitize_terminal_text(raw_hash[:16], max_chars=20),
                summary=summary_clean,
            )
        )

    known_ev_ids = {item.evidence_id for item in ev_vms}
    unresolved_refs: list[UnresolvedEvidenceRefVM] = []
    seen_unresolved: set[tuple[str, str, str]] = set()
    for h_vm in hyp_vms:
        for eid in h_vm.supporting_ids:
            if eid not in known_ev_ids and (h_vm.hypothesis_id, eid, "supporting") not in seen_unresolved:
                seen_unresolved.add((h_vm.hypothesis_id, eid, "supporting"))
                unresolved_refs.append(
                    UnresolvedEvidenceRefVM(
                        hypothesis_id=h_vm.hypothesis_id,
                        hypothesis_rank=h_vm.rank,
                        evidence_id=eid,
                        role="supporting",
                    )
                )
        for eid in h_vm.contradicting_ids:
            if eid not in known_ev_ids and (h_vm.hypothesis_id, eid, "contradicting") not in seen_unresolved:
                seen_unresolved.add((h_vm.hypothesis_id, eid, "contradicting"))
                unresolved_refs.append(
                    UnresolvedEvidenceRefVM(
                        hypothesis_id=h_vm.hypothesis_id,
                        hypothesis_rank=h_vm.rank,
                        evidence_id=eid,
                        role="contradicting",
                    )
                )
    # Also surface unresolved references recorded in checkpoint before DossierSerializer stripped unknown IDs
    for idx_ch, ch_h in enumerate(chk_ctx.get("hypotheses") or [], start=1):
        if not isinstance(ch_h, Mapping):
            continue
        ch_hid = sanitize_terminal_text(ch_h.get("hypothesis_id") or f"hyp-{idx_ch:03d}", max_chars=96)
        ch_rank = int(ch_h.get("rank", idx_ch)) if isinstance(ch_h.get("rank"), int) else idx_ch
        for role_label, field_name in (("supporting", "supporting_evidence_ids"), ("contradicting", "contradicting_evidence_ids")):
            for raw_eid in ch_h.get(field_name) or []:
                eid_s = sanitize_terminal_text(raw_eid, max_chars=96)
                if eid_s and eid_s not in known_ev_ids and (ch_hid, eid_s, role_label) not in seen_unresolved:
                    seen_unresolved.add((ch_hid, eid_s, role_label))
                    unresolved_refs.append(
                        UnresolvedEvidenceRefVM(
                            hypothesis_id=ch_hid,
                            hypothesis_rank=ch_rank,
                            evidence_id=eid_s,
                            role=role_label,
                        )
                    )

    # Missing Sources
    missing_clean: list[Dict[str, str]] = []
    for ms in (dos_dict or {}).get("missing_sources") or chk_ctx.get("missing_sources") or []:
        if isinstance(ms, Mapping):
            missing_clean.append({
                "tool_name": sanitize_terminal_text(ms.get("tool_name") or "unknown", max_chars=48),
                "error_code": sanitize_terminal_text(ms.get("error_code") or "UNAVAILABLE", max_chars=48),
                "impact_note": sanitize_terminal_text(ms.get("impact_note") or "", max_chars=320, empty_placeholder=""),
            })

    # RAG & SOP Transparency + Manual Verification (Work Package J1-J5)
    raw_citations = (dos_dict or {}).get("sop_citations") or []
    chk_citations_by_chunk: Dict[str, Mapping[str, Any]] = {}
    for rc in chk_ctx.get("runbook_citations") or []:
        if isinstance(rc, Mapping) and rc.get("chunk_id"):
            chk_citations_by_chunk[str(rc["chunk_id"])] = rc

    sop_banner_raw = availability_text(dos_dict) if dos_dict is not None else "Retrieval not yet completed for in-progress incident."
    sop_banner = sanitize_terminal_text(sop_banner_raw, max_chars=360)

    if len(sop_document_keys(raw_citations)) > 1:
        avail_code = "CONFLICTING_OR_COMPETING_SOPS"
        avail_expl = "Multiple distinct eligible SOP documents/versions matched without precedence; human escalation required."
        competing_warn = "Do NOT combine instructions across competing runbooks; verify precedence with service owner."
    elif raw_citations:
        avail_code = "APPLICABLE_SOP_FOUND"
        avail_expl = "Authorized active SOP reference matched service, environment, and effective window."
        competing_warn = ""
    else:
        avail_code = ""
        for ms in missing_clean:
            if ms["tool_name"] == "retrieve_runbooks":
                prefix = ms["impact_note"].split(":", 1)[0].strip().upper()
                if prefix in SOP_GAPS:
                    avail_code = prefix
                elif ms["error_code"] == "SOURCE_UNAVAILABLE":
                    avail_code = "RETRIEVAL_UNAVAILABLE"
                else:
                    avail_code = "NO_APPLICABLE_RUNBOOK"
                break
        if not avail_code and dos_dict is None:
            avail_code = str(chk_ctx.get("sop_availability") or "").upper()
        if not avail_code:
            avail_code = "NOT_ASSESSED" if dos_dict else "PENDING_RETRIEVAL"
        _, gap_desc = SOP_GAPS.get(avail_code, ("SOURCE_UNAVAILABLE", "SOP applicability has not been established."))
        avail_expl = gap_desc
        competing_warn = ""

    # Retrieval vs LLM Context Delivery (P1-04 instrumentation)
    rag_diag = chk_ctx.get("rag_diagnostics") if isinstance(chk_ctx.get("rag_diagnostics"), Mapping) else None
    if rag_diag is None and isinstance(llm_run, Mapping) and llm_run.get("context_diagnostics"):
        try:
            parsed_cd = (
                json.loads(llm_run["context_diagnostics"])
                if isinstance(llm_run["context_diagnostics"], str)
                else llm_run["context_diagnostics"]
            )
            if isinstance(parsed_cd, Mapping):
                rag_diag = parsed_cd
        except Exception:
            rag_diag = None

    if isinstance(rag_diag, Mapping):
        delivery_recorded = True
        ret_cnt = rag_diag.get("retrieved_count") if isinstance(rag_diag.get("retrieved_count"), int) else None
        elig_cnt = rag_diag.get("eligible_count") if isinstance(rag_diag.get("eligible_count"), int) else None
        deliv_cnt = (
            rag_diag.get("delivered_sop_count")
            if isinstance(rag_diag.get("delivered_sop_count"), int)
            else (rag_diag.get("sop_count_in_prompt") if isinstance(rag_diag.get("sop_count_in_prompt"), int) else None)
        )
        omit_cnt = rag_diag.get("omitted_sop_count") if isinstance(rag_diag.get("omitted_sop_count"), int) else None
        omit_reasons = tuple(
            sanitize_terminal_text(r, max_chars=80)
            for r in (rag_diag.get("omission_reasons") or rag_diag.get("omitted_reasons") or [])
            if r
        )
        comp_rung = sanitize_terminal_text(rag_diag.get("compaction_rung") or "rung_0_full", max_chars=40)
        delivery_summary = (
            f"Recorded: retrieved={ret_cnt if ret_cnt is not None else 'n/a'}, "
            f"eligible={elig_cnt if elig_cnt is not None else len(raw_citations)}, "
            f"included_in_llm_prompt={deliv_cnt if deliv_cnt is not None else 'n/a'}, "
            f"omitted={omit_cnt if omit_cnt is not None else 0} (compaction={comp_rung})"
        )
    else:
        delivery_recorded = False
        ret_cnt = None
        elig_cnt = len(raw_citations) if dos_dict is not None else None
        deliv_cnt = None
        omit_cnt = None
        omit_reasons = ()
        comp_rung = "not_recorded"
        if inv_mode != "agentic_llm":
            delivery_summary = "Not applicable / not recorded (no online LLM context request in deterministic or fallback mode)."
        else:
            delivery_summary = "LLM prompt delivery telemetry not recorded in persisted checkpoint (citation presence alone does not prove prompt delivery)."

    sop_vms: list[SOPCitationVM] = []
    for cit in raw_citations:
        if not isinstance(cit, Mapping):
            continue
        # Never expose unsanitized or restricted entries
        if cit.get("sanitized") is False:
            continue
        cls_val = str(cit.get("classification") or "").lower()
        if cls_val in ("restricted", "secret", "confidential_restricted"):
            continue
        cid_chunk = sanitize_terminal_text(cit.get("chunk_id") or "chunk unavailable", max_chars=80)
        chk_cit = chk_citations_by_chunk.get(str(cit.get("chunk_id") or "")) or {}
        score_val = cit.get("score") if cit.get("score") is not None else chk_cit.get("score")
        score_type = cit.get("score_type") or chk_cit.get("score_type") or "rrf_fusion"
        if isinstance(score_val, (int, float)) and not isinstance(score_val, bool):
            score_note = (
                f"Retrieval score={float(score_val):.4f} ({sanitize_terminal_text(score_type, max_chars=24)}: "
                "lexical/dense rank relevance only, NOT diagnostic confidence)"
            )
        else:
            score_note = ""

        sop_vms.append(
            SOPCitationVM(
                doc_id=sanitize_terminal_text(cit.get("doc_id") or cit.get("document_id") or "Runbook", max_chars=64),
                version=sanitize_terminal_text(cit.get("version") or cit.get("document_version") or "unknown", max_chars=32),
                section_path=sanitize_terminal_text(cit.get("section_path") or cit.get("section") or "section unavailable", max_chars=120),
                chunk_id=cid_chunk,
                source_uri=sanitize_terminal_text(cit.get("source_uri") or "source unavailable", max_chars=120),
                excerpt=sanitize_terminal_text(
                    cit.get("excerpt") or cit.get("text_excerpt") or cit.get("summary"),
                    max_chars=240,
                    empty_placeholder="Excerpt unavailable.",
                ),
                retrieval_score_note=score_note,
            )
        )

    manual_vms: list[ManualCheckVM] = []
    for idx_c, chk in enumerate((dos_dict or {}).get("recommended_checks") or [], start=1):
        if isinstance(chk, Mapping):
            desc = sanitize_terminal_text(chk.get("description") or "", max_chars=380)
            if "HUMAN ESCALATION REQUIRED" in desc.upper():
                prov_tag = "HUMAN_ESCALATION_REQUIRED"
            elif "NOT SOP-BACKED" in desc.upper():
                prov_tag = "GENERAL_GUIDANCE (NOT SOP-BACKED)"
            elif "SOP-BACKED" in desc.upper() or chk.get("related_sop_doc_id"):
                prov_tag = "SOP_BACKED"
            else:
                prov_tag = "HUMAN_VERIFICATION"
            manual_vms.append(
                ManualCheckVM(
                    index=idx_c,
                    check_id=sanitize_terminal_text(chk.get("check_id") or f"chk-{idx_c:02d}", max_chars=40),
                    status="NOT_PERFORMED",
                    provenance_tag=prov_tag,
                    risk_level=sanitize_terminal_text(chk.get("risk_level") or "medium", max_chars=16).upper(),
                    related_sop_doc_id=sanitize_terminal_text(chk.get("related_sop_doc_id") or "-", max_chars=64),
                    description=desc,
                    requires_human_approval=bool(chk.get("requires_human_approval", True)),
                    auto_execution_allowed=bool(chk.get("auto_execution_allowed", False)),
                )
            )
        elif isinstance(chk, str):
            manual_vms.append(
                ManualCheckVM(
                    index=idx_c,
                    check_id=f"chk-{idx_c:02d}",
                    status="NOT_PERFORMED",
                    provenance_tag="HUMAN_VERIFICATION",
                    risk_level="MEDIUM",
                    related_sop_doc_id="-",
                    description=sanitize_terminal_text(chk, max_chars=380),
                    requires_human_approval=True,
                    auto_execution_allowed=False,
                )
            )

    rag_vm = RAGTransparencyVM(
        availability_code=avail_code,
        availability_banner=sop_banner,
        availability_explanation=avail_expl,
        competing_sop_warning=competing_warn,
        delivery_recorded=delivery_recorded,
        retrieved_count=ret_cnt,
        eligible_count=elig_cnt,
        delivered_to_llm_count=deliv_cnt,
        omitted_count=omit_cnt,
        omitted_reasons=omit_reasons,
        compaction_rung=comp_rung,
        delivery_summary=delivery_summary,
        citations=tuple(sop_vms),
        manual_checks=tuple(manual_vms),
    )

    # Human Review Eligibility & Closure Semantics (Work Package K1-K6, E6)
    rev_ok, rev_reason = check_reviewer_actor_format(
        reviewer_ref,
        reviewer_role,
        reviewer_directory=reviewer_directory,
        require_registered_reviewer=require_registered_reviewer,
    )
    if require_authenticated_context:
        identity_mode = "SCOPED_PRINCIPAL_CONTEXT_REQUIRED"
        identity_disclosure = "Scoped principal context required + local operator ref (not SSO-authenticated)"
    else:
        identity_mode = "POC_CALLER_ASSERTED_UNAUTHENTICATED"
        identity_disclosure = "Local PoC caller-asserted identity (unauthenticated)"

    rev_sum_detail = (dos_dict or {}).get("review_summary")
    rev_sum_detail = rev_sum_detail if isinstance(rev_sum_detail, Mapping) else {}
    has_human_review_marker = bool(
        rev_sum_detail.get("latest_review_event_id")
        or rev_sum_detail.get("reviewed_by")
        or rev_sum_detail.get("reviewed_at")
    )

    if dossier_review_status == "APPROVED" or lifecycle_state in ("CLOSED", "LEARNED"):
        closure_display = ADMINISTRATIVE_CLOSURE_SHORT
    elif lifecycle_state == "REJECTED" or dossier_review_status == "REJECTED":
        closure_display = "DOSSIER_REJECTED (diagnosis_verified=False, technical_resolved=False, remediation_authorized=False)"
    elif lifecycle_state == "MANUAL_TRIAGE_REQUIRED" or (dossier_review_status == "MANUAL_TRIAGE" and has_human_review_marker):
        closure_display = "ESCALATED_FOR_MANUAL_TRIAGE (diagnosis_verified=False, technical_resolved=False, remediation_authorized=False)"
    elif dossier_review_status == "MANUAL_TRIAGE":
        closure_display = "MANUAL_TRIAGE_FALLBACK_PENDING_HUMAN_REVIEW (diagnosis_verified=False, remediation_authorized=False)"
    else:
        closure_display = f"{dossier_review_status} (diagnosis_verified=False, remediation_authorized=False)"

    if not dossier_available:
        eligible = False
        lock_code = "DOSSIER_UNAVAILABLE"
        lock_msg = f"Review unavailable: dossier not yet generated (state={lifecycle_state})."
    elif lifecycle_state != "HUMAN_REVIEW":
        eligible = False
        lock_code = f"FINALIZED_{lifecycle_state}"
        lock_msg = f"REVIEW LOCKED - FINALIZED ({lifecycle_state}): historical dossier is read-only."
    elif (
        finalizing_reviews
        or dossier_review_status in ("APPROVED", "REJECTED")
        or (dossier_review_status == "MANUAL_TRIAGE" and has_human_review_marker)
    ):
        eligible = False
        lock_code = "ALREADY_FINALIZED"
        lock_msg = f"REVIEW LOCKED - FINALIZED ({dossier_review_status}): final review decision already recorded."
    elif not rev_ok:
        eligible = False
        lock_code = "REVIEWER_UNAUTHORIZED"
        lock_msg = f"Review actions disabled for current identity: {rev_reason}"
    else:
        eligible = True
        lock_code = ""
        lock_msg = f"Ready for authorized human review on Revision v{dossier_version}."

    review_elig = ReviewEligibilityVM(
        eligible=eligible,
        lock_code=lock_code,
        lock_message=lock_msg,
        lifecycle_state=lifecycle_state,
        dossier_review_status=dossier_review_status,
        closure_display=closure_display,
        target_version=dossier_version,
        target_hash=dossier_hash,
        reviewer_ref=sanitize_terminal_text(reviewer_ref, max_chars=64),
        reviewer_role=sanitize_terminal_text(reviewer_role, max_chars=32),
        reviewer_authorized=rev_ok,
        reviewer_auth_reason=rev_reason,
        identity_mode=identity_mode,
        identity_disclosure=identity_disclosure,
    )

    clean_reviews = tuple(
        {
            "review_event_id": sanitize_terminal_text(r.get("review_event_id"), max_chars=40),
            "target_dossier_version": r.get("target_dossier_version", 1),
            "decision": sanitize_terminal_text(r.get("decision"), max_chars=24).upper(),
            "reviewer_ref": sanitize_terminal_text(r.get("reviewer_ref"), max_chars=64),
            "reviewer_role": sanitize_terminal_text(r.get("reviewer_role"), max_chars=32),
            "reviewed_at": format_local_timestamp(r.get("reviewed_at"), compact=False),
            "rationale": sanitize_terminal_text(r.get("rationale"), max_chars=240),
            "edited_dossier_version": r.get("edited_dossier_version"),
            "escalation_target": sanitize_terminal_text(r.get("escalation_target") or "", max_chars=64, empty_placeholder=""),
        }
        for r in reviews
        if isinstance(r, Mapping)
    )

    return IncidentDetailVM(
        incident_id=incident_id,
        severity=raw_sev,
        severity_badge=severity_badge,
        primary_service=primary_service,
        environment=environment,
        affected_services=affected_services,
        lifecycle_state=lifecycle_state,
        lifecycle_display=lifecycle_display,
        dossier_available=dossier_available,
        dossier_version=dossier_version,
        latest_dossier_version=latest_ver,
        dossier_hash=dossier_hash,
        revision_history_note=revision_history_note,
        incident_time_display=incident_time_display,
        incident_time_compact=incident_time_compact,
        alert_received_at=alert_received_at,
        investigation_started_at=investigation_started_at,
        dossier_ready_at=dossier_ready_at,
        duration_display=duration_display,
        tool_calls_used=tool_calls_used,
        investigation_mode=inv_mode,
        mode_badge=mode_badge,
        mode_headline=mode_headline,
        provider_name=provider_name,
        model_version=model_ver,
        prompt_version=prompt_ver,
        token_usage_display=token_usage_display,
        fallback_reason=fallback_reason,
        observed_symptoms=observed_symptoms,
        error_budget_impact=error_budget_impact,
        topology_flow=topology_flow,
        cascade_summary=cascade_summary,
        topology_uncertainty=topology_uncertainty,
        stages=tuple(stages_out),
        completed_stage_count=completed_count,
        hypotheses=tuple(hyp_vms),
        ranking_note=ranking_note,
        evidence_items=tuple(ev_vms),
        unresolved_evidence_refs=tuple(unresolved_refs),
        missing_sources=tuple(missing_clean),
        unknowns=unknowns_clean,
        rag=rag_vm,
        review_eligibility=review_elig,
        review_history=clean_reviews,
        consistency_warnings=tuple(dict.fromkeys(consistency_warnings)),
        raw_incident=inc_dict,
        raw_dossier=dos_dict,
    )


# ---------------------------------------------------------------------------
# Authoritative Consistent Read Snapshot & Generation-Bound Refresh Coordinator
# ---------------------------------------------------------------------------

def _triage_sort_key(vm: IncidentDetailVM, *, is_archive: bool = False) -> Tuple[Any, ...]:
    """Deterministic ordering: HUMAN_REVIEW first, then higher severity, then newest timestamp, then ID."""
    raw_updated = str(vm.raw_incident.get("updated_at") or vm.alert_received_at or "")
    parsed_dt = _parse_iso_dt(raw_updated)
    neg_epoch = -parsed_dt.timestamp() if parsed_dt is not None else 0.0
    if is_archive:
        return (neg_epoch, SEVERITY_PRIORITY_ORDER.get(vm.severity, 4), vm.incident_id)
    needs_review_rank = 0 if vm.review_eligibility.eligible else (1 if vm.lifecycle_state == "HUMAN_REVIEW" else 2)
    return (
        needs_review_rank,
        SEVERITY_PRIORITY_ORDER.get(vm.severity, 4),
        neg_epoch,
        vm.incident_id,
    )


class AuthoritativeSnapshotCoordinator:
    """Atomic SQLite snapshot reader with generation-bound refresh and stale last-known fallback.

    - Reads `incidents`, `dossiers`, `checkpoints`, `state_transitions`, `review_records`, and
      optional `c13_llm_runs` inside ONE `store.transaction(immediate=False)` boundary on
      `store._conn` (eliminating torn cross-table reads and `:memory:` connection splits).
    - Tracks monotonically increasing `generation` IDs so out-of-order asynchronous refresh
      completions are deterministically discarded (`A07`, `A08`).
    - Retains the last valid snapshot explicitly marked `is_stale_last_known=True` if a backend
      read fails (`F07`, `F08`, `Scenario O9`).
    - Bounds external probe frequency (`ServiceHealthInspector`, `CostMetricsReader`) via TTL
      caching so scrolling/rendering never spawns subprocesses or consumes tool budgets (`F10`, `F11`).
    """

    def __init__(
        self,
        store: WorkflowStateStore,
        *,
        probe_ttl_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.probe_ttl_seconds = max(1.0, probe_ttl_seconds)
        self._next_generation = 0
        self.last_applied_generation = 0
        self.current_snapshot: Optional[DashboardSnapshot] = None
        self._cached_health: Optional[Tuple[float, Dict[str, Any]]] = None
        self._cached_costs: Optional[Tuple[float, Dict[str, Any]]] = None

    def next_generation(self) -> int:
        self._next_generation += 1
        return self._next_generation

    def get_cached_health(
        self,
        inspector_fn: Callable[[], Dict[str, Any]],
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        now_m = time.monotonic()
        if not force and self._cached_health is not None:
            ts, payload = self._cached_health
            if (now_m - ts) < self.probe_ttl_seconds:
                return payload
        payload = dict(inspector_fn())
        payload["checked_at_local"] = dt.datetime.now().strftime("%H:%M:%S")
        self._cached_health = (now_m, payload)
        return payload

    def peek_cached_health(self) -> Optional[Dict[str, Any]]:
        """Return cached Docker health without blocking on subprocess execution."""
        if self._cached_health is None:
            return None
        return self._cached_health[1]

    def get_cached_costs(
        self,
        reader_fn: Callable[[], Dict[str, Any]],
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        now_m = time.monotonic()
        if not force and self._cached_costs is not None:
            ts, payload = self._cached_costs
            if (now_m - ts) < self.probe_ttl_seconds:
                return payload
        payload = dict(reader_fn())
        self._cached_costs = (now_m, payload)
        return payload

    def apply_external_snapshot(self, snapshot: DashboardSnapshot) -> bool:
        """Apply an asynchronous snapshot only if its generation is newer than last applied."""
        if snapshot.generation < self.last_applied_generation:
            return False
        self.last_applied_generation = snapshot.generation
        if snapshot.generation > self._next_generation:
            self._next_generation = snapshot.generation
        self.current_snapshot = snapshot
        return True

    def refresh(
        self,
        *,
        reviewer_ref: str = "sre_reviewer",
        reviewer_role: str = "L2_SRE",
        reviewer_directory: Optional[Mapping[str, Any]] = None,
        require_registered_reviewer: bool = False,
        require_authenticated_context: bool = False,
        generation: Optional[int] = None,
    ) -> DashboardSnapshot:
        """Read a consistent atomic snapshot from WorkflowStateStore, falling back safely on error."""
        gen = generation if generation is not None else self.next_generation()
        if gen < self.last_applied_generation and self.current_snapshot is not None:
            return self.current_snapshot

        try:
            snapshot = self._read_atomic_snapshot(
                generation=gen,
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
                reviewer_directory=reviewer_directory,
                require_registered_reviewer=require_registered_reviewer,
                require_authenticated_context=require_authenticated_context,
            )
            self.apply_external_snapshot(snapshot)
            return self.current_snapshot or snapshot
        except Exception as exc:
            err_msg = sanitize_terminal_text(f"{type(exc).__name__}: {exc}", max_chars=160)
            if self.current_snapshot is not None:
                stale = dataclasses.replace(
                    self.current_snapshot,
                    generation=max(gen, self.last_applied_generation),
                    store_connected=False,
                    is_stale_last_known=True,
                    refresh_error=err_msg,
                )
                self.apply_external_snapshot(stale)
                return self.current_snapshot or stale

            now_utc = utc_now_z()
            empty_err = DashboardSnapshot(
                generation=gen,
                fetched_at_utc=now_utc,
                fetched_at_local=format_local_timestamp(now_utc, compact=True),
                store_connected=False,
                is_stale_last_known=False,
                refresh_error=err_msg,
                environments=(),
                active_entries=(),
                archived_entries=(),
                in_progress_count=0,
                awaiting_review_count=0,
                archived_count=0,
                by_incident_id={},
            )
            self.apply_external_snapshot(empty_err)
            return self.current_snapshot or empty_err

    def _read_atomic_snapshot(
        self,
        *,
        generation: int,
        reviewer_ref: str,
        reviewer_role: str,
        reviewer_directory: Optional[Mapping[str, Any]],
        require_registered_reviewer: bool,
        require_authenticated_context: bool,
    ) -> DashboardSnapshot:
        now_utc = utc_now_z()
        with self.store.transaction(immediate=False):
            conn = self.store._conn
            inc_rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM incidents ORDER BY updated_at DESC, incident_id ASC"
                ).fetchall()
            ]

            dossiers_by_inc: Dict[str, list[Dict[str, Any]]] = {}
            for d_row in conn.execute(
                "SELECT incident_id, dossier_version, dossier_hash, dossier_json, created_at "
                "FROM dossiers ORDER BY incident_id ASC, dossier_version DESC"
            ).fetchall():
                inc_id = str(d_row["incident_id"])
                dossiers_by_inc.setdefault(inc_id, []).append(
                    {
                        "incident_id": inc_id,
                        "dossier_version": int(d_row["dossier_version"]),
                        "dossier_hash": str(d_row["dossier_hash"]),
                        "dossier_json": json.loads(d_row["dossier_json"]),
                        "created_at": str(d_row["created_at"]),
                    }
                )

            checkpoints_by_inc: Dict[str, Dict[str, Any]] = {}
            for c_row in conn.execute(
                "SELECT incident_id, state, context_blob, updated_at FROM checkpoints"
            ).fetchall():
                inc_id = str(c_row["incident_id"])
                try:
                    c_ctx = json.loads(c_row["context_blob"])
                except Exception:
                    c_ctx = {}
                checkpoints_by_inc[inc_id] = {
                    "incident_id": inc_id,
                    "state": str(c_row["state"]),
                    "context": c_ctx,
                    "updated_at": str(c_row["updated_at"]),
                }

            transitions_by_inc: Dict[str, list[Dict[str, Any]]] = {}
            for t_row in conn.execute(
                "SELECT * FROM state_transitions ORDER BY id ASC"
            ).fetchall():
                inc_id = str(t_row["incident_id"])
                transitions_by_inc.setdefault(inc_id, []).append(dict(t_row))

            reviews_by_inc: Dict[str, list[Dict[str, Any]]] = {}
            for r_row in conn.execute(
                "SELECT * FROM review_records ORDER BY reviewed_at ASC"
            ).fetchall():
                rd = dict(r_row)
                rd["auto_action_triggered"] = bool(rd.get("auto_action_triggered"))
                reviews_by_inc.setdefault(str(rd["incident_id"]), []).append(rd)

            llm_runs_by_inc: Dict[str, Dict[str, Any]] = {}
            has_llm_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='c13_llm_runs'"
            ).fetchone()
            if has_llm_table:
                cols = {
                    str(col_row[1])
                    for col_row in conn.execute("PRAGMA table_info(c13_llm_runs)").fetchall()
                }
                select_cols = [
                    c for c in ("incident_id", "provider", "model", "input_reported", "output_reported", "status", "error_code", "result", "context_diagnostics")
                    if c in cols
                ]
                if "incident_id" in select_cols:
                    for l_row in conn.execute(
                        f"SELECT {', '.join(select_cols)} FROM c13_llm_runs ORDER BY rowid ASC"
                    ).fetchall():
                        ld = dict(l_row)
                        llm_runs_by_inc[str(ld["incident_id"])] = ld

        active_list: list[IncidentDetailVM] = []
        archived_list: list[IncidentDetailVM] = []
        by_id: Dict[str, IncidentDetailVM] = {}
        envs: set[str] = set()
        in_progress_count = 0
        awaiting_review_count = 0

        for inc in inc_rows:
            inc_id = str(inc["incident_id"])
            ver_rows = dossiers_by_inc.get(inc_id, [])
            latest_dossier = ver_rows[0]["dossier_json"] if ver_rows else None
            vm = build_incident_detail_vm(
                incident=inc,
                dossier=latest_dossier,
                dossier_versions=ver_rows,
                checkpoint=checkpoints_by_inc.get(inc_id),
                transitions=transitions_by_inc.get(inc_id, ()),
                reviews=reviews_by_inc.get(inc_id, ()),
                llm_run=llm_runs_by_inc.get(inc_id),
                reviewer_ref=reviewer_ref,
                reviewer_role=reviewer_role,
                reviewer_directory=reviewer_directory,
                require_registered_reviewer=require_registered_reviewer,
                require_authenticated_context=require_authenticated_context,
            )
            by_id[vm.incident_id] = vm
            if vm.environment and vm.environment != "unknown":
                envs.add(vm.environment)

            st = vm.lifecycle_state
            is_finalized_review = (
                vm.review_eligibility.dossier_review_status in ("APPROVED", "REJECTED", "MANUAL_TRIAGE")
                or any(r["decision"] in ("APPROVE", "REJECT", "ESCALATE_MANUAL") for r in vm.review_history)
            )
            if st in ARCHIVED_LIFECYCLE_STATES or (st == "HUMAN_REVIEW" and is_finalized_review):
                archived_list.append(vm)
            else:
                active_list.append(vm)
                if st == "HUMAN_REVIEW" and vm.dossier_available:
                    awaiting_review_count += 1
                else:
                    in_progress_count += 1

        active_sorted = tuple(sorted(active_list, key=lambda item: _triage_sort_key(item, is_archive=False)))
        archived_sorted = tuple(sorted(archived_list, key=lambda item: _triage_sort_key(item, is_archive=True)))

        return DashboardSnapshot(
            generation=generation,
            fetched_at_utc=now_utc,
            fetched_at_local=format_local_timestamp(now_utc, compact=True),
            store_connected=True,
            is_stale_last_known=False,
            refresh_error="",
            environments=tuple(sorted(envs)) or ("lab",),
            active_entries=active_sorted,
            archived_entries=archived_sorted,
            in_progress_count=in_progress_count,
            awaiting_review_count=awaiting_review_count,
            archived_count=len(archived_sorted),
            by_incident_id=by_id,
        )
