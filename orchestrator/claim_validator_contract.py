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


class ValidationReasonCode(str, Enum):
    """Canonical reason codes for claim and evidence validation."""
    CLAIM_CORROBORATED = "CLAIM_CORROBORATED"
    MISSING_EVIDENCE_REF = "MISSING_EVIDENCE_REF"
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

        # 5. Claim corroborated
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
        evidence_map = {ev.get("evidence_id"): ev for ev in evidence_items if ev.get("evidence_id")}

        for ev_id in supporting_ids:
            claim_val = self.validate_claim(
                claim_text=diagnosis,
                evidence_id=ev_id,
                context=context,
            )
            claims.append(claim_val)
            if claim_val.reason_code not in reason_codes:
                reason_codes.append(claim_val.reason_code)

        # 3. Detect contradictions and missing trace sources
        contradictions, unknowns, contra_reasons = self.detect_contradictions(evidence_items)
        for r in contra_reasons:
            if r not in reason_codes:
                reason_codes.append(r)

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
        # FAIL-CLOSED principle: any severe issue downgrades to INCONCLUSIVE or PARTIAL
        trace_outage = ValidationReasonCode.SOURCE_UNAVAILABLE.value in reason_codes
        has_contradictions = bool(contradictions) or ValidationReasonCode.CONTRADICTING_SIGNALS.value in reason_codes
        has_unsupported_claims = any(c.status == HypothesisStatus.UNSUPPORTED for c in claims)
        has_missing_refs = ValidationReasonCode.MISSING_EVIDENCE_REF.value in reason_codes
        has_out_of_window = ValidationReasonCode.OUT_OF_WINDOW.value in reason_codes

        if has_forbidden_verified:
            # Strictly downgraded per RULE-007
            final_status = HypothesisStatus.INCONCLUSIVE if trace_outage else HypothesisStatus.PARTIAL
            confidence = min(0.30, hypothesis.get("confidence_score", 0.5))
        elif trace_outage:
            final_status = HypothesisStatus.INCONCLUSIVE
            confidence = min(0.40, hypothesis.get("confidence_score", 0.5))
        elif has_contradictions or has_out_of_window:
            final_status = HypothesisStatus.PARTIAL
            confidence = min(0.45, hypothesis.get("confidence_score", 0.5))
        elif has_unsupported_claims or has_missing_refs:
            final_status = HypothesisStatus.UNSUPPORTED
            confidence = 0.15
        elif not supporting_ids:
            final_status = HypothesisStatus.INCONCLUSIVE
            confidence = 0.20
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
            supporting_evidence_ids=supporting_ids,
            contradicting_evidence_ids=contradicting_ids,
            rejected_sop_citations=rejected_citations,
            valid_sop_citations=valid_citations,
            reason_codes=reason_codes,
            origin_service=cascade_info["origin_service"],
            is_cascade=cascade_info["is_cascade"],
            is_multi_fault=cascade_info["is_multi_fault"],
        )
