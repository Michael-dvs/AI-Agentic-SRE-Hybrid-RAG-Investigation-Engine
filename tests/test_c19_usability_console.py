"""Chapter 19 Stage 1A tests for the Rich console and passive Telegram dispatcher."""

from __future__ import annotations

import pathlib
from typing import Any

import httpx
import pytest
from rich.console import Console

from observability.audit_chain import AuditHashChain, verify_chain_integrity
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer, compute_canonical_dossier_hash
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import (
    CostMetricsReader,
    ReviewActionController,
    SREDashboard,
)


def _dossier(incident_id: str) -> dict[str, Any]:
    context = {
        "incident_id": incident_id,
        "service_id": "ledger-service",
        "environment": "lab",
        "event_time": "2026-11-20T10:00:00Z",
        "priority": "critical",
        "message": "Database connection pool saturation caused elevated 5xx responses.",
        "investigation_scope": ["ledger-service", "transaction-service"],
        "query_window": {
            "start": "2026-11-20T09:55:00Z",
            "end": "2026-11-20T10:00:00Z",
        },
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "title": "Ledger connection pool saturation",
                "description": "Pool checkout latency and error logs align in the same window.",
                "candidate_cause": "connection_pool_saturation",
                "supporting_evidence_ids": ["ev-log-001", "ev-metric-001"],
                "refuting_evidence_ids": [],
                "confidence_score": 0.91,
                "status": "SUPPORTED",
            }
        ],
        "evidence_items": [
            {
                "evidence_id": "ev-log-001",
                "tool_name": "search_error_logs",
                "status": "ok",
                "data_quality": "complete",
                "source_ref": "loki:ledger-service",
                "observed_at": "2026-11-20T10:00:00Z",
                "query_window": {
                    "start": "2026-11-20T09:55:00Z",
                    "end": "2026-11-20T10:00:00Z",
                },
                "records": [{"message": "connection checkout timeout"}],
            }
        ],
        "runbook_citations": [
            {
                "chunk_id": "chunk-sop-ledger-002-04",
                "doc_id": "SOP-LEDGER-002",
                "document_version": "2.0.0",
                "section_path": "4.2 Pool saturation",
                "source_uri": "kb://sop-ledger-002",
                "content_hash": "a" * 64,
            }
        ],
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "model_version": "replay-c19",
            "prompt_version": "prompt-c19",
            "tool_schema_version": "1.0",
            "kb_version": "kb-c19",
        },
    }
    return DossierSerializer.serialize(context)


def _persist_pending(store: WorkflowStateStore, incident_id: str) -> dict[str, Any]:
    dossier = _dossier(incident_id)
    store.create_incident(
        incident_id=incident_id,
        service_id="ledger-service",
        environment="lab",
        initial_state="HUMAN_REVIEW",
        status="ACTIVE",
    )
    store.save_dossier(
        incident_id=incident_id,
        dossier_version=1,
        dossier_hash=dossier["dossier_hash"],
        dossier_json=dossier,
        dossier_markdown=DossierMarkdownRenderer.render(dossier),
    )
    return dossier


class _HealthFixture:
    def inspect(self) -> dict[str, Any]:
        return {
            "status": "OK",
            "reason": "",
            "services": [{"name": "ledger-service", "state": "running", "health": "healthy"}],
        }


def test_rich_dashboard_renders_wide_narrow_and_detail(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(":memory:")
    dossier = _persist_pending(store, "inc-c19-render-001")
    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
        telegram=TelegramDispatcher(bot_token="", chat_id=""),
    )

    console.print(dashboard.render(width=120))
    dashboard.selected_incident_id = dossier["incident_id"]
    console.print(dashboard.render(width=72))
    dashboard.selected_incident_id = None
    dashboard.view = "model"
    console.print(dashboard.render(width=120))
    rendered = console.export_text()

    assert "Active Incidents" in rendered
    assert "Observed Symptoms" in rendered
    assert "Ledger connection pool saturation" in rendered
    assert "SOP-LEDGER-002" in rendered
    assert "ev-log-001" in rendered
    assert "auto_action_triggered=False" in rendered
    assert "replay-c19" in rendered
    assert "Tidak ada nilai yang difabrikasi." in rendered
    assert "ground_truth" not in rendered.lower()
    store.close()


