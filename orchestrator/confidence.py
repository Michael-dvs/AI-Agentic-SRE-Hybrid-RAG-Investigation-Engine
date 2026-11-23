"""Deterministic evidence-aware confidence scoring, hypothesis ranking, and SOP diagnostic relevance.

All scores produced here are bounded heuristic diagnostics in [0.05, 0.85]
(`is_calibrated_probability = False`). They are NOT calibrated empirical
probabilities and never imply `VERIFIED` root cause status (RULE-007).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ConfidenceScoringConfig:
    """Centralized coefficients and bounds for deterministic confidence scoring."""

    min_score: float = 0.05
    max_score: float = 0.85
    high_threshold: float = 0.70
    medium_threshold: float = 0.40
    score_semantics: str = "heuristic_evidence_aware_non_probabilistic"
    is_calibrated_probability: bool = False

    # Corroborated hypothesis scoring parameters (SOP availability has weight 0.0)
    base_supported: float = 0.45
    support_increments: tuple[float, ...] = (0.12, 0.08, 0.04)
    two_modalities_bonus: float = 0.06
    three_plus_modalities_bonus: float = 0.10
    coverage_weight: float = 0.08
    contradiction_penalty_per_signal: float = 0.18
    max_contradiction_penalty: float = 0.36
    rejected_claim_penalty: float = 0.08
    max_rejected_claim_penalty: float = 0.24
    unavailable_source_penalty: float = 0.06
    max_unavailable_source_penalty: float = 0.18
    trace_outage_penalty: float = 0.15
    excess_unknowns_threshold: int = 3
    excess_unknowns_penalty: float = 0.02
    corroborated_llm_prior_adjustment: tuple[tuple[str, float], ...] = (
        ("HIGH", 0.02),
        ("MEDIUM", 0.00),
        ("LOW", -0.05),
    )
    sop_availability_weight: float = 0.0

    # Status ceilings and defaults for uncorroborated / constrained outcomes
    contradicted_base: float = 0.10
    contradicted_min: float = 0.05
    contradicted_max: float = 0.15
    unsupported_base: float = 0.14
    unsupported_min: float = 0.08
    unsupported_max: float = 0.20
    inconclusive_no_support_base: float = 0.20
    inconclusive_no_support_min: float = 0.12
    inconclusive_no_support_max: float = 0.25
    inconclusive_with_support_cap: float = 0.38
    partial_cap: float = 0.45
    rule007_cap: float = 0.30
    manual_fallback_cap: float = 0.30


DEFAULT_SCORING_CONFIG = ConfidenceScoringConfig()


_STATUS_ORDER = {
    "SUPPORTED": 4,
    "PARTIAL": 3,
    "INCONCLUSIVE": 2,
    "UNSUPPORTED": 1,
    "CONTRADICTED": 0,
}

_ERROR_CODE_RE = re.compile(r"\b(?:ERR|WARN)_[A-Z0-9_]{2,64}\b")
_HTTP_CODE_RE = re.compile(r"\b(401|403|404|429|500|502|503|504)\b")


def confidence_label_for_score(
    score: float,
    config: ConfidenceScoringConfig = DEFAULT_SCORING_CONFIG,
) -> str:
    """Map numeric confidence score monotonically to LOW / MEDIUM / HIGH."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "LOW"
    val = float(score)
    if val >= config.high_threshold:
        return "HIGH"
    if val >= config.medium_threshold:
        return "MEDIUM"
    return "LOW"


