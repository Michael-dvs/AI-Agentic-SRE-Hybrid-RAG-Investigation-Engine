"""Synthetic Notification Microservice (notification-service).

Consumes asynchronous transaction completion events from RabbitMQ with explicit
acknowledgment, bounded retries (max 3 attempts before DLQ), and idempotent processing.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager
from contextvars import Context
from typing import Any, AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel, Field

from services.common.catalog import register_standard_endpoints
from services.common.config import ServiceConfig, load_service_config
from services.common.errors import ServiceError, register_exception_handlers
from services.common.fault_control import (
    ActiveFault,
    FaultStateController,
    register_fault_control_endpoints,
)
from services.common.telemetry import (
    MetricsRegistry,
    ObservabilityMiddleware,
    emit_structured_log,
    generate_span_id,
    get_parent_span_id,
    get_telemetry_context,
    parse_or_create_trace_context,
    record_span,
    set_telemetry_context,
    utc_now_iso,
)

MAX_RETRIES = 3


class NotificationEventPayload(BaseModel):
    event_id: str = Field(..., min_length=4, max_length=128)
    event_type: str = Field(default="transaction.completed", max_length=64)
    transaction_id: str = Field(..., min_length=4, max_length=64)
    idempotency_key: str = Field(..., min_length=4, max_length=128)
    account_id: str = Field(..., min_length=4, max_length=64)
    counterparty_id: str = Field(..., min_length=4, max_length=64)
    amount: float = Field(..., gt=0.0)
    currency: str = Field(default="IDR")
    channel: str = Field(default="mobile-sim")
    correlation_id: str = Field(..., min_length=4, max_length=128)
    trace_id: str | None = Field(default=None)
    traceparent: str | None = Field(default=None)
    published_at: str = Field(default_factory=utc_now_iso)
    retry_count: int = Field(default=0, ge=0, le=10)


class NotificationProcessor:
    """Thread-safe idempotent event consumer with bounded retries and DLQ tracking."""

    def __init__(self, config: ServiceConfig, max_retries: int = MAX_RETRIES) -> None:
        self.config = config
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._by_tx_id: dict[str, dict[str, Any]] = {}
        self._seen_event_ids: set[str] = set()
        self._attempt_tracker: dict[str, int] = {}
        self._dlq_events: list[dict[str, Any]] = []
        self._backlog_buffer: list[NotificationEventPayload] = []
        self.processed_count = 0
        self.duplicate_ignored_count = 0
        self.retried_count = 0
        self.dlq_count = 0
        self.consumer_connected = False
        self.consumer_lag_active = False
        self.consumer_lag_delay_ms = 0
        self._consumer_lag_generation = 0
        self.rabbit_backlog_depth = 0

    def set_consumer_lag(self, active: bool, delay_ms: int = 0) -> None:
        flush_items: list[NotificationEventPayload] = []
        with self._lock:
            if self.consumer_lag_active != active:
                self._consumer_lag_generation += 1
            self.consumer_lag_active = active
            self.consumer_lag_delay_ms = delay_ms if active else 0
            if not active and self._backlog_buffer:
                flush_items = list(self._backlog_buffer)
                self._backlog_buffer.clear()
        for item in flush_items:
            self.process_event(item)

    def process_event(self, payload: NotificationEventPayload) -> dict[str, Any]:
        """Process an incoming event idempotently with bounded retry rules."""
        start_iso = utc_now_iso()
        t0 = time.perf_counter()
        corr_id, trace_id, span_id = parse_or_create_trace_context(
            payload.traceparent, payload.correlation_id
        )
        parent_span_id = get_parent_span_id()
        if payload.trace_id and len(payload.trace_id) == 32:
            trace_id = payload.trace_id
        active_span_id = span_id or generate_span_id()
        set_telemetry_context(
            corr_id,
            trace_id,
            active_span_id,
            parent_span_id=parent_span_id,
            service_id=self.config.service_id,
        )

        with self._lock:
            if self.consumer_lag_active:
                self._backlog_buffer.append(payload)
                depth = len(self._backlog_buffer) + self.rabbit_backlog_depth
                emit_structured_log(
                    config=self.config,
                    severity="WARN",
                    event_type="notification.consumer.lag_backlog",
                    message=(
                        f"Notification consumer throttled ({self.consumer_lag_delay_ms}ms); "
                        f"event {payload.event_id} queued in backlog (depth={depth})"
                    ),
                    error_code="WARN_QUEUE_CONSUMER_LAG",
                    correlation_id=corr_id,
                    trace_id=trace_id,
                    span_id=active_span_id,
                )
                record_span(
                    config=self.config,
                    trace_id=trace_id,
                    span_id=active_span_id,
                    parent_span_id=parent_span_id,
                    correlation_id=corr_id,
                    span_name=f"QUEUE backlog {self.config.rabbitmq_queue}",
                    span_kind="CONSUMER",
                    relation_type="async_queue",
                    from_service_id="transaction-service",
                    to_service_id=self.config.service_id,
                    http_method="AMQP",
                    http_path=self.config.rabbitmq_queue,
                    status_code=202,
                    error_code="WARN_QUEUE_CONSUMER_LAG",
                    start_time=start_iso,
                    end_time=utc_now_iso(),
                    duration_ms=float(self.consumer_lag_delay_ms),
                )
                return {
                    "status": "QUEUED_BACKLOG",
                    "acknowledged": False,
                    "backlog_depth": depth,
                }

            if (
                payload.event_id in self._seen_event_ids
                or payload.transaction_id in self._by_tx_id
            ):
                self.duplicate_ignored_count += 1
                existing = self._by_tx_id.get(payload.transaction_id, {})
                emit_structured_log(
                    config=self.config,
                    severity="INFO",
                    event_type="notification.duplicate_ignored",
                    message=(
                        f"Ignored duplicate notification event {payload.event_id} "
                        f"for tx {payload.transaction_id}"
                    ),
                    correlation_id=corr_id,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                return {
                    "status": "DUPLICATE_IGNORED",
                    "acknowledged": True,
                    "idempotent_replay": True,
                    "notification": existing,
                }

            attempts = self._attempt_tracker.get(payload.event_id, payload.retry_count) + 1
            self._attempt_tracker[payload.event_id] = attempts

            # Deterministic transient failure simulation for bounded-retry verification
            should_fail = (
                (payload.channel == "fail-once-sim" and attempts == 1)
                or (payload.channel == "fail-dlq-sim")
            )

            if should_fail:
                if attempts <= self.max_retries:
                    self.retried_count += 1
                    emit_structured_log(
                        config=self.config,
                        severity="WARN",
                        event_type="notification.delivery.retry_scheduled",
                        message=(
                            f"Transient delivery failure for event {payload.event_id} "
                            f"(attempt {attempts}/{self.max_retries}); scheduling retry"
                        ),
                        error_code="ERR_NOTIFICATION_TRANSIENT_FAILURE",
                        correlation_id=corr_id,
                        trace_id=trace_id,
                        span_id=span_id,
                    )
                    return {
                        "status": "RETRY_SCHEDULED",
                        "acknowledged": False,
                        "retry_count": attempts,
                        "max_retries": self.max_retries,
                    }

                self.dlq_count += 1
                dlq_record = {
                    "event_id": payload.event_id,
                    "transaction_id": payload.transaction_id,
                    "attempts": attempts,
                    "reason": "MAX_RETRIES_EXCEEDED",
                    "correlation_id": corr_id,
                    "trace_id": trace_id,
                    "failed_at": utc_now_iso(),
                }
                self._dlq_events.append(dlq_record)
                emit_structured_log(
                    config=self.config,
                    severity="ERROR",
                    event_type="notification.delivery.dlq",
                    message=(
                        f"Event {payload.event_id} for tx {payload.transaction_id} "
                        f"exceeded max retries ({self.max_retries}); moved to DLQ"
                    ),
                    error_code="ERR_NOTIFICATION_MAX_RETRIES_EXCEEDED",
                    correlation_id=corr_id,
                    trace_id=trace_id,
                    span_id=span_id,
                )
                return {
                    "status": "DEAD_LETTERED",
                    "acknowledged": True,
                    "dlq_record": dlq_record,
                }

            record = {
                "notification_id": f"ntf-{payload.transaction_id[3:]}",
                "event_id": payload.event_id,
                "transaction_id": payload.transaction_id,
                "idempotency_key": payload.idempotency_key,
                "account_id": payload.account_id,
                "counterparty_id": payload.counterparty_id,
                "amount": payload.amount,
                "currency": payload.currency,
                "channel": payload.channel,
                "delivery_status": "DELIVERED_ACKED",
                "attempts": attempts,
                "correlation_id": corr_id,
                "trace_id": trace_id,
                "delivered_at": utc_now_iso(),
            }
            self._seen_event_ids.add(payload.event_id)
            self._by_tx_id[payload.transaction_id] = record
            self.processed_count += 1

        emit_structured_log(
            config=self.config,
            severity="INFO",
            event_type="notification.consumed",
            message=(
                f"Delivered and acknowledged notification {record['notification_id']} "
                f"for tx {payload.transaction_id}"
            ),
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=active_span_id,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        record_span(
            config=self.config,
            trace_id=trace_id,
            span_id=active_span_id,
            parent_span_id=parent_span_id,
            correlation_id=corr_id,
            span_name=f"QUEUE consume {self.config.rabbitmq_queue}",
            span_kind="CONSUMER",
            relation_type="async_queue",
            from_service_id="transaction-service",
            to_service_id=self.config.service_id,
            http_method="AMQP",
            http_path=self.config.rabbitmq_queue,
            status_code=200,
            error_code=None,
            start_time=start_iso,
            end_time=utc_now_iso(),
            duration_ms=elapsed_ms,
        )
        return {
            "status": "DELIVERED_ACKED",
            "acknowledged": True,
            "idempotent_replay": False,
            "notification": record,
        }

    def get_by_transaction_id(self, transaction_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._by_tx_id.get(transaction_id)

    def snapshot_stats(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._by_tx_id.values())[-50:]
            backlog = len(self._backlog_buffer) + self.rabbit_backlog_depth
            return {
                "processed_count": self.processed_count,
                "duplicate_ignored_count": self.duplicate_ignored_count,
                "retried_count": self.retried_count,
                "dlq_count": self.dlq_count,
                "consumer_connected": self.consumer_connected,
                "consumer_lag_active": self.consumer_lag_active,
                "backlog_depth": backlog,
                "notifications": items,
                "dlq_events": list(self._dlq_events[-20:]),
            }


class RabbitMQConsumerWorker:
    """Background consumer reading from RabbitMQ with explicit ack and bounded retries."""

    def __init__(self, config: ServiceConfig, processor: NotificationProcessor) -> None:
        self.config = config
        self.processor = processor
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.rabbitmq_enabled:
            self.processor.consumer_connected = True
            return
        self._thread = threading.Thread(
            target=self._run_loop, name="rabbitmq-consumer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        import pika
        last_lag_log_at: float | None = None
        lag_generation = self.processor._consumer_lag_generation

        while not self._stop_event.is_set():
            connection = None
            try:
                params = pika.URLParameters(self.config.rabbitmq_url)
                params.socket_timeout = 3.0
                params.connection_attempts = 1
                params.retry_delay = 1.0
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                channel.queue_declare(queue=self.config.rabbitmq_queue, durable=True)
                channel.queue_declare(queue=self.config.rabbitmq_dlq, durable=True)
                channel.basic_qos(prefetch_count=10)
                self.processor.consumer_connected = True

                while not self._stop_event.is_set() and connection.is_open:
                    if self.processor.consumer_lag_active:
                        if lag_generation != self.processor._consumer_lag_generation:
                            lag_generation = self.processor._consumer_lag_generation
                            last_lag_log_at = None
                        q_state = channel.queue_declare(
                            queue=self.config.rabbitmq_queue, durable=True, passive=True
                        )
                        self.processor.rabbit_backlog_depth = int(
                            q_state.method.message_count
                        )
                        if self.processor.rabbit_backlog_depth > 0:
                            now = time.monotonic()
                            if last_lag_log_at is None or now - last_lag_log_at >= 1.0:
                                Context().run(
                                    emit_structured_log,
                                    config=self.config,
                                    severity="WARN",
                                    event_type="notification.consumer.lag_backlog",
                                    message=(
                                        "Notification consumer backlog detected "
                                        f"(depth={self.processor.rabbit_backlog_depth})"
                                    ),
                                    error_code="WARN_QUEUE_CONSUMER_LAG",
                                    trace_absent_reason="BACKGROUND_WORKER_NO_ACTIVE_SPAN",
                                )
                                last_lag_log_at = now
                        else:
                            last_lag_log_at = None
                        connection.process_data_events(time_limit=0.1)
                        time.sleep(0.1)
                        continue

                    last_lag_log_at = None
                    self.processor.rabbit_backlog_depth = 0
                    method_frame, properties, body = channel.basic_get(
                        queue=self.config.rabbitmq_queue, auto_ack=False
                    )
                    if method_frame is None:
                        connection.process_data_events(time_limit=0.1)
                        time.sleep(0.05)
                        continue

                    try:
                        raw = json.loads(body.decode("utf-8"))
                        event = NotificationEventPayload(**raw)
                        outcome = self.processor.process_event(event)
                        if outcome["status"] == "RETRY_SCHEDULED":
                            raw["retry_count"] = outcome["retry_count"]
                            channel.basic_publish(
                                exchange="",
                                routing_key=self.config.rabbitmq_queue,
                                body=json.dumps(raw).encode("utf-8"),
                                properties=pika.BasicProperties(delivery_mode=2),
                            )
                            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                        elif outcome["status"] == "DEAD_LETTERED":
                            channel.basic_publish(
                                exchange="",
                                routing_key=self.config.rabbitmq_dlq,
                                body=json.dumps(outcome["dlq_record"]).encode("utf-8"),
                                properties=pika.BasicProperties(delivery_mode=2),
                            )
                            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                        else:
                            channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    except Exception as parse_exc:
                        emit_structured_log(
                            config=self.config,
                            severity="ERROR",
                            event_type="notification.malformed_message",
                            message=f"Rejected malformed queue message: {parse_exc}",
                            error_code="ERR_MALFORMED_QUEUE_EVENT",
                            trace_absent_reason="BACKGROUND_WORKER_NO_ACTIVE_SPAN",
                        )
                        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
            except Exception:
                self.processor.consumer_connected = False
                time.sleep(1.0)
            finally:
                if connection is not None and connection.is_open:
                    try:
                        connection.close()
                    except Exception:
                        pass


def create_app(
    config: ServiceConfig | None = None,
    processor: NotificationProcessor | None = None,
) -> FastAPI:
    cfg = config or load_service_config(
        default_service_id="notification-service",
        default_component="notification_worker",
        default_dependencies=[],
    )
    proc = processor or NotificationProcessor(cfg)
    worker = RabbitMQConsumerWorker(cfg, proc)
    metrics = MetricsRegistry(cfg)

    def _sync_notif_faults(active: list[ActiveFault]) -> None:
        lag_fault = next(
            (f for f in active if f.fault_mode == "queue_consumer_lag"), None
        )
        if lag_fault is not None:
            proc.set_consumer_lag(True, lag_fault.delay_ms)
        else:
            proc.set_consumer_lag(False, 0)

    fault_controller = FaultStateController(cfg, on_change=_sync_notif_faults)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        worker.start()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(
        title="Synthetic Notification Service",
        version=cfg.build_version,
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.metrics = metrics
    app.state.processor = proc
    app.state.worker = worker
    app.state.fault_controller = fault_controller

    async def readiness_check() -> tuple[bool, dict[str, Any]]:
        if not cfg.rabbitmq_enabled:
            return True, {"queue_mode": "in_process", "consumer_connected": True}
        return proc.consumer_connected, {
            "queue_mode": "rabbitmq",
            "consumer_connected": proc.consumer_connected,
            "queue_name": cfg.rabbitmq_queue,
        }

    app.add_middleware(ObservabilityMiddleware, config=cfg, metrics=metrics)
    register_exception_handlers(app, cfg)
    register_fault_control_endpoints(app, cfg, fault_controller)
    register_standard_endpoints(app, cfg, metrics, readiness_check=readiness_check)

    @app.post("/internal/notifications/consume")
    async def consume_event_direct(payload: NotificationEventPayload) -> dict[str, Any]:
        """Direct event consumption endpoint for deterministic in-process & retry testing."""
        return proc.process_event(payload)

    @app.get("/internal/notifications")
    async def list_notifications() -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        stats = proc.snapshot_stats()
        stats["service_id"] = cfg.service_id
        stats["correlation_id"] = corr_id
        stats["trace_id"] = trace_id
        return stats

    @app.get("/internal/notifications/{transaction_id}")
    async def get_notification(transaction_id: str) -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        item = proc.get_by_transaction_id(transaction_id)
        if item is None:
            raise ServiceError(
                status_code=404,
                error_code="ERR_NOTIFICATION_NOT_FOUND",
                message=f"No delivered notification found for transaction_id '{transaction_id}'",
            )
        return {
            "notification": item,
            "service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }

    return app


app = create_app()

