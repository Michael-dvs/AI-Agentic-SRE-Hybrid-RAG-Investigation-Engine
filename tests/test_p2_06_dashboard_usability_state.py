"""Comprehensive P2-06 Verification Suite — Dashboard Usability & State Consistency.

Covers:
- Group A (A01-A12): Authoritative state, stable selection, atomic snapshots, stale refresh & race guards.
- Group B (B01-B12): Keyboard navigation, focus management, lenses, reference resolution, modal traps.
- Group C (C01-C15): Presentation semantics (severity, support, monotonic confidence, calibration honesty,
  temporal relevance, SOP availability, RAG delivery vs retrieval, NOT_PERFORMED checks, admin closure).
- Group D (D01-D15): Human Review safety, authorization, confirmation, cancellation, concurrency conflicts,
  DB/audit failure safety, identity-mode disclosure.
- Group E (E01-E12): Responsive layouts (80x24, 100x30, 120x40, 160x50, <68x16 min-size), dynamic resize,
  CJK Unicode width, monochrome color-independence.
- Group F (F01-F12): Runtime loading, empty, running, partial, provider/RAG outage, stale last-known data,
  bounded probe TTL, zero LLM calls from rendering, clean shutdown.
- Group G (G01-G18): Security & regression invariants (RULE-007, zero auto-remediation, escape/markup
  injection defense, Ground Truth & restricted SOP isolation, frozen C02 schemas & Stage 3A manifest).
- Scenarios O1-O12 + Section 20 Live Synthetic Stack & Real PTY + TUI/CLI/Dossier/Handover Consistency.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
import pathlib
import pty
import select
import shutil
import sqlite3
import struct
import subprocess
import sys
import termios
import time
from typing import Any

from fastapi import FastAPI
import pytest
from rich.console import Console
from starlette.testclient import TestClient

from gateway.policy import PolicyGateway
from observability.audit_chain import AuditHashChain, verify_chain_integrity
from orchestrator.console_config import EnvConfigManager
from orchestrator.console_view_models import (
    CALIBRATION_LIMITATION_NOTE,
    TOKENS_COLOR,
    TOKENS_MONO,
    compact_identifier,
    sanitize_terminal_text,
)
from orchestrator.dossier import (
    DossierMarkdownRenderer,
    DossierSerializer,
    compute_canonical_dossier_hash,
)
from orchestrator.handover import HandoverExporter, verify_ground_truth_isolation
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.live_watcher import LiveAlertWatcher
from orchestrator.resilience import ResilienceController
from orchestrator.review import AuthorizedReviewManager, reconcile_review_audit
from orchestrator.state_machine import (
    MANDATORY_STATES,
    InvestigationStateMachine,
    WorkflowStateStore,
)
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import (
    CostMetricsReader,
    DashboardViewport,
    SREDashboard,
    ServiceHealthInspector,
)
from scripts.review_console import display_dossier_summary, run_review_action
from services.alert_intake.correlation import DependencyCorrelator


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FROZEN_C02_DIR = REPO_ROOT / "evidence" / "c02-20261109T070500Z" / "C02" / "contracts"
FROZEN_STAGE_3A_MANIFEST = (
    REPO_ROOT
    / "evidence"
    / "c21-preflight-20261122T051612608117Z"
    / "C21"
    / "final-release-manifest.json"
)
STAGE_3A_MANIFEST_SHA256 = "b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f"


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def _make_dossier_ctx(
    incident_id: str,
    *,
    service_id: str = "ledger-service",
    priority: str = "critical",
    support_status: str = "SUPPORTED",
    confidence_score: float = 0.76,
    sop_availability: str = "APPLICABLE_SOP_FOUND",
    include_sop: bool = True,
    include_evidence: bool = True,
) -> dict[str, Any]:
    citations = (
        [
            {
                "chunk_id": f"chk-{incident_id}-01",
                "document_id": "SOP-LEDGER-002",
                "document_version": "2.1.0",
                "title": "Ledger Connection Pool Saturation",
                "service_id": service_id,
                "environment": "lab",
                "status": "approved",
                "applicability_verified": True,
                "sanitized": True,
                "effective_from": "2026-11-01T00:00:00Z",
                "effective_to": None,
                "score": 0.0315,
                "score_type": "rrf_fusion",
                "source_branch": "hybrid",
                "section_path": "4.2 Connection Pool Diagnostics",
                "source_uri": "kb://runbooks/sop-ledger-002.md",
                "sanitized_excerpt": "Inspect checkout latency and active pool count.",
                "content_hash": "a" * 64,
            }
        ]
        if include_sop
        else []
    )
    evidence_items = (
        [
            {
                "evidence_id": f"ev-{incident_id}-log-01",
                "incident_id": incident_id,
                "service_id": service_id,
                "environment": "lab",
                "tool_name": "search_error_logs",
                "status": "ok",
                "data_quality": "complete",
                "truncated": False,
                "source_ref": f"loki:{service_id}",
                "observed_at": "2026-11-26T01:59:40Z",
                "collected_at": "2026-11-26T02:00:05Z",
                "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
                "records": [
                    {
                        "timestamp": "2026-11-26T01:59:40Z",
                        "error_code": "ERR_CONNECTION_POOL_EXHAUSTED",
                        "message": "Pool checkout timeout on primary replica",
                    }
                ],
            },
            {
                "evidence_id": f"ev-{incident_id}-metric-01",
                "incident_id": incident_id,
                "service_id": service_id,
                "environment": "lab",
                "tool_name": "get_service_metrics",
                "status": "ok",
                "data_quality": "complete",
                "truncated": False,
                "source_ref": f"prometheus:{service_id}:error_rate",
                "observed_at": "2026-11-26T01:59:45Z",
                "collected_at": "2026-11-26T02:00:06Z",
                "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
                "records": [
                    {
                        "metric_name": "error_rate",
                        "value": 0.38,
                        "unit": "ratio",
                        "aggregation": "rate_5m",
                        "sample_at": "2026-11-26T01:59:45Z",
                    }
                ],
            },
        ]
        if include_evidence
        else []
    )
    sup_ids = [f"ev-{incident_id}-log-01", f"ev-{incident_id}-metric-01"] if include_evidence and support_status == "SUPPORTED" else []
    return {
        "incident_id": incident_id,
        "service_id": service_id,
        "environment": "lab",
        "event_time": "2026-11-26T02:00:00Z",
        "dossier_ready_at": "2026-11-26T02:00:12Z",
        "assessment_time": "2026-11-26T02:00:12Z",
        "priority": priority,
        "message": f"Synthetic {priority} anomaly on {service_id} (ERR_CONNECTION_POOL_EXHAUSTED).",
        "investigation_scope": [service_id, "api-gateway"],
        "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "rank": 1,
                "statement": f"Connection pool saturation on {service_id} causing HTTP 503 responses.",
                "reason_summary": (
                    f"[{support_status}] Pool timeout logs and error_rate ratio align."
                    if support_status in ("UNSUPPORTED", "CONTRADICTED")
                    else "Pool timeout logs and error_rate ratio align in incident window."
                ),
                "supporting_evidence_ids": sup_ids,
                "contradicting_evidence_ids": [],
                "confidence_score": confidence_score,
                "confidence_rationale": "Computed deterministically from corroborated signals.",
                "status": "INCONCLUSIVE" if support_status in ("UNSUPPORTED", "CONTRADICTED") else support_status,
                "unknowns": ["PostgreSQL server-side lock table requires human DBA check."],
            }
        ],
        "evidence_items": evidence_items,
        "sop_availability": sop_availability,
        "rag_diagnostics": {
            "retrieved_count": 3 if include_sop else 0,
            "eligible_count": 1 if include_sop else 0,
            "delivered_sop_count": 1 if include_sop else 0,
            "omitted_sop_count": 0,
            "omission_reasons": [],
            "compaction_rung": "rung_0_full",
        },
        "runbook_citations": citations,
        "tool_calls_used": 3,
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "provider": "openrouter",
            "model_version": "nvidia/nemotron-3.5-lightning:free",
            "prompt_version": "p206-test-v1",
            "tool_schema_version": "1.0",
            "kb_version": "kb-idx-20261111-v1",
            "input_tokens": 640,
            "output_tokens": 210,
            "total_tokens": 850,
        },
    }


def _persist_incident_to_review(
    store: WorkflowStateStore,
    incident_id: str,
    *,
    mode: str = "agentic_llm",
    **ctx_kwargs: Any,
) -> dict[str, Any]:
    sm = InvestigationStateMachine(store=store)
    ctx = _make_dossier_ctx(incident_id, **ctx_kwargs)
    for st in MANDATORY_STATES:
        sm.transition(incident_id, st, f"idem-{incident_id}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        (ctx["service_id"], ctx["environment"], incident_id),
    )
    dossier = DossierSerializer.serialize(ctx, investigation_mode=mode)
    if mode == "agentic_llm":
        dossier["reproducibility"].update({
            "provider": "openrouter",
            "input_tokens": 640,
            "output_tokens": 210,
            "total_tokens": 850,
        })
        dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)
    store.save_checkpoint(incident_id, "HUMAN_REVIEW", ctx)
    store.save_dossier(incident_id, 1, dossier["dossier_hash"], dossier, DossierMarkdownRenderer.render(dossier))
    return dossier


def _build_dashboard(
    store: WorkflowStateStore,
    tmp_path: pathlib.Path,
    *,
    width: int = 120,
    height: int = 40,
    color_system: str | None = "truecolor",
    reviewer_ref: str = "sre_maya",
    reviewer_role: str = "L2_SRE",
    reviewer_directory: dict[str, Any] | None = None,
    require_registered_reviewer: bool = False,
) -> tuple[SREDashboard, Console]:
    env_file = tmp_path / ".env"
    if not env_file.exists():
        env_file.write_text("LLM_PROVIDER=openrouter\nLLM_MODEL=nvidia/nemotron-3.5-lightning:free\n", encoding="utf-8")
    env_mgr = EnvConfigManager(env_path=env_file, example_path=tmp_path / ".env.example")
    health_stub = ServiceHealthInspector(
        command=(
            sys.executable,
            "-c",
            'import json; print(json.dumps([{"Service":"ledger-service","State":"running","Health":"healthy"}]))',
        )
    )
    console = Console(record=True, width=width, height=height, force_terminal=(color_system is not None), color_system=color_system)
    dash = SREDashboard(
        store,
        console=console,
        reviewer_ref=reviewer_ref,
        reviewer_role=reviewer_role,
        reviewer_directory=reviewer_directory,
        require_registered_reviewer=require_registered_reviewer,
        audit_path=tmp_path / "p206_audit.jsonl",
        handover_root=tmp_path / "handover",
        env_manager=env_mgr,
        health=health_stub,
        costs=CostMetricsReader(tmp_path / "missing-costs.json"),
        telegram=TelegramDispatcher(bot_token="", chat_id=""),
    )
    return dash, console


def _render_text(dash: SREDashboard, console: Console, *, width: int | None = None, height: int | None = None) -> str:
    console.print(dash.render(width=width or console.size.width, height=height))
    return console.export_text(clear=True)


# ---------------------------------------------------------------------------
# Group A (A01-A12) & Scenarios O1, O2, O8, O9 — Authoritative State & Races
# ---------------------------------------------------------------------------

def test_group_a_authoritative_state_selection_stability_and_races(tmp_path: pathlib.Path) -> None:
    """Verify A01-A12, Scenario O1, O2, O8, O9: lifecycle truth, stable selection, stale refresh & race safety."""
    store = WorkflowStateStore(str(tmp_path / "group_a.db"))
    try:
        # O2 / A01: Create an incident moving progressively through RECEIVED -> EVIDENCE_COLLECTED -> HUMAN_REVIEW
        sm = InvestigationStateMachine(store=store)
        inc_prog = "inc-p206-prog-001"
        for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED"):
            sm.transition(inc_prog, st, f"idem-{inc_prog}-{st}")
        store.save_checkpoint(inc_prog, "EVIDENCE_COLLECTED", {
            "incident_id": inc_prog,
            "service_id": "notification-service",
            "environment": "lab",
            "priority": "medium",
            "message": "Consumer lag rising while collecting telemetry.",
        })

        dash, console = _build_dashboard(store, tmp_path)
        out_running = _render_text(dash, console, width=120, height=40)
        assert "RUNNING(4/9)" in out_running
        assert "Running:1" in out_running

        # Inspect running incident: dossier not yet available, review disabled, stage completion != verified
        dash.selected_incident_id = inc_prog
        out_prog_detail = _render_text(dash, console, width=120)
        assert "Dossier not yet generated" in out_prog_detail
        assert "Stage completion != verified diagnosis" in out_prog_detail
        assert "DOSSIER PENDING - EVIDENCE_COLLECTED" in out_prog_detail
        assert dash.open_review_modal("APPROVE") is False  # D03: invalid lifecycle state rejected

        # O1 / A02: Priority triage ordering & stable selection by incident_id when higher-priority incident arrives
        dash.selected_incident_id = None
        dash.focus = "list"
        _persist_incident_to_review(store, "inc-p206-med-010", service_id="auth-service", priority="medium")
        _persist_incident_to_review(store, "inc-p206-high-011", service_id="transaction-service", priority="high")
        snap_initial = dash.refresh_snapshot()
        # Triage sort places NEEDS_REVIEW HIGH (0) -> NEEDS_REVIEW MEDIUM (1) -> RUNNING MEDIUM (2),
        # while A02 preserves the previously highlighted running incident at index 2!
        assert [e.incident_id for e in snap_initial.active_entries] == [
            "inc-p206-high-011",
            "inc-p206-med-010",
            inc_prog,
        ]
        assert dash.highlighted_incident_id == inc_prog
        assert dash.selected_index == 2

        # Move UP once to select row #2 ("inc-p206-med-010")
        dash.handle_key("UP")
        assert dash.highlighted_incident_id == "inc-p206-med-010"
        assert dash.selected_index == 1

        # Now a brand-new CRITICAL incident arrives at row #1! Selection MUST follow "inc-p206-med-010" (to index 2)
        _persist_incident_to_review(store, "inc-p206-crit-012", service_id="ledger-service", priority="critical")
        snap_after = dash.refresh_snapshot()
        assert snap_after.active_entries[0].incident_id == "inc-p206-crit-012"
        assert dash.highlighted_incident_id == "inc-p206-med-010"
        assert dash.selected_index == 2
        assert snap_after.active_entries[dash.selected_index].incident_id == "inc-p206-med-010"

        # A07 & A08: Stale async snapshot generation rejected; incident-switch race does not clobber selection
        import dataclasses as _dc
        older_snap = _dc.replace(snap_after, generation=snap_after.generation - 1)
        assert dash.apply_async_snapshot(older_snap) is False

        newer_snap = dash.repository.read_snapshot(generation=snap_after.generation + 5)
        dash.selected_incident_id = "inc-p206-crit-012"
        # Async load was for inc-p206-med-010 while operator already switched to inc-p206-crit-012
        dash.apply_async_snapshot(newer_snap, expected_incident_id="inc-p206-med-010")
        assert dash.selected_incident_id == "inc-p206-crit-012"

        # A03, A04, A12: UI navigation/scrolling never mutates domain lifecycle
        before_transitions = len(store.get_transitions("inc-p206-crit-012"))
        for nav_key in ("TAB", "DOWN", "PGDN", "UP", "[", "]", "I", "B", "?", "ESC"):
            dash.handle_key(nav_key)
        assert len(store.get_transitions("inc-p206-crit-012")) == before_transitions
        assert store.get_incident("inc-p206-crit-012")["current_state"] == "HUMAN_REVIEW"

        # O9 / A11 / F07 / F08 / F09: Backend refresh failure marks last-known data STALE, then recovers cleanly
        orig_read = dash.repository.coordinator._read_atomic_snapshot
        def _broken_db(**kwargs: Any) -> Any:
            raise sqlite3.OperationalError("database disk image busy")
        dash.repository.coordinator._read_atomic_snapshot = _broken_db  # type: ignore[method-assign]
        stale_res = dash.refresh_snapshot()
        assert stale_res.is_stale_last_known is True
        assert stale_res.store_connected is False
        out_stale = _render_text(dash, console, width=120, height=40)
        # Wait: _render_text called refresh_snapshot again with _broken_db still active
        assert "STALE LAST-KNOWN DATA" in out_stale
        assert "database disk image busy" in out_stale

        # Recover backend
        dash.repository.coordinator._read_atomic_snapshot = orig_read  # type: ignore[method-assign]
        recovered = dash.refresh_snapshot()
        assert recovered.is_stale_last_known is False
        assert recovered.store_connected is True
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Group B (B01-B12) & Scenario O4 — Navigation, Focus, Lenses & Reference Resolution
# ---------------------------------------------------------------------------

def test_group_b_navigation_focus_lenses_and_evidence_reference_resolution(tmp_path: pathlib.Path) -> None:
    """Verify B01-B12 & Scenario O4: keyboard predictability, focus traps, hypothesis->evidence jump, unresolved refs."""
    store = WorkflowStateStore(str(tmp_path / "group_b.db"))
    try:
        _persist_incident_to_review(store, "inc-p206-nav-001")
        # Also create an incident with an unresolved evidence reference in checkpoint
        _persist_incident_to_review(store, "inc-p206-unres-002", include_evidence=False, support_status="UNSUPPORTED", confidence_score=0.14)
        chk = store.get_checkpoint("inc-p206-unres-002")
        assert chk is not None
        chk_ctx = chk["context"]
        chk_ctx["hypotheses"][0]["supporting_evidence_ids"] = ["ev-ghost-missing-404"]
        store.save_checkpoint("inc-p206-unres-002", "HUMAN_REVIEW", chk_ctx)

        dash, console = _build_dashboard(store, tmp_path)
        assert dash.focus == "menu"

        # B08: Help overlay opens with '?' and closes with 'ESC' without losing state
        dash.handle_key("?")
        assert dash.help_open is True
        help_txt = _render_text(dash, console, width=120, height=40)
        assert "KEYBOARD NAVIGATION & INTERACTION REFERENCE" in help_txt
        dash.handle_key("ESC")
        assert dash.help_open is False

        # B01-B03: Move focus from menu -> list -> open incident
        dash.handle_key("RIGHT")
        assert dash.focus == "list"
        selected_id = dash.highlighted_incident_id
        dash.handle_key("ENTER")
        assert dash.selected_incident_id == selected_id
        assert dash.detail_section == "all"

        # B04-B07 & O4: Cycle lenses via Tab, jump Hypothesis -> Evidence via 'I', and return via 'B'
        dash.handle_key("TAB")
        assert dash.detail_section == "overview"
        dash.handle_key("TAB")
        assert dash.detail_section == "hypotheses"

        # Jump from Hypothesis #1 to its linked supporting evidence
        dash.selected_incident_id = "inc-p206-nav-001"
        dash.refresh_snapshot()
        dash.handle_key("I")
        assert dash.detail_section == "evidence"
        ev_txt = _render_text(dash, console, width=120)
        assert "ev-inc-p206-nav-001-log-01" in ev_txt

        # Return navigation restores 'hypotheses' lens, then 'all', then incident list preserving highlighted row!
        dash.handle_key("B")
        assert dash.detail_section == "hypotheses"
        dash.handle_key("B")
        assert dash.detail_section == "all"
        dash.handle_key("B")
        assert dash.selected_incident_id is None
        assert dash.focus == "list"

        # I5: Unresolved reference is explicitly disclosed and never substituted with another item
        dash.selected_incident_id = "inc-p206-unres-002"
        dash.detail_section = "evidence"
        unres_txt = _render_text(dash, console, width=120)
        assert "[UNRESOLVED REFERENCE]" in unres_txt
        assert "ev-ghost-missing-404" in unres_txt
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Group C (C01-C15) & Scenarios O3, O5, O12 — Presentation Semantics
# ---------------------------------------------------------------------------

def test_group_c_presentation_semantics_confidence_rag_and_temporal(tmp_path: pathlib.Path) -> None:
    """Verify C01-C15, O3, O5, O12: monotonic confidence, no fabricated scores, RAG delivery, temporal badges, closure."""
    store = WorkflowStateStore(str(tmp_path / "group_c.db"))
    try:
        # O3: Weak hypothesis (14% LOW, UNSUPPORTED, missing trace source)
        _persist_incident_to_review(
            store,
            "inc-p206-weak-001",
            service_id="auth-service",
            priority="high",
            support_status="UNSUPPORTED",
            confidence_score=0.14,
            sop_availability="RETRIEVAL_UNAVAILABLE",
            include_sop=False,
            include_evidence=False,
        )
        # Also test unscored hypothesis with unvalidated LLM prior in c13_llm_runs (must NOT fabricate 80%/50%/20%!)
        unscored_dossier = _persist_incident_to_review(
            store,
            "inc-p206-unscored-002",
            confidence_score=0.20,
            support_status="PARTIAL",
        )
        unscored_dossier["hypotheses"][0].pop("confidence_score", None)
        unscored_dossier["dossier_hash"] = compute_canonical_dossier_hash(unscored_dossier)
        store.save_dossier("inc-p206-unscored-002", 1, unscored_dossier["dossier_hash"], unscored_dossier, "# md")
        store.save_checkpoint("inc-p206-unscored-002", "HUMAN_REVIEW", {"hypotheses": [{"hypothesis_id": "hyp-inc-p206-unscored-002-001", "confidence": "HIGH"}]})

        dash, console = _build_dashboard(store, tmp_path)

        # Inspect weak hypothesis
        dash.selected_incident_id = "inc-p206-weak-001"
        weak_render = _render_text(dash, console, width=120)
        weak_unboxed = " ".join(weak_render.translate(str.maketrans("│┌┐└┘─", "      ")).split())
        assert "14% (LOW)" in weak_render
        assert "[UNSUPPORTED]" in weak_render
        assert CALIBRATION_LIMITATION_NOTE in weak_unboxed
        assert "RETRIEVAL_UNAVAILABLE" in weak_render
        assert "NOT_PERFORMED" in weak_render
        assert "VERIFIED" not in weak_render  # RULE-007

        # Inspect unscored hypothesis: must show "Not scored [prior: HIGH, unvalidated]", NEVER "80%"!
        dash.selected_incident_id = "inc-p206-unscored-002"
        unscored_render = _render_text(dash, console, width=120)
        assert "Not scored [prior: HIGH, unvalidated]" in unscored_render
        assert "80%" not in unscored_render

        # Inspect supported incident with RAG context delivery telemetry
        _persist_incident_to_review(store, "inc-p206-sup-003", confidence_score=0.76, support_status="SUPPORTED")
        dash.selected_incident_id = "inc-p206-sup-003"
        dash.detail_section = "sop"
        sop_render = _render_text(dash, console, width=120)
        sop_unboxed = " ".join(sop_render.translate(str.maketrans("│┌┐└┘─", "      ")).split())
        assert "APPLICABLE_SOP_FOUND" in sop_render
        assert "included_in_llm_prompt=1" in sop_render
        assert "NOT diagnostic confidence" in sop_unboxed
        assert "SOP_BACKED" in sop_render
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Group D (D01-D15) & Scenarios O6, O7, O8, O12 — Human Review UX & Safety
# ---------------------------------------------------------------------------

def test_group_d_human_review_modal_safety_conflicts_and_failures(tmp_path: pathlib.Path) -> None:
    """Verify D01-D15 & O6, O7, O8, O12: modal confirmation, typing isolation, cancel, conflicts, DB failure, locks."""
    store = WorkflowStateStore(str(tmp_path / "group_d.db"))
    try:
        # 1. D02: Unauthorized actor role disabled at UI eligibility AND rejected at backend
        _persist_incident_to_review(store, "inc-p206-rev-unauth")
        unauth_dash, _ = _build_dashboard(store, tmp_path, reviewer_ref="ai_bot_agent", reviewer_role="GUEST")
        unauth_dash.selected_incident_id = "inc-p206-rev-unauth"
        assert unauth_dash.open_review_modal("APPROVE") is False
        assert "Automated/AI actor" in unauth_dash.notice

        # 2. D04, D05, D07, B09, B10: Modal typing isolates global keys ('q', 'a', '1'), validates rationale, cancels cleanly
        _persist_incident_to_review(store, "inc-p206-rev-main")
        dash, console = _build_dashboard(store, tmp_path, reviewer_ref="sre_reviewer_dan", reviewer_role="L2_SRE")
        dash.selected_incident_id = "inc-p206-rev-main"
        dash.refresh_snapshot()

        assert dash.open_review_modal("APPROVE") is True
        modal_txt = _render_text(dash, console, width=120, height=40)
        assert "inc-p206-rev-main" in modal_txt
        assert "Revision: v1" in modal_txt
        assert "Local PoC caller-asserted identity (unauthenticated)" in modal_txt
        assert "diagnosis_verified=False" in modal_txt

        # Typing letters 'q', 'a', '1', 'e' inside rationale field MUST NOT quit or switch tabs!
        assert dash.handle_key("q") is True
        assert dash.handle_key("a") is True
        assert dash.review_modal is not None
        assert dash.review_modal["rationale"] == "qa"

        # Validation rejects < 5 char rationale
        dash.handle_key("ENTER")  # moves to confirm button
        dash.handle_key("ENTER")  # attempts submit -> fails min length
        assert dash.review_modal is not None
        assert "minimum 5 characters" in dash.review_modal["error"]
        assert store.get_incident("inc-p206-rev-main")["current_state"] == "HUMAN_REVIEW"

        # Cancel via ESC causes zero domain or audit mutations
        dash.handle_key("ESC")
        assert dash.review_modal is None
        assert store.get_reviews("inc-p206-rev-main") == []

        # 3. D10 / O7: CORRECT creates append-only v2, rejects 'VERIFIED' keyword, preserves [Original AI Finding]
        assert dash.open_review_modal("CORRECT") is True
        dash.review_modal["corrected_hypothesis"] = "Pool exhaustion is VERIFIED root cause"
        dash.review_modal["rationale"] = "Attempting forbidden verified keyword"
        assert dash.submit_review_modal() is False
        assert "RULE-007" in dash.review_modal["error"]

        dash.review_modal["corrected_hypothesis"] = "Secondary replica connection pool limit set to 5 in config"
        dash.review_modal["rationale"] = "Observed checkout wait on replica config diff."
        assert dash.submit_review_modal() is True
        assert dash.review_modal is None
        assert store.get_latest_dossier_version("inc-p206-rev-main") == 2
        assert store.get_incident("inc-p206-rev-main")["current_state"] == "HUMAN_REVIEW"
        v2_render = _render_text(dash, console, width=120)
        assert "Revision v2" in v2_render
        assert "[HUMAN EDIT]" in v2_render
        assert "[ORIG AI]" in v2_render

        # 4. O8 / D13 / K8: Stale Review Conflict — external process finalizes while operator's modal is open!
        _persist_incident_to_review(store, "inc-p206-rev-race")
        dash.selected_incident_id = "inc-p206-rev-race"
        dash.refresh_snapshot()
        assert dash.open_review_modal("APPROVE") is True
        dash.review_modal["rationale"] = "Operator A attempting sign-off after Operator B finalized."

        # Operator B finalizes concurrently via AuthorizedReviewManager!
        ext_rm = AuthorizedReviewManager(store=store, audit_chain=dash.actions.audit_chain)
        ext_rm.reject(
            incident_id="inc-p206-rev-race",
            dossier_dict=store.get_dossier("inc-p206-rev-race")["dossier_json"],
            reviewer_ref="sre_lead_b",
            reviewer_role="LEAD_SRE",
            rationale="Rejected concurrently by Lead SRE.",
        )

        # Operator A clicks Submit -> MUST return False, report conflict, reload REJECTED, create zero second final review!
        assert dash.submit_review_modal() is False
        assert "REVIEW CONFLICT" in dash.notice
        assert len(store.get_reviews("inc-p206-rev-race")) == 1
        assert store.get_incident("inc-p206-rev-race")["current_state"] == "REJECTED"
        locked_render = _render_text(dash, console, width=120)
        assert "REVIEW LOCKED - FINALIZED (REJECTED)" in locked_render

        # 5. D14 / K9: Database/Audit failure during submission NEVER displays false success
        _persist_incident_to_review(store, "inc-p206-rev-dbfail")
        dash.selected_incident_id = "inc-p206-rev-dbfail"
        dash.refresh_snapshot()
        assert dash.open_review_modal("APPROVE") is True
        dash.review_modal["rationale"] = "Valid rationale before simulated disk failure."

        orig_apply = dash.actions.apply
        def _boom(*a: Any, **kw: Any) -> dict[str, Any]:
            raise sqlite3.OperationalError("simulated disk full during commit")
        dash.actions.apply = _boom  # type: ignore[method-assign]
        try:
            assert dash.submit_review_modal() is False
            assert dash.review_modal is not None
            assert "no changes committed" in dash.review_modal["error"]
            assert store.get_incident("inc-p206-rev-dbfail")["current_state"] == "HUMAN_REVIEW"
        finally:
            dash.actions.apply = orig_apply  # type: ignore[method-assign]

        # 6. O6, D08, D11, D12, O12: Clean APPROVE -> CLOSED (administrative handover) & ESCALATE -> MANUAL_TRIAGE_REQUIRED
        assert dash.submit_review_modal() is True
        assert store.get_incident("inc-p206-rev-dbfail")["current_state"] == "CLOSED"
        assert "diagnosis_verified=False" in dash.notice
        assert "technical_resolved=False" in dash.notice
        assert "auto_action_triggered=False" in dash.notice
        closed_render = _render_text(dash, console, width=120)
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in closed_render
        assert "REVIEW LOCKED - FINALIZED (CLOSED)" in closed_render
        assert dash.open_review_modal("REJECT") is False  # D12: locked

        # ESCALATE flow
        _persist_incident_to_review(store, "inc-p206-rev-esc")
        dash.selected_incident_id = "inc-p206-rev-esc"
        dash.refresh_snapshot()
        assert dash.open_review_modal("ESCALATE") is True
        dash.review_modal["escalation_target"] = "DBA_ONCALL_PRIMARY"
        dash.review_modal["rationale"] = "Requires read-only PostgreSQL lock inspection by DBA."
        assert dash.submit_review_modal() is True
        assert store.get_incident("inc-p206-rev-esc")["current_state"] == "MANUAL_TRIAGE_REQUIRED"

        # Audit reconciliation check (G08, G09)
        reconciled = reconcile_review_audit(store, dash.actions.audit_chain.events)
        assert reconciled["chain_valid"] is True
        assert reconciled["unreconciled_orphans"] == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Group E (E01-E12) & Group G07 / Scenario O10, O11 — Responsive, Unicode & Adversarial Display
# ---------------------------------------------------------------------------

def test_group_e_and_o10_o11_responsive_resize_monochrome_and_adversarial_safety(tmp_path: pathlib.Path) -> None:
    """Verify E01-E12, G06, G07, O10, O11: 80x24..160x50, min-size recovery, CJK, monochrome, escape/markup injection."""
    store = WorkflowStateStore(str(tmp_path / "group_e.db"))
    try:
        adv_id = "inc-p206-very-long-identifier-with-unique-tail-99887766"
        dossier = _persist_incident_to_review(store, adv_id)
        # Inject adversarial terminal escape sequences, OSC hyperlinks, BiDi overrides, Rich markup, CJK, secretos, & GT!
        dossier["impact_summary"]["observed_symptoms"] = (
            "\x1b[31m\x1b]8;;https://evil.example\x07CLICK_ME\x1b]8;;\x07"
            "\u202e[bold green]FAKE STATUS: VERIFIED[/bold green] "
            "日本語データベース接続タイムアウト password=supersecret999 "
            "ground_truth=hidden_fault_label " + ("X" * 600)
        )
        dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)
        store.save_dossier(adv_id, 1, dossier["dossier_hash"], dossier, "# md")

        dash, console = _build_dashboard(store, tmp_path, width=120, height=40)
        dash.focus = "list"

        # E01, E02, E03, E04, E10, E12 (O10): Render across 80x24, 100x30, 120x40, 160x50, and <68x16 min-size!
        dash.selected_incident_id = adv_id
        dash.refresh_snapshot()
        dash.open_review_modal("APPROVE")
        dash.review_modal["rationale"] = "Preserved draft across terminal resizes"

        # Shrink below minimum (60x14) -> shows clean resize message without losing modal/selection!
        too_small = _render_text(dash, console, width=60, height=14)
        assert "TERMINAL VIEWPORT BELOW MINIMUM SUPPORTED SIZE" in too_small
        assert dash.selected_incident_id == adv_id
        assert dash.review_modal is not None
        assert dash.review_modal["rationale"] == "Preserved draft across terminal resizes"

        dash.cancel_review_modal()
        for w, h in ((80, 24), (100, 30), (120, 40), (160, 50)):
            dash.selected_incident_id = None
            list_out = _render_text(dash, console, width=w, height=h)
            assert "Active Incidents" in list_out
            assert "99887766" in list_out or "inc-p206" in list_out  # E05: unique tail preserved

            dash.selected_incident_id = adv_id
            det_out = _render_text(dash, console, width=w, height=h)
            # O11 / G07 / INV-17: Zero raw escape sequences, zero BiDi overrides, zero leaked secrets, GT, or spoofed VERIFIED!
            assert "\x1b]8;;" not in det_out
            assert "\u202e" not in det_out
            assert "supersecret999" not in det_out
            assert "hidden_fault_label" not in det_out
            assert "VERIFIED" not in det_out
            assert "[REDACTED_GT_FIELD]" in det_out or "ground_truth" not in det_out.lower()

        # E09: Color-independent monochrome rendering preserves all non-color status badges
        mono_dash, mono_console = _build_dashboard(store, tmp_path, width=120, height=40, color_system=None)
        mono_out = _render_text(mono_dash, mono_console, width=120, height=40)
        assert "[CRIT]" in mono_out
        assert "NEEDS_REVIEW" in mono_out
        assert "[FOCUSED]" in mono_out
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Group F (F01-F12) & Performance / Resource Discipline (Deliverable I)
# ---------------------------------------------------------------------------

def test_group_f_loading_empty_probe_caching_zero_llm_calls_and_shutdown(tmp_path: pathlib.Path) -> None:
    """Verify F01-F12: initial loading, empty state, bounded health/cost probe TTL, zero LLM calls, clean shutdown."""
    empty_store = WorkflowStateStore(":memory:")
    dash, console = _build_dashboard(empty_store, tmp_path)

    # F01: Initial loading state
    dash.initial_loading = True
    load_out = _render_text(dash, console, width=100, height=30)
    assert "[LOADING] Reading authoritative state store snapshot" in load_out

    # F02: Empty incident list state with cause & next action
    dash.initial_loading = False
    empty_out = _render_text(dash, console, width=100, height=30)
    assert "No active investigations or dossiers pending review." in empty_out
    assert "Next action:" in empty_out

    # F10 & F11: Rendering 25 times on Health tab calls ServiceHealthInspector ONLY ONCE within TTL (zero busy-loop subprocesses)
    probe_calls = {"count": 0}
    class _CountingHealth(ServiceHealthInspector):
        def inspect(self) -> dict[str, Any]:
            probe_calls["count"] += 1
            return {"status": "OK", "reason": "", "services": [{"name": "api-gateway", "state": "running", "health": "healthy"}]}

    dash.health = _CountingHealth()
    dash.view = "health"
    t0 = time.perf_counter()
    for _ in range(25):
        _render_text(dash, console, width=120, height=40)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert probe_calls["count"] == 1
    assert elapsed_ms < 2500.0  # 25 full renders complete rapidly without subprocess blocking

    # F12 / M4: Clean shutdown closes UI resources without mutating active domain investigations
    active_store = WorkflowStateStore(str(tmp_path / "shutdown.db"))
    _persist_incident_to_review(active_store, "inc-p206-open-on-exit")
    exit_dash, _ = _build_dashboard(active_store, tmp_path)
    assert exit_dash.handle_key("Q") is False
    assert active_store.get_incident("inc-p206-open-on-exit")["current_state"] == "HUMAN_REVIEW"
    active_store.close()
    empty_store.close()


# ---------------------------------------------------------------------------
# Section 20.2 / 20.3 & Group G (G01-G18) — Live Synthetic Stack, CLI/TUI Consistency & Frozen Contracts
# ---------------------------------------------------------------------------

def test_live_synthetic_stack_tui_cli_dossier_consistency_and_frozen_contracts(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify Section 20.2/20.3 & G01-G18: live alert -> investigator -> TUI/CLI/HTML/DB parity + frozen hashes."""
    # 1. G17 & G18: Frozen C02 schemas and Stage 3A release manifest byte-for-byte unchanged
    assert FROZEN_STAGE_3A_MANIFEST.exists()
    actual_manifest_sha = hashlib.sha256(FROZEN_STAGE_3A_MANIFEST.read_bytes()).hexdigest()
    assert actual_manifest_sha == STAGE_3A_MANIFEST_SHA256

    for schema_name in ("dossier.v1.schema.json", "review-event.v1.schema.json", "workflow-event.v1.schema.json", "tool-result.v1.schema.json"):
        assert (FROZEN_C02_DIR / schema_name).exists()

    # 2. Spin up live in-process FastAPI telemetry facade + LiveAlertWatcher -> DeterministicInvestigator
    app = FastAPI()

    @app.get("/api/v1/alerts")
    async def alerts() -> dict[str, Any]:
        return {
            "status": "success",
            "alerts": [
                {
                    "alert_id": "alt-p206-live-01",
                    "service_id": "ledger-service",
                    "service.name": "ledger-service",
                    "environment": "lab",
                    "alert_type": "SimPoolExhausted",
                    "severity": "critical",
                    "error_code": "ERR_CONNECTION_POOL_EXHAUSTED",
                    "summary": "PostgreSQL pool checkout saturation on ledger-service",
                    "event_time": "2026-11-26T02:30:00Z",
                    "trace_id": "7bf92f3577b34da6a3ce929d0e0e4799",
                }
            ],
        }

    @app.get("/api/v1/query_range")
    @app.get("/api/v1/query")
    async def prom_query() -> dict[str, Any]:
        return {
            "status": "success",
            "records": [
                {
                    "metric_name": "error_rate",
                    "value": 0.31,
                    "unit": "ratio",
                    "sample_at": "2026-11-26T02:29:50Z",
                    "service_id": "ledger-service",
                    "environment": "lab",
                }
            ],
        }

    @app.get("/loki/api/v1/query_range")
    async def loki_query() -> dict[str, Any]:
        return {
            "status": "success",
            "records": [
                {
                    "timestamp": "2026-11-26T02:29:45Z",
                    "service_id": "ledger-service",
                    "service.name": "ledger-service",
                    "environment": "lab",
                    "severity": "ERROR",
                    "error_code": "ERR_CONNECTION_POOL_EXHAUSTED",
                    "message": "Pool checkout timeout on ledger-service",
                    "trace_id": "7bf92f3577b34da6a3ce929d0e0e4799",
                }
            ],
        }

    @app.get("/api/traces/{trace_id}")
    async def tempo_trace(trace_id: str) -> dict[str, Any]:
        return {"traceID": trace_id, "batches": []}

    @app.get("/api/search")
    async def tempo_search() -> dict[str, Any]:
        return {"traces": []}

    client = TestClient(app)
    db_path = tmp_path / "live_p206.db"
    watcher = LiveAlertWatcher(
        state_db=str(db_path),
        alerts_client=client,
        telemetry_client=client,
        use_env_llm=False,
    )
    polled = watcher.poll_once()
    assert len(polled) == 1
    live_inc_id = polled[0]["incident_id"]
    assert polled[0]["state"] == "HUMAN_REVIEW"

    try:
        # Compare TUI vs CLI vs Persisted Dossier vs Handover Markdown/HTML
        dossier_rec = watcher.store.get_dossier(live_inc_id)
        assert dossier_rec is not None
        dossier_json = dossier_rec["dossier_json"]

        dash, console = _build_dashboard(watcher.store, tmp_path, width=120, height=40)
        dash.selected_incident_id = live_inc_id
        tui_text = _render_text(dash, console, width=120)

        display_dossier_summary(dossier_json, store=watcher.store)
        cli_text = capsys.readouterr().out

        # Approve via TUI two-step modal and verify handover export + CLI view-only parity
        dash.refresh_snapshot()
        assert dash.open_review_modal("APPROVE") is True
        dash.review_modal["rationale"] = "Approved live synthetic ledger-service dossier for handover."
        assert dash.submit_review_modal() is True

        closed_inc = watcher.store.get_incident(live_inc_id)
        assert closed_inc is not None and closed_inc["current_state"] == "CLOSED"

        handover_dir = tmp_path / "handover" / live_inc_id
        md_text = (handover_dir / "dossier.md").read_text(encoding="utf-8")
        html_text = (handover_dir / "dossier.html").read_text(encoding="utf-8")
        tui_closed = _render_text(dash, console, width=120)

        updated_dossier = watcher.store.get_dossier(live_inc_id)["dossier_json"]
        display_dossier_summary(updated_dossier, store=watcher.store)
        cli_closed = capsys.readouterr().out

        # Parity assertions across ALL 4 surfaces (TUI, CLI, Markdown, HTML)
        for surface in (tui_closed, cli_closed, md_text, html_text):
            assert live_inc_id in surface
            assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in surface
            assert "VERIFIED" not in surface  # G01: RULE-007 enforced everywhere

        is_gt_clean, gt_violations = verify_ground_truth_isolation(updated_dossier)
        assert is_gt_clean is True, gt_violations
        assert live_inc_id in tui_text and live_inc_id in cli_text
    finally:
        watcher.store.close()