def _normalize_record_signature(tool_name: str, rec: Mapping[str, Any]) -> tuple[Any, ...]:
    if tool_name == "get_service_metrics":
        metric = str(rec.get("metric_enum") or rec.get("metric_name") or "").strip().lower()
        val = rec.get("value")
        val_norm = round(float(val), 4) if isinstance(val, (int, float)) and not isinstance(val, bool) else None
        unit = str(rec.get("unit") or "").strip().lower()
        return ("metric", metric, val_norm, unit)
    if tool_name == "search_error_logs":
        sc = rec.get("status_code")
        ec = str(rec.get("error_code") or "").strip().upper()
        msg = " ".join(str(rec.get("message") or "").strip().lower().split())[:120]
        return ("log", sc, ec, msg)
    if tool_name == "get_trace_summary":
        sc = str(rec.get("status_code") or "").strip().upper()
        op = str(rec.get("operation") or rec.get("operation_name") or "").strip().lower()
        err = bool(rec.get("error"))
        dur = rec.get("duration_ms")
        dur_bucket = round(float(dur), 1) if isinstance(dur, (int, float)) and not isinstance(dur, bool) else None
        return ("trace", sc, op, err, dur_bucket)
    return ("other", tuple(sorted((str(k), str(v)[:40]) for k, v in rec.items())))


def evidence_signal_fingerprint(ev: Mapping[str, Any]) -> tuple[Any, ...]:
    """Build a canonical signal fingerprint so identical duplicate artifacts collapse to one unit."""
    tool_name = str(ev.get("tool_name") or "")
    service_id = str(ev.get("service_id") or "")
    records = [r for r in (ev.get("records") or []) if isinstance(r, Mapping)]
    if not records:
        return (tool_name, service_id, ("empty", str(ev.get("error_code") or ""), str(ev.get("data_quality") or "")))
    sigs = tuple(sorted({_normalize_record_signature(tool_name, r) for r in records}))
    return (tool_name, service_id, sigs)


@dataclass(frozen=True)
class ConfidenceAssessment:
    """Structured output of deterministic evidence-aware confidence scoring."""

    score: float
    label: str
    rationale: str
    breakdown: dict[str, Any]
    unique_supporting_count: int
    duplicate_supporting_count: int
    distinct_modalities: tuple[str, ...]
    score_semantics: str
    is_calibrated_probability: bool


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 4)