@pytest.mark.parametrize(
    ("action", "expected_state"),
    (("APPROVE", "CLOSED"), ("REJECT", "REJECTED"), ("CORRECT", "HUMAN_REVIEW")),
)
def test_review_actions_persist_state_hash_and_audit_chain(
    tmp_path: pathlib.Path,
    action: str,
    expected_state: str,
) -> None:
    store = WorkflowStateStore(":memory:")
    incident_id = f"inc-c19-{action.lower()}-001"
    dossier = _persist_pending(store, incident_id)
    audit_path = tmp_path / f"{action.lower()}-audit.jsonl"
    controller = ReviewActionController(
        store,
        audit_path=audit_path,
        handover_root=tmp_path / "handover",
    )

    result = controller.apply(
        dossier,
        action,
        reviewer_ref="sre_c19_reviewer",
        reviewer_role="L2_SRE",
        rationale=f"{action} verified against the displayed evidence.",
        corrected_hypothesis="Database pool exhaustion confirmed by correlated signals"
        if action == "CORRECT"
        else None,
    )

    assert result["auto_action_triggered"] is False
    assert store.get_incident(incident_id)["current_state"] == expected_state
    latest = store.get_dossier(incident_id)
    assert latest is not None
    assert len(latest["dossier_hash"]) == 64
    assert latest["dossier_hash"] == compute_canonical_dossier_hash(latest["dossier_json"])
    if action == "APPROVE":
        assert set(result["artifacts"]) == {"json", "markdown", "html"}
    elif action == "CORRECT":
        assert latest["dossier_version"] == 2
        assert store.get_dossier(incident_id, version=1) is not None

    reloaded_audit = AuditHashChain(log_path=audit_path)
    valid, violations = verify_chain_integrity(reloaded_audit.events)
    assert valid is True, violations
    assert reloaded_audit.events
    assert all(len(event["event_hash"]) == 64 for event in reloaded_audit.events)
    store.close()


def test_telegram_dispatcher_formats_allowlisted_message_and_dry_run() -> None:
    dossier = _dossier("inc-c19-telegram-001")
    dossier["ground_truth"] = "MUST_NOT_LEAK"
    dossier["holdout_id"] = "H-G4-MUST_NOT_LEAK"
    dispatcher = TelegramDispatcher(bot_token="", chat_id="")

    result = dispatcher.dispatch_pending_review(dossier)

    assert result.status == "DRY_RUN"
    assert result.dry_run is True
    assert result.delivered is False
    assert "inc-c19-telegram-001" in result.message
    assert "ledger-service" in result.message
    assert "Database connection pool saturation" in result.message
    assert "Ledger connection pool saturation" in result.message
    assert "SOP-LEDGER-002" in result.message
    assert "python3 scripts/sre_dashboard.py" in result.message
    assert "MUST_NOT_LEAK" not in result.message
    assert "H-G4" not in result.message


def test_telegram_dispatcher_network_failure_returns_safe_fallback() -> None:
    def fail_request(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("lab network unavailable", request=request)

    client = httpx.Client(transport=httpx.MockTransport(fail_request))
    dispatcher = TelegramDispatcher(
        bot_token="synthetic-token",
        chat_id="synthetic-chat",
        client=client,
    )

    result = dispatcher.dispatch_pending_review(_dossier("inc-c19-telegram-002"))

    assert result.status == "FALLBACK"
    assert result.delivered is False
    assert result.dry_run is False
    assert result.reason.startswith("NETWORK_UNAVAILABLE:")
    client.close()


def test_non_pending_dossier_is_not_dispatched() -> None:
    dossier = _dossier("inc-c19-telegram-closed")
    dossier["review_summary"]["status"] = "APPROVED"
    dispatcher = TelegramDispatcher(bot_token="synthetic-token", chat_id="synthetic-chat")

    result = dispatcher.dispatch_pending_review(dossier)

    assert result.status == "SKIPPED"
    assert result.delivered is False
    assert result.reason == "DOSSIER_NOT_PENDING_REVIEW"