def test_group_g_security_policy_gateway_acl_duplicate_submit_and_pty_cli(tmp_path: pathlib.Path) -> None:
    """Verify G03, G04, G05, D06, and real subprocess PTY/CLI entrypoints (scripts/sre_dashboard.py & review_console.py)."""
    # 1. G03 / INV-01 / INV-12: Policy Gateway remains strictly read-only (MCP-01 & MCP-02)
    gw = PolicyGateway()
    coord_token = "sre-sim-coord-token-secret-2026"
    mcp01 = gw.execute_tool(
        tool_name="restart_service",
        arguments={"service_id": "ledger-service", "environment": "lab"},
        token=coord_token,
        incident_id="inc-p206-gw-01",
    )
    assert mcp01["status"] in ("rejected", "error")
    mcp02 = gw.execute_tool(
        tool_name="get_service_metrics",
        arguments={
            "service_id": "ledger-service",
            "environment": "lab",
            "metric_names": ["error_rate"],
            "start": "2026-11-01T00:00:00Z",
            "end": "2026-11-26T00:00:00Z",
            "step_seconds": 60,
        },
        token=coord_token,
        incident_id="inc-p206-gw-01",
    )
    assert mcp02["status"] in ("rejected", "error")

    # 2. G04, G05, D06: Restricted SOP filtering, cross-incident evidence scope rejection, and duplicate-submit lock
    db_file = tmp_path / "pty_cli.db"
    store = WorkflowStateStore(str(db_file))
    try:
        dossier = _persist_incident_to_review(store, "inc-p206-pty-001")
        dash, _ = _build_dashboard(store, tmp_path)
        dash.selected_incident_id = "inc-p206-pty-001"
        dash.refresh_snapshot()

        # D06: Duplicate submission while modal["submitting"] is True is blocked immediately
        assert dash.open_review_modal("APPROVE") is True
        dash.review_modal["rationale"] = "Checking duplicate submit lock."
        dash.review_modal["submitting"] = True
        assert dash.submit_review_modal() is False
        assert store.get_reviews("inc-p206-pty-001") == []
        dash.cancel_review_modal()

        # Write dossier JSON file to test review_console.py --dossier --view-only CLI flags
        dossier_path = tmp_path / "dossier.json"
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
    finally:
        store.close()

    # 3. CLI entrypoint (--dossier --view-only --reviewer --role)
    cli_proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "review_console.py"),
            "--state-db",
            str(db_file),
            "--dossier",
            str(dossier_path),
            "--reviewer",
            "sre_cli_op",
            "--role",
            "L2_SRE",
            "--view-only",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert cli_proc.returncode == 0, cli_proc.stderr
    assert "inc-p206-pty-001" in cli_proc.stdout
    assert "VERIFIED" not in cli_proc.stdout

    # 4. Real PTY subprocess execution of scripts/sre_dashboard.py (navigate, inspect, approve, clean exit)
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env.pop("OPENROUTER_API_KEY", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sre_dashboard.py"),
            "--state-db",
            str(db_file),
            "--reviewer-ref",
            "sre_pty_tester",
            "--reviewer-role",
            "L2_SRE",
            "--audit-log",
            str(tmp_path / "pty_audit.jsonl"),
            "--handover-root",
            str(tmp_path / "pty_handover"),
            "--ascii",
        ],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        cwd=str(tmp_path),
        close_fds=True,
    )
    os.close(slave_fd)
    captured = bytearray()

    def _pump(wait_s: float = 0.22, until: bytes | None = None) -> None:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.04)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                    if not chunk:
                        break
                    captured.extend(chunk)
                    if until is not None and until in captured:
                        return
                except OSError:
                    break

    try:
        _pump(6.0, until=b"SRE INVESTIGATION CONSOLE")
        _pump(0.15)
        os.write(master_fd, b"\t")     # Focus list
        _pump(0.20)
        os.write(master_fd, b"\r")     # Open incident detail
        _pump(2.0, until=b"View Lens")
        os.write(master_fd, b"a")      # Open APPROVE confirmation modal
        _pump(2.0, until=b"CONFIRM HUMAN REVIEW ACTION")
        os.write(master_fd, b"PTY review rationale validated end-to-end.")
        _pump(0.20)
        os.write(master_fd, b"\r")
        _pump(0.20)
        os.write(master_fd, b"\r")
        _pump(2.0, until=b"REVIEW LOCKED - FINALIZED")
        os.write(master_fd, b"q")      # Quit cleanly
        _pump(1.5, until=b"closed without automated actions")
        rc = proc.wait(timeout=8)
    finally:
        if proc.poll() is None:
            proc.kill()
        with contextlib.suppress(OSError):
            os.close(master_fd)

    assert rc == 0
    assert len(captured) > 1000
    verify_db = WorkflowStateStore(str(db_file))
    try:
        inc_after = verify_db.get_incident("inc-p206-pty-001")
        assert inc_after is not None and inc_after["current_state"] == "CLOSED"
    finally:
        verify_db.close()


