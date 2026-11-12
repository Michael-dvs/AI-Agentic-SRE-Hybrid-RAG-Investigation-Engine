"""Read-only Metrics Adapter querying Prometheus HTTP API (C09, MCP-01, MCP-02, ADR-S05)."""

from __future__ import annotations

import datetime
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
from services.common.telemetry import utc_now_iso

# Allowlisted metric names and RED aliases (ADR-S02, C05)
ALLOWED_METRIC_NAMES = {
    # RED signals
    "request_rate",
    "error_rate",
    "latency_p95",
    "sim_red_request_rate_rps",
    "sim_red_error_rate_ratio",
    "sim_red_latency_p95_ms",
    # System and runtime telemetry
    "http_requests_total",
    "http_request_duration_seconds_bucket",
    "http_request_duration_seconds_count",
    "process_cpu_seconds_total",
    "process_resident_memory_bytes",
}

# Metric mapping to simulation Prometheus query names
METRIC_QUERY_MAP = {
    "request_rate": "sim_red_request_rate_rps",
    "error_rate": "sim_red_error_rate_ratio",
    "latency_p95": "sim_red_latency_p95_ms",
}

# Known services from Service Catalog (C05)
KNOWN_SERVICES = {
    "api-gateway",
    "auth-service",
    "transaction-service",
    "ledger-service",
    "notification-service",
    "db-dummy",
}


class MetricsAdapter(BaseTelemetryAdapter):
    """Read-only telemetry adapter for Prometheus metrics API."""

    tool_name = "get_service_metrics"
    default_source_ref = "prometheus:http://localhost:9090"
    max_points = 1000

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: Any = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
        max_points: int = 1000,
    ) -> None:
        super().__init__(
            base_url=base_url or "http://localhost:9090",
            client=client,
            sanitizer=sanitizer,
            max_window_seconds=max_window_seconds,
            timeout_seconds=timeout_seconds,
        )
        self.max_points = max_points

    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute parameterized read-only metrics query against Prometheus."""
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
        metric_name = arguments.get("metric_name") or arguments.get("metric_enum")
        start = arguments.get("start") or arguments.get("start_time")
        end = arguments.get("end") or arguments.get("end_time")
        step = str(arguments.get("step") or "15s")
        req_max_points = arguments.get("max_points", self.max_points)

        # Step C: Validate Service ID
        if not service_id or service_id not in KNOWN_SERVICES:
            return self._error_envelope(
                error_code="SERVICE_NOT_FOUND",
                message=f"Service {service_id!r} is not registered in catalog",
                status="rejected",
            )

        # Step D: Validate Metric Name allowlist
        if not metric_name or metric_name not in ALLOWED_METRIC_NAMES:
            return self._error_envelope(
                error_code="TOOL_NOT_ALLOWED",
                message=f"Metric {metric_name!r} not in allowlist",
                status="rejected",
            )

        # Step E: Validate Time Window (MCP-02: strict rejection, no silent clamping)
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

        # Step F: Translate to Prometheus query
        promql_query = METRIC_QUERY_MAP.get(metric_name, metric_name)
        params = {
            "query": f"{promql_query}{{service_id=\"{service_id}\"}}",
            "service_id": service_id,
            "start": dt_start.timestamp(),
            "end": dt_end.timestamp(),
            "step": float(step.rstrip("s")) if step.rstrip("s").replace(".", "", 1).isdigit() else 15.0,
        }

        # Step G: Query Prometheus HTTP API with 5.0s timeout
        url = f"{self.base_url}/api/v1/query_range"
        records: list[dict[str, Any]] = []

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
            # Handle Prometheus matrix result
            data_field = body.get("data", {})
            if isinstance(data_field, dict) and data_field.get("resultType") == "matrix":
                results = data_field.get("result", [])
                for series in results:
                    meta = series.get("metric", {})
                    for val_pair in series.get("values", []):
                        if len(val_pair) >= 2:
                            ts_epoch = float(val_pair[0])
                            ts_iso = datetime.datetime.fromtimestamp(
                                ts_epoch, datetime.timezone.utc
                            ).isoformat().replace("+00:00", "Z")
                            val_num = float(val_pair[1]) if val_pair[1] is not None else 0.0
                            records.append({
                                "timestamp": ts_iso,
                                "service_id": meta.get("service_id", service_id),
                                "metric_name": metric_name,
                                "value": val_num,
                                "unit": "ratio" if "rate" in metric_name else "ms",
                            })
            elif "records" in body and isinstance(body["records"], list):
                records = body["records"]
            elif "metrics" in body and isinstance(body["metrics"], list):
                records = body["metrics"]

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

        # Step H: Truncate to max_points (ADR-S05 cap: 1000)
        point_limit = min(req_max_points, self.max_points)
        truncated = False
        if len(records) > point_limit:
            records = records[:point_limit]
            truncated = True

        # Step I: Pre-sink SEC-03 Sanitization
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
