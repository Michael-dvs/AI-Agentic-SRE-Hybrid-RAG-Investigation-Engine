"""Deterministic error envelopes and exception handlers for C03 services."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.common.config import ServiceConfig
from services.common.telemetry import (
    emit_structured_log,
    format_traceparent,
    get_telemetry_context,
    utc_now_iso,
)


class ServiceError(Exception):
    """Structured error carrying HTTP status code and deterministic error_code."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def build_error_envelope(
    config: ServiceConfig,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    corr_id, trace_id, span_id = get_telemetry_context()
    envelope: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "service_id": config.service_id,
        "environment": config.environment,
        "correlation_id": corr_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "timestamp": utc_now_iso(),
    }
    if details:
        envelope["details"] = details
    return envelope


def register_exception_handlers(app: FastAPI, config: ServiceConfig) -> None:
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        request.state.last_error_code = exc.error_code
        corr_id, trace_id, span_id = get_telemetry_context()
        emit_structured_log(
            config=config,
            severity="ERROR" if exc.status_code >= 500 else "WARN",
            event_type="service.error",
            message=f"{exc.error_code}: {exc.message}",
            error_code=exc.error_code,
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        body = build_error_envelope(config, exc.error_code, exc.message, exc.details)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={
                "X-Correlation-ID": corr_id,
                "traceparent": format_traceparent(trace_id, span_id),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request.state.last_error_code = "ERR_INVALID_PAYLOAD"
        corr_id, trace_id, span_id = get_telemetry_context()
        msg = f"Invalid request payload or parameters: {exc.errors()}"
        emit_structured_log(
            config=config,
            severity="WARN",
            event_type="request.validation_failed",
            message=msg,
            error_code="ERR_INVALID_PAYLOAD",
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        body = build_error_envelope(
            config,
            "ERR_INVALID_PAYLOAD",
            "Request payload failed contract validation",
            {"validation_errors": exc.errors()},
        )
        return JSONResponse(
            status_code=422,
            content=body,
            headers={
                "X-Correlation-ID": corr_id,
                "traceparent": format_traceparent(trace_id, span_id),
            },
        )

