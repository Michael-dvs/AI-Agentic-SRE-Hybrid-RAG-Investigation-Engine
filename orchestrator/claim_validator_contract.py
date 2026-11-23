"""Contract, interfaces, dataclasses, and deterministic validator for Chapter 14 (C14).

C14: Evidence Validation and Uncertainty.
Enforces semantic claim validation, cross-signal contradiction detection (EV-01),
honest missing-trace uncertainty (EV-02, SC-09), time window boundaries (SC-14),
post-retrieval SOP applicability verification (RAG-01, RAG-02, AT-007),
cascade failure origin attribution (AT-016, SC-04), multi-fault separation (SC-08),
and strict prohibition of the 'VERIFIED' status/keyword (RULE-007).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Sequence


class HypothesisStatus(str, Enum):
    """Permitted hypothesis and investigation status levels.

    RULE-007: 'VERIFIED' is strictly prohibited. Only L1/L2 human review
    can approve root cause findings for post-incident action.
    """
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class ValidationReasonCode(str, Enum):
    """Canonical reason codes for claim and evidence validation."""
    CLAIM_CORROBORATED = "CLAIM_CORROBORATED"
    MISSING_EVIDENCE_REF = "MISSING_EVIDENCE_REF"
    MISSING_SUPPORTING_EVIDENCE = "MISSING_SUPPORTING_EVIDENCE"
    IRRELEVANT_EVIDENCE = "IRRELEVANT_EVIDENCE"
    CLAIM_CONTRADICTED = "CLAIM_CONTRADICTED"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    VALUE_MISMATCH = "VALUE_MISMATCH"
    CONTRADICTING_SIGNALS = "CONTRADICTING_SIGNALS"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    OBSOLETE_SOP = "OBSOLETE_SOP"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    VERIFIED_STATUS_FORBIDDEN = "VERIFIED_STATUS_FORBIDDEN"
    DOWNSTREAM_SYMPTOM_CASCADE = "DOWNSTREAM_SYMPTOM_CASCADE"
    CONCURRENT_INDEPENDENT_FAULT = "CONCURRENT_INDEPENDENT_FAULT"
    NO_APPLICABLE_RUNBOOK = "NO_APPLICABLE_RUNBOOK"


VALIDATION_REASON_CODES: frozenset[str] = frozenset(code.value for code in ValidationReasonCode)

_VERIFIED_PATTERN = re.compile(r"\bVERIFIED\b", re.IGNORECASE)
_NUMERIC_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)(?:\s*(?:ms|s|%|req/s|rps|errors?|hits?|pts?|points?|kb|mb|gb))?\b", re.IGNORECASE)
_KNOWN_SERVICES: tuple[str, ...] = (
    "api-gateway",
    "auth-service",
    "transaction-service",
    "ledger-service",
    "notification-service",
    "db-dummy",
)
_NO_ERROR_PATTERN = re.compile(
    r"\b(?:no\s+(?:degradation|error|errors|failure|failures|fault)|normal|nominal|healthy|zero\s+error)\b",
    re.IGNORECASE,
)
_RATE_LIMIT_PATTERN = re.compile(
    r"\b(?:rate[\s_-]?limit\w*|throttl\w*|429|too\s+many\s+requests|quota\s+exceeded)\b",
    re.IGNORECASE,
)
_TRAFFIC_SURGE_PATTERN = re.compile(
    r"\b(?:traffic[\s_-]?(?:surge|spike)|request[\s_-]?surge|spike\s+in\s+traffic|"
    r"sudden\s+increase\s+in\s+(?:client\s+)?request\w*|high\s+request\s+rate|"
    r"load\s+spike|overwhelming\b.*\bcapacity|ddos|burst\s+of\s+traffic)\b",
    re.IGNORECASE,
)
_DB_POOL_PATTERN = re.compile(
    r"\b(?:database|db|connection\s+pool|pool\s+exhaust\w*|deadlock|lock\s+timeout|postgres\w*|sqlite)\b",
    re.IGNORECASE,
)
_AUTH_FAILURE_PATTERN = re.compile(
    r"\b(?:401|403|unauthorized|forbidden|invalid\s+(?:bearer\s+)?token|token\s+signature|"
    r"invalid\s+credentials|authentication\s+(?:reject|fail)\w*)\b",
    re.IGNORECASE,
)
_FAILURE_ASSERTION_PATTERN = re.compile(
    r"\b(?:500|502|503|504|error|errors|fail\w*|outage|degrad\w*|timeout|refus\w*|exhaust\w*|spike|reject\w*)\b",
    re.IGNORECASE,
)


def parse_utc_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp string ending with 'Z' into a timezone-aware datetime."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Timestamp must be ISO-8601 UTC string ending with 'Z', got: {value!r}")
    try:
        # Replace Z with +00:00 for fromisoformat compatibility
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 UTC timestamp {value!r}") from exc


def extract_numeric_value(text: str) -> float | None:
    """Extract the first numeric value from a claim text, if present."""
    match = _NUMERIC_PATTERN.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class ValidatedClaim:
    """Detailed validation outcome for an individual material claim."""
    claim_text: str
    evidence_id: str | None
    status: HypothesisStatus
    reason_code: str
    value_delta: dict[str, Any] | None = None
    observed_at: str | None = None
    details: str = ""

    def __post_init__(self) -> None:
        if self.reason_code not in VALIDATION_REASON_CODES:
            raise ValueError(f"Invalid reason_code {self.reason_code!r}; must be in VALIDATION_REASON_CODES")


@dataclass
class ValidationReport:
    """Comprehensive validation outcome for a candidate hypothesis."""
    hypothesis_id: str
    status: HypothesisStatus
    confidence_score: float
    claims: list[ValidatedClaim] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    rejected_sop_citations: list[dict[str, Any]] = field(default_factory=list)
    valid_sop_citations: list[dict[str, Any]] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    origin_service: str | None = None
    is_cascade: bool = False
    is_multi_fault: bool = False

    def __post_init__(self) -> None:
        # RULE-007 Hard enforcement: 'VERIFIED' is forbidden as a status
        if self.status == "VERIFIED" or str(self.status).upper() == "VERIFIED":
            raise ValueError("RULE-007 Violation: Status 'VERIFIED' is strictly prohibited.")


def _detect_claim_mechanisms(text: str) -> set[str]:
    """Identify specific failure mechanisms asserted in a claim or hypothesis."""
    mechanisms: set[str] = set()
    if _RATE_LIMIT_PATTERN.search(text):
        mechanisms.add("rate_limit")
    if _TRAFFIC_SURGE_PATTERN.search(text):
        mechanisms.add("traffic_surge")
    if _DB_POOL_PATTERN.search(text):
        mechanisms.add("db_pool")
    if _AUTH_FAILURE_PATTERN.search(text):
        mechanisms.add("auth_failure")
    if _FAILURE_ASSERTION_PATTERN.search(text) and not _NO_ERROR_PATTERN.search(text):
        mechanisms.add("failure_assertion")
    return mechanisms


def _extract_evidence_signals(ev: dict[str, Any]) -> dict[str, Any]:
    """Extract structured telemetry signals from an evidence item for relevance checking."""
    records = [r for r in ev.get("records", []) if isinstance(r, dict)]
    status_codes_str: set[str] = set()
    error_codes: set[str] = set()
    messages_parts: list[str] = []
    metric_names: set[str] = set()
    metric_values: list[tuple[str, float]] = []
    record_services: set[str] = set()
    ok_trace_count = 0

    for rec in records:
        sc = rec.get("status_code")
        if sc is not None and sc != "":
            status_codes_str.add(str(sc).strip().upper())
        ec = rec.get("error_code")
        if isinstance(ec, str) and ec.strip():
            error_codes.add(ec.strip().upper())
        for key in ("message", "exception.message", "error.message", "operation", "operation_name"):
            val = rec.get(key)
            if isinstance(val, str) and val.strip():
                messages_parts.append(val.strip().lower())
        m_name = rec.get("metric_enum") or rec.get("metric_name")
        m_name_norm = str(m_name).strip().lower() if isinstance(m_name, str) and m_name.strip() else ""
        if m_name_norm:
            metric_names.add(m_name_norm)
        val = rec.get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            metric_values.append((m_name_norm, float(val)))
        for svc_key in ("service_id", "service_name", "peer.service"):
            svc_val = rec.get(svc_key)
            if isinstance(svc_val, str) and svc_val.strip():
                record_services.add(svc_val.strip())
        if str(sc).strip().upper() == "OK" and rec.get("error") is not True:
            ok_trace_count += 1

    return {
        "records": records,
        "status_codes": status_codes_str,
        "error_codes": error_codes,
        "messages": " ".join(messages_parts),
        "metric_names": metric_names,
        "metric_values": metric_values,
        "record_services": record_services,
        "all_ok_traces": (
            ev.get("tool_name") == "get_trace_summary"
            and bool(records)
            and ok_trace_count == len(records)
        ),
    }


def _assess_evidence_relevance(
    claim_text: str,
    ev: dict[str, Any],
    context: dict[str, Any],
) -> tuple[HypothesisStatus, str, str] | None:
    """Verify that evidence item is available, in-scope, relevant, and non-contradicting."""
    ev_id = ev.get("evidence_id") or "unknown"
    tool_name = str(ev.get("tool_name") or "")

    if ev.get("data_quality") == "unavailable" or ev.get("error_code"):
        return (
            HypothesisStatus.UNSUPPORTED,
            ValidationReasonCode.SOURCE_UNAVAILABLE.value,
            f"Evidence {ev_id} is unavailable ({ev.get('error_code') or 'unavailable'}) and cannot support claims.",
        )

    signals = _extract_evidence_signals(ev)
    records = signals["records"]
    is_no_error = bool(_NO_ERROR_PATTERN.search(claim_text))

    if not records and not is_no_error:
        return (
            HypothesisStatus.UNSUPPORTED,
            ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
            f"Evidence {ev_id} ({tool_name}) returned 0 telemetry records and cannot substantiate the claim.",
        )

    known_services = set(_KNOWN_SERVICES)
    if isinstance(context.get("service_id"), str) and context["service_id"]:
        known_services.add(context["service_id"])
    for svc in context.get("investigation_scope") or []:
        if isinstance(svc, str) and svc:
            known_services.add(svc)
    for item in context.get("evidence_items") or []:
        if isinstance(item, dict) and isinstance(item.get("service_id"), str) and item["service_id"]:
            known_services.add(item["service_id"])

    claim_lower = claim_text.lower()
    mentioned_services = {svc for svc in known_services if re.search(rf"\b{re.escape(svc)}\b", claim_lower)}
    ev_service = ev.get("service_id")
    if mentioned_services and isinstance(ev_service, str) and ev_service:
        in_ev_service = ev_service in mentioned_services
        in_record_services = bool(signals["record_services"] & mentioned_services)
        in_messages = any(svc.lower() in signals["messages"] for svc in mentioned_services)
        if not (in_ev_service or in_record_services or in_messages):
            return (
                HypothesisStatus.UNSUPPORTED,
                ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                f"Evidence {ev_id} belongs to '{ev_service}' and does not match claimed service(s) {sorted(mentioned_services)}.",
            )

    mechanisms = _detect_claim_mechanisms(claim_text)
    status_codes = signals["status_codes"]
    error_codes = signals["error_codes"]
    messages = signals["messages"]
    metric_names = signals["metric_names"]
    metric_values = signals["metric_values"]

    if "rate_limit" in mechanisms:
        has_rate_limit_signal = (
            "429" in status_codes
            or any("rate" in ec.lower() or "throttl" in ec.lower() or "quota" in ec.lower() or "429" in ec for ec in error_codes)
            or bool(_RATE_LIMIT_PATTERN.search(messages))
            or any("rate_limit" in mn or "throttl" in mn or "rejected" in mn for mn in metric_names)
        )
        if not has_rate_limit_signal:
            if tool_name in ("search_error_logs", "get_trace_summary") or (
                tool_name == "get_service_metrics" and bool(metric_names)
            ):
                observed_desc = sorted(status_codes | error_codes | metric_names) or ["unrelated telemetry"]
                return (
                    HypothesisStatus.UNSUPPORTED,
                    ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                    f"Evidence {ev_id} ({tool_name}: {', '.join(observed_desc)}) does not show HTTP 429, throttling, or rate-limit configuration.",
                )

    if "traffic_surge" in mechanisms:
        if tool_name == "search_error_logs":
            has_surge_signal = any(
                kw in messages or any(kw in ec.lower() for ec in error_codes)
                for kw in ("surge", "overload", "too many", "429", "queue full", "backpressure", "high load", "rate limit")
            ) or "429" in status_codes
            if not has_surge_signal:
                observed_desc = sorted(status_codes | error_codes) or ["unrelated error logs"]
                return (
                    HypothesisStatus.UNSUPPORTED,
                    ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                    f"Log evidence {ev_id} ({', '.join(observed_desc)}) reflects downstream/runtime errors rather than an upstream traffic surge.",
                )
        elif tool_name == "get_service_metrics":
            req_vals = [
                v for name, v in metric_values
                if name in ("request_rate", "rps", "qps", "throughput", "traffic_rate")
            ]
            if req_vals:
                if len(req_vals) >= 2 and max(req_vals) <= req_vals[0] and max(req_vals) <= 1.0:
                    return (
                        HypothesisStatus.CONTRADICTED,
                        ValidationReasonCode.CLAIM_CONTRADICTED.value,
                        f"Metric evidence {ev_id} reports flat/non-increasing low request_rate ({req_vals}), contradicting a traffic surge claim.",
                    )
                if max(req_vals) <= 1.0:
                    return (
                        HypothesisStatus.UNSUPPORTED,
                        ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                        f"Metric evidence {ev_id} reports low request_rate ({req_vals}) with no traffic baseline demonstrating a surge.",
                    )

    if "db_pool" in mechanisms and tool_name == "search_error_logs":
        has_db_signal = any(
            kw in messages or any(kw in ec.lower() for ec in error_codes)
            for kw in ("db", "database", "pool", "sql", "postgres", "sqlite", "lock", "deadlock", "timeout", "connection")
        ) or bool({"500", "503", "504"} & status_codes)
        if not has_db_signal:
            return (
                HypothesisStatus.UNSUPPORTED,
                ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                f"Log evidence {ev_id} ({sorted(status_codes | error_codes)}) does not indicate database or connection pool issues.",
            )

    if "auth_failure" in mechanisms and tool_name == "search_error_logs":
        has_auth_signal = bool({"401", "403"} & status_codes) or any(
            kw in messages or any(kw in ec.lower() for ec in error_codes)
            for kw in ("auth", "token", "unauthorized", "forbidden", "credential", "signature")
        )
        if not has_auth_signal:
            if ("not an http 5xx" in claim_lower or "not 5xx" in claim_lower) and bool({"500", "502", "503", "504"} & status_codes):
                return (
                    HypothesisStatus.CONTRADICTED,
                    ValidationReasonCode.CLAIM_CONTRADICTED.value,
                    f"Log evidence {ev_id} shows 5xx errors ({sorted(status_codes)}), contradicting non-5xx auth claim.",
                )
            return (
                HypothesisStatus.UNSUPPORTED,
                ValidationReasonCode.IRRELEVANT_EVIDENCE.value,
                f"Log evidence {ev_id} ({sorted(status_codes | error_codes)}) does not indicate authentication or token errors.",
            )

    if "failure_assertion" in mechanisms and not is_no_error:
        if signals["all_ok_traces"] and not any(k in claim_lower for k in ("latency", "duration", "slow", "ms")):
            return (
                HypothesisStatus.CONTRADICTED,
                ValidationReasonCode.CLAIM_CONTRADICTED.value,
                f"Trace evidence {ev_id} shows only OK spans without errors, contradicting failure claim.",
            )
        if tool_name == "get_service_metrics" and metric_names == {"error_rate"} and metric_values and all(v == 0.0 for _, v in metric_values):
            return (
                HypothesisStatus.CONTRADICTED,
                ValidationReasonCode.CLAIM_CONTRADICTED.value,
                f"Metric evidence {ev_id} reports error_rate=0.0, contradicting failure claim.",
            )

    return None


class ClaimValidator:
    """Deterministic evidence and applicability validator for Chapter 14 (C14)."""

    def __init__(self, value_tolerance_pct: float = 0.15) -> None:
        self.value_tolerance_pct = value_tolerance_pct

    def validate_claim(
        self,
        claim_text: str,
        evidence_id: str | None,
        context: dict[str, Any],
        claimed_value: float | None = None,
        *,
        hypothesis_text: str | None = None,
    ) -> ValidatedClaim:
        """Validate a single claim string against the original evidence context."""
        # 1. Check for forbidden VERIFIED keyword (RULE-007)
        if _VERIFIED_PATTERN.search(claim_text):
            return ValidatedClaim(
                claim_text=claim_text,
                evidence_id=evidence_id,
                status=HypothesisStatus.PARTIAL,
                reason_code=ValidationReasonCode.VERIFIED_STATUS_FORBIDDEN.value,
                details="RULE-007 Violation: Claim text contains forbidden 'VERIFIED' keyword; downgraded.",
            )

        evidence_items = context.get("evidence_items", [])
        evidence_map = {ev.get("evidence_id"): ev for ev in evidence_items if ev.get("evidence_id")}

        # 2. Check evidence ID presence
        if not evidence_id or evidence_id not in evidence_map:
            return ValidatedClaim(
                claim_text=claim_text,
                evidence_id=evidence_id,
                status=HypothesisStatus.UNSUPPORTED,
                reason_code=ValidationReasonCode.MISSING_EVIDENCE_REF.value,
                details=f"Evidence ID {evidence_id!r} not found in usable evidence set.",
            )

        ev = evidence_map[evidence_id]
        observed_at = ev.get("observed_at")

        # 3. Check time window bounds (SC-14)
        query_window = context.get("query_window")
        if query_window and observed_at:
            try:
                obs_dt = parse_utc_iso(observed_at)
                win_start = parse_utc_iso(query_window["start"])
                win_end = parse_utc_iso(query_window["end"])
                if obs_dt < win_start or obs_dt > win_end:
                    return ValidatedClaim(
                        claim_text=claim_text,
                        evidence_id=evidence_id,
                        status=HypothesisStatus.UNSUPPORTED,
                        reason_code=ValidationReasonCode.OUT_OF_WINDOW.value,
                        observed_at=observed_at,
                        details=f"Evidence observed at {observed_at} is outside query window [{query_window['start']} - {query_window['end']}].",
                    )
            except Exception as exc:
                return ValidatedClaim(
                    claim_text=claim_text,
                    evidence_id=evidence_id,
                    status=HypothesisStatus.UNSUPPORTED,
                    reason_code=ValidationReasonCode.OUT_OF_WINDOW.value,
                    observed_at=observed_at,
                    details=f"Time window validation failed: {exc}",
                )

        # 4. Check values against evidence records (VALUE_MISMATCH)
        records = ev.get("records", [])
        extracted_claimed = claimed_value if claimed_value is not None else extract_numeric_value(claim_text)

        if extracted_claimed is not None and records:
            observed_values = []
            for rec in records:
                if isinstance(rec, dict):
                    for key in ("value", "duration_ms", "status_code"):
                        if key in rec and isinstance(rec[key], (int, float)):
                            observed_values.append(float(rec[key]))

            if observed_values:
                # Find closest observed value
                closest = min(observed_values, key=lambda v: abs(v - extracted_claimed))
                # Check discrepancy threshold
                abs_diff = abs(closest - extracted_claimed)
                # Allow tolerance percentage or small absolute delta
                threshold = max(abs(closest) * self.value_tolerance_pct, 1.0)
                if abs_diff > threshold:
                    return ValidatedClaim(
                        claim_text=claim_text,
                        evidence_id=evidence_id,
                        status=HypothesisStatus.UNSUPPORTED,
                        reason_code=ValidationReasonCode.VALUE_MISMATCH.value,
                        value_delta={"claimed": extracted_claimed, "observed": closest, "difference": abs_diff},
                        observed_at=observed_at,
                        details=f"Claimed value {extracted_claimed} mismatches observed telemetry {closest}.",
                    )

        # 5. Check evidence availability, scope, mechanism relevance, and direct contradiction
        relevance_issue = _assess_evidence_relevance(hypothesis_text or claim_text, ev, context)
        if relevance_issue is not None:
            rel_status, rel_code, rel_details = relevance_issue
            return ValidatedClaim(
                claim_text=claim_text,
                evidence_id=evidence_id,
                status=rel_status,
                reason_code=rel_code,
                observed_at=observed_at,
                details=rel_details,
            )

        # 6. Claim corroborated
        return ValidatedClaim(
            claim_text=claim_text,
            evidence_id=evidence_id,
            status=HypothesisStatus.SUPPORTED,
            reason_code=ValidationReasonCode.CLAIM_CORROBORATED.value,
            observed_at=observed_at,
            details="Claim substantiated by valid within-window telemetry evidence.",
        )

    def detect_contradictions(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        """Detect cross-signal contradictions and missing source outages.

        Returns (contradictions, unknowns, reason_codes).
        """
        contradictions: list[str] = []
        unknowns: list[str] = []
        reason_codes: list[str] = []

        # 1. Trace source availability check (EV-02, SC-09)
        trace_items = [ev for ev in evidence_items if ev.get("tool_name") == "get_trace_summary"]
        trace_outage = False
        if not trace_items:
            trace_outage = True
        else:
            for ev in trace_items:
                if ev.get("data_quality") == "unavailable" or ev.get("error_code") in ("SOURCE_UNAVAILABLE", "TIMEOUT"):
                    trace_outage = True
                    break
                records = ev.get("records", [])
                if not records and ev.get("status") in ("unavailable", "source_unavailable"):
                    trace_outage = True
                    break

        if trace_outage:
            unknowns.append(
                "Distributed trace backend is unavailable (EV-02, SC-09); causal relationships across service hops cannot be verified."
            )
            reason_codes.append(ValidationReasonCode.SOURCE_UNAVAILABLE.value)

        # 2. Metrics vs Logs contradiction check (EV-01)
        log_errors = []
        for ev in evidence_items:
            if ev.get("tool_name") == "search_error_logs":
                for rec in ev.get("records", []):
                    if isinstance(rec, dict):
                        sc = rec.get("status_code", 0)
                        is_server_err = (isinstance(sc, int) and sc >= 500) or (isinstance(sc, str) and sc.isdigit() and int(sc) >= 500)
                        msg = str(rec.get("message", "")).lower()
                        if is_server_err or "error" in msg or "exception" in msg:
                            log_errors.append(rec)

        metrics_zero_errors = False
        for ev in evidence_items:
            if ev.get("tool_name") == "get_service_metrics":
                for rec in ev.get("records", []):
                    if isinstance(rec, dict):
                        metric_name = str(rec.get("metric_enum") or rec.get("metric_name") or "")
                        if "error" in metric_name.lower() and rec.get("value") == 0:
                            metrics_zero_errors = True
                        elif metric_name == "error_rate" and rec.get("value") == 0.0:
                            metrics_zero_errors = True

        if log_errors and metrics_zero_errors:
            contradictions.append(
                f"Contradicting signals: search_error_logs captured {len(log_errors)} server error log(s), but get_service_metrics reported zero error rate (EV-01)."
            )
            reason_codes.append(ValidationReasonCode.CONTRADICTING_SIGNALS.value)

        return contradictions, unknowns, reason_codes

    def validate_sop_citations(
        self,
        citations: list[dict[str, Any]],
        incident_service: str,
        incident_environment: str,
        event_time_iso: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """Validate SOP/runbook citations against service scope, environment, and validity window.

        Returns (valid_citations, rejected_citations, reason_codes).
        """
        valid_citations: list[dict[str, Any]] = []
        rejected_citations: list[dict[str, Any]] = []
        reason_codes: list[str] = []

        try:
            event_dt = parse_utc_iso(event_time_iso)
        except Exception:
            event_dt = None

        for cit in citations:
            chunk_id = cit.get("chunk_id", "unknown")
            doc_id = cit.get("document_id", "unknown")

            # Check scope: service and environment (RAG-02)
            svc = cit.get("service_id")
            env = cit.get("environment")
            if svc != incident_service or env != incident_environment:
                rejected_citations.append({
                    **cit,
                    "rejection_reason": ValidationReasonCode.SCOPE_MISMATCH.value,
                    "details": f"Citation service '{svc}' or environment '{env}' mismatches incident [{incident_service}/{incident_environment}].",
                })
                reason_codes.append(ValidationReasonCode.SCOPE_MISMATCH.value)
                continue

            # Check status: must be approved / active (RAG-01)
            status = cit.get("status", "active")
            if status not in ("active", "approved"):
                rejected_citations.append({
                    **cit,
                    "rejection_reason": ValidationReasonCode.OBSOLETE_SOP.value,
                    "details": f"Citation status '{status}' is not active/approved.",
                })
                reason_codes.append(ValidationReasonCode.OBSOLETE_SOP.value)
                continue

            # Check validity dates (RAG-01, SC-10)
            if event_dt is not None:
                eff_from = cit.get("effective_from")
                eff_to = cit.get("effective_to")
                is_obsolete = False
                try:
                    if eff_from and parse_utc_iso(eff_from) > event_dt:
                        is_obsolete = True
                    if eff_to and parse_utc_iso(eff_to) <= event_dt:
                        is_obsolete = True
                except Exception:
                    is_obsolete = True

                if is_obsolete:
                    rejected_citations.append({
                        **cit,
                        "rejection_reason": ValidationReasonCode.OBSOLETE_SOP.value,
                        "details": f"Citation {doc_id} ({chunk_id}) is obsolete or inactive at incident event time {event_time_iso}.",
                    })
                    reason_codes.append(ValidationReasonCode.OBSOLETE_SOP.value)
                    continue

            # Citation is valid
            valid_citations.append(cit)

        return valid_citations, rejected_citations, reason_codes

    def evaluate_cascade_and_multifault(
        self,
        hypotheses: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Distinguish origin vs downstream cascade effects (AT-016, SC-04) and concurrent faults (SC-08)."""
        evidence_items = context.get("evidence_items", [])
        incident_service = context.get("service_id", "")

        # Collect services exhibiting errors
        error_services: set[str] = set()
        error_types: set[str] = set()
        for ev in evidence_items:
            for rec in ev.get("records", []):
                if isinstance(rec, dict):
                    sc = rec.get("status_code", 0)
                    is_err = False
                    if isinstance(sc, int) and sc >= 400:
                        is_err = True
                    elif isinstance(sc, str) and (
                        (sc.isdigit() and int(sc) >= 400)
                        or sc.upper() in ("ERROR", "INTERNAL", "UNAVAILABLE")
                    ):
                        is_err = True
                    elif rec.get("error_code") or rec.get("error"):
                        is_err = True

                    if is_err:
                        svc = rec.get("service_id") or ev.get("service_id")
                        if svc:
                            error_services.add(svc)
                        if rec.get("status_code"):
                            error_types.add(str(rec.get("status_code")))
                        if rec.get("error_code"):
                            error_types.add(str(rec.get("error_code")))

        is_cascade = len(error_services) > 1 and any(
            upstream != incident_service for upstream in error_services
        )
        is_multi_fault = len(error_services) > 1 and len(error_types) > 1

        origin_service = None
        if is_cascade:
            # Deterministically identify upstream origin service (not the front gateway/caller)
            non_incident_services = sorted(s for s in error_services if s != incident_service)
            if non_incident_services:
                origin_service = non_incident_services[0]

        return {
            "is_cascade": is_cascade,
            "is_multi_fault": is_multi_fault,
            "origin_service": origin_service,
            "error_services": sorted(error_services),
            "error_types": sorted(error_types),
        }

    def validate_hypothesis(
        self,
        hypothesis: dict[str, Any],
        context: dict[str, Any],
    ) -> ValidationReport:
        """Validate candidate hypothesis against all semantic rules and evidence bounds."""
        hyp_id = hypothesis.get("hypothesis_id", "hyp-001")
        confidence_str = str(hypothesis.get("confidence", "MEDIUM")).upper()

        claims: list[ValidatedClaim] = []
        reason_codes: list[str] = []

        # 1. Hard check for VERIFIED keyword in diagnosis or title (RULE-007)
        title = hypothesis.get("title", "")
        summary = hypothesis.get("summary", "")
        diagnosis = hypothesis.get("diagnosis", "")
        root_cause = hypothesis.get("estimated_root_cause", hypothesis.get("candidate_cause", ""))

        all_text = f"{title} {summary} {diagnosis} {root_cause}"
        has_forbidden_verified = bool(_VERIFIED_PATTERN.search(all_text) or confidence_str == "VERIFIED")
        if has_forbidden_verified:
            reason_codes.append(ValidationReasonCode.VERIFIED_STATUS_FORBIDDEN.value)

        # 2. Validate individual supporting claims
        supporting_ids = list(hypothesis.get("supporting_evidence_ids", []))
        contradicting_ids = list(hypothesis.get("contradicting_evidence_ids", []))

        evidence_items = context.get("evidence_items", [])
        claim_text = diagnosis or title or summary or root_cause

        for ev_id in supporting_ids:
            claim_val = self.validate_claim(
                claim_text=claim_text,
                evidence_id=ev_id,
                context=context,
                hypothesis_text=all_text,
            )
            claims.append(claim_val)
            if claim_val.reason_code not in reason_codes:
                reason_codes.append(claim_val.reason_code)

        # 3. Detect contradictions and missing trace sources
        contradictions, unknowns, contra_reasons = self.detect_contradictions(evidence_items)
        for r in contra_reasons:
            if r not in reason_codes:
                reason_codes.append(r)

        # Retain only corroborated evidence IDs as supporting; move directly contradicting IDs
        validated_supporting_ids: list[str] = []
        validated_contradicting_ids: list[str] = list(dict.fromkeys(contradicting_ids))
        for claim_val in claims:
            if claim_val.status == HypothesisStatus.SUPPORTED and claim_val.evidence_id:
                if claim_val.evidence_id not in validated_supporting_ids:
                    validated_supporting_ids.append(claim_val.evidence_id)
            elif claim_val.status == HypothesisStatus.CONTRADICTED:
                if claim_val.evidence_id and claim_val.evidence_id not in validated_contradicting_ids:
                    validated_contradicting_ids.append(claim_val.evidence_id)
                unknowns.append(f"Rejected supporting evidence {claim_val.evidence_id}: {claim_val.details}")
            elif claim_val.status == HypothesisStatus.UNSUPPORTED:
                unknowns.append(f"Evidence {claim_val.evidence_id or 'none'} does not substantiate hypothesis: {claim_val.details}")

        # 4. SOP Applicability Validation
        citations = context.get("runbook_citations", [])
        service_id = context.get("service_id", "")
        environment = context.get("environment", "lab")
        event_time = context.get("event_time", "")

        valid_citations, rejected_citations, sop_reasons = self.validate_sop_citations(
            citations=citations,
            incident_service=service_id,
            incident_environment=environment,
            event_time_iso=event_time,
        )
        for r in sop_reasons:
            if r not in reason_codes:
                reason_codes.append(r)

        if not citations and context.get("no_applicable_runbook"):
            reason_codes.append(ValidationReasonCode.NO_APPLICABLE_RUNBOOK.value)

        # 5. Cascade and Multi-Fault Evaluation
        cascade_info = self.evaluate_cascade_and_multifault([hypothesis], context)
        if cascade_info["is_cascade"]:
            reason_codes.append(ValidationReasonCode.DOWNSTREAM_SYMPTOM_CASCADE.value)
        if cascade_info["is_multi_fault"]:
            reason_codes.append(ValidationReasonCode.CONCURRENT_INDEPENDENT_FAULT.value)

        # 6. Determine final status and confidence score
        # FAIL-CLOSED principle: never upgrade unvalidated or contradicted claims
        trace_outage = ValidationReasonCode.SOURCE_UNAVAILABLE.value in reason_codes
        has_contradictions = bool(contradictions) or ValidationReasonCode.CONTRADICTING_SIGNALS.value in reason_codes
        supported_claims = [c for c in claims if c.status == HypothesisStatus.SUPPORTED]
        contradicted_claims = [c for c in claims if c.status == HypothesisStatus.CONTRADICTED]
        unsupported_claims = [c for c in claims if c.status == HypothesisStatus.UNSUPPORTED]
        has_missing_refs = ValidationReasonCode.MISSING_EVIDENCE_REF.value in reason_codes
        has_out_of_window = ValidationReasonCode.OUT_OF_WINDOW.value in reason_codes
        has_irrelevant = ValidationReasonCode.IRRELEVANT_EVIDENCE.value in reason_codes
        claims_specific_mechanism = bool(_detect_claim_mechanisms(all_text) - {"failure_assertion"})

        if not supporting_ids:
            if ValidationReasonCode.MISSING_SUPPORTING_EVIDENCE.value not in reason_codes:
                reason_codes.append(ValidationReasonCode.MISSING_SUPPORTING_EVIDENCE.value)
            unknowns.append(f"Hypothesis '{hyp_id}' has no supporting evidence IDs attached.")

        unknowns = list(dict.fromkeys(unknowns))

        if has_forbidden_verified:
            # Strictly downgraded per RULE-007
            final_status = HypothesisStatus.INCONCLUSIVE if trace_outage else HypothesisStatus.PARTIAL
            confidence = min(0.30, hypothesis.get("confidence_score", 0.5))
        elif (contradicted_claims and not supported_claims) or (validated_contradicting_ids and not supporting_ids and not supported_claims):
            final_status = HypothesisStatus.CONTRADICTED
            confidence = 0.10
        elif (unsupported_claims or has_missing_refs or has_irrelevant) and not supported_claims:
            final_status = HypothesisStatus.UNSUPPORTED
            confidence = 0.15
        elif trace_outage:
            final_status = HypothesisStatus.INCONCLUSIVE
            confidence = min(0.40, hypothesis.get("confidence_score", 0.5))
        elif not supporting_ids:
            if claims_specific_mechanism and any(ev.get("records") for ev in evidence_items):
                final_status = HypothesisStatus.UNSUPPORTED
                confidence = 0.15
            else:
                final_status = HypothesisStatus.INCONCLUSIVE
                confidence = 0.20
        elif has_contradictions or has_out_of_window or contradicted_claims or unsupported_claims or has_irrelevant:
            final_status = HypothesisStatus.PARTIAL
            confidence = min(0.45, hypothesis.get("confidence_score", 0.5))
        else:
            final_status = HypothesisStatus.SUPPORTED
            confidence = max(0.60, min(0.85, hypothesis.get("confidence_score", 0.75)))

        return ValidationReport(
            hypothesis_id=hyp_id,
            status=final_status,
            confidence_score=confidence,
            claims=claims,
            contradictions=contradictions,
            unknowns=unknowns,
            supporting_evidence_ids=validated_supporting_ids,
            contradicting_evidence_ids=validated_contradicting_ids,
            rejected_sop_citations=rejected_citations,
            valid_sop_citations=valid_citations,
            reason_codes=reason_codes,
            origin_service=cascade_info["origin_service"],
            is_cascade=cascade_info["is_cascade"],
            is_multi_fault=cascade_info["is_multi_fault"],
        )
