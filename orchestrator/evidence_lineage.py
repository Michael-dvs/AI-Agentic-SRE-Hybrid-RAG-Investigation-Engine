"""Deterministic Evidence Identity, Provenance, Temporal Integrity, Freshness, Isolation, and Cache Safety (P1-05).

Provides reusable, pure-Python verification primitives across the investigation pipeline:
1. Seven-dimension timestamp normalization (UTC ISO-8601, offset-aware ISO-8601, Unix s/ms;
   rejects naive/ambiguous, malformed, missing, and unbounded future timestamps without fabrication).
2. Centralized EvidenceTemporalPolicy separating current-state Freshness from incident-window
   Historical Relevance with explicit assessment_time and bounded clock-skew tolerance.
3. Canonical evidence identity & SHA-256 content consistency fingerprinting (explicitly documented
   as post-collection content consistency, not cryptographic proof of upstream source authenticity).
4. Incident/service/environment/window isolation with explicit justification rules for legitimately
   shared correlated observations.
5. ScopedTelemetryCache enforcing authorization, service, environment, query parameters, and window
   keys while never masking SOURCE_UNAVAILABLE behind stale cached entries.
6. Cross-signal correlation metadata (trace/log identity vs metric/log temporal coincidence).
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


INTEGRITY_SEMANTICS_NOTE = (
    "SHA-256 content_hash verifies post-collection payload consistency against the captured "
    "normalized snapshot only; it does not independently prove upstream source authenticity."
)

# ---------------------------------------------------------------------------
# Timestamp Parsing & Normalization (Work Package D1, D2, D4)
# ---------------------------------------------------------------------------

_ISO_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_CURRENT_STATE_CLAIM_RE = re.compile(
    r"\b(?:"
    r"is\s+currently\s+(?:down|failing|degraded|unavailable|experiencing|saturated|exhausted|throttling|active|broken)|"
    r"are\s+currently\s+(?:down|failing|degraded|unavailable|experiencing|saturated|exhausted|throttling|active|broken)|"
    r"still\s+(?:down|failing|degraded|unavailable|active|ongoing|persisting)\s*(?:right\s+now|currently|at\s+present)?|"
    r"(?:active|failing|down|degraded|ongoing)\s+(?:right\s+now|at\s+this\s+moment|at\s+present)|"
    r"current(?:\s+live)?\s+(?:service\s+)?state\s+is"
    r")\b",
    re.IGNORECASE,
)

# Sane epoch bounds: 2001-09-09T01:46:40Z .. 5138-11-16T09:46:40Z
_EPOCH_SECONDS_MIN = 1_000_000_000.0
_EPOCH_SECONDS_MAX = 99_999_999_999.0
_EPOCH_MILLIS_MIN = 1_000_000_000_000.0
_EPOCH_MILLIS_MAX = 99_999_999_999_999.0


@dataclasses.dataclass(frozen=True)
class NormalizedTimestamp:
    """Result of deterministic timestamp normalization without guessing or wall-clock substitution."""

    ok: bool
    status: str
    utc_iso: str | None = None
    dt: datetime.datetime | None = None
    raw_value: Any = None
    source_format: str | None = None
    had_subsecond_precision: bool = False
    clock_skew_suspected: bool = False
    skew_seconds: float = 0.0
    is_future: bool = False
    error_detail: str | None = None


def format_utc_iso(dt: datetime.datetime) -> str:
    """Format a timezone-aware datetime into canonical UTC ISO-8601 ending with 'Z', preserving subseconds."""
    utc_dt = dt.astimezone(datetime.timezone.utc)
    if utc_dt.microsecond:
        frac = f"{utc_dt.microsecond:06d}".rstrip("0")
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac}Z"
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_timestamp(
    raw_value: Any,
    *,
    reference_time: datetime.datetime | str | None = None,
    max_clock_skew_seconds: float = 5.0,
) -> NormalizedTimestamp:
    """Normalize UTC ISO-8601, offset-aware ISO-8601, or Unix s/ms to canonical UTC ISO-8601.

    Never substitutes wall-clock time for missing/invalid inputs and never guesses timezones
    for naive datetime strings.
    """
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        return NormalizedTimestamp(
            ok=False,
            status="TIMESTAMP_MISSING",
            raw_value=raw_value,
            error_detail="Timestamp is missing or empty.",
        )

    if isinstance(raw_value, bool):
        return NormalizedTimestamp(
            ok=False,
            status="TIMESTAMP_INVALID",
            raw_value=raw_value,
            error_detail="Boolean is not a valid timestamp.",
        )

    dt: datetime.datetime | None = None
    source_format: str | None = None
    had_subsecond = False

    if isinstance(raw_value, datetime.datetime):
        if raw_value.tzinfo is None or raw_value.tzinfo.utcoffset(raw_value) is None:
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_AMBIGUOUS_NAIVE",
                raw_value=str(raw_value),
                error_detail="Naive datetime without timezone offset is ambiguous.",
            )
        dt = raw_value.astimezone(datetime.timezone.utc)
        source_format = "datetime_tz"
        had_subsecond = dt.microsecond != 0

    elif isinstance(raw_value, (int, float)):
        fval = float(raw_value)
        if not math.isfinite(fval) or fval <= 0:
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_INVALID",
                raw_value=raw_value,
                error_detail=f"Non-finite or non-positive numeric timestamp: {raw_value!r}",
            )
        if _EPOCH_SECONDS_MIN <= fval <= _EPOCH_SECONDS_MAX:
            dt = datetime.datetime.fromtimestamp(fval, tz=datetime.timezone.utc)
            source_format = "unix_seconds"
            had_subsecond = (fval % 1.0) != 0.0
        elif _EPOCH_MILLIS_MIN <= fval <= _EPOCH_MILLIS_MAX:
            dt = datetime.datetime.fromtimestamp(fval / 1000.0, tz=datetime.timezone.utc)
            source_format = "unix_milliseconds"
            had_subsecond = (fval % 1000.0) != 0.0
        else:
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_INVALID",
                raw_value=raw_value,
                error_detail=f"Numeric timestamp outside supported Unix s/ms bounds: {raw_value!r}",
            )

    elif isinstance(raw_value, str):
        text = raw_value.strip()
        # Numeric string support only if purely numeric Unix epoch
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return normalize_timestamp(
                float(text) if "." in text else int(text),
                reference_time=reference_time,
                max_clock_skew_seconds=max_clock_skew_seconds,
            )
        if not _ISO_DATE_PREFIX_RE.match(text):
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_INVALID",
                raw_value=raw_value,
                error_detail=f"Malformed ISO-8601 timestamp: {raw_value!r}",
            )
        iso_candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            parsed = datetime.datetime.fromisoformat(iso_candidate)
        except ValueError as exc:
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_INVALID",
                raw_value=raw_value,
                error_detail=f"Invalid ISO-8601 calendar/time value {raw_value!r}: {exc}",
            )
        if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
            return NormalizedTimestamp(
                ok=False,
                status="TIMESTAMP_AMBIGUOUS_NAIVE",
                raw_value=raw_value,
                error_detail=f"Timestamp {raw_value!r} is missing an explicit timezone ('Z' or offset).",
            )
        dt = parsed.astimezone(datetime.timezone.utc)
        source_format = "iso8601_utc" if text.endswith(("Z", "z")) else "iso8601_offset"
        had_subsecond = "." in text
    else:
        return NormalizedTimestamp(
            ok=False,
            status="TIMESTAMP_INVALID",
            raw_value=repr(raw_value),
            error_detail=f"Unsupported timestamp type: {type(raw_value).__name__}",
        )

    utc_iso = format_utc_iso(dt)
    skew_suspected = False
    skew_seconds = 0.0
    is_future = False
    status = "VALID_UTC"

    ref_dt: datetime.datetime | None = None
    if isinstance(reference_time, datetime.datetime):
        if reference_time.tzinfo is not None:
            ref_dt = reference_time.astimezone(datetime.timezone.utc)
    elif isinstance(reference_time, str) and reference_time.strip():
        ref_norm = normalize_timestamp(reference_time)
        if ref_norm.ok:
            ref_dt = ref_norm.dt

    if ref_dt is not None:
        delta = (dt - ref_dt).total_seconds()
        if delta > max_clock_skew_seconds:
            is_future = True
            skew_seconds = round(delta, 6)
            status = "FUTURE_TIMESTAMP"
        elif delta > 0.0:
            skew_suspected = True
            skew_seconds = round(delta, 6)
            status = "CLOCK_SKEW_SUSPECTED"

    return NormalizedTimestamp(
        ok=not is_future,
        status=status,
        utc_iso=utc_iso,
        dt=dt,
        raw_value=raw_value,
        source_format=source_format,
        had_subsecond_precision=had_subsecond,
        clock_skew_suspected=skew_suspected,
        skew_seconds=skew_seconds,
        is_future=is_future,
        error_detail=(
            f"Timestamp {utc_iso} is {skew_seconds:.3f}s ahead of reference time "
            f"(exceeds max_clock_skew_seconds={max_clock_skew_seconds:.1f}s)."
            if is_future
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Centralized Temporal & Freshness Policy (Work Packages D & E)
# ---------------------------------------------------------------------------

DEFAULT_FRESHNESS_THRESHOLDS_SECONDS: dict[str, float] = {
    "get_service_metrics": 120.0,       # 2x typical 15s-60s Prometheus scrape/eval interval
    "search_error_logs": 180.0,         # OTel batch export + Loki ingestion window
    "get_trace_summary": 180.0,         # Distributed span completion + Tempo flush window
    "get_service_dependencies": 300.0,  # Matches DependencyCorrelator._edge 300s freshness rule
    "get_apm_health": 120.0,
}


@dataclasses.dataclass(frozen=True)
class EvidenceTemporalPolicy:
    """Centralized, deterministic policy for temporal relevance, freshness, and clock skew."""

    max_clock_skew_seconds: float = 5.0
    default_freshness_seconds: float = 180.0
    freshness_by_tool: Mapping[str, float] = dataclasses.field(
        default_factory=lambda: dict(DEFAULT_FRESHNESS_THRESHOLDS_SECONDS)
    )

    def freshness_threshold_for(self, tool_name: str) -> float:
        return float(self.freshness_by_tool.get(tool_name, self.default_freshness_seconds))


DEFAULT_TEMPORAL_POLICY = EvidenceTemporalPolicy()


def is_current_state_claim(claim_text: str, investigation_purpose: str | None = None) -> bool:
    """Return True when the investigation purpose or claim explicitly asserts current live state."""
    if str(investigation_purpose or "").strip().lower() in ("current_state", "live_current_state"):
        return True
    return bool(_CURRENT_STATE_CLAIM_RE.search(claim_text or ""))


def extract_record_timestamps(
    tool_name: str,
    records: Sequence[Mapping[str, Any]],
    *,
    reference_time: str | None = None,
    max_clock_skew_seconds: float = 5.0,
) -> dict[str, Any]:
    """Extract canonical observation timestamps/intervals and ingestion timestamps from records."""
    valid_obs: list[NormalizedTimestamp] = []
    valid_ingest: list[NormalizedTimestamp] = []
    invalid_errors: list[str] = []
    explicit_timestamp_fields_seen = 0

    for idx, rec in enumerate(records):
        if not isinstance(rec, Mapping):
            continue
        obs_candidates: list[Any] = []
        if tool_name == "get_service_metrics":
            if "sample_at" in rec:
                obs_candidates.append(rec.get("sample_at"))
            elif "timestamp" in rec:
                obs_candidates.append(rec.get("timestamp"))
        elif tool_name == "get_trace_summary":
            for k in ("start_time", "end_time", "timestamp"):
                if k in rec and rec.get(k) is not None:
                    obs_candidates.append(rec.get(k))
        elif tool_name == "get_service_dependencies":
            if "observed_at" in rec and rec.get("observed_at") is not None:
                obs_candidates.append(rec.get("observed_at"))
        else:
            for k in ("timestamp", "event_time", "sample_at", "observed_at"):
                if k in rec:
                    obs_candidates.append(rec.get(k))
                    break

        for raw_ts in obs_candidates:
            explicit_timestamp_fields_seen += 1
            norm = normalize_timestamp(
                raw_ts,
                reference_time=reference_time,
                max_clock_skew_seconds=max_clock_skew_seconds,
            )
            if norm.ok and norm.dt is not None:
                valid_obs.append(norm)
            else:
                invalid_errors.append(f"record[{idx}]: {norm.status} ({norm.error_detail})")

        for ing_key in ("ingested_at", "ingestion_time", "received_at"):
            if ing_key in rec and rec.get(ing_key) is not None:
                ing_norm = normalize_timestamp(
                    rec.get(ing_key),
                    max_clock_skew_seconds=max_clock_skew_seconds,
                )
                if ing_norm.ok:
                    valid_ingest.append(ing_norm)

    valid_obs_sorted = sorted(valid_obs, key=lambda x: x.dt)  # type: ignore[arg-type]
    earliest = valid_obs_sorted[0].utc_iso if valid_obs_sorted else None
    latest = valid_obs_sorted[-1].utc_iso if valid_obs_sorted else None
    latest_ingest = (
        sorted(valid_ingest, key=lambda x: x.dt)[-1].utc_iso  # type: ignore[arg-type]
        if valid_ingest
        else None
    )

    return {
        "has_record_timestamps": bool(valid_obs_sorted),
        "explicit_timestamp_fields_seen": explicit_timestamp_fields_seen,
        "observation_time": latest,
        "observation_window": (
            {"start": earliest, "end": latest} if earliest and latest else None
        ),
        "ingestion_time": latest_ingest,
        "invalid_record_timestamps": invalid_errors,
        "clock_skew_suspected": any(x.clock_skew_suspected for x in valid_obs_sorted),
        "max_skew_seconds": max((x.skew_seconds for x in valid_obs_sorted), default=0.0),
    }


def evaluate_evidence_temporal_validity(
    ev: Mapping[str, Any],
    *,
    incident_window: Mapping[str, Any] | None,
    assessment_time: str | None,
    purpose: str = "incident_window",
    policy: EvidenceTemporalPolicy = DEFAULT_TEMPORAL_POLICY,
) -> dict[str, Any]:
    """Deterministically evaluate freshness and incident-window relevance using explicit assessment_time."""
    tool_name = str(ev.get("tool_name") or "unknown")
    data_quality = str(ev.get("data_quality") or "complete")
    truncated = bool(ev.get("truncated", False))
    error_code = ev.get("error_code")
    records = ev.get("records") if isinstance(ev.get("records"), list) else []

    if error_code or data_quality == "unavailable":
        return {
            "classification": "SOURCE_UNAVAILABLE",
            "eligible_for_incident_window": False,
            "eligible_for_current_state": False,
            "fresh_for_current_assessment": False,
            "temporally_relevant_to_incident": False,
            "clock_skew_suspected": False,
            "partial_observation": True,
            "observation_time": None,
            "observation_window": None,
            "collection_time": ev.get("collected_at"),
            "assessment_time": assessment_time,
            "limitations": [f"Source unavailable ({error_code or 'SOURCE_UNAVAILABLE'})."],
        }

    limitations: list[str] = []
    partial_obs = truncated or data_quality == "partial"
    if truncated:
        limitations.append("Result set was truncated at adapter hit/point cap.")
    elif data_quality == "partial":
        limitations.append("Source returned partial observation coverage.")

    # Resolve assessment_time deterministically without calling wall clock
    assess_norm = normalize_timestamp(assessment_time) if assessment_time else None
    assess_dt = assess_norm.dt if (assess_norm and assess_norm.ok) else None
    assess_iso = assess_norm.utc_iso if (assess_norm and assess_norm.ok) else None

    # Resolve record-level timestamps first
    rec_ts = extract_record_timestamps(
        tool_name,
        records,
        reference_time=assess_iso,
        max_clock_skew_seconds=policy.max_clock_skew_seconds,
    )

    if rec_ts["invalid_record_timestamps"] and not rec_ts["has_record_timestamps"]:
        first_err = rec_ts["invalid_record_timestamps"][0]
        cls = "FUTURE_TIMESTAMP" if "FUTURE_TIMESTAMP" in first_err else "TIMESTAMP_INVALID"
        return {
            "classification": cls if cls == "TIMESTAMP_INVALID" else "TIMESTAMP_INVALID",
            "sub_status": cls,
            "eligible_for_incident_window": False,
            "eligible_for_current_state": False,
            "fresh_for_current_assessment": False,
            "temporally_relevant_to_incident": False,
            "clock_skew_suspected": False,
            "partial_observation": partial_obs,
            "observation_time": None,
            "observation_window": None,
            "collection_time": ev.get("collected_at"),
            "assessment_time": assess_iso,
            "limitations": [*limitations, *rec_ts["invalid_record_timestamps"]],
        }

    # Resolve envelope-level observation_time ONLY if it is distinct from collection_time
    # or explicitly supplied as an observation timestamp.
    collected_at_raw = ev.get("collected_at")
    raw_obs_at = ev.get("observation_time") if "observation_time" in ev else ev.get("observed_at")
    obs_start_dt: datetime.datetime | None = None
    obs_end_dt: datetime.datetime | None = None
    obs_iso: str | None = None
    obs_window: dict[str, str] | None = None
    clock_skew_suspected = bool(rec_ts["clock_skew_suspected"])

    # Static catalog declarations have no runtime observation timestamp unless edge observed_at exists
    is_static_catalog = (
        tool_name == "get_service_dependencies"
        and not rec_ts["has_record_timestamps"]
        and all(
            isinstance(r, Mapping) and r.get("kind") == "catalog_declared" and not r.get("observed_at")
            for r in records
        )
        and bool(records)
    )

    if rec_ts["has_record_timestamps"]:
        obs_iso = rec_ts["observation_time"]
        obs_window = rec_ts["observation_window"]
        if obs_window:
            obs_start_dt = normalize_timestamp(obs_window["start"]).dt
            obs_end_dt = normalize_timestamp(obs_window["end"]).dt
    elif is_static_catalog:
        limitations.append(
            "Static catalog_declared dependency topology has no live observation timestamp."
        )
    elif raw_obs_at is not None and (
        collected_at_raw is None or str(raw_obs_at) != str(collected_at_raw)
    ):
        env_obs_norm = normalize_timestamp(
            raw_obs_at,
            reference_time=assess_iso,
            max_clock_skew_seconds=policy.max_clock_skew_seconds,
        )
        if not env_obs_norm.ok:
            return {
                "classification": (
                    "TIMESTAMP_MISSING"
                    if env_obs_norm.status == "TIMESTAMP_MISSING"
                    else "TIMESTAMP_INVALID"
                ),
                "sub_status": env_obs_norm.status,
                "eligible_for_incident_window": False,
                "eligible_for_current_state": False,
                "fresh_for_current_assessment": False,
                "temporally_relevant_to_incident": False,
                "clock_skew_suspected": False,
                "partial_observation": partial_obs,
                "observation_time": None,
                "observation_window": None,
                "collection_time": collected_at_raw,
                "assessment_time": assess_iso,
                "limitations": [*limitations, env_obs_norm.error_detail or env_obs_norm.status],
            }
        obs_iso = env_obs_norm.utc_iso
        obs_start_dt = env_obs_norm.dt
        obs_end_dt = env_obs_norm.dt
        obs_window = {"start": obs_iso, "end": obs_iso} if obs_iso else None
        clock_skew_suspected = clock_skew_suspected or env_obs_norm.clock_skew_suspected
    else:
        # Check whether an explicit authorized query_window bounds the aggregated/queried result
        qw = ev.get("query_window") if isinstance(ev.get("query_window"), Mapping) else None
        qw_start = normalize_timestamp(qw.get("start")) if qw and qw.get("start") else None
        qw_end = normalize_timestamp(qw.get("end")) if qw and qw.get("end") else None
        if qw_start and qw_start.ok and qw_end and qw_end.ok and qw_start.dt and qw_end.dt:
            obs_start_dt = qw_start.dt
            # A query window extending past assessment_time (e.g. [event_time-300s, event_time+60s]
            # evaluated at event_time) only covers observations up to min(qw_end, assessment_time),
            # never fabricating a future observation timestamp!
            effective_end_dt = (
                min(qw_end.dt, assess_dt)
                if (assess_dt is not None and assess_dt >= qw_start.dt)
                else qw_end.dt
            )
            obs_end_dt = effective_end_dt
            obs_iso = format_utc_iso(effective_end_dt)
            obs_window = {"start": qw_start.utc_iso or "", "end": obs_iso}
            if not records:
                limitations.append("Zero records returned within authorized query window.")
            else:
                limitations.append(
                    "Records carry no per-event timestamp; bounded by authorized query_window."
                )
        else:
            return {
                "classification": "TIMESTAMP_MISSING",
                "sub_status": "TEMPORAL_VALIDITY_UNKNOWN",
                "eligible_for_incident_window": False,
                "eligible_for_current_state": False,
                "fresh_for_current_assessment": False,
                "temporally_relevant_to_incident": False,
                "clock_skew_suspected": False,
                "partial_observation": partial_obs,
                "observation_time": None,
                "observation_window": None,
                "collection_time": collected_at_raw,
                "assessment_time": assess_iso,
                "limitations": [
                    *limitations,
                    "Observation timestamp and query window are missing; freshness and window alignment unknown.",
                ],
            }

    # Evaluate incident-window relevance
    in_incident_window = True
    if is_static_catalog:
        # Static topology is contextual for incident window, never current-state proof
        in_incident_window = True
    elif isinstance(incident_window, Mapping) and incident_window.get("start") and incident_window.get("end"):
        win_s = normalize_timestamp(incident_window.get("start"))
        win_e = normalize_timestamp(incident_window.get("end"))
        if win_s.ok and win_e.ok and win_s.dt and win_e.dt and obs_start_dt and obs_end_dt:
            skew_td = datetime.timedelta(seconds=policy.max_clock_skew_seconds)
            # Overlap check between [obs_start_dt, obs_end_dt] and [win_s.dt, win_e.dt]
            strictly_overlaps = obs_end_dt >= win_s.dt and obs_start_dt <= win_e.dt
            skew_overlaps = obs_end_dt >= (win_s.dt - skew_td) and obs_start_dt <= (win_e.dt + skew_td)
            if strictly_overlaps:
                in_incident_window = True
            elif skew_overlaps:
                in_incident_window = True
                clock_skew_suspected = True
                skew_amt = (
                    (win_s.dt - obs_end_dt).total_seconds()
                    if obs_end_dt < win_s.dt
                    else (obs_start_dt - win_e.dt).total_seconds()
                )
                limitations.append(
                    f"Observation falls {skew_amt:.3f}s outside nominal window boundary but within "
                    f"bounded clock-skew tolerance ({policy.max_clock_skew_seconds:.1f}s)."
                )
            else:
                in_incident_window = False
                limitations.append(
                    f"Observation interval [{format_utc_iso(obs_start_dt)}..{format_utc_iso(obs_end_dt)}] "
                    f"is outside incident window [{win_s.utc_iso}..{win_e.utc_iso}]."
                )

    # Evaluate current-state freshness against explicit assessment_time
    threshold_s = policy.freshness_threshold_for(tool_name)
    fresh_for_current: bool | None = None
    age_seconds: float | None = None
    if is_static_catalog:
        fresh_for_current = False
    elif assess_dt is not None and obs_end_dt is not None:
        age_seconds = round((assess_dt - obs_end_dt).total_seconds(), 6)
        if age_seconds < -policy.max_clock_skew_seconds:
            return {
                "classification": "TIMESTAMP_INVALID",
                "sub_status": "FUTURE_TIMESTAMP",
                "eligible_for_incident_window": False,
                "eligible_for_current_state": False,
                "fresh_for_current_assessment": False,
                "temporally_relevant_to_incident": False,
                "clock_skew_suspected": True,
                "partial_observation": partial_obs,
                "observation_time": obs_iso,
                "observation_window": obs_window,
                "collection_time": collected_at_raw,
                "assessment_time": assess_iso,
                "age_seconds": age_seconds,
                "freshness_threshold_seconds": threshold_s,
                "limitations": [
                    *limitations,
                    f"Observation timestamp {obs_iso} is {-age_seconds:.3f}s in the future relative to assessment_time {assess_iso}.",
                ],
            }
        if age_seconds < 0.0:
            clock_skew_suspected = True
            limitations.append(
                f"Observation timestamp {obs_iso} leads assessment_time {assess_iso} by {-age_seconds:.3f}s "
                f"(within max_clock_skew_seconds={policy.max_clock_skew_seconds:.1f}s)."
            )
        fresh_for_current = age_seconds <= threshold_s
        if not fresh_for_current:
            limitations.append(
                f"Observation age {age_seconds:.1f}s exceeds current-state freshness threshold "
                f"{threshold_s:.1f}s for {tool_name}."
            )

    # Derive primary conceptual diagnostic classification
    normalized_purpose = str(purpose or "incident_window").strip().lower()
    if not in_incident_window:
        classification = "OUTSIDE_INCIDENT_WINDOW"
    elif normalized_purpose in ("current_state", "live_current_state"):
        if fresh_for_current is True:
            classification = (
                "CLOCK_SKEW_SUSPECTED" if clock_skew_suspected else "FRESH_FOR_CURRENT_ASSESSMENT"
            )
        elif fresh_for_current is False:
            classification = "STALE_FOR_CURRENT_ASSESSMENT"
        else:
            classification = "TEMPORAL_VALIDITY_UNKNOWN"
    else:
        if is_static_catalog:
            classification = "TEMPORALLY_RELEVANT"
        elif clock_skew_suspected:
            classification = "CLOCK_SKEW_SUSPECTED"
        elif fresh_for_current is False:
            classification = "HISTORICAL_BUT_RELEVANT"
        elif fresh_for_current is True:
            classification = "TEMPORALLY_RELEVANT"
        else:
            classification = "TEMPORALLY_RELEVANT"

    return {
        "classification": classification,
        "eligible_for_incident_window": bool(in_incident_window),
        "eligible_for_current_state": bool(fresh_for_current is True),
        "fresh_for_current_assessment": bool(fresh_for_current is True),
        "temporally_relevant_to_incident": bool(in_incident_window),
        "clock_skew_suspected": clock_skew_suspected,
        "partial_observation": partial_obs,
        "observation_time": obs_iso,
        "observation_window": obs_window,
        "ingestion_time": rec_ts["ingestion_time"],
        "collection_time": collected_at_raw,
        "assessment_time": assess_iso,
        "age_seconds": age_seconds,
        "freshness_threshold_seconds": threshold_s,
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# Evidence Identity, Canonical Content Hash & Isolation (Work Packages B, F, H)
# ---------------------------------------------------------------------------

def _canonicalize_value(val: Any) -> Any:
    if isinstance(val, float):
        if not math.isfinite(val):
            return str(val)
        return round(val, 6)
    if isinstance(val, Mapping):
        return {str(k): _canonicalize_value(v) for k, v in sorted(val.items(), key=lambda kv: str(kv[0]))}
    if isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    return val


def compute_source_observation_id(
    tool_name: str,
    service_id: str | None,
    record: Mapping[str, Any],
) -> str:
    """Compute deterministic source observation identity from immutable event/sample attributes.

    Distinguishes:
    - Same underlying event collected twice -> identical `obs-...` digest.
    - Distinct legitimate events with identical message text (different timestamp/trace_id/span_id/log_id) -> distinct `obs-...` digest.
    """
    svc = str(record.get("service_id") or record.get("service.name") or record.get("service_name") or service_id or "")
    env = str(record.get("environment") or "")
    if tool_name == "get_service_metrics":
        key_obj: dict[str, Any] = {
            "kind": "metric",
            "service_id": svc,
            "environment": env,
            "metric": str(record.get("metric_enum") or record.get("metric_name") or ""),
            "sample_at": str(record.get("sample_at") or record.get("timestamp") or ""),
            "aggregation": str(record.get("aggregation") or ""),
            "unit": str(record.get("unit") or ""),
            "value": _canonicalize_value(record.get("value")),
        }
    elif tool_name == "get_trace_summary":
        key_obj = {
            "kind": "span",
            "service_id": svc,
            "environment": env,
            "trace_id": str(record.get("trace_id") or ""),
            "span_id": str(record.get("span_id") or ""),
            "start_time": str(record.get("start_time") or ""),
            "status_code": str(record.get("status_code") or record.get("status") or ""),
            "duration_ms": _canonicalize_value(record.get("duration_ms")),
        }
    elif tool_name == "get_service_dependencies":
        key_obj = {
            "kind": "dependency_edge",
            "edge_id": str(record.get("edge_id") or ""),
            "source": str(record.get("source") or record.get("from_service_id") or ""),
            "target": str(record.get("target") or record.get("to_service_id") or ""),
            "relation_type": str(record.get("relation_type") or ""),
        }
    else:
        key_obj = {
            "kind": "log",
            "service_id": svc,
            "environment": env,
            "event_id": str(record.get("log_id") or record.get("event_id") or ""),
            "timestamp": str(record.get("timestamp") or record.get("event_time") or ""),
            "trace_id": str(record.get("trace_id") or ""),
            "span_id": str(record.get("span_id") or ""),
            "correlation_id": str(record.get("correlation_id") or ""),
            "status_code": str(record.get("status_code") or ""),
            "error_code": str(record.get("error_code") or ""),
            "message": " ".join(str(record.get("message") or "").split()),
        }
    canonical = json.dumps(key_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "obs-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def compute_evidence_content_hash(ev: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 content consistency digest over normalized immutable observation fields.

    Excludes volatile presentation/collection timestamps (`collected_at`, `summary`, `temporal_evaluation`)
    so the digest verifies payload consistency across pipeline stages without overclaiming source authenticity.
    """
    records = ev.get("records") if isinstance(ev.get("records"), list) else []
    qw = ev.get("query_window") if isinstance(ev.get("query_window"), Mapping) else {}
    canonical_payload = {
        "schema": "evidence-content-fingerprint.v1",
        "evidence_id": str(ev.get("evidence_id") or ""),
        "tool_name": str(ev.get("tool_name") or ""),
        "service_id": str(ev.get("service_id") or ""),
        "environment": str(ev.get("environment") or ""),
        "source_ref": str(ev.get("source_ref") or ""),
        "query_window": {
            "start": str(qw.get("start") or ""),
            "end": str(qw.get("end") or ""),
        } if qw else None,
        "data_quality": str(ev.get("data_quality") or "complete"),
        "truncated": bool(ev.get("truncated", False)),
        "error_code": ev.get("error_code"),
        "records": _canonicalize_value(records),
    }
    encoded = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_VALID_EVIDENCE_ID_RE = re.compile(r"^ev-[a-zA-Z0-9._:-]{2,124}$")


