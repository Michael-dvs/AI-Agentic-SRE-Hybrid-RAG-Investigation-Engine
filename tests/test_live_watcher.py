import pathlib

from fastapi import FastAPI
from starlette.testclient import TestClient

from observability.backends import (
    create_loki_app,
    create_prometheus_app,
    create_tempo_app,
)
from gateway.audit import SecurityAuditLogger
from orchestrator.live_watcher import LiveAlertWatcher
from orchestrator.llm_investigator import LLMInvestigator, LLMRunLedger
from orchestrator.llm_provider import OPENROUTER_MODEL, ProviderReply, ReplayProvider
from orchestrator.usability_console import DashboardRepository, ReviewActionController


def _make_mock_prom_with_alert() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/alerts")
    async def alerts():
        return {
            "status": "success",
            "alerts": [
                {
                    "alert_id": "alt-tx-5xx-test01",
                    "service_id": "transaction-service",
                    "service.name": "transaction-service",
                    "environment": "lab",
                    "alert_type": "SimHighErrorRate",
                    "severity": "critical",
                    "error_code": "ERR_TRANSACTION_FAILED",
                    "summary": "HTTP 500 error rate exceeded threshold on transaction-service",
                    "event_time": "2026-11-22T14:00:00Z",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                }
            ],
        }

    @app.get("/api/v1/query_range")
    @app.get("/api/v1/query")
    async def query():
        return {"status": "success", "data": {"resultType": "vector", "result": []}, "records": []}

    @app.get("/loki/api/v1/query_range")
    async def loki_query():
        return {
            "status": "success",
            "records": [
                {
                    "timestamp": "2026-11-22T14:00:00Z",
                    "service_id": "transaction-service",
                    "service.name": "transaction-service",
                    "severity": "ERROR",
                    "error_code": "ERR_TRANSACTION_FAILED",
                    "message": "HTTP 500 error rate exceeded threshold on transaction-service",
                    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                }
            ],
        }

    @app.get("/api/traces/{trace_id}")
    async def tempo_trace(trace_id: str):
        return {"traceID": trace_id, "batches": []}

    @app.get("/api/search")
    async def tempo_search():
        return {"traces": []}

    return app


def test_live_alert_watcher_populates_active_and_archive_via_review(tmp_path: pathlib.Path):
    db_path = str(tmp_path / "test_state.db")
    prom_app = _make_mock_prom_with_alert()
    prom_client = TestClient(prom_app)

    watcher = LiveAlertWatcher(
        state_db=db_path,
        prometheus_url="http://127.0.0.1:19090",
        loki_url="http://127.0.0.1:13100",
        tempo_url="http://127.0.0.1:13200",
        cooldown_sec=60.0,
        alerts_client=prom_client,
        telemetry_client=prom_client,
        use_env_llm=False,
    )

    results = watcher.poll_once()
    assert len(results) == 1
    inc_id = results[0]["incident_id"]
    assert results[0]["state"] == "HUMAN_REVIEW"

    # Cooldown prevents duplicate incident on immediate re-poll
    assert watcher.poll_once() == []

    repo = DashboardRepository(watcher.store)
    active = repo.active_dossiers()
    assert len(active) == 1
    assert active[0]["incident"]["incident_id"] == inc_id
    assert repo.archived_dossiers() == []

    # Human review moves incident from Active Incidents -> Archive Incidents
    controller = ReviewActionController(
        watcher.store,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
    )
    controller.apply(
        active[0]["dossier"],
        "APPROVE",
        reviewer_ref="sre_reviewer",
        reviewer_role="L2_SRE",
        rationale="Verified synthetic 5xx burst on transaction-service.",
    )

    assert repo.active_dossiers() == []
    archived = repo.archived_dossiers()
    assert len(archived) == 1
    assert archived[0]["incident"]["incident_id"] == inc_id
