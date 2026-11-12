"""Telemetry Query, Cross-Signal Correlation, and Tool-Result Wrapper for C05.

Implements:
  - Cross-signal correlation & data quality validation (`BRD §13.3`, `AT-001`)
  - Missing trace source handling (`SC-09`, `FR-OBS-007`, `EV-02`, `AT-009`, `RULE-006`)
  - Zero ground-truth leakage verification across logs, metrics, traces, catalog, and alerts (`AT-008`)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from observability.alerts import evaluate_alert_rules, package_signed_alert_deliveries
from observability.catalog import (
    build_default_service_catalogs,
    build_observed_dependency_graph,
)
from services.common.telemetry import utc_now_iso

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_FORBIDDEN_GT_PATTERNS = re.compile(
    r"\b(SC-0[1-9]|SC-1[0-4]|expected_root_cause_services|expected_fault_types|split_freeze_hash|SYNTH-EVALUATOR-KEY-C04)\b"
)


def scan_telemetry_for_gt_leakage(payload: Any) -> dict[str, Any]:
    """Scan serialized telemetry/catalog/alert payloads for forbidden ground-truth strings (AT-008)."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    matches = sorted(set(_FORBIDDEN_GT_PATTERNS.findall(serialized)))
    return {
        "leakage_detected": len(matches) > 0,
        "matched_forbidden_tokens": matches,
        "scanned_bytes": len(serialized.encode("utf-8")),
    }