def compute_evidence_confidence(
    *,
    status: str,
    supporting_evidence_ids: Sequence[str],
    contradicting_evidence_ids: Sequence[str],
    evidence_items: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
    contradictions: Sequence[str] = (),
    unknowns: Sequence[str] = (),
    reason_codes: Sequence[str] = (),
    llm_proposed_confidence: str | None = None,
    trace_outage: bool = False,
    has_forbidden_verified: bool = False,
    manual_fallback: bool = False,
    config: ConfidenceScoringConfig = DEFAULT_SCORING_CONFIG,
) -> ConfidenceAssessment:
    """Compute bounded, deterministic, evidence-aware confidence score and rationale."""
    norm_status = str(status.value if hasattr(status, "value") else status).upper()
    ev_map: dict[str, Mapping[str, Any]] = {
        str(ev.get("evidence_id")): ev
        for ev in evidence_items
        if isinstance(ev, Mapping) and ev.get("evidence_id")
    }

    # Deduplicate exact IDs and collapse duplicate/identical signal payloads
    unique_sup_ids = list(dict.fromkeys(str(eid) for eid in supporting_evidence_ids if eid))
    seen_fps: set[tuple[Any, ...]] = set()
    unique_signal_ids: list[str] = []
    duplicate_count = 0
    modalities: set[str] = set()
    for eid in unique_sup_ids:
        ev = ev_map.get(eid)
        if ev is None:
            continue
        fp = evidence_signal_fingerprint(ev)
        if fp in seen_fps:
            duplicate_count += 1
            continue
        seen_fps.add(fp)
        unique_signal_ids.append(eid)
        tool_name = str(ev.get("tool_name") or "").strip()
        if tool_name:
            modalities.add(tool_name)

    unique_count = len(unique_signal_ids)
    modality_tuple = tuple(sorted(modalities))

    # Deduplicate contradicting evidence signals
    unique_con_ids = list(dict.fromkeys(str(eid) for eid in contradicting_evidence_ids if eid))
    con_fps: set[tuple[Any, ...]] = set()
    for eid in unique_con_ids:
        ev = ev_map.get(eid)
        if ev is not None:
            con_fps.add(evidence_signal_fingerprint(ev))
        else:
            con_fps.add(("raw_id", eid))
    contradiction_signals_count = max(len(con_fps), len(list(dict.fromkeys(contradictions))))

    # Inspect validated claims when provided
    total_claims = len(claims)
    supported_claim_count = 0
    rejected_claim_count = 0
    for c in claims:
        c_stat = c.get("status") if isinstance(c, Mapping) else getattr(c, "status", None)
        c_stat_str = str(c_stat.value if hasattr(c_stat, "value") else c_stat).upper()
        if c_stat_str == "SUPPORTED":
            supported_claim_count += 1
        elif c_stat_str in ("UNSUPPORTED", "CONTRADICTED"):
            rejected_claim_count += 1

    # Count unavailable telemetry sources in evidence_items
    unavailable_tools: set[tuple[str, str]] = set()
    for ev in evidence_items:
        if not isinstance(ev, Mapping):
            continue
        if ev.get("data_quality") == "unavailable" or ev.get("error_code") in (
            "SOURCE_UNAVAILABLE",
            "TIMEOUT",
            "BACKEND_TIMEOUT",
        ):
            unavailable_tools.add((str(ev.get("tool_name") or ""), str(ev.get("service_id") or "")))
    unavailable_count = len(unavailable_tools)

    reason_set = set(str(r) for r in reason_codes)
    prior_map = dict(config.corroborated_llm_prior_adjustment)
    prior_key = str(llm_proposed_confidence or "").strip().upper()

    components: dict[str, Any] = {
        "status": norm_status,
        "unique_supporting_count": unique_count,
        "duplicate_supporting_count": duplicate_count,
        "distinct_modalities": list(modality_tuple),
        "contradiction_signals_count": contradiction_signals_count,
        "rejected_claim_count": rejected_claim_count,
        "unavailable_sources_count": unavailable_count,
        "trace_outage": bool(trace_outage),
        "has_forbidden_verified": bool(has_forbidden_verified),
        "manual_fallback": bool(manual_fallback),
        "sop_availability_weight": config.sop_availability_weight,
        "is_calibrated_probability": config.is_calibrated_probability,
        "score_semantics": config.score_semantics,
    }

    if manual_fallback:
        base = config.inconclusive_no_support_base if unique_count == 0 else config.manual_fallback_cap
        penalty = min(config.max_unavailable_source_penalty, unavailable_count * 0.03)
        score = _clamp(base - penalty, config.min_score, config.manual_fallback_cap)
        rationale = (
            f"Manual fallback active; capped at {score:.0%} ({confidence_label_for_score(score, config)}) "
            f"with {unique_count} unique supporting signal(s)."
        )
    elif has_forbidden_verified:
        raw_cap = config.rule007_cap - (0.05 if trace_outage else 0.0)
        score = _clamp(raw_cap, config.min_score, config.rule007_cap)
        rationale = (
            f"RULE-007 downgrade applied (forbidden VERIFIED claim); "
            f"score capped at {score:.0%}."
        )
    elif norm_status == "CONTRADICTED":
        extra_con = max(0, contradiction_signals_count - 1)
        raw = config.contradicted_base - min(0.05, extra_con * 0.02)
        score = _clamp(raw, config.contradicted_min, config.contradicted_max)
        rationale = (
            f"Hypothesis contradicted by {contradiction_signals_count} signal(s); "
            f"score bounded in [{config.contradicted_min:.0%}, {config.contradicted_max:.0%}]."
        )
    elif norm_status == "UNSUPPORTED" or (unique_count == 0 and norm_status != "INCONCLUSIVE"):
        penalty = 0.0
        if "VALUE_MISMATCH" in reason_set or "MISSING_EVIDENCE_REF" in reason_set:
            penalty += 0.02
        if "IRRELEVANT_EVIDENCE" in reason_set:
            penalty += 0.02
        raw = config.unsupported_base - penalty
        score = _clamp(raw, config.unsupported_min, config.unsupported_max)
        rationale = (
            f"No corroborated supporting evidence (rejected_claims={rejected_claim_count}); "
            f"LLM prior ignored; score={score:.0%}."
        )
    elif norm_status == "INCONCLUSIVE" and unique_count == 0:
        penalty = 0.04 if (trace_outage or unavailable_count > 0) else 0.0
        raw = config.inconclusive_no_support_base - penalty
        score = _clamp(raw, config.inconclusive_no_support_min, config.inconclusive_no_support_max)
        rationale = (
            f"Inconclusive with 0 unique supporting signals "
            f"(unavailable_sources={unavailable_count}); score={score:.0%}."
        )
    else:
        # SUPPORTED, PARTIAL, or INCONCLUSIVE with >=1 unique supporting signal (e.g. trace outage)
        support_bonus = 0.0
        for idx in range(unique_count):
            inc = config.support_increments[idx] if idx < len(config.support_increments) else 0.0
            support_bonus += inc
        modality_bonus = (
            config.three_plus_modalities_bonus
            if len(modalities) >= 3
            else (config.two_modalities_bonus if len(modalities) == 2 else 0.0)
        )
        if total_claims > 0:
            coverage_bonus = config.coverage_weight * (supported_claim_count / total_claims)
        else:
            coverage_bonus = config.coverage_weight if unique_count > 0 else 0.0

        contra_pen = min(
            config.max_contradiction_penalty,
            contradiction_signals_count * config.contradiction_penalty_per_signal,
        )
        rejected_pen = min(
            config.max_rejected_claim_penalty,
            rejected_claim_count * config.rejected_claim_penalty,
        )
        if trace_outage:
            unavail_pen = max(
                config.trace_outage_penalty,
                min(config.max_unavailable_source_penalty, unavailable_count * config.unavailable_source_penalty),
            )
        else:
            unavail_pen = min(
                config.max_unavailable_source_penalty,
                unavailable_count * config.unavailable_source_penalty,
            )
        unknowns_pen = config.excess_unknowns_penalty if len(unknowns) > config.excess_unknowns_threshold else 0.0
        llm_adj = prior_map.get(prior_key, 0.0) if unique_count > 0 and norm_status in ("SUPPORTED", "PARTIAL") else 0.0

        raw = (
            config.base_supported
            + support_bonus
            + modality_bonus
            + coverage_bonus
            + llm_adj
            - contra_pen
            - rejected_pen
            - unavail_pen
            - unknowns_pen
        )
        upper_cap = config.max_score
        if norm_status == "INCONCLUSIVE" or trace_outage:
            upper_cap = min(upper_cap, config.inconclusive_with_support_cap)
        elif norm_status == "PARTIAL":
            upper_cap = min(upper_cap, config.partial_cap)

        score = _clamp(raw, config.min_score, upper_cap)
        components.update({
            "base": config.base_supported,
            "support_bonus": round(support_bonus, 4),
            "modality_bonus": round(modality_bonus, 4),
            "coverage_bonus": round(coverage_bonus, 4),
            "llm_prior_adjustment": round(llm_adj, 4),
            "contradiction_penalty": round(contra_pen, 4),
            "rejected_claim_penalty": round(rejected_pen, 4),
            "unavailable_source_penalty": round(unavail_pen, 4),
            "unknowns_penalty": round(unknowns_pen, 4),
            "applied_cap": upper_cap,
        })
        rationale = (
            f"status={norm_status}, unique_support={unique_count} "
            f"(duplicates_collapsed={duplicate_count}, modalities={len(modalities)}), "
            f"contradictions={contradiction_signals_count}, rejected_claims={rejected_claim_count}, "
            f"unavailable_sources={unavailable_count}; score={score:.0%}."
        )

    label = confidence_label_for_score(score, config)
    components["final_score"] = score
    components["final_label"] = label
    return ConfidenceAssessment(
        score=score,
        label=label,
        rationale=rationale,
        breakdown=components,
        unique_supporting_count=unique_count,
        duplicate_supporting_count=duplicate_count,
        distinct_modalities=modality_tuple,
        score_semantics=config.score_semantics,
        is_calibrated_probability=config.is_calibrated_probability,
    )


