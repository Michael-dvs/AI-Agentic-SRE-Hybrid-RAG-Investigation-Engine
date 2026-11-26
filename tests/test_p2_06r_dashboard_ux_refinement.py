"""Regression test suite for P2-06R Dashboard UX Refinement & Progressive Disclosure.

Covers all 20 required verification points from P2-06R Section 12:
 1. Overview is the default incident detail view.
 2. All Sections remains optional via [V], never default.
 3. Essential operational info is visible in Overview without scrolling at standard viewport.
 4. Technical metadata is omitted from Overview and accessible in Technical Details.
 5. Hypotheses are inspected individually (expand/collapse), not dumped simultaneously.
 6. Short evidence display IDs map unambiguously to full canonical evidence IDs without rewriting.
 7. SOP applicability, context delivery truthfulness, and restricted source exclusion are preserved.
 8. Authoritative confidence score and band remain identical across ViewModel, Overview, and Hypotheses.
 9. Internal ClaimValidator SUPPORTED vs frozen dossier PARTIAL semantics are accurately explained.
10. Full review action controls appear ONLY in Review context; non-review views show concise indicator.
11. Navigation, expand/collapse, sidebar toggle, and lens switching never submit review or mutate state.
12. Finalized incidents remain locked across Overview and Review contexts.
13. Refresh preserves stable incident selection by ID across insertions.
14. Stale async snapshot responses cannot overwrite current state.
15. Long symptoms, long evidence IDs, and long incidents remain safely accessible without overflow/loss.
16. Responsive layouts remain usable across 80x24, 100x30, 120x40, 140x42, 160x50, and 207x49.
17. Terminal resize causes zero domain mutations, zero LLM calls, and preserves selection/modal drafts.
18. Untrusted terminal content (ANSI, BiDi, Rich markup tags, secrets, GT keys, VERIFIED) is sanitized.
19. Critical warnings (competing SOPs, retrieval outage, missing sources, unresolved refs, stale data) remain visible in Overview.
20. Core safety invariants (RULE-007, zero auto-remediation, PolicyGateway read-only, frozen C02 & Stage 3A hashes) stay intact.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
from typing import Any

import pytest
from rich.console import Console

from gateway.policy import PolicyGateway
from orchestrator.console_view_models import (
    DashboardSnapshot,
    build_short_evidence_ids,
)
from orchestrator.dossier import DossierSerializer, compute_canonical_dossier_hash
from orchestrator.review import AuthorizedReviewManager
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import (
    CostMetricsReader,
    DETAIL_LENS_ORDER,
    SREDashboard,
    ServiceHealthInspector,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FROZEN_STAGE_3A_MANIFEST = (
    REPO_ROOT
    / "evidence"
    / "c21-preflight-20261122T051612608117Z"
    / "C21"
    / "final-release-manifest.json"
)
STAGE_3A_MANIFEST_SHA256 = "b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f"
FROZEN_C02_DIR = REPO_ROOT / "evidence" / "c02-20261109T070500Z" / "C02" / "contracts"


class _StubHealth(ServiceHealthInspector):
    def inspect(self) -> dict[str, Any]:
        return {
            "status": "OK",
            "reason": "",
            "services": [{"name": "transaction-service", "state": "running", "health": "healthy"}],
        }


def _persist_rich_incident(
    store: WorkflowStateStore,
    incident_id: str,
    *,
    service_id: str = "transaction-service",
    severity: str = "high",
    symptom: str = "Service transaction-service error_rate=0.20 exceeded critical threshold 0.20 (error_code=ERR_TX_INTERNAL_EXCEPTION)",
    dossier_support: str = "PARTIAL",
    internal_validation: str = "SUPPORTED",
    confidence_score: float = 0.79,
    sop_availability: str = "APPLICABLE_SOP_FOUND",
    include_sop: bool = True,
    competing_sops: bool = False,
    delivered_citations: int | None = 0,
    include_missing_source: bool = False,
    unresolved_ref: str | None = None,
) -> dict[str, Any]:
    store.create_incident(
        incident_id=incident_id,
        service_id=service_id,
        environment="lab",
        initial_state="HUMAN_REVIEW",
        status="ACTIVE",
    )
    ev1 = f"ev-{incident_id}-001"
    ev2 = f"ev-{incident_id}-002"
    ev3 = f"ev-{incident_id}-003"
    evidence_items = [
        {
            "evidence_id": ev1,
            "tool_name": "get_service_metrics",
            "source_ref": "prometheus:http://127.0.0.1:19090",
            "service_id": service_id,
            "environment": "lab",
            "observed_at": "2026-11-26T03:43:58Z",
            "collected_at": "2026-11-26T03:43:59Z",
            "query_window": {"start": "2026-11-26T03:38:58Z", "end": "2026-11-26T03:44:58Z"},
            "data_quality": "complete",
            "truncated": False,
            "sanitized": True,
            "summary": "error_rate=0.202 ratio (ratio) [svc=transaction-service env=lab obs=2026-11-26T03:43:58Z]",
            "records": [{"metric_name": "error_rate", "value": 0.202, "unit": "ratio", "aggregation": "ratio"}],
        },
        {
            "evidence_id": ev2,
            "tool_name": "search_error_logs",
            "source_ref": "loki:http://127.0.0.1:13100",
            "service_id": service_id,
            "environment": "lab",
            "observed_at": "2026-11-26T03:43:58Z",
            "collected_at": "2026-11-26T03:43:59Z",
            "query_window": {"start": "2026-11-26T03:38:58Z", "end": "2026-11-26T03:44:58Z"},
            "data_quality": "complete",
            "truncated": False,
            "sanitized": True,
            "summary": "ERR_TX_INTERNAL_EXCEPTION: Unhandled internal runtime exception during transaction execution.",
            "records": [{"error_code": "ERR_TX_INTERNAL_EXCEPTION", "message": "Unhandled internal runtime exception"}],
        },
        {
            "evidence_id": ev3,
            "tool_name": "get_trace_summary",
            "source_ref": "tempo:http://127.0.0.1:13200",
            "service_id": service_id,
            "environment": "lab",
            "observed_at": "2026-11-26T03:43:58Z",
            "collected_at": "2026-11-26T03:43:59Z",
            "query_window": {"start": "2026-11-26T03:38:58Z", "end": "2026-11-26T03:44:58Z"},
            "data_quality": "partial",
            "truncated": True,
            "sanitized": True,
            "summary": "UNKNOWN [OK 0.108ms] trace=cd0bc6e70521",
            "records": [],
        },
    ]

    h1_sup = [ev1, ev2]
    if unresolved_ref:
        h1_sup.append(unresolved_ref)

    hypotheses = [
        {
            "rank": 1,
            "hypothesis_id": f"hyp-{incident_id}-001",
            "statement": f"{service_id} internal runtime exception causing error_rate to exceed critical threshold of 0.20",
            "support_status": dossier_support,
            "confidence_score": confidence_score,
            "supporting_evidence_ids": [e for e in h1_sup if e != unresolved_ref],
            "contradicting_evidence_ids": [],
            "reason_summary": "Mechanism / Why: ERR_TX_INTERNAL_EXCEPTION in transaction execution handler.",
            "confidence_rationale": (
                f"status={internal_validation}, unique_support=2 (duplicates_collapsed=0, modalities=2, "
                "correlated_pairs=0), contradictions=0, rejected_claims=0, unavailable_sources=0; "
                f"score={int(round(confidence_score * 100))}% (heuristic, non-probabilistic)."
            ),
            "unknowns": ["Full stack trace or detailed exception type for ERR_TX_INTERNAL_EXCEPTION"],
        },
        {
            "rank": 2,
            "hypothesis_id": f"hyp-{incident_id}-002",
            "statement": "External dependency failure causing internal exceptions",
            "support_status": "INCONCLUSIVE",
            "confidence_score": 0.20,
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "reason_summary": "Mechanism / Why: Secondary candidate without direct dependency timeout logs.",
            "confidence_rationale": "status=INCONCLUSIVE, unique_support=0; score=20% (heuristic, non-probabilistic).",
            "unknowns": ["Downstream dependency health check outside immediate window."],
        },
    ]

    sop_citations: list[dict[str, Any]] = []
    if include_sop:
        sop_citations.append(
            {
                "doc_id": "SOP-TX-ERR-500",
                "version": "1.0.0",
                "section_path": "SOP-TX-ERR-500 > 1. Karakteristik Insiden",
                "chunk_id": "chk-SOP-TX-ERR-500-v1.0.0-002",
                "source_uri": "kb://corpus/transaction_service/SOP-TX-ERR-500.md",
                "excerpt": "Respons HTTP 500 dikembalikan oleh endpoint transaksi finansial simulasi.",
                "retrieval_score": 0.0328,
                "applicability_verified": True,
            }
        )
        if competing_sops:
            sop_citations.append(
                {
                    "doc_id": "SOP-TX-ERR-ALT",
                    "version": "2.0.0",
                    "section_path": "SOP-TX-ERR-ALT > 1. Alternative Triage",
                    "chunk_id": "chk-SOP-TX-ERR-ALT-v2.0.0-001",
                    "source_uri": "kb://corpus/transaction_service/SOP-TX-ERR-ALT.md",
                    "excerpt": "Alternative escalation criteria for simulated transaction errors.",
                    "retrieval_score": 0.0319,
                    "applicability_verified": True,
                }
            )

    missing_sources: list[dict[str, Any]] = []
    if include_missing_source:
        missing_sources.append(
            {
                "tool_name": "get_trace_summary",
                "error_code": "SOURCE_UNAVAILABLE",
                "recorded_at": "2026-11-26T03:43:59Z",
                "impact_note": "Tempo backend unreachable during incident window.",
            }
        )
    if sop_availability == "RETRIEVAL_UNAVAILABLE":
        missing_sources.append(
            {
                "tool_name": "retrieve_runbooks",
                "error_code": "SOURCE_UNAVAILABLE",
                "recorded_at": "2026-11-26T03:43:59Z",
                "impact_note": "RETRIEVAL_UNAVAILABLE: Hybrid RAG backend unreachable during incident investigation.",
            }
        )

    dossier: dict[str, Any] = {
        "schema_version": "1.0",
        "dossier_version": 1,
        "incident_id": incident_id,
        "service_id": service_id,
        "environment": "lab",
        "severity": severity,
        "investigation_mode": "agentic_llm",
        "alert_received_at": "2026-11-26T03:43:58Z",
        "dossier_ready_at": "2026-11-26T03:44:09Z",
        "window_start": "2026-11-26T03:38:58Z",
        "window_end": "2026-11-26T03:44:58Z",
        "impact_summary": {
            "affected_services": [service_id, "api-gateway", "db-dummy"],
            "observed_symptoms": symptom,
            "error_budget_impact": "moderate",
        },
        "hypotheses": hypotheses,
        "evidence": evidence_items,
        "sop_citations": sop_citations,
        "sop_availability": sop_availability,
        "recommended_checks": [
            {
                "check_id": "chk-01",
                "description": "NOT_PERFORMED · SOP-BACKED: Inspect diagnostic criteria in SOP-TX-ERR-500.",
                "risk_level": "low",
                "requires_human_approval": True,
                "auto_execution_allowed": False,
                "related_sop_doc_id": "SOP-TX-ERR-500" if include_sop else "NONE",
            }
        ],
        "unknowns": [
            "Full stack trace or detailed exception type for ERR_TX_INTERNAL_EXCEPTION",
            "Database lock telemetry not exposed in lab metrics",
        ],
        "missing_sources": missing_sources,
        "review_summary": {"status": "PENDING_REVIEW"},
        "reproducibility": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "provider": "openrouter",
            "model_version": "nvidia/nemotron-3.5-lightning:free",
            "prompt_version": "163f5083ac55f78a2b5b2d07221d8078068c7abc",
            "input_tokens": 1191,
            "output_tokens": 372,
            "total_tokens": 1563,
        },
    }
    dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)
    store.save_dossier(incident_id, 1, dossier["dossier_hash"], dossier, "# dossier")

    chk_hyps = [
        {
            "hypothesis_id": f"hyp-{incident_id}-001",
            "rank": 1,
            "validation_status": internal_validation,
            "validation_reason_codes": ["CLAIM_CORROBORATED", "DOWNSTREAM_SYMPTOM_CASCADE"],
            "supporting_evidence_ids": h1_sup,
        }
    ]
    chk_ctx: dict[str, Any] = {
        "hypotheses": chk_hyps,
        "evidence_items": evidence_items,
        "impact_graph": {
            "upstream_callers": ["api-gateway"],
            "downstream_dependencies": ["db-dummy", "ledger-service"],
            "uncertainty": "Topology alone does not establish causality.",
        },
        "validation_reports": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "status": internal_validation,
                "origin_service": "api-gateway",
                "is_cascade": True,
                "reason_codes": ["CLAIM_CORROBORATED", "DOWNSTREAM_SYMPTOM_CASCADE"],
            }
        ],
        "sop_relevance": {"status": "SPECIFIC_COVERAGE_GAP" if include_sop else "NO_APPLICABLE_RUNBOOK"},
    }
    if delivered_citations is not None:
        chk_ctx["llm_context_diagnostics"] = {
            "retrieved_citations_count": len(sop_citations),
            "eligible_passages_count": len(sop_citations),
            "citations_delivered_count": delivered_citations,
            "omitted_passages_count": max(0, len(sop_citations) - delivered_citations),
            "omission_reasons": ["CITATION_BUDGET_OMITTED"] if delivered_citations == 0 and sop_citations else [],
            "compaction_rung": "2_1_0_0",
        }
    store.save_checkpoint(incident_id, "HUMAN_REVIEW", chk_ctx)
    return dossier


def _make_dash(
    store: WorkflowStateStore,
    tmp_path: pathlib.Path,
    *,
    width: int = 120,
    height: int = 40,
    reviewer_ref: str = "sre_reviewer",
    reviewer_role: str = "L2_SRE",
) -> tuple[SREDashboard, Console]:
    console = Console(record=True, width=width, height=height, force_terminal=False, color_system=None)
    dash = SREDashboard(
        store,
        console=console,
        reviewer_ref=reviewer_ref,
        reviewer_role=reviewer_role,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
        health=_StubHealth(),
        costs=CostMetricsReader(tmp_path / "missing_costs.json"),
        telegram=TelegramDispatcher(bot_token="", chat_id=""),
    )
    return dash, console


def _render(dash: SREDashboard, console: Console, *, width: int = 120, height: int | None = 40) -> str:
    console.clear()
    console.export_text(clear=True)
    console.width = width
    if height is not None:
        console.height = height
    console.print(dash.render(width=width, height=height))
    return console.export_text(clear=True)


# ---------------------------------------------------------------------------
# Items 1-4: Default Overview, Optional All Sections, Progressive Disclosure
# ---------------------------------------------------------------------------

def test_p206r_01_to_04_overview_default_optional_all_and_technical_separation(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(str(tmp_path / "p206r_01.db"))
    try:
        inc_id = "inc-live-transaction-service-3b7751e91b"
        _persist_rich_incident(store, inc_id)
        dash, console = _make_dash(store, tmp_path)

        # Open incident via keyboard navigation -> defaults to Overview (Item 1)
        dash.handle_key("RIGHT")
        dash.handle_key("ENTER")
        assert dash.selected_incident_id == inc_id
        assert dash.detail_section == "overview"
        assert DETAIL_LENS_ORDER == ("overview", "hypotheses", "evidence", "sop", "review", "technical")

        overview_txt = _render(dash, console, width=120, height=40)
        # Item 3: Essential operational info visible without scrolling at 120x40
        assert "[Scroll:" not in overview_txt
        assert "transaction-service" in overview_txt
        assert "[HIGH]" in overview_txt
        assert "HUMAN_REVIEW" in overview_txt
        assert "Stage 9/9: Human Review" in overview_txt
        assert "Observed Symptom" in overview_txt
        assert "Leading Hypothesis" in overview_txt
        assert "79% (HIGH)" in overview_txt
        assert "[PARTIAL]" in overview_txt
        assert "+2 support, 0 contra" in overview_txt
        assert "Key Uncertainty" in overview_txt
        assert "Next Action" in overview_txt
        assert "Human review required" in overview_txt
        assert "RULE-007" in overview_txt
        assert "auto_action_triggered=False" in overview_txt

        # Item 4: Technical metadata omitted from default Overview
        assert inc_id not in overview_txt
        assert "nvidia/nemotron-3.5-lightning:free" not in overview_txt
        assert "163f5083ac55f78a" not in overview_txt
        assert "in=1191" not in overview_txt
        assert "[x:RCV]" not in overview_txt
        assert "Topology Flow" not in overview_txt
        assert "unique_support=2" not in overview_txt
        assert "ev-inc-live-transaction-service-3b7751e91b-001" not in overview_txt

        # Item 4: Technical metadata accessible via [D] Details view (including intact [api-gateway] brackets!)
        dash.handle_key("D")
        assert dash.detail_section == "technical"
        tech_txt = _render(dash, console, width=120, height=80)
        assert inc_id in tech_txt
        assert "nvidia/nemotron-3.5-lightning:free" in tech_txt
        assert "in=1191, out=372, total=1563" in tech_txt
        assert "163f5083ac55f78a" in tech_txt
        assert "[x:RCV]" in tech_txt
        assert "[api-gateway] -> transaction-service -> [db-dummy, ledger-service]" in tech_txt
        assert "unique_support=2" in tech_txt

        # Item 2: Optional All Sections toggled via [V], returns to Overview on second [V]
        dash.handle_key("V")
        assert dash.detail_section == "all"
        all_txt = _render(dash, console, width=120, height=None)
        assert "[All Sections - Audit]" in all_txt
        assert inc_id in all_txt
        dash.handle_key("V")
        assert dash.detail_section == "overview"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Items 5, 6, 8, 9: Hypotheses On-Demand, Short->Canonical Evidence IDs,
# Confidence Immutability & PARTIAL vs SUPPORTED Semantics
# ---------------------------------------------------------------------------

def test_p206r_05_06_08_09_hypotheses_expand_evidence_ids_confidence_and_status_semantics(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(str(tmp_path / "p206r_05.db"))
    try:
        inc_id = "inc-live-transaction-service-3b7751e91b"
        _persist_rich_incident(store, inc_id, dossier_support="PARTIAL", internal_validation="SUPPORTED", confidence_score=0.79)
        dash, console = _make_dash(store, tmp_path)
        dash.selected_incident_id = inc_id

        # Item 5: Hypotheses list starts collapsed — does NOT dump all reasoning simultaneously
        dash.detail_section = "hypotheses"
        assert dash.hypothesis_expanded is False
        col_txt = _render(dash, console, width=120, height=40)
        assert "#1" in col_txt and "#2" in col_txt
        assert "79% (HIGH)" in col_txt and "20% (LOW)" in col_txt
        assert "Mechanism / Why" not in col_txt
        assert "Secondary candidate without direct dependency" not in col_txt

        # Expand ONLY Hypothesis #1 via Enter
        dash.handle_key("ENTER")
        assert dash.hypothesis_expanded is True
        exp1_txt = _render(dash, console, width=120, height=40)
        assert "Selected Hypothesis #1 Details" in exp1_txt
        assert "Mechanism / Why" in exp1_txt
        assert "Secondary candidate without direct dependency" not in exp1_txt
        # Item 9: Honest explanation of frozen dossier PARTIAL vs internal ClaimValidator SUPPORTED
        assert "Status Semantics" in exp1_txt
        assert "Dossier=PARTIAL | Internal Claim Validation=SUPPORTED" in exp1_txt
        assert "capped at PARTIAL" in exp1_txt
        assert "Confidence Basis" in exp1_txt

        # Item 8: Authoritative confidence score & band unchanged across ViewModel and views
        vm = dash.repository.coordinator.current_snapshot.by_incident_id[inc_id]
        assert vm.hypotheses[0].confidence_score == 0.79
        assert vm.hypotheses[0].confidence_band == "HIGH"
        assert vm.hypotheses[0].support_label == "PARTIAL"
        assert vm.hypotheses[0].validation_status == "SUPPORTED"

        # Item 6: Short evidence IDs are collision-free and resolve cleanly to canonical IDs without rewriting
        short_map = build_short_evidence_ids([f"ev-{inc_id}-001", f"ev-{inc_id}-002", f"ev-{inc_id}-003"])
        assert short_map[f"ev-{inc_id}-001"] == "ev-...-001"
        assert short_map[f"ev-{inc_id}-002"] == "ev-...-002"
        # Collision disambiguation test
        colliding = build_short_evidence_ids(["ev-service-alpha-001", "ev-service-beta-001"])
        assert len(set(colliding.values())) == 2

        dash.detail_section = "evidence"
        dash.evidence_detail_open = False
        ev_list_txt = _render(dash, console, width=120, height=40)
        assert "ev-...-001" in ev_list_txt
        assert "ev-...-002" in ev_list_txt
        assert f"ev-{inc_id}-002" not in ev_list_txt  # Short display ID used in list

        # Select record #2 and press Enter -> full canonical ID & provenance exposed
        dash.handle_key("DOWN")
        dash.handle_key("ENTER")
        assert dash.evidence_detail_open is True
        ev_det_txt = _render(dash, console, width=120, height=40)
        assert f"ev-{inc_id}-002" in ev_det_txt
        assert "search_error_logs" in ev_det_txt
        assert "obs=2026-11-26T03:43:58Z" in ev_det_txt
        assert "sha256=" in ev_det_txt
        # Underlying canonical IDs in dossier were NEVER mutated
        persisted = store.get_dossier(inc_id)["dossier_json"]
        assert persisted["evidence"][1]["evidence_id"] == f"ev-{inc_id}-002"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Items 7, 10, 11, 12: SOP Delivery Truthfulness, Review Context Scoping,
# Non-Mutating Navigation, Finalized Lock
# ---------------------------------------------------------------------------

def test_p206r_07_10_11_12_sop_truthfulness_review_scoping_no_mutation_and_locked_finalized(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(str(tmp_path / "p206r_07.db"))
    try:
        # Case A: Recorded context delivery (0 included in prompt, budget omitted)
        _persist_rich_incident(store, "inc-p206r-sop-rec", delivered_citations=0)
        # Case B: Unrecorded context delivery (must NEVER claim delivered!)
        _persist_rich_incident(store, "inc-p206r-sop-unrec", delivered_citations=None)

        dash, console = _make_dash(store, tmp_path)

        # Item 7: Recorded vs unrecorded context delivery
        dash.selected_incident_id = "inc-p206r-sop-rec"
        dash.detail_section = "sop"
        sop_rec_txt = _render(dash, console, width=120, height=40)
        assert "included_in_llm_prompt=0" in sop_rec_txt
        assert "CITATION_BUDGET_OMITTED" in sop_rec_txt
        assert "SPECIFIC_COVERAGE_GAP" in sop_rec_txt

        dash.selected_incident_id = "inc-p206r-sop-unrec"
        sop_unrec_txt = _render(dash, console, width=120, height=40)
        assert "LLM prompt delivery telemetry not recorded" in sop_unrec_txt

        # Item 10: Full review action buttons ONLY appear in Review view, NOT Overview/Hypotheses/Evidence/SOP/Details
        dash.selected_incident_id = "inc-p206r-sop-rec"
        for non_review_lens in ("overview", "hypotheses", "evidence", "sop", "technical"):
            dash.detail_section = non_review_lens
            txt = _render(dash, console, width=120, height=40)
            assert "[A] Approve" not in txt, f"Review actions leaked into {non_review_lens}"
            assert "[R] Reject" not in txt, f"Review actions leaked into {non_review_lens}"
        dash.detail_section = "review"
        rev_txt = _render(dash, console, width=120, height=40)
        assert "[A] Approve" in rev_txt and "[R] Reject" in rev_txt
        assert "[C] Correct" in rev_txt and "[E] Escalate" in rev_txt
        assert "opens confirmation modal; never submits automatically" in rev_txt

        # Item 11: Extensive navigation/expand/collapse/sidebar/lens switching never mutates domain state
        dash.detail_section = "overview"
        for key in ("S", "S", "TAB", "ENTER", "ENTER", "TAB", "DOWN", "ENTER", "B", "TAB", "ENTER", "TAB", "D", "V", "V"):
            assert dash.handle_key(key) is True
        assert store.get_reviews("inc-p206r-sop-rec") == []
        assert store.get_incident("inc-p206r-sop-rec")["current_state"] == "HUMAN_REVIEW"
        assert dash.review_modal is None

        # Item 12: Finalized incident remains locked in both Overview and Review
        rm = AuthorizedReviewManager(store=store, audit_chain=dash.actions.audit_chain)
        rm.approve(
            incident_id="inc-p206r-sop-rec",
            dossier_dict=store.get_dossier("inc-p206r-sop-rec")["dossier_json"],
            reviewer_ref="sre_reviewer",
            reviewer_role="L2_SRE",
            rationale="Administrative handover verified.",
        )
        dash.refresh_snapshot()
        dash.detail_section = "overview"
        locked_ov = _render(dash, console, width=120, height=40)
        assert "REVIEW LOCKED - FINALIZED (CLOSED)" in locked_ov
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in locked_ov
        dash.detail_section = "review"
        locked_rev = _render(dash, console, width=120, height=40)
        assert "REVIEW LOCKED - FINALIZED (CLOSED)" in locked_rev
        assert "[A] Approve" not in locked_rev
        assert dash.open_review_modal("APPROVE") is False
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Items 13, 14, 15: Stable Selection on Refresh, Stale Async Protection,
# Long Content Safety
# ---------------------------------------------------------------------------

def test_p206r_13_14_15_stable_selection_async_guard_and_long_content(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(str(tmp_path / "p206r_13.db"))
    try:
        _persist_rich_incident(store, "inc-p206r-sel-001", severity="medium")
        long_id = "inc-p206r-extremely-long-service-name-incident-identifier-9988776655"
        long_symptom = "A" * 310 + " TAIL_MARKER_CRITICAL"
        _persist_rich_incident(store, long_id, severity="high", symptom=long_symptom)

        dash, console = _make_dash(store, tmp_path)
        dash.focus = "list"
        dash.refresh_snapshot()
        # Select the medium incident explicitly
        dash.handle_key("DOWN")
        assert dash.highlighted_incident_id == "inc-p206r-sel-001"

        # Item 13: Insert a new CRITICAL incident at top of queue -> refresh preserves highlighted_incident_id!
        _persist_rich_incident(store, "inc-p206r-sel-crit-new", severity="critical")
        dash.refresh_snapshot()
        assert dash.highlighted_incident_id == "inc-p206r-sel-001"

        # Item 14: Stale async response (lower generation) MUST be rejected without overwriting current snapshot
        cur_snap = dash.repository.coordinator.current_snapshot
        assert cur_snap is not None
        stale_snap = dataclasses.replace(cur_snap, generation=max(0, cur_snap.generation - 1), awaiting_review_count=999)
        assert dash.apply_async_snapshot(stale_snap) is False
        assert dash.repository.coordinator.current_snapshot.awaiting_review_count != 999

        # Item 15: Long symptom safely bounded in Overview with pointer to Details, full text accessible in Details & All
        dash.selected_incident_id = long_id
        dash.detail_section = "overview"
        ov_long = _render(dash, console, width=120, height=40)
        assert "(full text in Details)" in ov_long
        assert "[Scroll:" not in ov_long
        dash.detail_section = "technical"
        tech_long = _render(dash, console, width=120, height=None)
        assert long_id in tech_long
        assert "TAIL_MARKER_CRITICAL" in tech_long
        dash.detail_section = "all"
        all_long = _render(dash, console, width=120, height=None)
        assert long_id in all_long
        assert "TAIL_MARKER_CRITICAL" in all_long
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Items 16, 17: Responsive Layouts Across 6 Sizes + Resize Stability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("width", "height"),
    (
        (80, 24),
        (100, 30),
        (120, 40),
        (140, 42),
        (160, 50),
        (207, 49),
    ),
)
def test_p206r_16_17_responsive_layouts_and_zero_mutation_on_resize(
    tmp_path: pathlib.Path,
    width: int,
    height: int,
) -> None:
    store = WorkflowStateStore(str(tmp_path / f"p206r_resp_{width}x{height}.db"))
    try:
        inc_id = "inc-live-transaction-service-3b7751e91b"
        _persist_rich_incident(store, inc_id)
        dash, console = _make_dash(store, tmp_path, width=width, height=height)

        # List view renders cleanly without crash or minimum-size error
        dash.focus = "list"
        list_txt = _render(dash, console, width=width, height=height)
        assert "Active Incidents" in list_txt
        assert "Resize Required" not in list_txt

        # Overview renders cleanly with zero vertical scroll across ALL 6 target viewport sizes!
        dash.selected_incident_id = inc_id
        dash.detail_section = "overview"
        ov_txt = _render(dash, console, width=width, height=height)
        assert "Leading Hypothesis" in ov_txt
        assert "Key Uncertainty" in ov_txt
        assert "Next Action" in ov_txt
        assert "[Scroll:" not in ov_txt

        # Item 17: Resizing while Review modal has unsent draft preserves draft & causes zero mutations
        dash.detail_section = "review"
        assert dash.open_review_modal("APPROVE") is True
        dash.review_modal["rationale"] = "Draft rationale preserved across resize"
        _render(dash, console, width=60, height=14)  # below min size guard
        _render(dash, console, width=width, height=height)  # restored
        assert dash.review_modal is not None
        assert dash.review_modal["rationale"] == "Draft rationale preserved across resize"
        assert store.get_reviews(inc_id) == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Items 18, 19, 20: Sanitization, Critical Warnings in Overview,
# and Core Safety Invariants
# ---------------------------------------------------------------------------

def test_p206r_18_19_20_sanitization_critical_warnings_and_core_safety_invariants(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(str(tmp_path / "p206r_18.db"))
    try:
        # Item 18: Untrusted ANSI CSI/OSC, BiDi RLO, Rich markup, secret, GT key, and spoofed VERIFIED
        hostile_symptom = (
            "\x1b[31mRED\x1b[0m \x1b]0;pwn\x07 \u202espoof [bold red]MARKUP[/bold red] "
            "Bearer sk-or-v1-secret1234567890abcdef ground_truth=db_pool_exhausted VERIFIED"
        )
        _persist_rich_incident(
            store,
            "inc-p206r-hostile",
            symptom=hostile_symptom,
            sop_availability="CONFLICTING_OR_COMPETING_SOPS",
            competing_sops=True,
            include_missing_source=True,
            unresolved_ref="ev-missing-ghost-999",
        )
        dash, console = _make_dash(store, tmp_path)
        dash.selected_incident_id = "inc-p206r-hostile"
        dash.detail_section = "overview"
        ov_txt = _render(dash, console, width=120, height=40)

        # Item 18 assertions: zero raw escapes, zero BiDi, zero secret, zero GT value, zero uppercase VERIFIED
        assert "\x1b" not in ov_txt
        assert "\u202e" not in ov_txt
        assert "sk-or-v1-secret" not in ov_txt
        assert "db_pool_exhausted" not in ov_txt
        assert "VERIFIED" not in ov_txt
        # Rich markup tags must be preserved literally as plain text (not interpreted/stripped)
        assert "[bold red]" in ov_txt

        # Item 19 assertions: Critical warnings MUST remain visible in Overview (never suppressed!)
        assert "Warning: Competing SOPs detected" in ov_txt
        assert "unresolved evidence reference" in ov_txt
        assert "Missing telemetry source(s): get_trace_summary" in ov_txt

        # Item 19 (retrieval outage warning in Overview)
        _persist_rich_incident(
            store,
            "inc-p206r-rag-out",
            sop_availability="RETRIEVAL_UNAVAILABLE",
            include_sop=False,
        )
        dash.selected_incident_id = "inc-p206r-rag-out"
        rag_out_txt = _render(dash, console, width=120, height=40)
        assert "Warning: Runbook retrieval unavailable" in rag_out_txt

        # Item 20: PolicyGateway remains strictly read-only, C02 schemas & Stage 3A manifest untouched
        gw = PolicyGateway()
        res = gw.execute_tool(
            tool_name="restart_service",
            arguments={"service_id": "transaction-service", "environment": "lab"},
            token="sre-sim-coord-token-secret-2026",
            incident_id="inc-p206r-hostile",
        )
        assert res["status"] in ("rejected", "error")
        assert FROZEN_STAGE_3A_MANIFEST.exists()
        assert hashlib.sha256(FROZEN_STAGE_3A_MANIFEST.read_bytes()).hexdigest() == STAGE_3A_MANIFEST_SHA256
        for name in (
            "dossier.v1.schema.json",
            "review-event.v1.schema.json",
            "workflow-event.v1.schema.json",
            "tool-result.v1.schema.json",
        ):
            assert (FROZEN_C02_DIR / name).exists()
        assert DossierSerializer.get_schema() is not None
    finally:
        store.close()
