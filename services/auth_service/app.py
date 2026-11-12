"""Synthetic Auth Microservice (auth-service).

Validates synthetic bearer tokens and authorizes scopes for synthetic accounts.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from services.common.catalog import register_standard_endpoints
from services.common.config import ServiceConfig, load_service_config
from services.common.errors import ServiceError, register_exception_handlers
from services.common.fault_control import (
    FaultStateController,
    register_fault_control_endpoints,
)
from services.common.telemetry import (
    MetricsRegistry,
    ObservabilityMiddleware,
    emit_structured_log,
    get_telemetry_context,
    utc_now_iso,
)

SYNTHETIC_TOKENS: dict[str, dict[str, Any]] = {
    "SYNTH-TOKEN-ACTIVE-001": {
        "subject": "synth-user-001",
        "status": "active",
        "scopes": ["transactions:read", "transactions:write"],
        "allowed_accounts": ["SYNTH-ACC-001", "SYNTH-ACC-002", "SYNTH-ACC-003", "*"],
    },
    "SYNTH-TOKEN-ACTIVE-002": {
        "subject": "synth-user-002",
        "status": "active",
        "scopes": ["transactions:read", "transactions:write"],
        "allowed_accounts": ["SYNTH-ACC-002", "SYNTH-ACC-003", "*"],
    },
    "SYNTH-TOKEN-READONLY-001": {
        "subject": "synth-auditor-001",
        "status": "active",
        "scopes": ["transactions:read"],
        "allowed_accounts": ["SYNTH-ACC-001", "SYNTH-ACC-002"],
    },
    "SYNTH-TOKEN-RESTRICTED-ACC": {
        "subject": "synth-user-restricted",
        "status": "active",
        "scopes": ["transactions:read", "transactions:write"],
        "allowed_accounts": ["SYNTH-ACC-999"],
    },
    "SYNTH-TOKEN-EXPIRED-001": {
        "subject": "synth-user-expired",
        "status": "expired",
        "scopes": ["transactions:read", "transactions:write"],
        "allowed_accounts": ["SYNTH-ACC-001"],
    },
}


class AuthVerifyRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    required_scope: str = Field(default="transactions:write", min_length=1, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)


class AuthVerifyResponse(BaseModel):
    authenticated: bool
    authorized: bool
    subject: str
    scopes: list[str]
    account_id: str | None
    verified_at: str
    correlation_id: str
    trace_id: str | None


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    cfg = config or load_service_config(
        default_service_id="auth-service",
        default_component="auth",
        default_dependencies=[],
    )
    metrics = MetricsRegistry(cfg)
    fault_controller = FaultStateController(cfg)
    app = FastAPI(title="Synthetic Auth Service", version=cfg.build_version)
    app.state.config = cfg
    app.state.metrics = metrics
    app.state.fault_controller = fault_controller

    app.add_middleware(ObservabilityMiddleware, config=cfg, metrics=metrics)
    register_exception_handlers(app, cfg)
    register_fault_control_endpoints(app, cfg, fault_controller)
    register_standard_endpoints(app, cfg, metrics)

    @app.post("/internal/auth/verify", response_model=AuthVerifyResponse)
    async def verify_token(payload: AuthVerifyRequest) -> AuthVerifyResponse:
        corr_id, trace_id, span_id = get_telemetry_context()
        raw_token = payload.token.strip()
        if raw_token.lower().startswith("bearer "):
            raw_token = raw_token[7:].strip()

        record = SYNTHETIC_TOKENS.get(raw_token)
        if record is None:
            raise ServiceError(
                status_code=401,
                error_code="ERR_AUTH_INVALID_TOKEN",
                message="Synthetic token is unrecognized or invalid",
            )

        if record["status"] != "active":
            raise ServiceError(
                status_code=401,
                error_code="ERR_AUTH_TOKEN_EXPIRED",
                message=f"Synthetic token status is {record['status']}",
            )

        if payload.required_scope not in record["scopes"]:
            raise ServiceError(
                status_code=403,
                error_code="ERR_AUTH_INSUFFICIENT_SCOPE",
                message=f"Principal lacks required scope '{payload.required_scope}'",
                details={"required_scope": payload.required_scope, "granted_scopes": record["scopes"]},
            )

        allowed_accounts = record["allowed_accounts"]
        if (
            payload.account_id
            and "*" not in allowed_accounts
            and payload.account_id not in allowed_accounts
        ):
            raise ServiceError(
                status_code=403,
                error_code="ERR_AUTH_ACCOUNT_FORBIDDEN",
                message=f"Principal is not authorized for account '{payload.account_id}'",
            )

        emit_structured_log(
            config=cfg,
            severity="INFO",
            event_type="auth.token.verified",
            message=f"Verified principal {record['subject']} for scope {payload.required_scope}",
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )

        return AuthVerifyResponse(
            authenticated=True,
            authorized=True,
            subject=record["subject"],
            scopes=record["scopes"],
            account_id=payload.account_id,
            verified_at=utc_now_iso(),
            correlation_id=corr_id,
            trace_id=trace_id,
        )

    return app


app = create_app()

