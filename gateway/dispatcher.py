"""Read-only tool dispatcher routing calls to telemetry adapters and knowledge retrieval (C08, C09)."""

from __future__ import annotations

import datetime
from typing import Any

from starlette.testclient import TestClient

from gateway.adapters import (
    ApmAdapter,
    CatalogAdapter,
    LogsAdapter,
    MetricsAdapter,
    TracesAdapter,
)
from knowledge_base.ingestion.lifecycle import KnowledgeLifecycleManager
from knowledge_base.retrieval import RetrievalEngine, RetrievalService
from observability.backends import (
    create_loki_app,
    create_prometheus_app,
    create_tempo_app,
)


class ToolDispatcher:
    """Dispatches authorized read-only requests to corresponding telemetry adapters or retrieval service."""

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        metrics_adapter: MetricsAdapter | None = None,
        logs_adapter: LogsAdapter | None = None,
        traces_adapter: TracesAdapter | None = None,
        catalog_adapter: CatalogAdapter | None = None,
        apm_adapter: ApmAdapter | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.simulated_outages: set[str] = set()

        # Initialize retrieval service if not injected
        if self.retrieval_service is None:
            try:
                manager = KnowledgeLifecycleManager()
                manifest, _ = manager.build_manifest_from_corpus(
                    "knowledge_base/corpus", "kb-idx-20261111-v1"
                )
                engine = RetrievalEngine(chunks=manifest.chunks, index_version="kb-idx-20261111-v1")
                self.retrieval_service = RetrievalService(engine=engine)
            except Exception:
                self.retrieval_service = None

        # Setup adapters with in-process C05 apps if not provided
        self._prom_app = create_prometheus_app()
        self._loki_app = create_loki_app()
        self._tempo_app = create_tempo_app()

        # Seed baseline in-process telemetry for lab resilience
        self._seed_default_telemetry()

        self.metrics_adapter = metrics_adapter or MetricsAdapter(
            client=TestClient(self._prom_app)
        )
        self.logs_adapter = logs_adapter or LogsAdapter(
            client=TestClient(self._loki_app)
        )
        self.traces_adapter = traces_adapter or TracesAdapter(
            client=TestClient(self._tempo_app)
        )
        self.catalog_adapter = catalog_adapter or CatalogAdapter()
        self.apm_adapter = apm_adapter or ApmAdapter()

    def _seed_default_telemetry(self) -> None:
        # Seed baseline logs in loki
        self._loki_app.state.ingest_records([
            {
                "timestamp": "2026-11-12T00:01:00Z",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "severity": "ERROR",
                "error_code": "ERR_GATEWAY_TIMEOUT",
                "message": "Simulated operational error for api-gateway",
                "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            },
            {
                "timestamp": "2026-11-12T00:02:00Z",
                "service_id": "transaction-service",
                "service.name": "transaction-service",
                "severity": "ERROR",
                "error_code": "ERR_TRANSACTION_FAILED",
                "message": "Transaction processing failed for transaction-service",
                "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            },
        ])

        # Seed baseline traces in tempo
        self._tempo_app.state.ingest_spans([
            {
                "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                "span_id": "00f067aa0ba902b7",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "operation": "HTTP POST /transactions",
                "duration_ms": 324.5,
                "status_code": "ERROR",
                "start_time": "2026-11-12T00:01:00Z",
                "end_time": "2026-11-12T00:01:00.324Z",
            }
        ])

    def set_outage(self, tool_or_source: str, is_outage: bool) -> None:
        """Simulate backend outage for negative / resilience tests (EV-02, NFR-016)."""
        if is_outage:
            self.simulated_outages.add(tool_or_source)
            if tool_or_source in ("get_trace_summary", "tempo", "src-tempo-traces"):
                self._tempo_app.state.outage_state["unavailable"] = True
        else:
            self.simulated_outages.discard(tool_or_source)
            if tool_or_source in ("get_trace_summary", "tempo", "src-tempo-traces"):
                self._tempo_app.state.outage_state["unavailable"] = False

    def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        caller_groups: list[str] | None = None,
        caller_scope_ref: str = "principal:investigator-coord",
    ) -> tuple[dict[str, Any], str, str | None, str | None]:
        """Dispatch tool call and return (result_data, status, error_code, source_ref).

        Status is one of: 'ok', 'partial', 'unavailable', 'rejected'.
        """
        # Outage check
        if tool_name in self.simulated_outages or "all_backends" in self.simulated_outages:
            return {}, "unavailable", "SOURCE_UNAVAILABLE", f"src-{tool_name}"

        if tool_name == "retrieve_runbooks":
            if self.retrieval_service is None:
                return {}, "unavailable", "SOURCE_UNAVAILABLE", "src-knowledge-base"
            res = self.retrieval_service.execute_retrieval(
                request_data=arguments,
                caller_scope_ref=caller_scope_ref,
                caller_groups=caller_groups or ["sre-core-l1"],
            )
            return res.to_dict(), res.status, res.gap_reason, "src-knowledge-base"

        elif tool_name == "get_service_metrics":
            env = self.metrics_adapter.execute(arguments)
            if env.status != "ok":
                return {}, env.status, env.error_code, env.source_ref

            records = env.data if isinstance(env.data, list) else []
            return {
                "records": records,
                "data": records,
                "truncated": env.truncated,
                "data_quality": env.data_quality,
            }, env.status, env.error_code, env.source_ref

        elif tool_name == "search_error_logs":
            env = self.logs_adapter.execute(arguments)
            if env.status != "ok":
                return {}, env.status, env.error_code, env.source_ref
            records = env.data if isinstance(env.data, list) else []
            return {
                "records": records,
                "data": records,
                "truncated": env.truncated,
                "data_quality": env.data_quality,
            }, env.status, env.error_code, env.source_ref

        elif tool_name == "get_trace_summary":
            env = self.traces_adapter.execute(arguments)
            if env.status != "ok":
                return {}, env.status, env.error_code, env.source_ref
            records = env.data if isinstance(env.data, list) else []
            return {
                "records": records,
                "data": records,
                "truncated": env.truncated,
                "data_quality": env.data_quality,
            }, env.status, env.error_code, env.source_ref

        elif tool_name == "get_service_dependencies":
            env = self.catalog_adapter.execute(arguments)
            if env.status != "ok":
                return {}, env.status, env.error_code, env.source_ref
            records = env.data if isinstance(env.data, list) else []
            return {
                "records": records,
                "data": records,
                "truncated": env.truncated,
                "data_quality": env.data_quality,
            }, env.status, env.error_code, env.source_ref

        elif tool_name == "get_apm_health":
            env = self.apm_adapter.execute(arguments)
            return {
                "records": [],
                "data": env.data,
                "truncated": False,
                "data_quality": env.data_quality,
            }, env.status, env.error_code, env.source_ref

        return {}, "rejected", "TOOL_NOT_ALLOWED", None