def rank_hypotheses(hypotheses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministically rank hypotheses by support tier, evidence-aware score, evidence count, and input order."""
    indexed = list(enumerate(hypotheses))

    def _sort_key(pair: tuple[int, Mapping[str, Any]]) -> tuple[int, float, int, int]:
        idx, h = pair
        raw_status = h.get("validation_status") or h.get("status") or h.get("support_status") or "INCONCLUSIVE"
        status_str = str(raw_status.value if hasattr(raw_status, "value") else raw_status).upper()
        tier = _STATUS_ORDER.get(status_str, 2)
        raw_score = h.get("confidence_score")
        score = round(float(raw_score), 4) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0.0
        sup_ids = h.get("supporting_evidence_ids")
        sup_count = len(sup_ids) if isinstance(sup_ids, (list, tuple, set)) else 0
        return (-tier, -score, -sup_count, idx)

    indexed.sort(key=_sort_key)
    ranked: list[dict[str, Any]] = []
    for rank_num, (_, h) in enumerate(indexed, start=1):
        item = dict(h)
        item["rank"] = rank_num
        ranked.append(item)
    return ranked


def _mechanism_families(text: str) -> set[str]:
    # Mask service-registry identifier 'auth-service' so naming it as a dependency does not masquerade as auth failure guidance.
    lower = text.lower().replace("auth-service", " ")
    families: set[str] = set()
    if re.search(
        r"\b(?:auth|authentication|401|403|token|signature|policy|unauthorized|forbidden|credential)\b|err_auth",
        lower,
    ):
        families.add("auth")
    if any(k in lower for k in ("504", "timeout", "deadline", "hanging span")):
        families.add("timeout")
    if any(k in lower for k in ("db", "database", "postgres", "sqlite", "pool", "deadlock", "lock", "slow_query", "latensi database")):
        families.add("db_pool")
    if any(k in lower for k in ("queue", "rabbitmq", "consumer", "backlog", "lag")):
        families.add("queue_lag")
    if any(k in lower for k in ("5xx", "500", "502", "503", "dependency", "unavailable")):
        families.add("http_5xx")
    return families


def _is_general_service_sop(doc_id: str, title: str, excerpt: str) -> bool:
    doc_upper = doc_id.upper()
    if "-ERR-" in doc_upper or "-QUEUE-" in doc_upper or "KNOWN-ERR-" in doc_upper:
        return False
    combined = f"{title} {excerpt}".lower()
    return doc_upper.startswith("SOP-") and (
        "5xx" in combined or "umum" in combined or "penanganan" in combined or "pemantauan" in combined or "investigasi" in combined
    )


def assess_sop_diagnostic_relevance(
    citations: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Assess diagnostic relevance and multi-SOP relation independently from hard eligibility."""
    if not citations:
        return {
            "status": "NONE",
            "multi_sop_relation": "NONE",
            "specific_coverage_gap": False,
            "incident_error_codes": [],
            "incident_mechanisms": [],
            "citations": [],
        }

    error_codes: set[str] = set()
    raw_ec = str(context.get("error_code") or "").strip().upper()
    if raw_ec and raw_ec not in ("ERR_UNKNOWN", "ERR_OBSERVED_ALERT"):
        error_codes.add(raw_ec)

    message_text = str(context.get("message") or "")
    for match in _ERROR_CODE_RE.findall(message_text.upper()):
        if match not in ("ERR_UNKNOWN", "ERR_OBSERVED_ALERT"):
            error_codes.add(match)

    http_codes: set[str] = set(_HTTP_CODE_RE.findall(message_text))
    for ev in context.get("evidence_items") or []:
        if not isinstance(ev, Mapping):
            continue
        for rec in ev.get("records") or []:
            if not isinstance(rec, Mapping):
                continue
            rec_ec = str(rec.get("error_code") or "").strip().upper()
            if rec_ec and rec_ec not in ("ERR_UNKNOWN", "ERR_OBSERVED_ALERT"):
                error_codes.add(rec_ec)
            sc = rec.get("status_code")
            if sc is not None and str(sc) in ("401", "403", "404", "429", "500", "502", "503", "504"):
                http_codes.add(str(sc))

    incident_signal_text = " ".join([raw_ec, message_text, *sorted(error_codes), *sorted(http_codes)])
    incident_families = _mechanism_families(incident_signal_text)

    assessed: list[dict[str, Any]] = []
    doc_ids: set[str] = set()
    doc_versions: set[tuple[str, str]] = set()
    has_specific_or_mech_match = False

    for cit in citations:
        if not isinstance(cit, Mapping):
            continue
        doc_id = str(cit.get("document_id") or cit.get("doc_id") or "")
        doc_ver = str(cit.get("document_version") or cit.get("version") or "")
        chunk_id = str(cit.get("chunk_id") or "")
        title = str(cit.get("title") or "")
        section = str(cit.get("section_path") or "")
        excerpt = str(cit.get("sanitized_excerpt") or cit.get("excerpt") or "")
        doc_text = f"{doc_id} {title} {section} {excerpt}"
        doc_upper = doc_id.upper()
        doc_text_upper = doc_text.upper()

        if doc_id:
            doc_ids.add(doc_id)
            doc_versions.add((doc_id, doc_ver))

        doc_families = _mechanism_families(doc_text)
        exact_code_match = any(ec in doc_text_upper for ec in error_codes)
        is_specific_err_doc = ("-ERR-" in doc_upper or "-QUEUE-" in doc_upper or "KNOWN-ERR-" in doc_upper)

        if exact_code_match:
            relevance_cls = "EXACT_ERROR_CODE_MATCH"
            has_specific_or_mech_match = True
        elif incident_families and (incident_families & doc_families):
            if not is_specific_err_doc and _is_general_service_sop(doc_id, title, excerpt) and "auth" in incident_families and "http_5xx" not in incident_families:
                relevance_cls = "GENERAL_SERVICE_GUIDANCE"
            else:
                relevance_cls = "MECHANISM_MATCH"
                has_specific_or_mech_match = True
        elif _is_general_service_sop(doc_id, title, excerpt):
            relevance_cls = "GENERAL_SERVICE_GUIDANCE"
        elif is_specific_err_doc or (doc_families and incident_families and not (doc_families & incident_families)):
            relevance_cls = "ADJACENT_MECHANISM_MISMATCH"
        else:
            relevance_cls = "GENERAL_SERVICE_GUIDANCE"

        assessed.append({
            "chunk_id": chunk_id,
            "document_id": doc_id,
            "document_version": doc_ver,
            "relevance_class": relevance_cls,
            "doc_mechanisms": sorted(doc_families),
        })

    if len(doc_versions) <= 1:
        multi_relation = "SINGLE_SOURCE"
    elif len(doc_ids) == 1:
        multi_relation = "MULTIPLE_VERSIONS"
    else:
        excerpts = [str(c.get("sanitized_excerpt") or c.get("excerpt") or "").lower() for c in citations if isinstance(c, Mapping)]
        has_prohibition = any(w in text for text in excerpts for w in ("jangan ", "do not ", "never ", "prohibited", "tidak berlaku"))
        multi_relation = (
            "CONFLICTING_INSTRUCTIONS"
            if has_prohibition
            else "MULTIPLE_ELIGIBLE_DOCS_UNRESOLVED_PRECEDENCE"
        )

    specific_coverage_gap = bool(error_codes) and bool(assessed) and not has_specific_or_mech_match
    overall_status = (
        "SPECIFIC_COVERAGE_GAP"
        if specific_coverage_gap
        else (
            "DIRECTLY_RELEVANT"
            if any(a["relevance_class"] in ("EXACT_ERROR_CODE_MATCH", "MECHANISM_MATCH") for a in assessed)
            else "GENERAL_GUIDANCE_ONLY"
        )
    )
    return {
        "status": overall_status,
        "multi_sop_relation": multi_relation,
        "specific_coverage_gap": specific_coverage_gap,
        "incident_error_codes": sorted(error_codes),
        "incident_mechanisms": sorted(incident_families),
        "citations": assessed,
    }


__all__ = [
    "ConfidenceAssessment",
    "ConfidenceScoringConfig",
    "DEFAULT_SCORING_CONFIG",
    "assess_sop_diagnostic_relevance",
    "confidence_label_for_score",
    "compute_evidence_confidence",
    "evidence_signal_fingerprint",
    "rank_hypotheses",
]
