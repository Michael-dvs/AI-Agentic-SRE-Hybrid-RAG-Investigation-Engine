"""Structured JSON logging, W3C traceparent propagation, span recording, and RED metrics registry."""

from __future__ import annotations

import collections
import contextvars
import json
import math
import queue
import re
import secrets
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from services.common.config import ServiceConfig

_correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="corr-unset"
)
_trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)
_span_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "span_id", default=None
)
_parent_span_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "parent_span_id", default=None
)
_caller_service_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caller_service_id", default=None
)
_extra_delay_ms_ctx: contextvars.ContextVar[float] = contextvars.ContextVar(
    "extra_delay_ms", default=0.0
)

_TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)
_CORR_RE = re.compile(r"^[a-zA-Z0-9._:-]{4,128}$")
_REDACT_RE = re.compile(
    r"(SYNTH-TOKEN-[A-Za-z0-9_-]+|SYNTH-SECRET-[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

_BUFFER_LOCK = threading.Lock()
_RECENT_LOGS: collections.deque[dict[str, Any]] = collections.deque(maxlen=2000)
_RECENT_SPANS: collections.deque[dict[str, Any]] = collections.deque(maxlen=2000)
_TELEMETRY_SINKS: list[Callable[[str, dict[str, Any]], None]] = []


class _OtelBackgroundShipper:
    """Non-blocking background HTTP shipper to OTel Collector (/v1/logs and /v1/traces)."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(
            maxsize=4000
        )
        self._thread = threading.Thread(
            target=self._worker, name="otel-bg-shipper", daemon=True
        )
        self._thread.start()

    def enqueue(self, signal_kind: str, collector_url: str, record: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((signal_kind, collector_url, record))
        except queue.Full:
            pass

    def _worker(self) -> None:
        while True:
            first_item = self._queue.get()
            batch_items = [first_item]
            while len(batch_items) < 64:
                try:
                    batch_items.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for kind, base_url, record in batch_items:
                grouped.setdefault((kind, base_url), []).append(record)

            for (kind, base_url), records in grouped.items():
                try:
                    endpoint = "/v1/logs" if kind == "log" else "/v1/traces"
                    url = f"{base_url.rstrip('/')}{endpoint}"
                    body = json.dumps(
                        {"records": records}, separators=(",", ":")
                    ).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=1.5) as _:
                        pass
                except Exception:
                    pass

            for _ in batch_items:
                self._queue.task_done()


_OTEL_SHIPPER = _OtelBackgroundShipper()


def register_telemetry_sink(sink: Callable[[str, dict[str, Any]], None]) -> None:
    """Register an in-process listener receiving ('log' | 'span', record)."""
    with _BUFFER_LOCK:
        if sink not in _TELEMETRY_SINKS:
            _TELEMETRY_SINKS.append(sink)


def clear_telemetry_sinks() -> None:
    with _BUFFER_LOCK:
        _TELEMETRY_SINKS.clear()


def clear_telemetry_buffers() -> None:
    with _BUFFER_LOCK:
        _RECENT_LOGS.clear()
        _RECENT_SPANS.clear()


def get_recent_logs(
    service_id: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with _BUFFER_LOCK:
        items = list(_RECENT_LOGS)
    if service_id:
        items = [x for x in items if x.get("service_id") == service_id]
    if trace_id:
        items = [x for x in items if x.get("trace_id") == trace_id]
    if correlation_id:
        items = [x for x in items if x.get("correlation_id") == correlation_id]
    return items[-limit:]


def get_recent_spans(
    service_id: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with _BUFFER_LOCK:
        items = list(_RECENT_SPANS)
    if service_id:
        items = [x for x in items if x.get("service_id") == service_id]
    if trace_id:
        items = [x for x in items if x.get("trace_id") == trace_id]
    if correlation_id:
        items = [x for x in items if x.get("correlation_id") == correlation_id]
    return items[-limit:]


def utc_now_iso() -> str:
    """Return RFC 3339 / ISO-8601 UTC timestamp ending in Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def generate_trace_id() -> str:
    val = secrets.token_hex(16)
    return val if val != "0" * 32 else "1" + ("0" * 31)


def generate_span_id() -> str:
    val = secrets.token_hex(8)
    return val if val != "0" * 16 else "1" + ("0" * 15)


def generate_correlation_id() -> str:
    return f"corr-{secrets.token_hex(8)}"


def parse_or_create_trace_context(
    traceparent: str | None, correlation_header: str | None
) -> tuple[str, str, str]:
    """Return (correlation_id, trace_id, span_id) from incoming headers or fresh IDs."""
    if correlation_header and _CORR_RE.match(correlation_header.strip()):
        correlation_id = correlation_header.strip()
    else:
        correlation_id = generate_correlation_id()

    trace_id: str | None = None
    parent_span_id: str | None = None
    if traceparent:
        m = _TRACEPARENT_RE.match(traceparent.strip().lower())
        if m and m.group(1) != "0" * 32 and m.group(2) != "0" * 16:
            trace_id = m.group(1)
            parent_span_id = m.group(2)

    if not trace_id:
        trace_id = generate_trace_id()

    span_id = generate_span_id()
    _parent_span_id_ctx.set(parent_span_id)
    return correlation_id, trace_id, span_id


def set_telemetry_context(
    correlation_id: str,
    trace_id: str | None,
    span_id: str | None,
    parent_span_id: str | None = None,
    service_id: str | None = None,
) -> None:
    _correlation_id_ctx.set(correlation_id)
    _trace_id_ctx.set(trace_id)
    _span_id_ctx.set(span_id)
    if parent_span_id is not None:
        _parent_span_id_ctx.set(parent_span_id)
    if service_id is not None:
        _caller_service_id_ctx.set(service_id)


def get_telemetry_context() -> tuple[str, str | None, str | None]:
    return (
        _correlation_id_ctx.get(),
        _trace_id_ctx.get(),
        _span_id_ctx.get(),
    )


def get_parent_span_id() -> str | None:
    return _parent_span_id_ctx.get()


def get_caller_service_id() -> str | None:
    return _caller_service_id_ctx.get()


def get_extra_delay_ms() -> float:
    return _extra_delay_ms_ctx.get()


def set_extra_delay_ms(delay_ms: float) -> None:
    _extra_delay_ms_ctx.set(max(0.0, float(delay_ms)))


def format_traceparent(trace_id: str | None, span_id: str | None = None) -> str:
    tid = trace_id or generate_trace_id()
    sid = span_id or generate_span_id()
    return f"00-{tid}-{sid}-01"


def outbound_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    corr_id, trace_id, current_span_id = get_telemetry_context()
    parent_for_downstream = current_span_id or generate_span_id()
    headers = {
        "X-Correlation-ID": corr_id
        if _CORR_RE.match(corr_id)
        else generate_correlation_id(),
        "traceparent": format_traceparent(trace_id, parent_for_downstream),
    }
    caller_svc = _caller_service_id_ctx.get()
    if caller_svc:
        headers["X-Caller-Service-ID"] = caller_svc
    if extra:
        headers.update(extra)
    return headers


def sanitize_message(message: str) -> str:
    cleaned = _REDACT_RE.sub("[REDACTED_SYNTH_CREDENTIAL]", message)
    return cleaned[:4096] if cleaned else "empty_message"


def build_structured_log(
    config: ServiceConfig,
    severity: str,
    event_type: str,
    message: str,
    error_code: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    trace_absent_reason: str | None = None,
) -> dict[str, Any]:
    ctx_corr, ctx_trace, ctx_span = get_telemetry_context()
    corr = correlation_id or ctx_corr
    if not _CORR_RE.match(corr):
        corr = generate_correlation_id()

    tid = trace_id if trace_id is not None else ctx_trace
    sid = span_id if span_id is not None else ctx_span
    absent_reason = trace_absent_reason
    if tid is None or sid is None:
        tid = None
        sid = None
        if absent_reason is None:
            absent_reason = "BACKGROUND_WORKER_NO_ACTIVE_SPAN"

    return {
        "schema_version": "1.0",
        "timestamp": utc_now_iso(),
        "severity": severity
        if severity in ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")
        else "INFO",
        "service.name": config.service_name,
        "service_id": config.service_id,
        "environment": config.environment,
        "instance_id": config.instance_id,
        "build_version": config.build_version,
        "event_type": event_type[:128],
        "correlation_id": corr,
        "trace_id": tid,
        "span_id": sid,
        "trace_absent_reason": absent_reason,
        "error_code": error_code,
        "message": sanitize_message(message),
        "sanitized": True,
    }


def emit_structured_log(
    config: ServiceConfig,
    severity: str,
    event_type: str,
    message: str,
    error_code: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    trace_absent_reason: str | None = None,
) -> dict[str, Any]:
    entry = build_structured_log(
        config=config,
        severity=severity,
        event_type=event_type,
        message=message,
        error_code=error_code,
        correlation_id=correlation_id,
        trace_id=trace_id,
        span_id=span_id,
        trace_absent_reason=trace_absent_reason,
    )
    sys.stdout.write(json.dumps(entry, separators=(",", ":")) + "\n")
    sys.stdout.flush()

    with _BUFFER_LOCK:
        _RECENT_LOGS.append(entry)
        sinks = list(_TELEMETRY_SINKS)
    for sink in sinks:
        try:
            sink("log", entry)
        except Exception:
            pass
    if config.otel_export_enabled and config.otel_collector_url:
        _OTEL_SHIPPER.enqueue("log", config.otel_collector_url, entry)
    return entry


def build_span_record(
    config: ServiceConfig,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    correlation_id: str,
    span_name: str,
    span_kind: str = "SERVER",
    relation_type: str = "sync_http",
    from_service_id: str | None = None,
    to_service_id: str | None = None,
    http_method: str | None = None,
    http_path: str | None = None,
    status_code: int = 200,
    error_code: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    duration_ms: float = 0.0,
    service_id_override: str | None = None,
    service_name_override: str | None = None,
) -> dict[str, Any]:
    now_iso = utc_now_iso()
    svc_id = service_id_override or config.service_id
    svc_name = service_name_override or config.service_name
    is_err = status_code >= 500 or (
        error_code is not None and not error_code.startswith("WARN_")
    )
    return {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "correlation_id": correlation_id,
        "service_id": svc_id,
        "service.name": svc_name,
        "environment": config.environment,
        "instance_id": config.instance_id,
        "build_version": config.build_version,
        "span_name": span_name[:128],
        "span_kind": span_kind,
        "relation_type": relation_type,
        "from_service_id": from_service_id,
        "to_service_id": to_service_id or svc_id,
        "http_method": http_method,
        "http_path": http_path,
        "http_status_code": status_code,
        "status": "error" if is_err else "ok",
        "error_code": error_code,
        "start_time": start_time or now_iso,
        "end_time": end_time or now_iso,
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
        "sanitized": True,
    }


def record_span(
    config: ServiceConfig,
    trace_id: str | None,
    span_id: str | None,
    parent_span_id: str | None,
    correlation_id: str,
    span_name: str,
    span_kind: str = "SERVER",
    relation_type: str = "sync_http",
    from_service_id: str | None = None,
    to_service_id: str | None = None,
    http_method: str | None = None,
    http_path: str | None = None,
    status_code: int = 200,
    error_code: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    duration_ms: float = 0.0,
    service_id_override: str | None = None,
    service_name_override: str | None = None,
) -> dict[str, Any] | None:
    if not trace_id or not span_id:
        return None
    span = build_span_record(
        config=config,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        correlation_id=correlation_id,
        span_name=span_name,
        span_kind=span_kind,
        relation_type=relation_type,
        from_service_id=from_service_id,
        to_service_id=to_service_id,
        http_method=http_method,
        http_path=http_path,
        status_code=status_code,
        error_code=error_code,
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
        service_id_override=service_id_override,
        service_name_override=service_name_override,
    )
    with _BUFFER_LOCK:
        _RECENT_SPANS.append(span)
        sinks = list(_TELEMETRY_SINKS)
    for sink in sinks:
        try:
            sink("span", span)
        except Exception:
            pass
    if config.otel_export_enabled and config.otel_collector_url:
        _OTEL_SHIPPER.enqueue("span", config.otel_collector_url, span)
    return span


class MetricsRegistry:
    """Thread-safe RED metrics collector for C03/C05 services."""

    def __init__(self, config: ServiceConfig, window_seconds: int = 60) -> None:
        self.config = config
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_errors = 0
        self._samples: list[tuple[float, float, bool]] = []  # (timestamp, latency_ms, is_error)

    def reset_samples(self) -> None:
        with self._lock:
            self._total_requests = 0
            self._total_errors = 0
            self._samples.clear()

    def record(self, latency_ms: float, status_code: int) -> None:
        now = time.time()
        is_error = status_code >= 500 or status_code in (401, 403, 409, 422, 400)
        with self._lock:
            self._total_requests += 1
            if is_error:
                self._total_errors += 1
            self._samples.append((now, max(0.0, latency_ms), is_error))
            cutoff = now - max(self.window_seconds, 300)
            if len(self._samples) > 5000:
                self._samples = [s for s in self._samples if s[0] >= cutoff]

    def snapshot_red(self) -> list[dict[str, Any]]:
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [s for s in self._samples if s[0] >= cutoff]

        count = len(recent)
        req_rate = round(count / float(self.window_seconds), 4)
        if count > 0:
            err_count = sum(1 for s in recent if s[2])
            err_rate = round(err_count / float(count), 4)
            latencies = sorted(s[1] for s in recent)
            idx = max(0, min(len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1))
            p95_ms = round(latencies[idx], 3)
        else:
            err_rate = 0.0
            p95_ms = 0.0

        sample_at = utc_now_iso()
        base = {
            "schema_version": "1.0",
            "service_id": self.config.service_id,
            "service.name": self.config.service_name,
            "environment": self.config.environment,
            "build_version": self.config.build_version,
            "sample_at": sample_at,
            "window_seconds": self.window_seconds,
            "source_ref": f"http://{self.config.service_id}:8000/metrics",
            "data_quality": "complete",
        }
        return [
            {
                **base,
                "metric_enum": "request_rate",
                "value": req_rate,
                "unit": "requests/s",
                "aggregation": "rate",
            },
            {
                **base,
                "metric_enum": "error_rate",
                "value": err_rate,
                "unit": "ratio",
                "aggregation": "ratio",
            },
            {
                **base,
                "metric_enum": "latency_p95",
                "value": p95_ms,
                "unit": "ms",
                "aggregation": "p95",
            },
        ]

    def format_prometheus(self) -> str:
        red = {m["metric_enum"]: m["value"] for m in self.snapshot_red()}
        with self._lock:
            total_req = self._total_requests
            total_err = self._total_errors
        labels = (
            f'service_id="{self.config.service_id}",'
            f'service_name="{self.config.service_name}",'
            f'environment="{self.config.environment}",'
            f'build_version="{self.config.build_version}"'
        )
        lines = [
            "# HELP sim_http_requests_total Total HTTP requests handled",
            "# TYPE sim_http_requests_total counter",
            f"sim_http_requests_total{{{labels}}} {total_req}",
            "# HELP sim_http_errors_total Total HTTP error responses",
            "# TYPE sim_http_errors_total counter",
            f"sim_http_errors_total{{{labels}}} {total_err}",
            "# HELP sim_red_request_rate_rps Request rate over window",
            "# TYPE sim_red_request_rate_rps gauge",
            f"sim_red_request_rate_rps{{{labels}}} {red['request_rate']}",
            "# HELP sim_red_error_rate_ratio Error ratio over window",
            "# TYPE sim_red_error_rate_ratio gauge",
            f"sim_red_error_rate_ratio{{{labels}}} {red['error_rate']}",
            "# HELP sim_red_latency_p95_ms P95 latency in milliseconds over window",
            "# TYPE sim_red_latency_p95_ms gauge",
            f"sim_red_latency_p95_ms{{{labels}}} {red['latency_p95']}",
        ]
        return "\n".join(lines) + "\n"


def _is_non_business_path(path: str) -> bool:
    return (
        path
        in (
            "/health/live",
            "/healthz",
            "/health/ready",
            "/readyz",
            "/metrics",
            "/catalog",
        )
        or path.startswith("/_sim/fault")
        or path.startswith("/internal/telemetry")
    )


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware propagating W3C traceparent and X-Correlation-ID, running fault hooks, and recording RED metrics/spans."""

    def __init__(self, app: Any, config: ServiceConfig, metrics: MetricsRegistry) -> None:
        super().__init__(app)
        self.config = config
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        corr_id, trace_id, span_id = parse_or_create_trace_context(
            request.headers.get("traceparent"),
            request.headers.get("X-Correlation-ID"),
        )
        parent_span_id = get_parent_span_id()
        caller_service = (request.headers.get("X-Caller-Service-ID") or "").strip() or None
        set_telemetry_context(
            corr_id,
            trace_id,
            span_id,
            parent_span_id=parent_span_id,
            service_id=self.config.service_id,
        )
        set_extra_delay_ms(0.0)
        request.state.correlation_id = corr_id
        request.state.trace_id = trace_id
        request.state.span_id = span_id
        request.state.parent_span_id = parent_span_id
        request.state.caller_service_id = caller_service
        request.state.last_error_code = None

        start_iso = utc_now_iso()
        start = time.perf_counter()

        fault_controller = getattr(request.app.state, "fault_controller", None)
        response: Response | None = None
        if fault_controller is not None and not getattr(
            request.state, "fault_hooks_applied", False
        ):
            request.state.fault_hooks_applied = True
            try:
                t0_hook = time.perf_counter()
                await fault_controller.apply_request_hooks(request)
                hook_ms = (time.perf_counter() - t0_hook) * 1000.0
                if hook_ms >= 20.0:
                    set_extra_delay_ms(hook_ms)
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                error_code = getattr(exc, "error_code", None)
                if status_code is not None and error_code is not None:
                    request.state.last_error_code = error_code
                    cur_corr, cur_tid, cur_sid = get_telemetry_context()
                    emit_structured_log(
                        config=self.config,
                        severity="ERROR" if status_code >= 500 else "WARN",
                        event_type="service.error",
                        message=f"{error_code}: { getattr(exc, 'message', str(exc)) }",
                        error_code=error_code,
                        correlation_id=cur_corr,
                        trace_id=cur_tid,
                        span_id=cur_sid,
                    )
                    if (
                        self.config.service_id == "ledger-service"
                        and not _is_non_business_path(request.url.path)
                        and error_code
                        in ("ERR_DEPENDENCY_UNAVAILABLE", "ERR_CONNECTION_POOL_EXHAUSTED")
                    ):
                        db_err_ms = (time.perf_counter() - start) * 1000.0
                        record_span(
                            config=self.config,
                            trace_id=cur_tid,
                            span_id=generate_span_id(),
                            parent_span_id=cur_sid,
                            correlation_id=cur_corr,
                            span_name="POSTGRESQL ledger_entries query",
                            span_kind="CLIENT",
                            relation_type="storage_call",
                            from_service_id="ledger-service",
                            to_service_id="db-dummy",
                            http_method="SQL",
                            http_path="ledger_entries",
                            status_code=status_code,
                            error_code=error_code,
                            start_time=start_iso,
                            end_time=utc_now_iso(),
                            duration_ms=db_err_ms,
                            service_id_override="db-dummy",
                            service_name_override="db-dummy",
                        )
                    envelope: dict[str, Any] = {
                        "error_code": error_code,
                        "message": getattr(exc, "message", str(exc)),
                        "service_id": self.config.service_id,
                        "environment": self.config.environment,
                        "correlation_id": cur_corr,
                        "trace_id": cur_tid,
                        "span_id": cur_sid,
                        "timestamp": utc_now_iso(),
                    }
                    details = getattr(exc, "details", None)
                    if details:
                        envelope["details"] = details
                    response = JSONResponse(status_code=status_code, content=envelope)
                else:
                    raise

        if response is None:
            response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        end_iso = utc_now_iso()
        cur_corr, cur_tid, cur_sid = get_telemetry_context()

        path = request.url.path
        if not _is_non_business_path(path):
            self.metrics.record(elapsed_ms, response.status_code)
            err_code = getattr(request.state, "last_error_code", None)
            if err_code is None and response.status_code >= 400:
                err_code = f"HTTP_{response.status_code}"

            severity = (
                "ERROR"
                if response.status_code >= 500
                else ("WARN" if response.status_code >= 400 else "INFO")
            )
            emit_structured_log(
                config=self.config,
                severity=severity,
                event_type="http.request.completed",
                message=(
                    f"{request.method} {path} -> {response.status_code} "
                    f"({elapsed_ms:.2f}ms)"
                ),
                error_code=err_code,
                correlation_id=cur_corr,
                trace_id=cur_tid,
                span_id=cur_sid,
            )
            record_span(
                config=self.config,
                trace_id=cur_tid,
                span_id=cur_sid,
                parent_span_id=parent_span_id,
                correlation_id=cur_corr,
                span_name=f"{request.method} {path}",
                span_kind="SERVER",
                relation_type="sync_http",
                from_service_id=caller_service,
                to_service_id=self.config.service_id,
                http_method=request.method,
                http_path=path,
                status_code=response.status_code,
                error_code=err_code,
                start_time=start_iso,
                end_time=end_iso,
                duration_ms=elapsed_ms,
            )

        response.headers["X-Correlation-ID"] = cur_corr
        response.headers["traceparent"] = format_traceparent(cur_tid, cur_sid)
        return response
