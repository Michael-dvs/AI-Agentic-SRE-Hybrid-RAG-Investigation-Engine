"""Synthetic API Gateway Microservice (api-gateway).

Public lab entry point handling request validation, correlation/trace propagation,
Auth integration, Transaction routing, and topology/notification read inspection.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.common.catalog import build_catalog_entry, register_standard_endpoints
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
    format_traceparent,
    get_telemetry_context,
    outbound_headers,
    utc_now_iso,
)


class GatewayTransactionRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=4, max_length=128)
    account_id: str = Field(..., min_length=4, max_length=64)
    counterparty_id: str = Field(..., min_length=4, max_length=64)
    amount: float = Field(..., gt=0.0, le=1_000_000_000.0)
    currency: str = Field(default="IDR", pattern="^(IDR|USD|SGD)$")
    channel: str = Field(default="mobile-sim", min_length=2, max_length=64)


def _extract_token(authorization: str | None, x_synthetic_token: str | None) -> str:
    if authorization and authorization.strip():
        raw = authorization.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        if raw:
            return raw
    if x_synthetic_token and x_synthetic_token.strip():
        return x_synthetic_token.strip()
    raise ServiceError(
        status_code=401,
        error_code="ERR_AUTH_MISSING_TOKEN",
        message="Missing Authorization Bearer token or X-Synthetic-Token header",
    )


def create_app(
    config: ServiceConfig | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    cfg = config or load_service_config(
        default_service_id="api-gateway",
        default_component="gateway",
        default_dependencies=["auth-service", "transaction-service"],
    )
    metrics = MetricsRegistry(cfg)
    fault_controller = FaultStateController(cfg)
    app = FastAPI(title="Synthetic API Gateway", version=cfg.build_version)
    app.state.config = cfg
    app.state.metrics = metrics
    app.state.fault_controller = fault_controller
    app.state.http_client = http_client

    service_urls = {
        "api-gateway": "http://api-gateway:8000",
        "auth-service": cfg.auth_service_url,
        "transaction-service": cfg.transaction_service_url,
        "ledger-service": cfg.ledger_service_url,
        "notification-service": cfg.notification_service_url,
    }

    async def _proxy_fault_command(
        target_service: str,
        path: str,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        base_url = service_urls.get(target_service)
        if not base_url:
            raise ServiceError(
                status_code=400,
                error_code="ERR_INVALID_FAULT_TARGET",
                message=f"Unknown fault target service '{target_service}'",
            )
        url = f"{base_url.rstrip('/')}{path}"
        client = app.state.http_client
        if client is not None:
            resp = await client.post(
                url, content=raw_body, headers=headers, timeout=cfg.request_timeout_sec
            )
        else:
            async with httpx.AsyncClient(timeout=cfg.request_timeout_sec) as ac:
                resp = await ac.post(url, content=raw_body, headers=headers)
        return resp.status_code, resp.json()

    async def _call_upstream(
        base_url: str,
        method: str,
        path: str,
        upstream_error_code: str,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{base_url.rstrip('/')}{path}"
        headers = outbound_headers()
        client = app.state.http_client
        try:
            if client is not None:
                return await client.request(
                    method, url, json=json_body, headers=headers, timeout=cfg.request_timeout_sec
                )
            async with httpx.AsyncClient(timeout=cfg.request_timeout_sec) as ac:
                return await ac.request(method, url, json=json_body, headers=headers)
        except Exception as exc:
            raise ServiceError(
                status_code=503,
                error_code=upstream_error_code,
                message=f"Upstream dependency unreachable at {base_url}: {exc}",
            ) from exc

    async def _verify_auth(
        token: str, required_scope: str, account_id: str | None = None
    ) -> dict[str, Any]:
        resp = await _call_upstream(
            cfg.auth_service_url,
            "POST",
            "/internal/auth/verify",
            "ERR_AUTH_UPSTREAM_UNAVAILABLE",
            json_body={
                "token": token,
                "required_scope": required_scope,
                "account_id": account_id,
            },
        )
        if resp.status_code in (401, 403):
            err_body = resp.json()
            raise ServiceError(
                status_code=resp.status_code,
                error_code=err_body.get("error_code", "ERR_AUTH_DENIED"),
                message=err_body.get("message", "Authentication or authorization denied"),
                details=err_body.get("details"),
            )
        if resp.status_code >= 500:
            raise ServiceError(
                status_code=503,
                error_code="ERR_AUTH_UPSTREAM_UNAVAILABLE",
                message=f"Auth service returned {resp.status_code}",
            )
        return resp.json()

    async def readiness_check() -> tuple[bool, dict[str, Any]]:
        checks: dict[str, bool] = {}
        for name, url, err_code in [
            ("auth-service", cfg.auth_service_url, "ERR_AUTH_UPSTREAM_UNAVAILABLE"),
            (
                "transaction-service",
                cfg.transaction_service_url,
                "ERR_TRANSACTION_UPSTREAM_UNAVAILABLE",
            ),
        ]:
            try:
                r = await _call_upstream(url, "GET", "/health/ready", err_code)
                checks[name] = r.status_code == 200
            except ServiceError:
                checks[name] = False
        return all(checks.values()), checks

    app.add_middleware(ObservabilityMiddleware, config=cfg, metrics=metrics)
    register_exception_handlers(app, cfg)
    register_fault_control_endpoints(
        app, cfg, fault_controller, proxy_dispatcher=_proxy_fault_command
    )
    register_standard_endpoints(app, cfg, metrics, readiness_check=readiness_check)

    @app.post("/api/v1/transactions")
    async def submit_transaction(
        payload: GatewayTransactionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_synthetic_token: str | None = Header(default=None),
    ) -> JSONResponse:
        corr_id, trace_id, span_id = get_telemetry_context()
        token = _extract_token(authorization, x_synthetic_token)
        auth_info = await _verify_auth(
            token=token,
            required_scope="transactions:write",
            account_id=payload.account_id,
        )

        tx_resp = await _call_upstream(
            cfg.transaction_service_url,
            "POST",
            "/internal/transactions/execute",
            "ERR_TRANSACTION_UPSTREAM_UNAVAILABLE",
            json_body={
                "idempotency_key": payload.idempotency_key,
                "account_id": payload.account_id,
                "counterparty_id": payload.counterparty_id,
                "amount": payload.amount,
                "currency": payload.currency,
                "channel": payload.channel,
                "subject": auth_info["subject"],
            },
        )

        if tx_resp.status_code >= 400:
            err_body = tx_resp.json()
            raise ServiceError(
                status_code=tx_resp.status_code,
                error_code=err_body.get("error_code", "ERR_TRANSACTION_FAILED"),
                message=err_body.get("message", "Transaction execution failed"),
                details=err_body.get("details"),
            )

        tx_data = tx_resp.json()
        emit_structured_log(
            config=cfg,
            severity="INFO",
            event_type="gateway.transaction.completed",
            message=(
                f"Gateway completed transaction {tx_data['transaction_id']} "
                f"for subject {auth_info['subject']} (status={tx_resp.status_code})"
            ),
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )

        response_body = {
            **tx_data,
            "authenticated_subject": auth_info["subject"],
            "gateway_service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }
        return JSONResponse(
            status_code=tx_resp.status_code,
            content=response_body,
            headers={
                "X-Correlation-ID": corr_id,
                "traceparent": format_traceparent(trace_id, span_id),
            },
        )

    @app.get("/api/v1/transactions/{transaction_id}")
    async def get_transaction_by_id(
        transaction_id: str,
        authorization: str | None = Header(default=None),
        x_synthetic_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        token = _extract_token(authorization, x_synthetic_token)
        await _verify_auth(token=token, required_scope="transactions:read")

        tx_resp = await _call_upstream(
            cfg.transaction_service_url,
            "GET",
            f"/internal/transactions/{transaction_id}",
            "ERR_TRANSACTION_UPSTREAM_UNAVAILABLE",
        )
        if tx_resp.status_code >= 400:
            err_body = tx_resp.json()
            raise ServiceError(
                status_code=tx_resp.status_code,
                error_code=err_body.get("error_code", "ERR_TRANSACTION_LOOKUP_FAILED"),
                message=err_body.get("message", "Transaction lookup failed"),
            )

        tx_data = tx_resp.json()
        notification_info: dict[str, Any] | None = None
        try:
            ntf_resp = await _call_upstream(
                cfg.notification_service_url,
                "GET",
                f"/internal/notifications/{transaction_id}",
                "ERR_NOTIFICATION_UPSTREAM_UNAVAILABLE",
            )
            if ntf_resp.status_code == 200:
                notification_info = ntf_resp.json().get("notification")
        except ServiceError:
            notification_info = None

        return {
            **tx_data,
            "notification": notification_info,
            "gateway_service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }

    @app.get("/api/v1/notifications")
    async def list_notifications_summary(
        authorization: str | None = Header(default=None),
        x_synthetic_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        token = _extract_token(authorization, x_synthetic_token)
        await _verify_auth(token=token, required_scope="transactions:read")
        ntf_resp = await _call_upstream(
            cfg.notification_service_url,
            "GET",
            "/internal/notifications",
            "ERR_NOTIFICATION_UPSTREAM_UNAVAILABLE",
        )
        return ntf_resp.json()

    @app.get("/api/v1/notifications/{transaction_id}")
    async def get_notification_by_tx_id(
        transaction_id: str,
        authorization: str | None = Header(default=None),
        x_synthetic_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        token = _extract_token(authorization, x_synthetic_token)
        await _verify_auth(token=token, required_scope="transactions:read")
        ntf_resp = await _call_upstream(
            cfg.notification_service_url,
            "GET",
            f"/internal/notifications/{transaction_id}",
            "ERR_NOTIFICATION_UPSTREAM_UNAVAILABLE",
        )
        if ntf_resp.status_code >= 400:
            err_body = ntf_resp.json()
            raise ServiceError(
                status_code=ntf_resp.status_code,
                error_code=err_body.get("error_code", "ERR_NOTIFICATION_NOT_FOUND"),
                message=err_body.get("message", "Notification not found"),
            )
        return ntf_resp.json()

    @app.get("/api/v1/topology")
    async def get_topology() -> dict[str, Any]:
        """Return all 5 service catalog entries and dependency edges."""
        corr_id, trace_id, _ = get_telemetry_context()
        catalogs = [build_catalog_entry(cfg)]
        for url, err_code in [
            (cfg.auth_service_url, "ERR_AUTH_UPSTREAM_UNAVAILABLE"),
            (cfg.transaction_service_url, "ERR_TRANSACTION_UPSTREAM_UNAVAILABLE"),
            (cfg.ledger_service_url, "ERR_LEDGER_UPSTREAM_UNAVAILABLE"),
            (cfg.notification_service_url, "ERR_NOTIFICATION_UPSTREAM_UNAVAILABLE"),
        ]:
            resp = await _call_upstream(url, "GET", "/catalog", err_code)
            if resp.status_code == 200:
                catalogs.append(resp.json())

        now = utc_now_iso()
        edges = [
            {
                "schema_version": "1.0",
                "edge_id": "edge-gw-auth",
                "from_service_id": "api-gateway",
                "to_service_id": "auth-service",
                "environment": cfg.environment,
                "deployment_version": cfg.build_version,
                "relation_type": "sync_http",
                "source_kind": "catalog_declared",
                "source_ref": "http://api-gateway:8000/api/v1/topology",
                "observed_at": now,
                "freshness_status": "fresh",
                "confidence": 1.0,
                "error_propagation_observed": False,
            },
            {
                "schema_version": "1.0",
                "edge_id": "edge-gw-tx",
                "from_service_id": "api-gateway",
                "to_service_id": "transaction-service",
                "environment": cfg.environment,
                "deployment_version": cfg.build_version,
                "relation_type": "sync_http",
                "source_kind": "catalog_declared",
                "source_ref": "http://api-gateway:8000/api/v1/topology",
                "observed_at": now,
                "freshness_status": "fresh",
                "confidence": 1.0,
                "error_propagation_observed": False,
            },
            {
                "schema_version": "1.0",
                "edge_id": "edge-tx-ledger",
                "from_service_id": "transaction-service",
                "to_service_id": "ledger-service",
                "environment": cfg.environment,
                "deployment_version": cfg.build_version,
                "relation_type": "sync_http",
                "source_kind": "catalog_declared",
                "source_ref": "http://api-gateway:8000/api/v1/topology",
                "observed_at": now,
                "freshness_status": "fresh",
                "confidence": 1.0,
                "error_propagation_observed": False,
            },
            {
                "schema_version": "1.0",
                "edge_id": "edge-ledger-db",
                "from_service_id": "ledger-service",
                "to_service_id": "db-dummy",
                "environment": cfg.environment,
                "deployment_version": cfg.build_version,
                "relation_type": "storage_call",
                "source_kind": "catalog_declared",
                "source_ref": "http://api-gateway:8000/api/v1/topology",
                "observed_at": now,
                "freshness_status": "fresh",
                "confidence": 1.0,
                "error_propagation_observed": False,
            },
            {
                "schema_version": "1.0",
                "edge_id": "edge-tx-notif",
                "from_service_id": "transaction-service",
                "to_service_id": "notification-service",
                "environment": cfg.environment,
                "deployment_version": cfg.build_version,
                "relation_type": "async_queue",
                "source_kind": "catalog_declared",
                "source_ref": "http://api-gateway:8000/api/v1/topology",
                "observed_at": now,
                "freshness_status": "fresh",
                "confidence": 1.0,
                "error_propagation_observed": False,
            },
        ]
        return {
            "services": catalogs,
            "dependency_edges": edges,
            "correlation_id": corr_id,
            "trace_id": trace_id,
            "observed_at": now,
        }

    return app


app = create_app()

