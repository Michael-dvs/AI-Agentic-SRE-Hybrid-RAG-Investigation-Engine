"""Read-only Error Logs Adapter querying Loki HTTP API (C09, SEC-03, MCP-01, MCP-02, ADR-S05)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from gateway.adapters.base import (
    BaseTelemetryAdapter,
    ForbiddenScopeError,
    InvalidTimeRangeError,
    LimitExceededError,
    SchemaInvalidError,
    ServiceNotFoundError,
    SourceUnavailableError,
    TelemetryResponseEnvelope,
    ToolNotAllowedError,
    WindowExceededError,
    check_ground_truth_isolation,
    check_mutation_attempt,
    validate_time_window,
)
from gateway.adapters.metrics import KNOWN_SERVICES
from services.common.telemetry import utc_now_iso

# Allowed severities (RFC 5424 subset)
ALLOWED_SEVERITIES = {"ERROR", "WARN", "FATAL", "CRITICAL"}

# Characters indicating arbitrary LogQL injection attempts
_LOGQL_INJECTION_CHARS = re.compile(r"[{}=~|]|\b(json|logfmt|regexp|unpack)\b", flags=re.IGNORECASE)


class LogsAdapter(BaseTelemetryAdapter):
    """Read-only telemetry adapter for Loki structured log API."""

    tool_name = "search_error_logs"
    default_source_ref = "loki:http://localhost:3100"
    max_hits_cap = 500

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: Any = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
        max_hits_cap: int = 500,
    ) -> None:
        super().__init__(
            base_url=base_url or "http://localhost:3100",
            client=client,
            sanitizer=sanitizer,
            max_window_seconds=max_window_seconds,
            timeout_seconds=timeout_seconds,
        )
        self.max_hits_cap = max_hits_cap

    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute strictly parameterized read-only log search."""
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
        service_id = arguments.get("service_id")
        start = arguments.get("start") or arguments.get("start_time")
        end = arguments.get("end") or arguments.get("end_time")
        severity = arguments.get("severity", "ERROR")
        search_query = arguments.get("search_query")
        error_code = arguments.get("error_code")
        req_max_hits = arguments.get("max_hits", self.max_hits_cap)

        # Step C: Validate Service ID
        if not service_id or service_id not in KNOWN_SERVICES:
            return self._error_envelope(
                error_code="SERVICE_NOT_FOUND",
                message=f"Service {service_id!r} is not registered in catalog",
                status="rejected",
            )

        # Step D: Validate Severity Allowlist
        if severity and severity.upper() not in ALLOWED_SEVERITIES:
            return self._error_envelope(
                error_code="SCHEMA_INVALID",
                message=f"Severity {severity!r} not in allowed set {ALLOWED_SEVERITIES}",
                status="rejected",
            )

        # Step E: Enforce Literal-Only Search Query (No LogQL Injections)
        if search_query:
            if _LOGQL_INJECTION_CHARS.search(search_query):
                return self._error_envelope(
                    error_code="SCHEMA_INVALID",
                    message="Arbitrary LogQL syntax is prohibited; search_query must be a plain literal",
                    status="rejected",
                )

        # Step F: Validate Time Window (MCP-02: strict rejection, no silent clamping)
        if not start or not end:
            return self._error_envelope(
                error_code="SCHEMA_INVALID",
                message="Missing required start or end timestamp",
                status="rejected",
            )

        try:
            dt_start, dt_end, duration = validate_time_window(
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
            "start": start,
            "end": end,
            "duration_seconds": duration,
        }

        # Step G: Prepare Query Parameters for Loki API
        target_limit = min(int(req_max_hits or self.max_hits_cap), self.max_hits_cap)
        # Fetch slightly more than target_limit to verify if backend has more hits
        fetch_limit = min(target_limit + 100, 2000)

        params: dict[str, Any] = {
            "service_id": service_id,
            "severity": severity.upper() if severity else "ERROR",
            "limit": fetch_limit,
        }
        if error_code:
            params["error_code"] = error_code
        if search_query:
            params["query"] = search_query

        # Step H: Call Loki HTTP API with 5.0s timeout
        url = f"{self.base_url}/loki/api/v1/query_range"
        raw_records: list[dict[str, Any]] = []

        try:
            if self.client is not None:
                if self.client.__class__.__name__ == "TestClient":
                    resp = self.client.get(url, params=params)
                else:
                    resp = self.client.get(url, params=params, timeout=self.timeout_seconds)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.get(url, params=params)

            if resp.status_code != 200:
                return self._error_envelope(
                    error_code="SOURCE_UNAVAILABLE",
                    status="unavailable",
                    data_quality="unavailable",
                    query_window=query_window,
                )

            body = resp.json()
            if "records" in body and isinstance(body["records"], list):
                raw_records = body["records"]
            elif "data" in body and isinstance(body["data"], dict):
                streams = body["data"].get("result", [])
                for st in streams:
                    for val_pair in st.get("values", []):
                        if len(val_pair) >= 2:
                            try:
                                parsed = json.loads(val_pair[1])
                                if isinstance(parsed, dict):
                                    raw_records.append(parsed)
                            except Exception:
                                pass

        except (httpx.TimeoutException, TimeoutError):
            return self._error_envelope(
                error_code="SOURCE_UNAVAILABLE",
                status="unavailable",
                data_quality="unavailable",
                query_window=query_window,
            )
        except (httpx.ConnectError, httpx.NetworkError, httpx.HTTPError, Exception):
            return self._error_envelope(
                error_code="SOURCE_UNAVAILABLE",
                status="unavailable",
                data_quality="unavailable",
                query_window=query_window,
            )

        # Step I: Truncate to max_hits (ADR-S05 cap: 500)
        truncated = False
        if len(raw_records) > target_limit:
            records = raw_records[:target_limit]
            truncated = True
        else:
            records = raw_records

        # Step J: Pre-sink SEC-03 Redaction (Mask synthetic JWT, PAN, credentials)
        sanitized_records, _ = self.sanitizer.sanitize_object(records)

        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self._get_source_ref(),
            observed_at=now_z,
            query_window=query_window,
            data_quality="complete",
            truncated=truncated,
            sanitized=True,
            error_code=None,
            data=sanitized_records,
            status="ok",
        )
