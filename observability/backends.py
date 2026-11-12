"""Protocol-accurate FastAPI backends for C05 Observability Stack (ADR-S02).

Provides container-ready and in-process ASGI apps for:
  - `otel-collector` (:4318) -> OTLP HTTP log/trace receiver, attribute sanitizer, and exporter
  - `prometheus` (:9090) -> RED metrics scraper, query API, and alert rule evaluator
  - `loki` (:3100) -> Structured JSON log store and query API
  - `tempo` (:3200) -> Distributed trace store, query API, and reversible SC-09 outage toggle
  - `grafana` (:3000) -> Provisioned datasource and dashboard visualization server
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from observability.alerts import evaluate_alert_rules, package_signed_alert_deliveries
from services.common.telemetry import utc_now_iso

FORBIDDEN_GT_KEYS = {
    "scenario_id",
    "ground_truth",
    "expected_root_cause",
    "expected_root_cause_services",
    "expected_fault_types",
    "split_id",
    "split_freeze_hash",
}

DEFAULT_SCRAPE_TARGETS: dict[str, str] = {
    "api-gateway": os.getenv("API_GATEWAY_URL", "http://api-gateway:8000"),
    "auth-service": os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000"),
    "transaction-service": os.getenv(
        "TRANSACTION_SERVICE_URL", "http://transaction-service:8000"
    ),
    "ledger-service": os.getenv("LEDGER_SERVICE_URL", "http://ledger-service:8000"),
    "notification-service": os.getenv(
        "NOTIFICATION_SERVICE_URL", "http://notification-service:8000"
    ),
}

_LABEL_RE = re.compile(r'([a-zA-Z0-9_.-]+)\s*=\s*"([^"]+)"')


def _strip_forbidden_gt_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in FORBIDDEN_GT_KEYS}


def create_loki_app() -> FastAPI:
    """Create the Loki log ingestion and query backend (:3100)."""
    app = FastAPI(title="C05 Synthetic Loki Backend", version="0.1.0-sim")
    lock = threading.Lock()
    logs_store: collections.deque[dict[str, Any]] = collections.deque(maxlen=5000)
    app.state.logs_store = logs_store
    app.state.lock = lock

    def _ingest_records(records: list[dict[str, Any]]) -> int:
        added = 0
        with lock:
            for item in records:
                if isinstance(item, dict) and item.get("timestamp") and item.get("message"):
                    logs_store.append(_strip_forbidden_gt_fields(item))
                    added += 1
        return added

    app.state.ingest_records = _ingest_records

    @app.get("/ready")
    @app.get("/healthz")
    async def ready() -> dict[str, Any]:
        return {"status": "ready", "component": "loki", "timestamp": utc_now_iso()}

    @app.post("/loki/api/v1/push")
    async def push_logs(request: Request) -> JSONResponse:
        body = await request.json()
        records: list[dict[str, Any]] = []
        if isinstance(body, dict):
            if isinstance(body.get("records"), list):
                records.extend(body["records"])
            if isinstance(body.get("streams"), list):
                for stream in body["streams"]:
                    for val_pair in stream.get("values", []):
                        if len(val_pair) >= 2:
                            try:
                                parsed = json.loads(val_pair[1])
                                if isinstance(parsed, dict):
                                    records.append(parsed)
                            except Exception:
                                pass
        count = _ingest_records(records)
        return JSONResponse(status_code=204 if count >= 0 else 200, content=None)

    def _filter_logs(
        query: str | None,
        service_id: str | None,
        severity: str | None,
        trace_id: str | None,
        correlation_id: str | None,
        error_code: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        with lock:
            items = list(logs_store)

        if query:
            for k, v in _LABEL_RE.findall(query):
                if k in ("service_id", "service.name", "service_name"):
                    service_id = service_id or v
                elif k == "severity":
                    severity = severity or v
                elif k == "trace_id":
                    trace_id = trace_id or v
                elif k == "correlation_id":
                    correlation_id = correlation_id or v
                elif k == "error_code":
                    error_code = error_code or v

        if service_id:
            items = [
                x
                for x in items
                if x.get("service_id") == service_id or x.get("service.name") == service_id
            ]
        if severity:
            items = [x for x in items if x.get("severity") == severity]
        if trace_id:
            items = [x for x in items if x.get("trace_id") == trace_id]
        if correlation_id:
            items = [x for x in items if x.get("correlation_id") == correlation_id]
        if error_code:
            items = [x for x in items if x.get("error_code") == error_code]

        return items[-limit:]

    @app.get("/loki/api/v1/query_range")
    @app.get("/loki/api/v1/query")
    async def query_logs(
        query: str | None = Query(default=None),
        service_id: str | None = Query(default=None),
        severity: str | None = Query(default=None),
        trace_id: str | None = Query(default=None),
        correlation_id: str | None = Query(default=None),
        error_code: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        matched = _filter_logs(
            query=query,
            service_id=service_id,
            severity=severity,
            trace_id=trace_id,
            correlation_id=correlation_id,
            error_code=error_code,
            limit=limit,
        )
        streams = []
        if matched:
            streams.append(
                {
                    "stream": {"environment": "lab", "job": "sre-sim-microservices"},
                    "values": [
                        [str(idx + 1), json.dumps(rec, separators=(",", ":"))]
                        for idx, rec in enumerate(matched)
                    ],
                }
            )
        return {
            "status": "success",
            "data": {"resultType": "streams", "result": streams},
            "records": matched,
        }

    @app.post("/_sim/reset", include_in_schema=False)
    async def reset_loki() -> dict[str, Any]:
        with lock:
            logs_store.clear()
        return {"status": "LOKI_RESET", "timestamp": utc_now_iso()}

    return app


def create_tempo_app() -> FastAPI:
    """Create the Tempo distributed trace store and query backend (:3200) with reversible SC-09 outage."""
    app = FastAPI(title="C05 Synthetic Tempo Backend", version="0.1.0-sim")
    lock = threading.Lock()
    spans_store: collections.deque[dict[str, Any]] = collections.deque(maxlen=6000)
    outage_state: dict[str, Any] = {
        "unavailable": False,
        "reason": None,
        "updated_at": utc_now_iso(),
    }
    app.state.spans_store = spans_store
    app.state.outage_state = outage_state
    app.state.lock = lock

    def _ingest_spans(records: list[dict[str, Any]]) -> int:
        if outage_state["unavailable"]:
            return 0
        added = 0
        with lock:
            for sp in records:
                if isinstance(sp, dict) and sp.get("trace_id") and sp.get("span_id"):
                    spans_store.append(_strip_forbidden_gt_fields(sp))
                    added += 1
        return added

    app.state.ingest_spans = _ingest_spans

    def _unavailable_response() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "data_quality": "unavailable",
                "error_code": "SOURCE_UNAVAILABLE",
                "reason": outage_state.get("reason") or "tempo_backend_unavailable",
                "message": "Distributed tracing backend (Tempo) is unreachable or disabled",
                "timestamp": utc_now_iso(),
            },
        )

    @app.get("/healthz")
    async def container_health() -> dict[str, Any]:
        return {
            "status": "alive",
            "component": "tempo",
            "outage_active": outage_state["unavailable"],
            "timestamp": utc_now_iso(),
        }

    @app.get("/ready")
    async def ready() -> JSONResponse:
        if outage_state["unavailable"]:
            return _unavailable_response()
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "component": "tempo", "timestamp": utc_now_iso()},
        )

    @app.post("/v1/traces")
    async def ingest_traces(request: Request) -> JSONResponse:
        if outage_state["unavailable"]:
            return _unavailable_response()
        body = await request.json()
        records = body.get("records", []) if isinstance(body, dict) else []
        count = _ingest_spans(records)
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "ingested_spans": count},
        )

    @app.get("/api/traces/{trace_id}")
    async def get_trace_by_id(trace_id: str) -> JSONResponse:
        if outage_state["unavailable"]:
            return _unavailable_response()
        with lock:
            matched = [s for s in spans_store if s.get("trace_id") == trace_id]
        if not matched:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "error_code": "TRACE_NOT_FOUND",
                    "trace_id": trace_id,
                    "spans": [],
                },
            )
        matched_sorted = sorted(
            matched, key=lambda x: str(x.get("start_time") or "")
        )
        services_traversed: list[str] = []
        for s in matched_sorted:
            sid = str(s.get("service_id") or s.get("service.name"))
            if sid and sid not in services_traversed:
                services_traversed.append(sid)

        root_spans = [s for s in matched_sorted if not s.get("parent_span_id")]
        root_span_id = (
            root_spans[0]["span_id"]
            if root_spans
            else matched_sorted[0]["span_id"]
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "trace_id": trace_id,
                "root_span_id": root_span_id,
                "span_count": len(matched_sorted),
                "services_traversed": services_traversed,
                "dependency_hops": max(0, len(services_traversed) - 1),
                "spans": matched_sorted,
            },
        )

    @app.get("/api/search")
    async def search_traces(
        service_id: str | None = Query(default=None),
        correlation_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> JSONResponse:
        if outage_state["unavailable"]:
            return _unavailable_response()
        with lock:
            items = list(spans_store)
        if service_id:
            items = [
                s
                for s in items
                if s.get("service_id") == service_id or s.get("service.name") == service_id
            ]
        if correlation_id:
            items = [s for s in items if s.get("correlation_id") == correlation_id]
        if status:
            items = [s for s in items if s.get("status") == status]
        selected = items[-limit:]
        trace_ids = sorted({str(s["trace_id"]) for s in selected if s.get("trace_id")})
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "trace_ids": trace_ids,
                "span_count": len(selected),
                "spans": selected,
            },
        )

    @app.post("/_sim/outage", include_in_schema=False)
    async def set_outage_mode(request: Request) -> dict[str, Any]:
        body = await request.json() if await request.body() else {}
        unavailable = bool(body.get("unavailable", False))
        reason = body.get("reason") or (
            "SC-09_trace_backend_outage" if unavailable else "operator_reset"
        )
        with lock:
            outage_state["unavailable"] = unavailable
            outage_state["reason"] = reason
            outage_state["updated_at"] = utc_now_iso()
        return {
            "status": "OUTAGE_ACTIVE" if unavailable else "RECOVERED",
            "component": "tempo",
            **outage_state,
        }

    @app.get("/_sim/outage", include_in_schema=False)
    async def get_outage_mode() -> dict[str, Any]:
        return {"component": "tempo", **outage_state}

    @app.post("/_sim/reset", include_in_schema=False)
    async def reset_tempo() -> dict[str, Any]:
        with lock:
            spans_store.clear()
            outage_state["unavailable"] = False
            outage_state["reason"] = "reset"
            outage_state["updated_at"] = utc_now_iso()
        return {"status": "TEMPO_RESET", "timestamp": utc_now_iso()}

    return app


def create_otel_collector_app(
    loki_url: str | None = None,
    tempo_url: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    loki_app_ref: FastAPI | None = None,
    tempo_app_ref: FastAPI | None = None,
) -> FastAPI:
    """Create the OpenTelemetry Collector (:4318) forwarding logs to Loki and spans to Tempo."""
    resolved_loki = loki_url or os.getenv("LOKI_URL", "http://loki:3100")
    resolved_tempo = tempo_url or os.getenv("TEMPO_URL", "http://tempo:3200")
    app = FastAPI(title="C05 OpenTelemetry Collector", version="0.1.0-sim")
    app.state.http_client = http_client
    app.state.loki_app_ref = loki_app_ref
    app.state.tempo_app_ref = tempo_app_ref
    app.state.forwarded_logs = 0
    app.state.forwarded_spans = 0

    @app.get("/ready")
    @app.get("/healthz")
    async def ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "component": "otel-collector",
            "forwarded_logs": app.state.forwarded_logs,
            "forwarded_spans": app.state.forwarded_spans,
            "timestamp": utc_now_iso(),
        }

    @app.post("/v1/logs")
    async def receive_logs(request: Request) -> dict[str, Any]:
        body = await request.json()
        raw_records = body.get("records", []) if isinstance(body, dict) else []
        cleaned = [
            _strip_forbidden_gt_fields(r) for r in raw_records if isinstance(r, dict)
        ]
        if app.state.loki_app_ref is not None:
            app.state.loki_app_ref.state.ingest_records(cleaned)
        else:
            url = f"{resolved_loki.rstrip('/')}/loki/api/v1/push"
            client = app.state.http_client
            try:
                if client is not None:
                    await client.post(url, json={"records": cleaned}, timeout=2.0)
                else:
                    async with httpx.AsyncClient(timeout=2.0) as ac:
                        await ac.post(url, json={"records": cleaned})
            except Exception:
                pass
        app.state.forwarded_logs += len(cleaned)
        return {"status": "ok", "accepted_logs": len(cleaned)}

    @app.post("/v1/traces")
    async def receive_traces(request: Request) -> dict[str, Any]:
        body = await request.json()
        raw_records = body.get("records", []) if isinstance(body, dict) else []
        cleaned = [
            _strip_forbidden_gt_fields(r) for r in raw_records if isinstance(r, dict)
        ]
        if app.state.tempo_app_ref is not None:
            app.state.tempo_app_ref.state.ingest_spans(cleaned)
        else:
            url = f"{resolved_tempo.rstrip('/')}/v1/traces"
            client = app.state.http_client
            try:
                if client is not None:
                    await client.post(url, json={"records": cleaned}, timeout=2.0)
                else:
                    async with httpx.AsyncClient(timeout=2.0) as ac:
                        await ac.post(url, json={"records": cleaned})
            except Exception:
                pass
        app.state.forwarded_spans += len(cleaned)
        return {"status": "ok", "accepted_spans": len(cleaned)}

    return app


def create_prometheus_app(
    service_targets: dict[str, str] | None = None,
    loki_url: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    loki_app_ref: FastAPI | None = None,
) -> FastAPI:
    """Create the Prometheus scraper, RED query API, and alert evaluator (:9090)."""
    targets = dict(service_targets or DEFAULT_SCRAPE_TARGETS)
    resolved_loki = loki_url or os.getenv("LOKI_URL", "http://loki:3100")
    app = FastAPI(title="C05 Synthetic Prometheus Backend", version="0.1.0-sim")
    app.state.http_client = http_client
    app.state.loki_app_ref = loki_app_ref
    app.state.targets = targets

    async def _scrape_all_red() -> tuple[list[dict[str, Any]], dict[str, str]]:
        metrics_records: list[dict[str, Any]] = []
        target_health: dict[str, str] = {}
        client = app.state.http_client

        for svc_id, base_url in sorted(targets.items()):
            url = f"{base_url.rstrip('/')}/metrics?format=json"
            try:
                if client is not None:
                    resp = await client.get(url, timeout=2.5)
                else:
                    async with httpx.AsyncClient(timeout=2.5) as ac:
                        resp = await ac.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        metrics_records.extend(data)
                    target_health[svc_id] = "up"
                else:
                    target_health[svc_id] = "down"
            except Exception:
                target_health[svc_id] = "down"
        return metrics_records, target_health

    async def _fetch_recent_logs() -> list[dict[str, Any]]:
        if app.state.loki_app_ref is not None:
            with app.state.loki_app_ref.state.lock:
                return list(app.state.loki_app_ref.state.logs_store)[-500:]
        url = f"{resolved_loki.rstrip('/')}/loki/api/v1/query_range?limit=500"
        client = app.state.http_client
        try:
            if client is not None:
                resp = await client.get(url, timeout=2.0)
            else:
                async with httpx.AsyncClient(timeout=2.0) as ac:
                    resp = await ac.get(url)
            if resp.status_code == 200:
                return resp.json().get("records", [])
        except Exception:
            pass
        return []

    @app.get("/-/ready")
    @app.get("/healthz")
    async def ready() -> dict[str, Any]:
        return {"status": "ready", "component": "prometheus", "timestamp": utc_now_iso()}

    @app.get("/api/v1/targets")
    async def get_targets() -> dict[str, Any]:
        _, health = await _scrape_all_red()
        active_targets = [
            {
                "discoveredLabels": {"job": "sre-sim-microservices", "service_id": sid},
                "labels": {
                    "job": "sre-sim-microservices",
                    "service_id": sid,
                    "environment": "lab",
                },
                "scrapeUrl": f"{url.rstrip('/')}/metrics",
                "health": health.get(sid, "down"),
                "lastScrape": utc_now_iso(),
            }
            for sid, url in sorted(targets.items())
        ]
        return {"status": "success", "data": {"activeTargets": active_targets}}

    @app.get("/api/v1/red_window")
    async def get_red_window() -> dict[str, Any]:
        records, health = await _scrape_all_red()
        return {
            "status": "success",
            "observed_at": utc_now_iso(),
            "target_health": health,
            "metrics": records,
        }

    @app.api_route("/api/v1/query", methods=["GET", "POST"])
    @app.api_route("/api/v1/query_range", methods=["GET", "POST"])
    async def query_metrics(
        request: Request,
        query: str | None = Query(default=None),
        service_id: str | None = Query(default=None),
        start: float | None = Query(default=None),
        end: float | None = Query(default=None),
        step: float | None = Query(default=None),
    ) -> dict[str, Any]:
        # Support both URL params and POST form-data/x-www-form-urlencoded from Grafana
        if request.method == "POST":
            try:
                form = await request.form()
                query = query or form.get("query")
                service_id = service_id or form.get("service_id")
                start = start if start is not None else (float(form.get("start")) if form.get("start") else None)
                end = end if end is not None else (float(form.get("end")) if form.get("end") else None)
                step = step if step is not None else (float(form.get("step")) if form.get("step") else None)
            except Exception:
                pass

        query = query or "sim_red_request_rate_rps"
        records, _ = await _scrape_all_red()
        for k, v in _LABEL_RE.findall(query):
            if k in ("service_id", "service_name"):
                service_id = service_id or v

        metric_enum_filter: str | None = None
        if "error_rate" in query:
            metric_enum_filter = "error_rate"
        elif "latency_p95" in query:
            metric_enum_filter = "latency_p95"
        elif "request_rate" in query:
            metric_enum_filter = "request_rate"

        filtered = records
        if service_id:
            filtered = [r for r in filtered if r.get("service_id") == service_id]
        if metric_enum_filter:
            filtered = [r for r in filtered if r.get("metric_enum") == metric_enum_filter]

        now_epoch = time.time()
        
        # If Grafana requested a time range (query_range), return matrix format
        if start is not None and end is not None:
            step_val = max(1.0, float(step or 15.0))
            t_points = []
            curr_t = float(start)
            while curr_t <= float(end):
                t_points.append(curr_t)
                curr_t += step_val
            if not t_points or t_points[-1] < float(end):
                t_points.append(float(end))

            matrix_result = [
                {
                    "metric": {
                        "__name__": query.split("{")[0].strip(),
                        "service_id": r["service_id"],
                        "service_name": r["service.name"],
                        "environment": r["environment"],
                        "build_version": r["build_version"],
                        "metric_enum": r["metric_enum"],
                    },
                    "values": [[t, str(r["value"])] for t in t_points],
                }
                for r in filtered
            ]
            return {
                "status": "success",
                "data": {"resultType": "matrix", "result": matrix_result},
                "records": filtered,
            }

        result = [
            {
                "metric": {
                    "__name__": query.split("{")[0].strip(),
                    "service_id": r["service_id"],
                    "service_name": r["service.name"],
                    "environment": r["environment"],
                    "build_version": r["build_version"],
                    "metric_enum": r["metric_enum"],
                },
                "value": [now_epoch, str(r["value"])],
            }
            for r in filtered
        ]
        return {
            "status": "success",
            "data": {"resultType": "vector", "result": result},
            "records": filtered,
        }

    @app.get("/api/v1/alerts")
    @app.get("/api/v1/rules")
    async def get_alerts() -> dict[str, Any]:
        records, _ = await _scrape_all_red()
        logs = await _fetch_recent_logs()
        alerts = evaluate_alert_rules(metrics=records, logs=logs)
        signed = package_signed_alert_deliveries(alerts)
        return {
            "status": "success",
            "evaluated_at": utc_now_iso(),
            "alerts": alerts,
            "signed_deliveries": signed,
        }

    return app


def create_grafana_app() -> FastAPI:
    """Create the read-only Grafana visualization server (:3000) loading C05 provisioned files."""
    app = FastAPI(title="C05 Synthetic Grafana Server", version="0.1.0-sim")
    base_dir = pathlib.Path(__file__).resolve().parent / "grafana"
    dashboard_path = base_dir / "dashboards" / "sre-sim-overview.json"

    @app.get("/api/health")
    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {
            "commit": "c05-sim",
            "database": "ok",
            "version": "11.2.0-sim",
            "timestamp": utc_now_iso(),
        }

    @app.get("/api/datasources")
    async def datasources() -> list[dict[str, Any]]:
        return [
            {
                "uid": "prom-sim-lab",
                "name": "Prometheus",
                "type": "prometheus",
                "url": "http://prometheus:9090",
                "isDefault": True,
            },
            {
                "uid": "loki-sim-lab",
                "name": "Loki",
                "type": "loki",
                "url": "http://loki:3100",
                "isDefault": False,
            },
            {
                "uid": "tempo-sim-lab",
                "name": "Tempo",
                "type": "tempo",
                "url": "http://tempo:3200",
                "isDefault": False,
            },
        ]

    @app.get("/api/search")
    async def search_dashboards() -> list[dict[str, Any]]:
        return [
            {
                "uid": "sre-sim-overview-v1",
                "title": "SRE Agentic Lab - RED Metrics, Logs & Traces Overview",
                "type": "dash-db",
                "tags": ["sre-sim", "c05", "observability"],
            }
        ]

    @app.get("/api/dashboards/uid/{uid}")
    async def get_dashboard(uid: str) -> JSONResponse:
        if uid != "sre-sim-overview-v1" or not dashboard_path.exists():
            return JSONResponse(status_code=404, content={"message": "Dashboard not found"})
        dash = json.loads(dashboard_path.read_text(encoding="utf-8"))
        return JSONResponse(status_code=200, content={"dashboard": dash, "meta": {"slug": uid}})

    return app


loki_app = create_loki_app()
tempo_app = create_tempo_app()
otel_collector_app = create_otel_collector_app()
prometheus_app = create_prometheus_app()
grafana_app = create_grafana_app()

