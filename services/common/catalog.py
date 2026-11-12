"""Service catalog builder and common health/metrics route registration."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from services.common.config import ServiceConfig
from services.common.errors import ServiceError
from services.common.telemetry import (
    MetricsRegistry,
    get_recent_logs,
    get_recent_spans,
    utc_now_iso,
)


def build_catalog_entry(config: ServiceConfig) -> dict[str, Any]:
    """Return a service-catalog.v1.schema.json compliant dictionary."""
    return {
        "schema_version": "1.0",
        "service_id": config.service_id,
        "service.name": config.service_name,
        "environment": config.environment,
        "application": config.application,
        "component": config.component,
        "instance_id": config.instance_id,
        "build_version": config.build_version,
        "owner_ref": config.owner_ref,
        "dependency_refs": config.dependency_refs,
        "health_endpoints": {
            "liveness_path": "/health/live",
            "readiness_path": "/health/ready",
            "metrics_path": "/metrics",
        },
        "updated_at": utc_now_iso(),
    }


def register_standard_endpoints(
    app: FastAPI,
    config: ServiceConfig,
    metrics: MetricsRegistry,
    readiness_check: Callable[[], Awaitable[tuple[bool, dict[str, Any]]]] | None = None,
) -> None:
    """Attach /health/live, /healthz, /health/ready, /readyz, /metrics, and /catalog."""

    @app.get("/health/live")
    @app.get("/healthz")
    async def liveness() -> dict[str, Any]:
        return {
            "status": "alive",
            "service_id": config.service_id,
            "environment": config.environment,
            "build_version": config.build_version,
            "timestamp": utc_now_iso(),
        }

    @app.get("/health/ready")
    @app.get("/readyz")
    async def readiness() -> JSONResponse:
        if readiness_check is not None:
            ok, details = await readiness_check()
            if not ok:
                raise ServiceError(
                    status_code=503,
                    error_code="ERR_DEPENDENCY_UNAVAILABLE",
                    message=f"Service {config.service_id} dependencies are not ready",
                    details=details,
                )
        else:
            details = {"dependencies": "none"}

        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "service_id": config.service_id,
                "environment": config.environment,
                "build_version": config.build_version,
                "details": details,
                "timestamp": utc_now_iso(),
            },
        )

    @app.get("/metrics")
    async def get_metrics(
        request: Request,
        format: str | None = Query(default=None),
    ) -> Response:
        accept = request.headers.get("accept", "")
        if format == "json" or "application/json" in accept:
            return JSONResponse(content=metrics.snapshot_red())
        return PlainTextResponse(
            content=metrics.format_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/catalog")
    async def get_catalog() -> dict[str, Any]:
        return build_catalog_entry(config)

    @app.get("/internal/telemetry/recent", include_in_schema=False)
    async def get_service_telemetry_recent(
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        return {
            "service_id": config.service_id,
            "logs": get_recent_logs(service_id=config.service_id, limit=limit),
            "spans": (
                get_recent_spans(service_id=config.service_id, limit=limit)
                + (
                    get_recent_spans(service_id="db-dummy", limit=limit)
                    if config.service_id == "ledger-service"
                    else []
                )
            ),
            "metrics_red": metrics.snapshot_red(),
            "observed_at": utc_now_iso(),
        }

    @app.post("/internal/telemetry/reset", include_in_schema=False)
    async def reset_service_telemetry() -> dict[str, Any]:
        metrics.reset_samples()
        return {"status": "TELEMETRY_RESET", "service_id": config.service_id}

