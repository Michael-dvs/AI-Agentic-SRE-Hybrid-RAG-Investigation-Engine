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

# Explicit units per metric name to avoid mislabeling absolute request rates as ratios
METRIC_UNIT_MAP = {
    "request_rate": "req/s",
    "sim_red_request_rate_rps": "req/s",
    "error_rate": "ratio",
    "sim_red_error_rate_ratio": "ratio",
    "latency_p95": "ms",
    "sim_red_latency_p95_ms": "ms",
    "http_requests_total": "count",
    "http_request_duration_seconds_count": "count",
    "http_request_duration_seconds_bucket": "s",
    "process_cpu_seconds_total": "s",
    "process_resident_memory_bytes": "bytes",
}

METRIC_AGGREGATION_MAP = {
    "request_rate": "rate",
    "sim_red_request_rate_rps": "rate",
    "error_rate": "ratio",
    "sim_red_error_rate_ratio": "ratio",
    "latency_p95": "p95",
    "sim_red_latency_p95_ms": "p95",
    "http_requests_total": "counter",
    "http_request_duration_seconds_count": "counter",
    "http_request_duration_seconds_bucket": "histogram_bucket",
    "process_cpu_seconds_total": "counter",
    "process_resident_memory_bytes": "gauge",
}

METRIC_KIND_MAP = {
    "request_rate": "rate",
    "sim_red_request_rate_rps": "rate",
    "error_rate": "ratio",
    "sim_red_error_rate_ratio": "ratio",
    "latency_p95": "quantile",
    "sim_red_latency_p95_ms": "quantile",
    "http_requests_total": "counter",
    "http_request_duration_seconds_count": "counter",
    "http_request_duration_seconds_bucket": "histogram",
    "process_cpu_seconds_total": "counter",
    "process_resident_memory_bytes": "gauge",
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
            from orchestrator.evidence_lineage import DEFAULT_TEMPORAL_POLICY, normalize_timestamp

            req_env = str(arguments.get("environment") or "").strip()
            skew_td = datetime.timedelta(seconds=DEFAULT_TEMPORAL_POLICY.max_clock_skew_seconds)
            raw_scraped_records = body.get("records") if isinstance(body.get("records"), list) else []
            any_scraped_partial = any(
                isinstance(r, dict) and r.get("data_quality") == "partial"
                for r in raw_scraped_records
            )

            # Handle Prometheus matrix result
            data_field = body.get("data", {})
            if isinstance(data_field, dict) and data_field.get("resultType") == "matrix":
                results = data_field.get("result", [])
                for series in results:
                    meta = series.get("metric", {}) if isinstance(series.get("metric"), dict) else {}
                    series_env = str(meta.get("environment") or "").strip()
                    if req_env and series_env and series_env != req_env:
                        continue
                    clean_labels = {
                        str(k): str(v)
                        for k, v in meta.items()
                        if k != "__name__" and v is not None
                    }
                    for val_pair in series.get("values", []):
                        if len(val_pair) >= 2:
                            ts_epoch = float(val_pair[0])
                            ts_iso = datetime.datetime.fromtimestamp(
                                ts_epoch, datetime.timezone.utc
                            ).isoformat().replace("+00:00", "Z")
                            val_num = float(val_pair[1]) if val_pair[1] is not None else 0.0
                            rec_obj: dict[str, Any] = {
                                "timestamp": ts_iso,
                                "sample_at": ts_iso,
                                "service_id": meta.get("service_id", service_id),
                                "metric_name": metric_name,
                                "value": val_num,
                                "unit": METRIC_UNIT_MAP.get(metric_name, "ms"),
                                "aggregation": METRIC_AGGREGATION_MAP.get(metric_name, "sample"),
                                "metric_kind": METRIC_KIND_MAP.get(metric_name, "gauge"),
                                "step": step,
                            }
                            if meta.get("metric_enum"):
                                rec_obj["metric_enum"] = meta["metric_enum"]
                            elif metric_name in ("request_rate", "error_rate", "latency_p95"):
                                rec_obj["metric_enum"] = metric_name
                            if series_env:
                                rec_obj["environment"] = series_env
                            if clean_labels:
                                rec_obj["labels"] = clean_labels
                            records.append(rec_obj)
            elif "records" in body and isinstance(body["records"], list):
                for r in body["records"]:
                    if not isinstance(r, dict):
                        continue
                    r_env = str(r.get("environment") or "").strip()
                    if req_env and r_env and r_env != req_env:
                        continue
                    r_ts = r.get("sample_at") or r.get("timestamp")
                    if r_ts is not None:
                        norm_ts = normalize_timestamp(r_ts)
                        if norm_ts.ok and norm_ts.dt is not None:
                            if norm_ts.dt < (dt_start - skew_td) or norm_ts.dt > (dt_end + skew_td):
                                continue
                    r_copy = dict(r)
                    r_copy.setdefault("metric_name", metric_name)
                    r_copy.setdefault("unit", METRIC_UNIT_MAP.get(metric_name, "ms"))
                    r_copy.setdefault("aggregation", METRIC_AGGREGATION_MAP.get(metric_name, "sample"))
                    r_copy.setdefault("metric_kind", METRIC_KIND_MAP.get(metric_name, "gauge"))
                    r_copy.setdefault("step", step)
                    records.append(r_copy)
            elif "metrics" in body and isinstance(body["metrics"], list):
                for r in body["metrics"]:
                    if not isinstance(r, dict):
                        continue
                    r_env = str(r.get("environment") or "").strip()
                    if req_env and r_env and r_env != req_env:
                        continue
                    r_copy = dict(r)
                    r_copy.setdefault("metric_name", metric_name)
                    r_copy.setdefault("unit", METRIC_UNIT_MAP.get(metric_name, "ms"))
                    r_copy.setdefault("aggregation", METRIC_AGGREGATION_MAP.get(metric_name, "sample"))
                    r_copy.setdefault("metric_kind", METRIC_KIND_MAP.get(metric_name, "gauge"))
                    r_copy.setdefault("step", step)
                    records.append(r_copy)

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
        source_count = len(records)
        point_limit = min(req_max_points, self.max_points)
        truncated = False
        if source_count > point_limit:
            records = records[:point_limit]
            truncated = True

        # Step I: Pre-sink SEC-03 Sanitization
        sanitized_records, _ = self.sanitizer.sanitize_object(records)
        scraped_sample_times = [
            str(r.get("sample_at"))
            for r in raw_scraped_records
            if isinstance(r, dict)
            and (not req_env or not r.get("environment") or str(r.get("environment")).strip() == req_env)
            and isinstance(r.get("sample_at"), str)
            and str(r.get("sample_at")).endswith("Z")
        ]
        if scraped_sample_times:
            observed_at_z = max(scraped_sample_times)
        else:
            observed_candidates = [
                str(r.get("sample_at") or r.get("timestamp"))
                for r in sanitized_records
                if isinstance(r, dict)
                and isinstance(r.get("sample_at") or r.get("timestamp"), str)
                and str(r.get("sample_at") or r.get("timestamp")).endswith("Z")
            ]
            observed_at_z = max(observed_candidates) if observed_candidates else now_z
        is_partial = bool(truncated or any_scraped_partial or body.get("partial"))

        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self._get_source_ref(),
            observed_at=observed_at_z,
            query_window=query_window,
            data_quality="partial" if is_partial else "complete",
            truncated=truncated,
            sanitized=True,
            error_code=None,
            data=sanitized_records,
            status="ok",
            collected_at=now_z,
            sampling={
                "applied": truncated,
                "method": "head_limit" if truncated else None,
                "returned_count": len(sanitized_records),
                "source_count": source_count,
            },
        )
