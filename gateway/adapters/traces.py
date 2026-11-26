"""Read-only Distributed Traces Adapter querying Tempo HTTP API (C09, SC-09, EV-02, SEC-03, MCP-01, MCP-02)."""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from gateway.adapters.base import (
    BaseTelemetryAdapter,
    ForbiddenScopeError,
    InvalidTimeRangeError,
    SchemaInvalidError,
    SourceUnavailableError,
    TelemetryResponseEnvelope,
    ToolNotAllowedError,
    WindowExceededError,
    check_ground_truth_isolation,
    check_mutation_attempt,
    validate_time_window,
)
from services.common.telemetry import utc_now_iso

# Strict 32-character hexadecimal format for trace_id (excluding all-zero)
_TRACE_ID_PATTERN = re.compile(r"^(?!0{32}$)[0-9a-fA-F]{32}$")


class TracesAdapter(BaseTelemetryAdapter):
    """Read-only telemetry adapter for Tempo distributed trace API."""

    tool_name = "get_trace_summary"
    default_source_ref = "tempo:http://localhost:3200"

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: Any = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            base_url=base_url or "http://localhost:3200",
            client=client,
            sanitizer=sanitizer,
            max_window_seconds=max_window_seconds,
            timeout_seconds=timeout_seconds,
        )

    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute parameterized read-only trace query against Tempo."""
        now_z = utc_now_iso()

        # Step A: Mutation & Ground Truth check (MCP-01, AT-005, AT-008)
        try:
            check_mutation_attempt(arguments)
            check_ground_truth_isolation(arguments)
        except ToolNotAllowedError:
            return self._error_envelope(
                error_code="TOOL_NOT_ALLOWED",
                message="Mutation actions are prohibited",
                status="rejected",
            )
        except ForbiddenScopeError:
            return self._error_envelope(
                error_code="FORBIDDEN_SCOPE",
                message="Access to ground truth is forbidden",
                status="rejected",
            )

        # Step B: Parameter extraction
        trace_id = str(arguments.get("trace_id") or "").strip()
        service_id = arguments.get("service_id")
        start = arguments.get("start") or arguments.get("start_time")
        end = arguments.get("end") or arguments.get("end_time")

        # Step C: Validate Trace ID format (wajib 32-karakter hex)
        if not trace_id or not _TRACE_ID_PATTERN.match(trace_id):
            return self._error_envelope(
                error_code="SCHEMA_INVALID",
                message=f"Trace ID must be a non-zero 32-character hex string: {trace_id!r}",
                status="rejected",
            )

        # Step D: Optional Time Window Validation
        duration = 0.0
        if start and end:
            try:
                _, _, duration = validate_time_window(
                    start, end, max_window_seconds=self.max_window_seconds
                )
            except WindowExceededError:
                return self._error_envelope(
                    error_code="WINDOW_EXCEEDED",
                    message=f"Window exceeds maximum {self.max_window_seconds}s",
                    status="rejected",
                    query_window={"start": start, "end": end, "duration_seconds": 0.0},
                )
            except InvalidTimeRangeError:
                return self._error_envelope(
                    error_code="INVALID_TIME_RANGE",
                    message="Start must be before end",
                    status="rejected",
                    query_window={"start": start, "end": end, "duration_seconds": 0.0},
                )
            except SchemaInvalidError as e:
                return self._error_envelope(
                    error_code="SCHEMA_INVALID",
                    message=str(e),
                    status="rejected",
                )

        query_window = {
            "start": start or now_z,
            "end": end or now_z,
            "duration_seconds": duration,
        }

        # Step E: Query Tempo API with 5.0s timeout
        url = f"{self.base_url}/api/traces/{trace_id}"
        raw_spans: list[dict[str, Any]] = []

        try:
            if self.client is not None:
                if self.client.__class__.__name__ == "TestClient":
                    resp = self.client.get(url)
                else:
                    resp = self.client.get(url, timeout=self.timeout_seconds)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.get(url)

            # SC-09 / EV-02: Backend outage check (503 Service Unavailable)
            if resp.status_code == 503:
                return TelemetryResponseEnvelope(
                    tool_name=self.tool_name,
                    source_ref=self._get_source_ref(),
                    observed_at=now_z,
                    query_window=query_window,
                    data_quality="unavailable",
                    truncated=False,
                    sanitized=True,
                    error_code="SOURCE_UNAVAILABLE",
                    data=None,  # DILARANG MEREKAYASA SPAN KOSONG ATAU DURASI 0
                    status="unavailable",
                )

            if resp.status_code == 404:
                # Trace legitimately not found
                return TelemetryResponseEnvelope(
                    tool_name=self.tool_name,
                    source_ref=self._get_source_ref(),
                    observed_at=now_z,
                    query_window=query_window,
                    data_quality="complete",
                    truncated=False,
                    sanitized=True,
                    error_code=None,
                    data=[],
                    status="ok",
                )

            if resp.status_code != 200:
                return self._error_envelope(
                    error_code="SOURCE_UNAVAILABLE",
                    status="unavailable",
                    data_quality="unavailable",
                    query_window=query_window,
                )

            body = resp.json()
            raw_spans = body.get("spans", [])

        except (httpx.TimeoutException, TimeoutError):
            # SC-09 / EV-02 Honest Source Unavailable
            return TelemetryResponseEnvelope(
                tool_name=self.tool_name,
                source_ref=self._get_source_ref(),
                observed_at=now_z,
                query_window=query_window,
                data_quality="unavailable",
                truncated=False,
                sanitized=True,
                error_code="SOURCE_UNAVAILABLE",
                data=None,
                status="unavailable",
            )
        except (httpx.ConnectError, httpx.NetworkError, httpx.HTTPError, Exception):
            return TelemetryResponseEnvelope(
                tool_name=self.tool_name,
                source_ref=self._get_source_ref(),
                observed_at=now_z,
                query_window=query_window,
                data_quality="unavailable",
                truncated=False,
                sanitized=True,
                error_code="SOURCE_UNAVAILABLE",
                data=None,
                status="unavailable",
            )

        # Step F: Check trace completeness prior to service_id projection, then filter scope (P1-05)
        from orchestrator.evidence_lineage import DEFAULT_TEMPORAL_POLICY, normalize_timestamp
        import datetime

        all_span_ids = {
            str(s.get("span_id"))
            for s in raw_spans
            if isinstance(s, dict) and s.get("span_id")
        }
        missing_parent_span = any(
            isinstance(s, dict)
            and s.get("parent_span_id")
            and str(s.get("parent_span_id")) not in all_span_ids
            for s in raw_spans
        )
        backend_partial = bool(body.get("partial") or body.get("truncated")) if isinstance(body, dict) else False

        req_env = str(arguments.get("environment") or "").strip()
        if req_env:
            raw_spans = [
                s for s in raw_spans
                if isinstance(s, dict)
                and (not s.get("environment") or str(s.get("environment")).strip() == req_env)
            ]

        if start and end:
            dt_start, dt_end, _ = validate_time_window(
                start, end, max_window_seconds=self.max_window_seconds
            )
            skew_td = datetime.timedelta(seconds=DEFAULT_TEMPORAL_POLICY.max_clock_skew_seconds)
            windowed_spans: list[dict[str, Any]] = []
            for s in raw_spans:
                if not isinstance(s, dict):
                    continue
                st_raw = s.get("start_time")
                et_raw = s.get("end_time") or st_raw
                if st_raw is not None:
                    st_norm = normalize_timestamp(st_raw)
                    et_norm = normalize_timestamp(et_raw) if et_raw is not None else st_norm
                    if not st_norm.ok or st_norm.dt is None or not et_norm.ok or et_norm.dt is None:
                        continue
                    if et_norm.dt < (dt_start - skew_td) or st_norm.dt > (dt_end + skew_td):
                        continue
                windowed_spans.append(s)
            raw_spans = windowed_spans

        if service_id:
            raw_spans = [
                s for s in raw_spans
                if s.get("service_id") == service_id or s.get("service.name") == service_id
            ]

        # Step G: Summarize span details while preserving trace_id, timing, service_id, and environment
        summarized_spans: list[dict[str, Any]] = []
        observed_candidates: list[str] = []
        for s in raw_spans:
            status_code = s.get("status_code", "OK")
            duration_val = float(s.get("duration_ms", 0.0))
            svc_id_val = s.get("service_id") or s.get("service.name") or ""
            span_entry: dict[str, Any] = {
                "trace_id": str(s.get("trace_id") or trace_id),
                "span_id": str(s.get("span_id", "")),
                "parent_span_id": s.get("parent_span_id"),
                "service_id": svc_id_val,
                "service_name": s.get("service.name") or svc_id_val,
                "operation": s.get("operation") or s.get("operation_name", "UNKNOWN"),
                "duration_ms": duration_val,
                "status_code": status_code,
                "error": s.get("error", status_code == "ERROR"),
                "attributes": s.get("attributes", {}),
            }
            if s.get("environment"):
                span_entry["environment"] = s["environment"]
            for t_key in ("start_time", "end_time"):
                if s.get(t_key) is not None:
                    t_norm = normalize_timestamp(s.get(t_key))
                    if t_norm.ok and t_norm.utc_iso:
                        span_entry[t_key] = t_norm.utc_iso
                        observed_candidates.append(t_norm.utc_iso)
                    else:
                        span_entry[t_key] = s.get(t_key)
            if missing_parent_span or backend_partial:
                span_entry["partial_trace"] = True
            summarized_spans.append(span_entry)

        # Step H: Pre-sink SEC-03 Sanitization on span attributes
        sanitized_spans, _ = self.sanitizer.sanitize_object(summarized_spans)
        is_partial = bool((missing_parent_span or backend_partial) and sanitized_spans)
        observed_at_z = max(observed_candidates) if observed_candidates else now_z

        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self._get_source_ref(),
            observed_at=observed_at_z,
            query_window=query_window,
            data_quality="partial" if is_partial else "complete",
            truncated=bool(body.get("truncated", False)) if isinstance(body, dict) else False,
            sanitized=True,
            error_code=None,
            data=sanitized_spans,
            status="ok",
            collected_at=now_z,
            sampling={
                "applied": is_partial,
                "method": "span_cap" if is_partial else None,
                "returned_count": len(sanitized_spans),
                "source_count": len(sanitized_spans),
            },
        )
