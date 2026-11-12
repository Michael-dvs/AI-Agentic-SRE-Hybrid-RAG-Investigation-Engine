"""Synthetic Transaction Microservice (transaction-service).

Orchestrates synthetic transaction lifecycle, persists ledger entries via
ledger-service, and publishes asynchronous completion events to RabbitMQ.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
    format_traceparent,
    get_telemetry_context,
    outbound_headers,
    utc_now_iso,
)


class TransactionExecuteRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=4, max_length=128)
    account_id: str = Field(..., min_length=4, max_length=64)
    counterparty_id: str = Field(..., min_length=4, max_length=64)
    amount: float = Field(..., gt=0.0, le=1_000_000_000.0)
    currency: str = Field(default="IDR", pattern="^(IDR|USD|SGD)$")
    channel: str = Field(default="mobile-sim", min_length=2, max_length=64)
    subject: str = Field(default="synth-user-001", max_length=128)


def publish_to_rabbitmq(config: ServiceConfig, event_payload: dict[str, Any]) -> None:
    """Publish a persistent JSON event to the configured RabbitMQ queue."""
    import pika

    params = pika.URLParameters(config.rabbitmq_url)
    params.socket_timeout = 3.0
    params.connection_attempts = 1
    conn = pika.BlockingConnection(params)
    try:
        channel = conn.channel()
        channel.queue_declare(queue=config.rabbitmq_queue, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=config.rabbitmq_queue,
            body=json.dumps(event_payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=event_payload.get("correlation_id"),
            ),
        )
    finally:
        if conn.is_open:
            conn.close()


def create_app(
    config: ServiceConfig | None = None,
    http_client: httpx.AsyncClient | None = None,
    event_publisher: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> FastAPI:
    cfg = config or load_service_config(
        default_service_id="transaction-service",
        default_component="transaction",
        default_dependencies=["ledger-service", "notification-service"],
    )
    metrics = MetricsRegistry(cfg)
    fault_controller = FaultStateController(cfg)
    app = FastAPI(title="Synthetic Transaction Service", version=cfg.build_version)
    app.state.config = cfg
    app.state.metrics = metrics
    app.state.fault_controller = fault_controller
    app.state.http_client = http_client
    app.state.event_publisher = event_publisher

    async def _request_ledger(
        method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> httpx.Response:
        url = f"{cfg.ledger_service_url.rstrip('/')}{path}"
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
                error_code="ERR_LEDGER_UPSTREAM_UNAVAILABLE",
                message=f"Ledger service unreachable at {cfg.ledger_service_url}: {exc}",
            ) from exc

    async def readiness_check() -> tuple[bool, dict[str, Any]]:
        try:
            resp = await _request_ledger("GET", "/health/ready")
            ledger_ok = resp.status_code == 200
        except ServiceError:
            ledger_ok = False
        return ledger_ok, {"ledger_service_ready": ledger_ok}

    app.add_middleware(ObservabilityMiddleware, config=cfg, metrics=metrics)
    register_exception_handlers(app, cfg)
    register_fault_control_endpoints(app, cfg, fault_controller)
    register_standard_endpoints(app, cfg, metrics, readiness_check=readiness_check)

    @app.post("/internal/transactions/execute")
    async def execute_transaction(payload: TransactionExecuteRequest) -> JSONResponse:
        corr_id, trace_id, span_id = get_telemetry_context()
        if payload.account_id == payload.counterparty_id:
            raise ServiceError(
                status_code=400,
                error_code="ERR_SAME_ACCOUNT_TRANSFER",
                message="Source account_id and counterparty_id must be distinct",
            )

        tx_hash = hashlib.sha256(payload.idempotency_key.encode("utf-8")).hexdigest()[:16]
        transaction_id = f"tx-{tx_hash}"

        ledger_resp = await _request_ledger(
            "POST",
            "/internal/ledger/entries",
            json_body={
                "transaction_id": transaction_id,
                "idempotency_key": payload.idempotency_key,
                "account_id": payload.account_id,
                "counterparty_id": payload.counterparty_id,
                "amount": payload.amount,
                "currency": payload.currency,
                "channel": payload.channel,
            },
        )

        if ledger_resp.status_code == 409:
            err_data = ledger_resp.json()
            raise ServiceError(
                status_code=409,
                error_code=err_data.get("error_code", "ERR_IDEMPOTENCY_KEY_CONFLICT"),
                message=err_data.get("message", "Idempotency key conflict"),
            )

        if ledger_resp.status_code >= 500:
            raise ServiceError(
                status_code=503,
                error_code="ERR_LEDGER_UPSTREAM_UNAVAILABLE",
                message=f"Ledger service returned status {ledger_resp.status_code}",
            )

        ledger_data = ledger_resp.json()
        entry = ledger_data["entry"]
        idempotent_replay = bool(ledger_data.get("idempotent_replay", False))

        event_id = f"evt-{tx_hash}"
        event_payload = {
            "event_id": event_id,
            "event_type": "transaction.completed",
            "transaction_id": entry["transaction_id"],
            "idempotency_key": payload.idempotency_key,
            "account_id": payload.account_id,
            "counterparty_id": payload.counterparty_id,
            "amount": entry["amount"],
            "currency": entry["currency"],
            "channel": entry["channel"],
            "correlation_id": corr_id,
            "trace_id": trace_id,
            "traceparent": format_traceparent(trace_id, span_id),
            "published_at": utc_now_iso(),
            "retry_count": 0,
        }

        notification_dispatch = "SKIPPED_IDEMPOTENT_REPLAY"
        if not idempotent_replay:
            try:
                custom_pub = app.state.event_publisher
                if custom_pub is not None:
                    res = custom_pub(event_payload)
                    if hasattr(res, "__await__"):
                        await res
                    notification_dispatch = "PUBLISHED_CUSTOM"
                elif cfg.rabbitmq_enabled:
                    publish_to_rabbitmq(cfg, event_payload)
                    notification_dispatch = "PUBLISHED_RABBITMQ"
                else:
                    notification_dispatch = "DISABLED"
            except Exception as exc:
                emit_structured_log(
                    config=cfg,
                    severity="ERROR",
                    event_type="transaction.queue_publish_failed",
                    message=f"Failed to publish notification event {event_id}: {exc}",
                    error_code="ERR_QUEUE_UNAVAILABLE",
                    correlation_id=corr_id,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                raise ServiceError(
                    status_code=503,
                    error_code="ERR_QUEUE_UNAVAILABLE",
                    message=f"Asynchronous event queue unavailable: {exc}",
                ) from exc

        emit_structured_log(
            config=cfg,
            severity="INFO",
            event_type="transaction.executed",
            message=(
                f"Executed transaction {entry['transaction_id']} "
                f"(idempotent_replay={idempotent_replay}, dispatch={notification_dispatch})"
            ),
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )

        status_code = 200 if idempotent_replay else 201
        return JSONResponse(
            status_code=status_code,
            content={
                "transaction_id": entry["transaction_id"],
                "entry_id": entry["entry_id"],
                "idempotency_key": entry["idempotency_key"],
                "account_id": entry["account_id"],
                "counterparty_id": entry["counterparty_id"],
                "amount": entry["amount"],
                "currency": entry["currency"],
                "channel": entry["channel"],
                "status": entry["status"],
                "idempotent_replay": idempotent_replay,
                "notification_event_id": event_id,
                "notification_dispatch": notification_dispatch,
                "created_at": entry["created_at"],
                "service_id": cfg.service_id,
                "correlation_id": corr_id,
                "trace_id": trace_id,
            },
            headers={
                "X-Correlation-ID": corr_id,
                "traceparent": format_traceparent(trace_id, span_id),
            },
        )

    @app.get("/internal/transactions/{transaction_id}")
    async def get_transaction(transaction_id: str) -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        resp = await _request_ledger("GET", f"/internal/ledger/entries/{transaction_id}")
        if resp.status_code == 404:
            raise ServiceError(
                status_code=404,
                error_code="ERR_TRANSACTION_NOT_FOUND",
                message=f"Transaction '{transaction_id}' not found",
            )
        if resp.status_code >= 500:
            raise ServiceError(
                status_code=503,
                error_code="ERR_LEDGER_UPSTREAM_UNAVAILABLE",
                message=f"Ledger service returned {resp.status_code}",
            )
        data = resp.json()
        entry = data["entry"]
        return {
            "transaction_id": entry["transaction_id"],
            "entry_id": entry["entry_id"],
            "idempotency_key": entry["idempotency_key"],
            "account_id": entry["account_id"],
            "counterparty_id": entry["counterparty_id"],
            "amount": entry["amount"],
            "currency": entry["currency"],
            "channel": entry["channel"],
            "status": entry["status"],
            "created_at": entry["created_at"],
            "service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }

    return app


app = create_app()