def verify_evidence_integrity_and_scope(
    ev: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministically verify evidence identity, content hash consistency, incident isolation, and env scope."""
    ev_id = ev.get("evidence_id")
    if not isinstance(ev_id, str) or not _VALID_EVIDENCE_ID_RE.match(ev_id):
        return {
            "ok": False,
            "code": "INVALID_EVIDENCE_ID",
            "detail": f"Malformed or missing evidence_id: {ev_id!r}",
        }

    # 1. Detect duplicate evidence_id collision with conflicting payload inside context
    all_items = context.get("evidence_items") if isinstance(context.get("evidence_items"), list) else []
    computed_hash = compute_evidence_content_hash(ev)
    matching_id_items = [
        item for item in all_items if isinstance(item, Mapping) and item.get("evidence_id") == ev_id
    ]
    if len(matching_id_items) > 1:
        distinct_hashes = {compute_evidence_content_hash(item) for item in matching_id_items}
        if len(distinct_hashes) > 1:
            return {
                "ok": False,
                "code": "DUPLICATE_EVIDENCE_ID_CONFLICT",
                "detail": (
                    f"Evidence ID {ev_id!r} collides across {len(matching_id_items)} items "
                    "with incompatible content payloads."
                ),
            }

    # 2. Verify captured content_hash consistency if recorded on the item
    expected_hash = ev.get("content_hash")
    if isinstance(expected_hash, str) and expected_hash:
        if expected_hash != computed_hash:
            return {
                "ok": False,
                "code": "CONTENT_INTEGRITY_MISMATCH",
                "detail": (
                    f"Evidence {ev_id} payload does not match its captured content_hash "
                    f"(expected {expected_hash[:12]}..., actual {computed_hash[:12]}...)."
                ),
            }

    # 3. Verify environment isolation (evidence envelope + records)
    ctx_env = str(context.get("environment") or "").strip()
    ev_env = str(ev.get("environment") or "").strip()
    if ctx_env and ev_env and ev_env != ctx_env:
        return {
            "ok": False,
            "code": "ENVIRONMENT_MISMATCH",
            "detail": (
                f"Evidence {ev_id} originates from environment {ev_env!r}, "
                f"incompatible with incident environment {ctx_env!r}."
            ),
        }
    records = ev.get("records") if isinstance(ev.get("records"), list) else []
    for rec in records:
        if isinstance(rec, Mapping):
            rec_env = str(rec.get("environment") or "").strip()
            if ctx_env and rec_env and rec_env != ctx_env:
                return {
                    "ok": False,
                    "code": "ENVIRONMENT_MISMATCH",
                    "detail": (
                        f"Evidence {ev_id} contains record from environment {rec_env!r}, "
                        f"incompatible with incident environment {ctx_env!r}."
                    ),
                }

    # 4. Verify service scope authorization if investigation_scope is explicitly defined
    allowed_scope_raw = context.get("investigation_scope")
    ev_svc = str(ev.get("service_id") or "").strip()
    if isinstance(allowed_scope_raw, (list, set, tuple)) and allowed_scope_raw and ev_svc:
        allowed_scope = {str(s) for s in allowed_scope_raw if s}
        if ev_svc not in allowed_scope:
            return {
                "ok": False,
                "code": "UNAUTHORIZED_SERVICE_SCOPE",
                "detail": (
                    f"Evidence {ev_id} service {ev_svc!r} is outside authorized "
                    f"investigation_scope {sorted(allowed_scope)}."
                ),
            }

    # 5. Verify incident isolation vs justified shared correlated evidence
    ctx_inc_id = str(context.get("incident_id") or "").strip()
    ev_inc_id = str(ev.get("incident_id") or "").strip()
    if ctx_inc_id and ev_inc_id and ev_inc_id != ctx_inc_id:
        shared = ev.get("shared_evidence_justification")
        correlated_ids = {
            str(cid)
            for cid in (context.get("correlated_incident_ids") or [])
            if cid
        }
        # Shared observation requires explicit justification + authorized scope + window overlap
        authorized_share = False
        if isinstance(shared, Mapping):
            authorized_for = {
                str(cid) for cid in (shared.get("authorized_incident_ids") or []) if cid
            }
            has_reason = bool(str(shared.get("reason") or "").strip())
            scope_ok = bool(shared.get("authorized", True))
            if (ctx_inc_id in authorized_for or ev_inc_id in correlated_ids) and has_reason and scope_ok:
                # Must ALSO be in service/dependency scope and overlapping incident window
                temp_check = evaluate_evidence_temporal_validity(
                    ev,
                    incident_window=context.get("query_window"),
                    assessment_time=context.get("assessment_time"),
                    purpose="incident_window",
                )
                svc_ok = True
                if isinstance(allowed_scope_raw, (list, set, tuple)) and allowed_scope_raw and ev_svc:
                    svc_ok = ev_svc in {str(s) for s in allowed_scope_raw}
                elif context.get("service_id") and ev_svc:
                    svc_ok = ev_svc == str(context.get("service_id"))
                if temp_check["eligible_for_incident_window"] and svc_ok:
                    authorized_share = True

        if not authorized_share:
            return {
                "ok": False,
                "code": "CROSS_INCIDENT_EVIDENCE",
                "detail": (
                    f"Evidence {ev_id} is bound to unrelated incident {ev_inc_id!r} "
                    f"without valid shared-observation justification for {ctx_inc_id!r}."
                ),
            }

    return {
        "ok": True,
        "code": "OK",
        "content_hash": computed_hash,
        "integrity_semantics": INTEGRITY_SEMANTICS_NOTE,
    }


# ---------------------------------------------------------------------------
# Cross-Signal Correlation Metadata (Work Package G)
# ---------------------------------------------------------------------------

def correlate_incident_signals(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    impact_graph: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate defensible cross-signal relationships without conflating coincidence with causality."""
    relationships: list[dict[str, Any]] = []
    trace_to_evidence: dict[str, list[tuple[str, str, str]]] = {}
    service_window_items: list[tuple[str, str, str]] = []

    declared_pairs: set[tuple[str, str]] = set()
    if isinstance(impact_graph, Mapping):
        for edge in impact_graph.get("edges") or []:
            if isinstance(edge, Mapping):
                src = str(edge.get("from_service_id") or edge.get("source") or "")
                dst = str(edge.get("to_service_id") or edge.get("target") or "")
                if src and dst:
                    declared_pairs.add((src, dst))

    for ev in evidence_items:
        if not isinstance(ev, Mapping):
            continue
        ev_id = str(ev.get("evidence_id") or "")
        tool = str(ev.get("tool_name") or "")
        svc = str(ev.get("service_id") or "")
        records = ev.get("records") if isinstance(ev.get("records"), list) else []
        if not ev_id or ev.get("error_code") or not records:
            continue

        if tool in ("get_service_metrics", "search_error_logs", "get_trace_summary"):
            service_window_items.append((ev_id, tool, svc))

        for rec in records:
            if not isinstance(rec, Mapping):
                continue
            tid = str(rec.get("trace_id") or "").strip().lower()
            if tid and tid != "0" * 32:
                bucket = trace_to_evidence.setdefault(tid, [])
                entry = (ev_id, tool, str(rec.get("service_id") or rec.get("service_name") or svc))
                if entry not in bucket:
                    bucket.append(entry)

    # 1. Direct shared trace_id correlation (same distributed request, NOT independent requests!)
    for tid, entries in sorted(trace_to_evidence.items()):
        distinct_ev_ids = sorted({e[0] for e in entries})
        distinct_tools = sorted({e[1] for e in entries})
        if len(distinct_ev_ids) >= 2:
            relationships.append({
                "relation_type": "DIRECT_TRACE_CORRELATED",
                "trace_id": tid,
                "evidence_ids": distinct_ev_ids,
                "tools": distinct_tools,
                "services": sorted({e[2] for e in entries if e[2]}),
                "independent_events": False,
                "causality_established": False,
                "note": (
                    f"Signals share trace_id={tid} (same request execution path; "
                    "mutually corroborating across signal types, not independent request samples)."
                ),
            })

    # 2. Same-service metric + log temporal association (without shared trace_id)
    by_svc: dict[str, list[tuple[str, str]]] = {}
    for ev_id, tool, svc in service_window_items:
        if svc:
            by_svc.setdefault(svc, []).append((ev_id, tool))
    for svc, items in sorted(by_svc.items()):
        metric_ids = sorted({eid for eid, t in items if t == "get_service_metrics"})
        log_ids = sorted({eid for eid, t in items if t == "search_error_logs"})
        if metric_ids and log_ids:
            relationships.append({
                "relation_type": "TEMPORALLY_ASSOCIATED_SAME_SERVICE",
                "service_id": svc,
                "evidence_ids": [*metric_ids, *log_ids],
                "independent_events": False,
                "causality_established": False,
                "note": (
                    f"Metrics {metric_ids} and logs {log_ids} co-occur on {svc} within the query window; "
                    "temporal co-occurrence supports service impact but does not alone prove root cause."
                ),
            })

    # 3. Directed dependency candidate association
    for src, dst in sorted(declared_pairs):
        if src in by_svc and dst in by_svc:
            src_ids = sorted({eid for eid, _ in by_svc[src]})
            dst_ids = sorted({eid for eid, _ in by_svc[dst]})
            relationships.append({
                "relation_type": "DEPENDENCY_CANDIDATE_ASSOCIATION",
                "from_service_id": src,
                "to_service_id": dst,
                "evidence_ids": [*src_ids, *dst_ids],
                "independent_events": False,
                "causality_established": False,
                "note": (
                    f"Declared dependency {src} -> {dst} has co-occurring observations; "
                    "topology indicates propagation candidacy only, not proven causation."
                ),
            })

    return relationships


# ---------------------------------------------------------------------------
# Scoped Telemetry Cache Guard (Work Package F4, F5)
# ---------------------------------------------------------------------------

class ScopedTelemetryCache:
    """Bounded, authorization- and scope-isolated telemetry response cache.

    Invariants enforced:
    1. Keys bind principal_id, allowed_groups, environment, service_id, tool_name,
       canonical query arguments, and exact query window.
    2. Cache creation timestamp (`cached_at`) never overwrites `observed_at`.
    3. Entries expire deterministically against explicit `assessment_time` (or caller reference clock)
       using source-specific freshness thresholds.
    4. Partial or error responses are never cached as complete hits.
    5. Backend unavailability (`SOURCE_UNAVAILABLE`) is NEVER hidden behind stale cached data.
    """

    def __init__(
        self,
        *,
        policy: EvidenceTemporalPolicy = DEFAULT_TEMPORAL_POLICY,
        max_entries: int = 128,
    ) -> None:
        self.policy = policy
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[str, dict[str, Any]] = {}

    @staticmethod
    def build_key(
        *,
        principal_id: str,
        allowed_groups: Sequence[str],
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> str:
        safe_args = {
            str(k): _canonicalize_value(v)
            for k, v in sorted(arguments.items(), key=lambda kv: str(kv[0]))
        }
        key_payload = {
            "principal_id": str(principal_id),
            "allowed_groups": sorted(str(g) for g in allowed_groups),
            "tool_name": str(tool_name),
            "service_id": str(arguments.get("service_id") or ""),
            "environment": str(arguments.get("environment") or ""),
            "start": str(arguments.get("start") or arguments.get("reference_time") or ""),
            "end": str(arguments.get("end") or arguments.get("reference_time") or ""),
            "arguments": safe_args,
        }
        raw = json.dumps(key_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "tcache-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def put(
        self,
        *,
        principal_id: str,
        allowed_groups: Sequence[str],
        tool_name: str,
        arguments: Mapping[str, Any],
        envelope: Mapping[str, Any],
        cached_at: str,
    ) -> str | None:
        """Store a successful, complete, sanitized response without mutating its observation timestamp."""
        if (
            envelope.get("status") != "ok"
            or envelope.get("error_code") is not None
            or envelope.get("data_quality") != "complete"
            or bool(envelope.get("truncated", False))
        ):
            return None

        cache_norm = normalize_timestamp(cached_at)
        if not cache_norm.ok or not cache_norm.utc_iso:
            return None

        key = self.build_key(
            principal_id=principal_id,
            allowed_groups=allowed_groups,
            tool_name=tool_name,
            arguments=arguments,
        )
        if len(self._entries) >= self.max_entries and key not in self._entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key, None)

        stored_envelope = copy.deepcopy(dict(envelope))
        self._entries[key] = {
            "cache_key": key,
            "cached_at": cache_norm.utc_iso,
            "source_observed_at": stored_envelope.get("observed_at"),
            "tool_name": tool_name,
            "envelope": stored_envelope,
        }
        return key

    def get(
        self,
        *,
        principal_id: str,
        allowed_groups: Sequence[str],
        tool_name: str,
        arguments: Mapping[str, Any],
        assessment_time: str,
    ) -> dict[str, Any]:
        """Inspect cache against explicit assessment_time; distinguish FRESH_HIT vs STALE_ENTRY vs MISS."""
        key = self.build_key(
            principal_id=principal_id,
            allowed_groups=allowed_groups,
            tool_name=tool_name,
            arguments=arguments,
        )
        entry = self._entries.get(key)
        if entry is None:
            return {"hit": False, "status": "CACHE_MISS", "cache_key": key, "envelope": None}

        assess_norm = normalize_timestamp(assessment_time)
        obs_norm = normalize_timestamp(entry.get("source_observed_at"))
        cached_norm = normalize_timestamp(entry.get("cached_at"))
        threshold_s = self.policy.freshness_threshold_for(tool_name)

        if not (assess_norm.ok and assess_norm.dt and obs_norm.ok and obs_norm.dt and cached_norm.ok and cached_norm.dt):
            return {
                "hit": False,
                "status": "CACHE_TEMPORAL_INVALID",
                "cache_key": key,
                "envelope": None,
            }

        # Critically: freshness is evaluated against SOURCE OBSERVATION TIME, NEVER cache creation time!
        obs_age = (assess_norm.dt - obs_norm.dt).total_seconds()
        cache_age = (assess_norm.dt - cached_norm.dt).total_seconds()
        if obs_age > threshold_s or cache_age > threshold_s or obs_age < -self.policy.max_clock_skew_seconds:
            return {
                "hit": False,
                "status": "CACHE_STALE",
                "cache_key": key,
                "cached_at": entry["cached_at"],
                "source_observed_at": entry["source_observed_at"],
                "observation_age_seconds": round(obs_age, 3),
                "freshness_threshold_seconds": threshold_s,
                "stale_envelope": copy.deepcopy(entry["envelope"]),
                "envelope": None,
            }

        return {
            "hit": True,
            "status": "CACHE_FRESH_HIT",
            "cache_key": key,
            "cached_at": entry["cached_at"],
            "source_observed_at": entry["source_observed_at"],
            "observation_age_seconds": round(obs_age, 3),
            "envelope": copy.deepcopy(entry["envelope"]),
        }

    def invalidate_service(self, service_id: str, environment: str | None = None) -> int:
        removed = 0
        for key in list(self._entries.keys()):
            recs = self._entries[key]["envelope"].get("records") or []
            matched = any(
                isinstance(r, Mapping)
                and (r.get("service_id") == service_id or r.get("service_name") == service_id)
                and (environment is None or not r.get("environment") or r.get("environment") == environment)
                for r in recs
            )
            if matched:
                self._entries.pop(key, None)
                removed += 1
        return removed
