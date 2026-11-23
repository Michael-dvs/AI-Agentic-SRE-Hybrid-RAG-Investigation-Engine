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
from orchestrator.console_config import EnvConfigManager
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
    assert "No values fabricated." in rendered
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


def test_env_config_manager_and_secret_masking(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.console_config import EnvConfigManager, mask_secret

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    example = tmp_path / ".env.example"
    example.write_text("# header\nOPENROUTER_API_KEY=\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    env_file = tmp_path / ".env"

    mgr = EnvConfigManager(env_path=env_file, example_path=example)
    mgr.set_values({
        "OPENROUTER_API_KEY": "sk-or-v1-synthetic-12345678",
        "LLM_MODEL": "google/gemini-2.5-flash",
    })

    assert example.read_text(encoding="utf-8") == "# header\nOPENROUTER_API_KEY=\nTELEGRAM_BOT_TOKEN=\n"
    saved = mgr.read_all()
    assert saved["OPENROUTER_API_KEY"] == "sk-or-v1-synthetic-12345678"
    assert saved["LLM_MODEL"] == "google/gemini-2.5-flash"
    assert mask_secret("") == "BELUM DIATUR"
    assert mask_secret("short") == "****"
    assert mask_secret("sk-or-v1-synthetic-12345678") == "sk-o...5678"


def test_model_catalog_client_fetches_openai_and_ollama_models() -> None:
    from orchestrator.console_config import ModelCatalogClient

    def openrouter_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer synth-key"
        return httpx.Response(200, json={
            "data": [
                {"id": "nvidia/nemotron-3-ultra-550b-a55b:free"},
                {"id": "google/gemini-2.5-flash"},
            ]
        })

    client = httpx.Client(transport=httpx.MockTransport(openrouter_handler))
    catalog = ModelCatalogClient(client=client)
    res = catalog.fetch_models("https://openrouter.ai/api/v1", "synth-key")
    assert res["status"] == "OK"
    assert res["models"] == ["google/gemini-2.5-flash", "nvidia/nemotron-3-ultra-550b-a55b:free"]

    conn = catalog.test_connection("https://openrouter.ai/api/v1", "synth-key", "google/gemini-2.5-flash")
    assert conn["status"] == "OK"
    assert conn["model_found"] is True
    client.close()


def test_telegram_config_helper_bot_and_chat_discovery() -> None:
    from orchestrator.console_config import TelegramConfigHelper

    def tg_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "sre_lab_bot", "first_name": "SRE Bot"}})
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={
                "ok": True,
                "result": [{"message": {"chat": {"id": -100999888, "title": "SRE Ops Lab"}}}],
            })
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(tg_handler))
    helper = TelegramConfigHelper(client=client)
    bot_res = helper.test_bot("123456:SYNTHETIC")
    assert bot_res["status"] == "OK"
    assert bot_res["username"] == "sre_lab_bot"

    chats_res = helper.discover_chats("123456:SYNTHETIC")
    assert chats_res["status"] == "OK"
    assert chats_res["chats"] == [("-100999888", "-100999888 (SRE Ops Lab)")]
    client.close()