class ObservabilityClient:
    """Unified query & correlation client for Prometheus, Loki, Tempo, and Service Catalog."""

    def __init__(
        self,
        gateway_url: str | None = None,
        prometheus_url: str | None = None,
        loki_url: str | None = None,
        tempo_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.gateway_url = (
            gateway_url or os.getenv("LIVE_GATEWAY_URL", "http://127.0.0.1:18080")
        ).rstrip("/")
        self.prometheus_url = (
            prometheus_url or os.getenv("PROMETHEUS_URL", "http://127.0.0.1:19090")
        ).rstrip("/")
        self.loki_url = (
            loki_url or os.getenv("LOKI_URL", "http://127.0.0.1:13100")
        ).rstrip("/")
        self.tempo_url = (
            tempo_url or os.getenv("TEMPO_URL", "http://127.0.0.1:13200")
        ).rstrip("/")
        self.http_client = http_client

    async def _request(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        timeout: float = 3.0,
    ) -> httpx.Response:
        if self.http_client is not None:
            return await self.http_client.request(
                method, url, json=json_body, timeout=timeout
            )
        async with httpx.AsyncClient(timeout=timeout) as ac:
            return await ac.request(method, url, json=json_body)

    async def fetch_logs(
        self,
        service_id: str | None = None,
        trace_id: str | None = None,
        correlation_id: str | None = None,
        error_code: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: list[str] = [f"limit={limit}"]
        if service_id:
            params.append(f"service_id={service_id}")
        if trace_id:
            params.append(f"trace_id={trace_id}")
        if correlation_id:
            params.append(f"correlation_id={correlation_id}")
        if error_code:
            params.append(f"error_code={error_code}")
        url = f"{self.loki_url}/loki/api/v1/query_range?{'&'.join(params)}"
        resp = await self._request("GET", url)
        if resp.status_code == 200:
            return resp.json().get("records", [])
        return []

    async def fetch_red_metrics(self) -> list[dict[str, Any]]:
        url = f"{self.prometheus_url}/api/v1/red_window"
        resp = await self._request("GET", url)
        if resp.status_code == 200:
            return resp.json().get("metrics", [])
        return []

    async def fetch_spans(
        self,
        service_id: str | None = None,
        trace_id: str | None = None,
        correlation_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if trace_id:
            url = f"{self.tempo_url}/api/traces/{trace_id}"
            resp = await self._request("GET", url)
            if resp.status_code == 200:
                return resp.json().get("spans", [])
            return []

        params = [f"limit={limit}"]
        if service_id:
            params.append(f"service_id={service_id}")
        if correlation_id:
            params.append(f"correlation_id={correlation_id}")
        url = f"{self.tempo_url}/api/search?{'&'.join(params)}"
        resp = await self._request("GET", url)
        if resp.status_code == 200:
            return resp.json().get("spans", [])
        return []

    async def set_tempo_outage(
        self,
        unavailable: bool,
        reason: str = "SC-09_trace_backend_outage",
    ) -> dict[str, Any]:
        """Toggle or recover Tempo distributed tracing backend availability (SC-09)."""
        url = f"{self.tempo_url}/_sim/outage"
        resp = await self._request(
            "POST",
            url,
            json_body={"unavailable": unavailable, "reason": reason},
        )
        return resp.json()

    async def reset_telemetry_backends(self) -> None:
        """Clear Loki and Tempo stores and reset Tempo outage state."""
        await self._request("POST", f"{self.loki_url}/_sim/reset")
        await self._request("POST", f"{self.tempo_url}/_sim/reset")

    async def get_trace_summary(
        self, trace_request: dict[str, Any]
    ) -> dict[str, Any]:
        """Query Tempo and return a C02 `tool-result.v1.schema.json` envelope.

        Enforces `RULE-006` / `EV-02` / `AT-009`: when Tempo is unreachable or returns
        503 (`SC-09`), returns `status="unavailable"`, `data_quality="unavailable"`,
        `error_code="SOURCE_UNAVAILABLE"`, `records=[]` without fabricating spans.
        """
        req_id = str(trace_request.get("request_id", "req-trace-c05-001"))
        service_id = str(trace_request.get("service_id", "api-gateway"))
        trace_id = trace_request.get("trace_id")
        corr_id = trace_request.get("correlation_id")
        win_start = str(
            trace_request.get("start")
            or trace_request.get("window_start")
            or utc_now_iso()
        )
        win_end = str(
            trace_request.get("end")
            or trace_request.get("window_end")
            or utc_now_iso()
        )
        max_spans = int(trace_request.get("max_spans", 50))

        if trace_id:
            query_url = f"{self.tempo_url}/api/traces/{trace_id}"
        else:
            q_parts = [f"service_id={service_id}", f"limit={max_spans}"]
            if corr_id:
                q_parts.append(f"correlation_id={corr_id}")
            query_url = f"{self.tempo_url}/api/search?{'&'.join(q_parts)}"

        try:
            resp = await self._request("GET", query_url, timeout=2.5)
        except Exception:
            return {
                "schema_version": "1.0",
                "tool_name": "get_trace_summary",
                "request_id": req_id,
                "status": "unavailable",
                "source_ref": query_url,
                "observed_at": utc_now_iso(),
                "query_window": {
                    "start": win_start,
                    "end": win_end,
                },
                "sampling": {
                    "applied": False,
                    "method": None,
                    "returned_count": 0,
                    "source_count": None,
                },
                "truncated": False,
                "data_quality": "unavailable",
                "sanitized": True,
                "records": [],
                "error_code": "SOURCE_UNAVAILABLE",
            }

        if resp.status_code == 503:
            return {
                "schema_version": "1.0",
                "tool_name": "get_trace_summary",
                "request_id": req_id,
                "status": "unavailable",
                "source_ref": query_url,
                "observed_at": utc_now_iso(),
                "query_window": {
                    "start": win_start,
                    "end": win_end,
                },
                "sampling": {
                    "applied": False,
                    "method": None,
                    "returned_count": 0,
                    "source_count": None,
                },
                "truncated": False,
                "data_quality": "unavailable",
                "sanitized": True,
                "records": [],
                "error_code": "SOURCE_UNAVAILABLE",
            }

        if resp.status_code == 404:
            return {
                "schema_version": "1.0",
                "tool_name": "get_trace_summary",
                "request_id": req_id,
                "status": "ok",
                "source_ref": query_url,
                "observed_at": utc_now_iso(),
                "query_window": {
                    "start": win_start,
                    "end": win_end,
                },
                "sampling": {
                    "applied": False,
                    "method": None,
                    "returned_count": 0,
                    "source_count": None,
                },
                "truncated": False,
                "data_quality": "partial",
                "sanitized": True,
                "records": [],
                "error_code": None,
            }

        body = resp.json()
        spans = body.get("spans", [])
        truncated = len(spans) > max_spans
        bounded_spans = spans[:max_spans]

        services_traversed: list[str] = []
        for s in bounded_spans:
            sid = str(s.get("service_id") or s.get("service.name"))
            if sid and sid not in services_traversed:
                services_traversed.append(sid)

        record_summary = {
            "trace_id": trace_id or (bounded_spans[0]["trace_id"] if bounded_spans else None),
            "span_count": len(bounded_spans),
            "services_traversed": services_traversed,
            "dependency_hops": max(0, len(services_traversed) - 1),
            "spans": bounded_spans,
        }
        return {
            "schema_version": "1.0",
            "tool_name": "get_trace_summary",
            "request_id": req_id,
            "status": "ok",
            "source_ref": query_url,
            "observed_at": utc_now_iso(),
            "query_window": {
                "start": win_start,
                "end": win_end,
            },
            "sampling": {
                "applied": truncated,
                "method": "span_cap" if truncated else None,
                "returned_count": len(bounded_spans),
                "source_count": len(spans),
            },
            "truncated": truncated,
            "data_quality": "complete" if bounded_spans else "partial",
            "sanitized": True,
            "records": [record_summary] if bounded_spans else [],
            "error_code": None,
        }

    async def build_catalog_snapshot(
        self,
        logs: list[dict[str, Any]] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        spans: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fetched_logs = logs if logs is not None else await self.fetch_logs(limit=400)
        fetched_metrics = (
            metrics if metrics is not None else await self.fetch_red_metrics()
        )
        fetched_spans = (
            spans if spans is not None else await self.fetch_spans(limit=400)
        )

        catalogs: list[dict[str, Any]] | None = None
        try:
            topo_resp = await self._request(
                "GET", f"{self.gateway_url}/api/v1/topology"
            )
            if topo_resp.status_code == 200:
                catalogs = topo_resp.json().get("services")
        except Exception:
            catalogs = None

        return build_observed_dependency_graph(
            spans=fetched_spans,
            logs=fetched_logs,
            metrics=fetched_metrics,
            catalogs=catalogs or build_default_service_catalogs(),
        )

    async def evaluate_alerts(
        self,
        metrics: list[dict[str, Any]] | None = None,
        logs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if metrics is None and logs is None:
            resp = await self._request("GET", f"{self.prometheus_url}/api/v1/alerts")
            if resp.status_code == 200:
                return resp.json()
        fetched_metrics = (
            metrics if metrics is not None else await self.fetch_red_metrics()
        )
        fetched_logs = logs if logs is not None else await self.fetch_logs(limit=400)
        alerts = evaluate_alert_rules(metrics=fetched_metrics, logs=fetched_logs)
        return {
            "status": "success",
            "evaluated_at": utc_now_iso(),
            "alerts": alerts,
            "signed_deliveries": package_signed_alert_deliveries(alerts),
        }


def validate_cross_signal_correlation(
    logs: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    target_trace_id: str | None = None,
) -> dict[str, Any]:
    """Validate BRD §13.3 data quality & cross-signal joinability across logs, metrics, and traces."""
    invalid_timestamps: list[str] = []
    for lg in logs:
        ts = str(lg.get("timestamp", ""))
        if not _ISO_UTC_RE.match(ts):
            invalid_timestamps.append(f"log:{ts}")
    for m in metrics:
        ts = str(m.get("sample_at", ""))
        if not _ISO_UTC_RE.match(ts):
            invalid_timestamps.append(f"metric:{ts}")
    for sp in spans:
        for field in ("start_time", "end_time"):
            ts = str(sp.get(field, ""))
            if not _ISO_UTC_RE.match(ts):
                invalid_timestamps.append(f"span.{field}:{ts}")

    log_services = sorted({str(lg.get("service_id")) for lg in logs if lg.get("service_id")})
    metric_services = sorted(
        {str(m.get("service_id")) for m in metrics if m.get("service_id")}
    )
    span_services = sorted({str(sp.get("service_id")) for sp in spans if sp.get("service_id")})

    if target_trace_id:
        trace_logs = [lg for lg in logs if lg.get("trace_id") == target_trace_id]
        trace_spans = [sp for sp in spans if sp.get("trace_id") == target_trace_id]
    else:
        trace_logs = [lg for lg in logs if lg.get("trace_id")]
        trace_spans = [sp for sp in spans if sp.get("trace_id")]

    trace_services_in_spans: list[str] = []
    for sp in trace_spans:
        sid = str(sp.get("service_id"))
        if sid and sid not in trace_services_in_spans:
            trace_services_in_spans.append(sid)

    dependency_hops = max(0, len(trace_services_in_spans) - 1)
    leakage = scan_telemetry_for_gt_leakage(
        {"logs": logs, "metrics": metrics, "spans": spans}
    )

    return {
        "all_timestamps_utc_iso8601": len(invalid_timestamps) == 0,
        "invalid_timestamps": invalid_timestamps,
        "log_services": log_services,
        "metric_services": metric_services,
        "span_services": span_services,
        "trace_id_evaluated": target_trace_id,
        "correlated_log_count": len(trace_logs),
        "correlated_span_count": len(trace_spans),
        "trace_services_traversed": trace_services_in_spans,
        "trace_dependency_hops": dependency_hops,
        "meets_at001_multi_hop_trace": dependency_hops >= 2,
        "gt_leakage_scan": leakage,
    }