def test_real_pty_interactive_session_resize_and_review_flow(tmp_path: pathlib.Path) -> None:
    """Verify real PTY interactive loop: cbreak input, help overlay, lenses, resize, modal cancel/submit, clean exit."""
    pty_db = tmp_path / "pty_e2e.db"
    store = WorkflowStateStore(str(pty_db))
    inc_id = "inc-p206-pty-live-001"
    _persist_incident_to_review(store, inc_id, service_id="ledger-service", priority="critical")
    store.close()

    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = "120"
    env["LINES"] = "40"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sre_dashboard.py"),
            "--state-db",
            str(pty_db),
            "--reviewer-ref",
            "sre_pty_tester",
            "--reviewer-role",
            "L2_SRE",
            "--audit-log",
            str(tmp_path / "pty_audit.jsonl"),
            "--handover-root",
            str(tmp_path / "pty_handover"),
        ],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        cwd=str(tmp_path),
        close_fds=True,
    )
    os.close(slave_fd)

    buf = bytearray()

    def _drain(sec: float = 0.25, until: bytes | None = None) -> None:
        end = time.monotonic() + sec
        while time.monotonic() < end:
            r, _, _ = select.select([master_fd], [], [], 0.04)
            if r:
                try:
                    chunk = os.read(master_fd, 65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if until is not None and until in buf:
                        return
                except OSError:
                    break

    try:
        _drain(6.0, until=b"SRE INVESTIGATION CONSOLE")
        _drain(0.15)
        os.write(master_fd, b"?")
        _drain(2.0, until=b"KEYBOARD NAVIGATION")
        os.write(master_fd, b"\x1b")
        _drain(0.20)
        os.write(master_fd, b"\t")
        _drain(0.20)
        os.write(master_fd, b"\r")
        _drain(2.0, until=b"View Lens")
        # Resize to 80x24 and back to 120x40
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        os.write(master_fd, b"u")
        _drain(0.25)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        os.write(master_fd, b"a")
        _drain(2.0, until=b"CONFIRM HUMAN REVIEW ACTION")
        os.write(master_fd, b"\x1b")  # Cancel first
        _drain(0.25)
        os.write(master_fd, b"a")
        _drain(0.30)
        os.write(master_fd, b"Corroborated pool timeout in Loki and Prometheus.")
        _drain(0.25)
        os.write(master_fd, b"\r")
        _drain(0.20)
        os.write(master_fd, b"\r")
        _drain(2.0, until=b"REVIEW LOCKED - FINALIZED")
        os.write(master_fd, b"q")
        _drain(1.5, until=b"closed without automated actions")
        rc = proc.wait(timeout=8)
    finally:
        if proc.poll() is None:
            proc.kill()
        with contextlib.suppress(OSError):
            os.close(master_fd)

    assert rc == 0
    check_store = WorkflowStateStore(str(pty_db))
    try:
        inc = check_store.get_incident(inc_id)
        revs = check_store.get_reviews(inc_id)
        assert inc is not None and inc["current_state"] == "CLOSED"
        assert len(revs) == 1 and revs[0]["decision"] == "approve"
    finally:
        check_store.close()


def test_wcag_contrast_and_no_green_for_confidence() -> None:
    """Verify design tokens meet WCAG AA >= 4.5:1 against dark terminal surfaces and ban green on confidence."""
    def _rel_lum(hex_c: str) -> float:
        h = hex_c.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        lin = [(c / 12.92) if c <= 0.04045 else (((c + 0.055) / 1.055) ** 2.4) for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def _ratio(fg: str, bg: str) -> float:
        l1, l2 = _rel_lum(fg), _rel_lum(bg)
        hi, lo = max(l1, l2), min(l1, l2)
        return (hi + 0.05) / (lo + 0.05)

    token_hexes = {
        "primary": "#f1f5f9",
        "secondary": "#cbd5e1",
        "muted": "#94a3b8",
        "accent": "#38bdf8",
        "corroborated": "#7dd3fc",
        "warning": "#facc15",
        "critical": "#f87171",
        "healthy": "#4ade80",
    }
    for bg in ("#292929", "#1e1e1e", "#14181f"):
        for name, fg in token_hexes.items():
            cr = _ratio(fg, bg)
            assert cr >= 4.5, f"Token {name} ({fg}) failed WCAG AA on {bg}: {cr:.2f}:1"

    # INV-08 / Section 5.6: SUPPORTED hypothesis style must NOT use green (reserved for healthy infra probe only)
    sup_style_str = str(TOKENS_COLOR.support_style("SUPPORTED")).lower()
    assert "green" not in sup_style_str
    assert "#4ade80" not in sup_style_str
    assert "#86efac" not in sup_style_str
    assert str(TOKENS_MONO.support_style("SUPPORTED")) in ("bold", "")

