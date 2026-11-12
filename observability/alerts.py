"""Deterministic Alert Evaluator and Signed Webhook Envelope Builder for C05 (FR-OBS-004, ADR-S02).

Evaluates RED metrics and structured logs against `observability/alert-rules.yml`
thresholds to emit C02-compliant `alert-event.v1.schema.json` payloads with
HMAC-SHA256 webhook headers for `principal:alert-intake`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from services.common.telemetry import utc_now_iso

AUTHORIZED_ALERT_PRINCIPAL = "principal:alert-intake"
DEFAULT_ALERT_WEBHOOK_TOKEN = "SYNTH-ALERT-WEBHOOK-KEY-C05"

ERROR_RATE_CRITICAL_THRESHOLD = 0.20
LATENCY_P95_HIGH_THRESHOLD_MS = 250.0


def compute_alert_signature(webhook_token: str, raw_body: bytes) -> str:
    return hmac.new(
        webhook_token.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


def build_alert_webhook_headers(
    raw_body: bytes,
    webhook_token: str = DEFAULT_ALERT_WEBHOOK_TOKEN,
    principal_id: str = AUTHORIZED_ALERT_PRINCIPAL,
) -> dict[str, str]:
    """Return signed HTTP headers for C10 Alert Intake webhook delivery (ADR-S02 §5.3)."""
    return {
        "X-Principal-ID": principal_id,
        "X-Webhook-Token": webhook_token,
        "X-Alert-Signature": compute_alert_signature(webhook_token, raw_body),
        "Content-Type": "application/json",
    }


def verify_alert_webhook_headers(
    headers: dict[str, str],
    raw_body: bytes,
    webhook_token: str = DEFAULT_ALERT_WEBHOOK_TOKEN,
) -> bool:
    norm = {k.lower(): v for k, v in headers.items()}
    principal = (norm.get("x-principal-id") or "").strip()
    token = (norm.get("x-webhook-token") or "").strip()
    sig = (norm.get("x-alert-signature") or "").strip()
    if principal != AUTHORIZED_ALERT_PRINCIPAL:
        return False
    if not token or not hmac.compare_digest(token, webhook_token):
        return False
    expected = compute_alert_signature(webhook_token, raw_body)
    return bool(sig) and hmac.compare_digest(sig, expected)


def _window_bounds(
    event_time_iso: str, window_seconds: int = 60
) -> tuple[str, str]:
    try:
        cleaned = (
            event_time_iso[:-1] + "+00:00"
            if event_time_iso.endswith("Z")
            else event_time_iso
        )
        end_dt = datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    except Exception:
        end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(seconds=max(1, window_seconds))
    return (
        start_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )


def _make_alert_id(
    service_id: str,
    alert_type: str,
    window_end: str,
    error_code: str | None,
) -> str:
    digest = hashlib.sha256(
        f"{service_id}:{alert_type}:{window_end}:{error_code or 'none'}".encode("utf-8")
    ).hexdigest()[:12]
    return f"alt-{service_id}-{alert_type}-{digest}"[:128]


def evaluate_alert_rules(
    metrics: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    environment: str = "lab",
    build_version: str = "0.1.0-sim",
    evaluation_time_iso: str | None = None,
    window_seconds: int = 60,
) -> list[dict[str, Any]]:
    """Evaluate RED metrics and structured logs to generate `alert-event.v1.schema.json` alerts.

    Guarantees 0 false-positive critical/high alerts on healthy baseline traffic (SC-01).
    """
    now_iso = evaluation_time_iso or utc_now_iso()
    window_start, window_end = _window_bounds(now_iso, window_seconds=window_seconds)

    # Group RED metrics by service_id
    red_by_service: dict[str, dict[str, Any]] = {}
    for m in metrics:
        sid = m.get("service_id") or m.get("service.name")
        m_enum = m.get("metric_enum")
        if sid and m_enum:
            svc_entry = red_by_service.setdefault(
                sid,
                {
                    "build_version": m.get("build_version", build_version),
                    "environment": m.get("environment", environment),
                },
            )
            svc_entry[m_enum] = float(m.get("value", 0.0))

    # Group logs by service_id to extract latest trace_id and specific error codes
    logs_by_service: dict[str, list[dict[str, Any]]] = {}
    for lg in logs:
        sid = lg.get("service_id") or lg.get("service.name")
        if sid:
            logs_by_service.setdefault(sid, []).append(lg)

    def _latest_trace_and_error(
        service_id: str, preferred_codes: tuple[str, ...] | None = None
    ) -> tuple[str | None, str | None]:
        svc_logs = logs_by_service.get(service_id, [])
        if preferred_codes:
            for lg in reversed(svc_logs):
                if lg.get("error_code") in preferred_codes:
                    return lg.get("trace_id"), lg.get("error_code")
        for lg in reversed(svc_logs):
            if lg.get("error_code") and lg.get("severity") in ("ERROR", "CRITICAL", "WARN"):
                return lg.get("trace_id"), lg.get("error_code")
        for lg in reversed(svc_logs):
            if lg.get("trace_id"):
                return lg.get("trace_id"), lg.get("error_code")
        return None, None

    alerts: list[dict[str, Any]] = []

    # 1. Metric-driven RED rules (SimHighErrorRate, SimHighLatencyP95)
    for sid, vals in sorted(red_by_service.items()):
        req_rate = float(vals.get("request_rate", 0.0))
        err_rate = float(vals.get("error_rate", 0.0))
        lat_p95 = float(vals.get("latency_p95", 0.0))
        svc_env = str(vals.get("environment", environment))
        svc_ver = str(vals.get("build_version", build_version))

        if req_rate > 0.0 and err_rate >= ERROR_RATE_CRITICAL_THRESHOLD:
            trace_id, err_code = _latest_trace_and_error(sid)
            err_code = err_code or "HTTP_500"
            alerts.append(
                {
                    "schema_version": "1.0",
                    "alert_id": _make_alert_id(sid, "high_error_rate", window_end, err_code),
                    "source_id": "src-prom-metrics",
                    "service_id": sid,
                    "environment": svc_env,
                    "alert_type": "high_error_rate",
                    "severity": "critical",
                    "event_time": now_iso,
                    "window_start": window_start,
                    "window_end": window_end,
                    "build_version": svc_ver,
                    "error_code": err_code,
                    "trace_id": trace_id,
                    "summary": (
                        f"Service {sid} error_rate={err_rate:.2f} exceeded critical "
                        f"threshold {ERROR_RATE_CRITICAL_THRESHOLD:.2f} (error_code={err_code})"
                    ),
                    "source_ref": f"http://prometheus:9090/api/v1/query?query=sim_red_error_rate_ratio{{service_id=\"{sid}\"}}",
                }
            )

        if req_rate > 0.0 and lat_p95 >= LATENCY_P95_HIGH_THRESHOLD_MS:
            trace_id, err_code = _latest_trace_and_error(
                sid, preferred_codes=("WARN_DB_SLOW_QUERY",)
            )
            err_code = err_code or "SLO_LATENCY_P95_BREACH"
            alerts.append(
                {
                    "schema_version": "1.0",
                    "alert_id": _make_alert_id(sid, "high_latency_p95", window_end, err_code),
                    "source_id": "src-prom-metrics",
                    "service_id": sid,
                    "environment": svc_env,
                    "alert_type": "high_latency_p95",
                    "severity": "high",
                    "event_time": now_iso,
                    "window_start": window_start,
                    "window_end": window_end,
                    "build_version": svc_ver,
                    "error_code": err_code,
                    "trace_id": trace_id,
                    "summary": (
                        f"Service {sid} latency_p95={lat_p95:.1f}ms exceeded high "
                        f"SLO threshold {LATENCY_P95_HIGH_THRESHOLD_MS:.1f}ms"
                    ),
                    "source_ref": f"http://prometheus:9090/api/v1/query?query=sim_red_latency_p95_ms{{service_id=\"{sid}\"}}",
                }
            )

    # 2. Log & service event rules (dependency_unavailable, connection_pool_exhausted, auth_failure_spike, queue_consumer_lag)
    specific_rules: list[tuple[tuple[str, ...], str, str, str, str]] = [
        (
            (
                "ERR_DEPENDENCY_UNAVAILABLE",
                "ERR_LEDGER_UPSTREAM_UNAVAILABLE",
                "ERR_TRANSACTION_UPSTREAM_UNAVAILABLE",
                "ERR_AUTH_UPSTREAM_UNAVAILABLE",
                "ERR_DB_UNAVAILABLE",
            ),
            "dependency_unavailable",
            "critical",
            "src-loki-logs",
            "Downstream dependency unavailable reported by {sid} ({code})",
        ),
        (
            ("ERR_CONNECTION_POOL_EXHAUSTED",),
            "connection_pool_exhausted",
            "critical",
            "src-loki-logs",
            "Database connection pool exhausted on {sid} ({code})",
        ),
        (
            ("ERR_AUTH_POLICY_MISMATCH",),
            "auth_failure_spike",
            "high",
            "src-loki-logs",
            "Authentication verifier policy mismatch spike on {sid} ({code})",
        ),
        (
            ("WARN_QUEUE_CONSUMER_LAG",),
            "queue_consumer_lag",
            "high",
            "src-sim-services",
            "Asynchronous queue consumer lag backlog active on {sid} ({code})",
        ),
    ]

    for sid, svc_logs in sorted(logs_by_service.items()):
        for codes, alert_type, severity, source_id, tmpl in specific_rules:
            matched_logs = [lg for lg in svc_logs if lg.get("error_code") in codes]
            if not matched_logs:
                continue
            last_lg = matched_logs[-1]
            code = str(last_lg.get("error_code"))
            tid = last_lg.get("trace_id")
            svc_env = str(last_lg.get("environment", environment))
            svc_ver = str(last_lg.get("build_version", build_version))
            source_ref = (
                f"http://loki:3100/loki/api/v1/query_range?service_id={sid}&error_code={code}"
                if source_id == "src-loki-logs"
                else f"http://{sid}:8000/internal/notifications"
            )
            alerts.append(
                {
                    "schema_version": "1.0",
                    "alert_id": _make_alert_id(sid, alert_type, window_end, code),
                    "source_id": source_id,
                    "service_id": sid,
                    "environment": svc_env,
                    "alert_type": alert_type,
                    "severity": severity,
                    "event_time": now_iso,
                    "window_start": window_start,
                    "window_end": window_end,
                    "build_version": svc_ver,
                    "error_code": code,
                    "trace_id": tid,
                    "summary": tmpl.format(sid=sid, code=code),
                    "source_ref": source_ref,
                }
            )

    return alerts


def package_signed_alert_deliveries(
    alerts: list[dict[str, Any]],
    webhook_token: str = DEFAULT_ALERT_WEBHOOK_TOKEN,
) -> list[dict[str, Any]]:
    """Wrap each `alert-event.v1` record with its signed webhook headers for C10 intake verification."""
    deliveries: list[dict[str, Any]] = []
    for alert in alerts:
        raw_bytes = json.dumps(alert, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        headers = build_alert_webhook_headers(raw_bytes, webhook_token=webhook_token)
        deliveries.append(
            {
                "alert": alert,
                "webhook_headers": headers,
            }
        )
    return deliveries

