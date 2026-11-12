"""Synthetic Ledger Microservice (ledger-service).

Persists synthetic transaction ledger entries in PostgreSQL with duplicate prevention
on idempotency_key and transaction_id, and exposes read APIs.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
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
    format_traceparent,
    generate_span_id,
    get_extra_delay_ms,
    get_telemetry_context,
    record_span,
    utc_now_iso,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id VARCHAR(64) PRIMARY KEY,
    transaction_id VARCHAR(64) UNIQUE NOT NULL,
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    counterparty_id VARCHAR(64) NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    currency VARCHAR(16) NOT NULL,
    channel VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    correlation_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(64),
    created_at VARCHAR(64) NOT NULL
);
"""


class LedgerEntryCreateRequest(BaseModel):
    transaction_id: str = Field(..., min_length=4, max_length=64)
    idempotency_key: str = Field(..., min_length=4, max_length=128)
    account_id: str = Field(..., min_length=4, max_length=64)
    counterparty_id: str = Field(..., min_length=4, max_length=64)
    amount: float = Field(..., gt=0.0, le=1_000_000_000.0)
    currency: str = Field(default="IDR", pattern="^(IDR|USD|SGD)$")
    channel: str = Field(default="mobile-sim", min_length=2, max_length=64)


class LedgerStore:
    """Database adapter supporting PostgreSQL (psycopg) and SQLite fallback for local unit tests."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        parsed = urlparse(database_url)
        self.backend = "sqlite" if parsed.scheme.startswith("sqlite") else "postgres"
        self._lock = threading.Lock()
        self._sqlite_conn: sqlite3.Connection | None = None
        self._initialized = False
        self.force_unavailable = False

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self.force_unavailable:
            raise RuntimeError("Simulated database connection failure")

        if self.backend == "sqlite":
            path = self.database_url.replace("sqlite:///", "", 1) or ":memory:"
            with self._lock:
                if self._sqlite_conn is None:
                    self._sqlite_conn = sqlite3.connect(path, check_same_thread=False)
                    self._sqlite_conn.row_factory = sqlite3.Row
                yield self._sqlite_conn
        else:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(
                self.database_url,
                connect_timeout=3,
                row_factory=dict_row,
                autocommit=False,
            )
            try:
                yield conn
            finally:
                conn.close()

    def ensure_schema(self) -> None:
        if self._initialized and not self.force_unavailable:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(SCHEMA_SQL)
            conn.commit()
            self._initialized = True

    def ping(self) -> tuple[bool, str]:
        try:
            self.ensure_schema()
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
            return True, self.backend
        except Exception as exc:
            return False, str(exc)

    def create_or_get_entry(
        self,
        payload: LedgerEntryCreateRequest,
        correlation_id: str,
        trace_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Insert a ledger entry or return existing entry on duplicate idempotency_key.

        Returns (entry_dict, idempotent_replay_bool).
        """
        try:
            self.ensure_schema()
        except Exception as exc:
            raise ServiceError(
                status_code=503,
                error_code="ERR_DB_UNAVAILABLE",
                message=f"PostgreSQL ledger storage unavailable: {exc}",
            ) from exc

        entry_hash = hashlib.sha256(payload.idempotency_key.encode("utf-8")).hexdigest()[:16]
        entry_id = f"led-{entry_hash}"
        created_at = utc_now_iso()

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                if self.backend == "sqlite":
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO ledger_entries (
                            entry_id, transaction_id, idempotency_key,
                            account_id, counterparty_id, amount, currency,
                            channel, status, correlation_id, trace_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry_id,
                            payload.transaction_id,
                            payload.idempotency_key,
                            payload.account_id,
                            payload.counterparty_id,
                            round(float(payload.amount), 2),
                            payload.currency,
                            payload.channel,
                            "COMMITTED",
                            correlation_id,
                            trace_id,
                            created_at,
                        ),
                    )
                    inserted = cur.rowcount == 1
                    conn.commit()
                    cur.execute(
                        "SELECT * FROM ledger_entries WHERE idempotency_key = ? OR transaction_id = ?",
                        (payload.idempotency_key, payload.transaction_id),
                    )
                    row = dict(cur.fetchone())
                else:
                    cur.execute(
                        """
                        INSERT INTO ledger_entries (
                            entry_id, transaction_id, idempotency_key,
                            account_id, counterparty_id, amount, currency,
                            channel, status, correlation_id, trace_id, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        """,
                        (
                            entry_id,
                            payload.transaction_id,
                            payload.idempotency_key,
                            payload.account_id,
                            payload.counterparty_id,
                            round(float(payload.amount), 2),
                            payload.currency,
                            payload.channel,
                            "COMMITTED",
                            correlation_id,
                            trace_id,
                            created_at,
                        ),
                    )
                    inserted = cur.rowcount == 1
                    conn.commit()
                    cur.execute(
                        "SELECT * FROM ledger_entries WHERE idempotency_key = %s OR transaction_id = %s",
                        (payload.idempotency_key, payload.transaction_id),
                    )
                    row = dict(cur.fetchone())
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                status_code=503,
                error_code="ERR_DB_UNAVAILABLE",
                message=f"Failed to persist ledger entry: {exc}",
            ) from exc

        if not inserted:
            if (
                row["account_id"] != payload.account_id
                or row["counterparty_id"] != payload.counterparty_id
                or round(float(row["amount"]), 2) != round(float(payload.amount), 2)
                or row["currency"] != payload.currency
            ):
                raise ServiceError(
                    status_code=409,
                    error_code="ERR_IDEMPOTENCY_KEY_CONFLICT",
                    message=(
                        f"Idempotency key '{payload.idempotency_key}' was already used "
                        "with different transaction parameters"
                    ),
                )
            return row, True

        return row, False

    def get_by_transaction_id(self, transaction_id: str) -> dict[str, Any] | None:
        try:
            self.ensure_schema()
            with self._connect() as conn:
                cur = conn.cursor()
                if self.backend == "sqlite":
                    cur.execute(
                        "SELECT * FROM ledger_entries WHERE transaction_id = ?",
                        (transaction_id,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM ledger_entries WHERE transaction_id = %s",
                        (transaction_id,),
                    )
                fetched = cur.fetchone()
                return dict(fetched) if fetched else None
        except Exception as exc:
            raise ServiceError(
                status_code=503,
                error_code="ERR_DB_UNAVAILABLE",
                message=f"Database read failed: {exc}",
            ) from exc

    def list_entries(self, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        try:
            self.ensure_schema()
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS cnt FROM ledger_entries")
                cnt_row = cur.fetchone()
                total = int(cnt_row["cnt"] if isinstance(cnt_row, dict) or hasattr(cnt_row, "keys") else cnt_row[0])
                if self.backend == "sqlite":
                    cur.execute(
                        "SELECT * FROM ledger_entries ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM ledger_entries ORDER BY created_at DESC LIMIT %s",
                        (limit,),
                    )
                rows = [dict(r) for r in cur.fetchall()]
                return rows, total
        except Exception as exc:
            raise ServiceError(
                status_code=503,
                error_code="ERR_DB_UNAVAILABLE",
                message=f"Database list query failed: {exc}",
            ) from exc


def create_app(
    config: ServiceConfig | None = None,
    store: LedgerStore | None = None,
) -> FastAPI:
    cfg = config or load_service_config(
        default_service_id="ledger-service",
        default_component="ledger",
        default_dependencies=["db-dummy"],
    )
    ledger_store = store or LedgerStore(cfg.database_url)
    metrics = MetricsRegistry(cfg)

    def _sync_store_faults(active: list[ActiveFault]) -> None:
        ledger_store.force_unavailable = any(
            f.fault_mode == "dependency_unavailable" for f in active
        )

    fault_controller = FaultStateController(cfg, on_change=_sync_store_faults)
    app = FastAPI(title="Synthetic Ledger Service", version=cfg.build_version)
    app.state.config = cfg
    app.state.metrics = metrics
    app.state.store = ledger_store
    app.state.fault_controller = fault_controller

    async def readiness_check() -> tuple[bool, dict[str, Any]]:
        ok, info = ledger_store.ping()
        return ok, {"database_backend": ledger_store.backend, "status": info}

    app.add_middleware(ObservabilityMiddleware, config=cfg, metrics=metrics)
    register_exception_handlers(app, cfg)
    register_fault_control_endpoints(app, cfg, fault_controller)
    register_standard_endpoints(app, cfg, metrics, readiness_check=readiness_check)

    @app.post("/internal/ledger/entries")
    async def create_ledger_entry(payload: LedgerEntryCreateRequest) -> JSONResponse:
        corr_id, trace_id, span_id = get_telemetry_context()
        db_start_iso = utc_now_iso()
        t0 = time.perf_counter()
        try:
            entry, idempotent_replay = ledger_store.create_or_get_entry(
                payload=payload,
                correlation_id=corr_id,
                trace_id=trace_id,
            )
        except ServiceError as exc:
            db_ms = (time.perf_counter() - t0) * 1000.0 + get_extra_delay_ms()
            record_span(
                config=cfg,
                trace_id=trace_id,
                span_id=generate_span_id(),
                parent_span_id=span_id,
                correlation_id=corr_id,
                span_name="POSTGRESQL ledger_entries insert",
                span_kind="CLIENT",
                relation_type="storage_call",
                from_service_id="ledger-service",
                to_service_id="db-dummy",
                http_method="SQL",
                http_path="ledger_entries",
                status_code=exc.status_code,
                error_code=exc.error_code,
                start_time=db_start_iso,
                end_time=utc_now_iso(),
                duration_ms=db_ms,
                service_id_override="db-dummy",
                service_name_override="db-dummy",
            )
            raise

        extra_delay = get_extra_delay_ms()
        db_ms = (time.perf_counter() - t0) * 1000.0 + extra_delay
        record_span(
            config=cfg,
            trace_id=trace_id,
            span_id=generate_span_id(),
            parent_span_id=span_id,
            correlation_id=corr_id,
            span_name="POSTGRESQL ledger_entries insert",
            span_kind="CLIENT",
            relation_type="storage_call",
            from_service_id="ledger-service",
            to_service_id="db-dummy",
            http_method="SQL",
            http_path="ledger_entries",
            status_code=200 if idempotent_replay else 201,
            error_code="WARN_DB_SLOW_QUERY" if extra_delay >= 20.0 else None,
            start_time=db_start_iso,
            end_time=utc_now_iso(),
            duration_ms=db_ms,
            service_id_override="db-dummy",
            service_name_override="db-dummy",
        )
        event_type = (
            "ledger.entry.idempotent_replay"
            if idempotent_replay
            else "ledger.entry.persisted"
        )
        emit_structured_log(
            config=cfg,
            severity="INFO",
            event_type=event_type,
            message=(
                f"Ledger entry {entry['entry_id']} for tx {entry['transaction_id']} "
                f"(idempotent_replay={idempotent_replay})"
            ),
            correlation_id=corr_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        status_code = 200 if idempotent_replay else 201
        return JSONResponse(
            status_code=status_code,
            content={
                "entry": entry,
                "idempotent_replay": idempotent_replay,
                "service_id": cfg.service_id,
                "correlation_id": corr_id,
                "trace_id": trace_id,
            },
            headers={
                "X-Correlation-ID": corr_id,
                "traceparent": format_traceparent(trace_id, span_id),
            },
        )

    @app.get("/internal/ledger/entries/{transaction_id}")
    async def get_ledger_entry(transaction_id: str) -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        row = ledger_store.get_by_transaction_id(transaction_id)
        if row is None:
            raise ServiceError(
                status_code=404,
                error_code="ERR_LEDGER_ENTRY_NOT_FOUND",
                message=f"No ledger entry found for transaction_id '{transaction_id}'",
            )
        return {
            "entry": row,
            "service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }

    @app.get("/internal/ledger/entries")
    async def list_ledger_entries(
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        corr_id, trace_id, _ = get_telemetry_context()
        entries, total = ledger_store.list_entries(limit=limit)
        return {
            "entries": entries,
            "total_count": total,
            "limit": limit,
            "service_id": cfg.service_id,
            "correlation_id": corr_id,
            "trace_id": trace_id,
        }

    return app


app = create_app()