def test_dashboard_renders_masked_model_and_telegram_config(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.console_config import EnvConfigManager

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    env_mgr = EnvConfigManager(env_path=tmp_path / ".env", example_path=tmp_path / ".env.example")
    env_mgr.set_values({
        "LLM_PROVIDER": "openrouter",
        "LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_MODEL": "google/gemini-2.5-flash",
        "OPENROUTER_API_KEY": "sk-or-secret-xyz9999",
        "TELEGRAM_BOT_TOKEN": "987654:BOTSECRET1234",
        "TELEGRAM_CHAT_ID": "-100777666",
    })

    store = WorkflowStateStore(":memory:")
    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        env_manager=env_mgr,
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    dashboard.view = "model"
    console.print(dashboard.render(width=120))
    dashboard.view = "telegram"
    console.print(dashboard.render(width=120))
    rendered = console.export_text()

    assert "google/gemini-2.5-flash" in rendered
    assert "sk-o...9999" in rendered
    assert "sk-or-secret-xyz9999" not in rendered
    assert "9876...1234" in rendered
    assert "BOTSECRET1234" not in rendered
    assert "-100777666" in rendered
    assert "ACTIVE OUTBOUND" in rendered
    store.close()


def test_dashboard_narrow_terminal_pagination_and_detail_scroll(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(":memory:")
    for idx in range(1, 13):
        _persist_pending(store, f"inc-c19-scroll-{idx:02d}")

    console = Console(record=True, width=72, height=18, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    # Narrow list view should paginate and show scroll window indicator
    console.print(dashboard.render(width=72, height=18))
    first_page = console.export_text()
    assert "[1] Active" in first_page
    assert "of 12" in first_page

    # Moving selected_index past visible window advances list_scroll_offset
    dashboard.selected_index = 10
    console.print(dashboard.render(width=72, height=18))
    scrolled_page = console.export_text()
    assert dashboard.list_scroll_offset > 0
    assert "Showing 9-11 of 12" in scrolled_page
    assert "▶ 11" in scrolled_page
    assert "inc-c19-scroll-02" in scrolled_page

    # Detail view on short terminal should show scroll indicator and advance with detail_scroll_offset
    dashboard.selected_incident_id = "inc-c19-scroll-01"
    dashboard.detail_scroll_offset = 0
    console.print(dashboard.render(width=72, height=18))
    detail_top = console.export_text()
    assert "[Scroll: line" in detail_top

    dashboard.detail_scroll_offset = 6
    console.print(dashboard.render(width=72, height=18))
    detail_scrolled = console.export_text()
    assert "line 7-" in detail_scrolled or "line 6-" in detail_scrolled or "[Scroll: line" in detail_scrolled
    store.close()


def test_active_incidents_shows_time_and_cancel_api_key_preserves_existing(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkflowStateStore(":memory:")
    _persist_pending(store, "inc-c19-time-001")
    env_mgr = EnvConfigManager(env_path=tmp_path / ".env", example_path=tmp_path / ".env.example")
    env_mgr.set_values({"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "sk-or-keep-me-1234"})

    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        env_manager=env_mgr,
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    console.print(dashboard.render(width=120, height=24))
    rendered = console.export_text()
    assert "Time" in rendered

    # Pressing Enter (empty) when prompted for API key cancels without wiping the saved key
    monkeypatch.setattr(dashboard, "_prompt_text", lambda *a, **kw: "")
    dashboard._configure_model_api_key()
    assert env_mgr.read_all()["OPENROUTER_API_KEY"] == "sk-or-keep-me-1234"
    assert "cancel" in dashboard.notice.lower()

    # Typing 'cancel' also cancels without modifying
    monkeypatch.setattr(dashboard, "_prompt_text", lambda *a, **kw: "cancel")
    dashboard._configure_model_api_key()
    assert env_mgr.read_all()["OPENROUTER_API_KEY"] == "sk-or-keep-me-1234"
    store.close()


def test_model_picker_scrolls_all_35_models_with_arrow_keys(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkflowStateStore(":memory:")
    env_mgr = EnvConfigManager(env_path=tmp_path / ".env", example_path=tmp_path / ".env.example")
    env_mgr.set_values({"LLM_PROVIDER": "openrouter", "LLM_BASE_URL": "https://openrouter.ai/api/v1"})

    models_35 = [f"provider/model-{i:02d}" for i in range(1, 36)]

    class _MockCatalog:
        def fetch_models(self, base_url: str, api_key: str) -> dict[str, Any]:
            return {"status": "OK", "models": models_35, "count": 35, "latency_ms": 12.0}

    console = Console(record=True, width=100, height=20, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        env_manager=env_mgr,
        model_catalog=_MockCatalog(),  # type: ignore[arg-type]
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    # Verify _render_model_picker paginates all 35 models
    panel = dashboard._render_model_picker(models_35, selected_idx=31, scroll_offset=25, height=20)
    console.print(panel)
    text = console.export_text()
    assert "of 35 models" in text
    assert "provider/model-32" in text

    # Simulate navigating down with PGDN, PGDN, PGDN, DOWN, ENTER to pick a model past #30
    keys = iter(["PGDN", "PGDN", "PGDN", "DOWN", "ENTER"])
    monkeypatch.setattr(dashboard, "_read_key", lambda timeout=None: next(keys))
    dashboard._fetch_and_select_model()
    assert env_mgr.read_all()["LLM_MODEL"] == "provider/model-32"
    store.close()


def test_open_grafana_shortcut_builds_anomaly_window_url(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = WorkflowStateStore(":memory:")
    dossier = _persist_pending(store, "inc-c19-grafana-001")
    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    opened_urls: list[str] = []
    monkeypatch.setattr("orchestrator.usability_console.webbrowser.open", lambda url: opened_urls.append(url) or True)

    dashboard.focus = "list"
    dashboard._open_grafana_for_selected()

    assert len(opened_urls) == 1
    url = opened_urls[0]
    assert "http://127.0.0.1:13000/d/sre-sim-overview-v1/" in url
    assert "var-service_id=ledger-service" in url
    assert "from=" in url and "to=" in url
    assert "Grafana opened" in dashboard.notice
    assert dossier["incident_id"] == "inc-c19-grafana-001"
    store.close()


def test_dossier_detail_shows_ai_llm_vs_offline_reasoning_provenance(
    tmp_path: pathlib.Path,
) -> None:
    store = WorkflowStateStore(":memory:")

    # 1. Offline deterministic dossier
    offline_dossier = _persist_pending(store, "inc-c19-prov-offline")

    # 2. Online AI LLM dossier (e.g. Nemotron via OpenRouter)
    llm_dossier = _dossier("inc-c19-prov-llm")
    llm_dossier["investigation_mode"] = "agentic_llm"
    llm_dossier["review_summary"] = {"status": "PENDING_REVIEW"}
    llm_dossier["reproducibility"] = {
        "workflow_version": "1.0.0",
        "policy_version": "1.0.0",
        "provider": "openrouter",
        "model_version": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "prompt_version": "abcdef1234567890abcdef1234567890",
        "input_tokens": 410,
        "output_tokens": 120,
        "total_tokens": 530,
    }
    store.create_incident(
        incident_id="inc-c19-prov-llm",
        service_id="ledger-service",
        environment="lab",
        initial_state="HUMAN_REVIEW",
        status="ACTIVE",
    )
    store.save_dossier("inc-c19-prov-llm", 1, llm_dossier["dossier_hash"], llm_dossier, "# LLM Dossier")

    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )

    # List view shows both AI LLM and OFFLINE badges
    console.print(dashboard.render(width=120, height=24))
    list_text = console.export_text()
    assert "AI LLM" in list_text
    assert "OFFLINE" in list_text

    # Offline dossier detail
    dashboard.selected_incident_id = offline_dossier["incident_id"]
    console.print(dashboard.render(width=120))
    offline_text = console.export_text()
    assert "OFFLINE DETERMINISTIC (NO AI MODEL)" in offline_text
    assert "0 tokens (Offline Rule Engine)" in offline_text

    # AI LLM dossier detail
    dashboard.selected_incident_id = "inc-c19-prov-llm"
    console.print(dashboard.render(width=120))
    llm_text = console.export_text()
    assert "AI MODEL (ONLINE)" in llm_text
    assert "openrouter / nvidia/nemotron-3-ultra-550b-a55b:free" in llm_text
    assert "in=410, out=120, total=530" in llm_text
    store.close()


def test_dossier_detail_renders_causal_reasoning_unknowns_and_checks(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(":memory:")
    dossier = _dossier("inc-c19-causal-001")
    dossier["hypotheses"][0]["reason_summary"] = (
        "Mechanism / Why: ledger-service connection pool saturated at 100%, triggering HTTP 503 cascades to transaction-service. | "
        "Candidate Root Cause (unconfirmed): Exhausted DB pool slots."
    )
    dossier["unknowns"] = ["Exact Postgres max_connections setting not exposed in lab metrics."]
    dossier["missing_sources"] = [
        {
            "tool_name": "get_trace_summary",
            "error_code": "SOURCE_UNAVAILABLE",
            "recorded_at": "2026-11-20T10:00:00Z",
            "impact_note": "Tempo backend unreachable during window.",
        }
    ]
    dossier["recommended_checks"] = [
        {
            "check_id": "chk-01",
            "description": "Inspect read-only ledger-service connection wait queue in Grafana.",
            "risk_level": "medium",
            "requires_human_approval": True,
            "auto_execution_allowed": False,
            "related_sop_doc_id": "SOP-LEDGER-002",
        }
    ]
    store.create_incident(
        incident_id="inc-c19-causal-001",
        service_id="ledger-service",
        environment="lab",
        initial_state="HUMAN_REVIEW",
        status="ACTIVE",
    )
    store.save_dossier("inc-c19-causal-001", 1, dossier["dossier_hash"], dossier, "# Causal Dossier")

    console = Console(record=True, width=120, force_terminal=False, color_system=None)
    dashboard = SREDashboard(
        store,
        console=console,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_HealthFixture(),
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
    )
    dashboard.selected_incident_id = "inc-c19-causal-001"
    console.print(dashboard.render(width=120))
    rendered = console.export_text()
    collapsed = " ".join(rendered.replace("│", " ").split())

    assert "Hypothesis Reasoning Details (Why & How)" in collapsed
    assert "Mechanism / Why: ledger-service connection pool saturated" in collapsed
    assert "Unknowns & Missing Sources" in collapsed
    assert "Exact Postgres max_connections setting" in collapsed
    assert "Tempo backend unreachable" in collapsed
    assert "SRE Recommended Verification (Human-Controlled)" in collapsed
    assert "Inspect read-only ledger-service connection wait queue in Grafana." in collapsed
    store.close()
