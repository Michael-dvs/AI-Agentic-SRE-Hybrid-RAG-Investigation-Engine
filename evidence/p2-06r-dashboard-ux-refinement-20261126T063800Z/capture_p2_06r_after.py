#!/usr/bin/env python3
"""Capture actual P2-06R After-State visual renders (TXT + SVG + PNG) across views, states, and terminal sizes."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
import tempfile
from typing import Any, Callable

import cairosvg
from rich.console import Console

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer
from orchestrator.review import AuthorizedReviewManager
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import CostMetricsReader, SREDashboard, ServiceHealthInspector

EVIDENCE_ROOT = pathlib.Path(__file__).resolve().parent
AFTER_DIR = EVIDENCE_ROOT / "after"


def _patch_svg_font_for_macos(svg_text: str) -> str:
    return (
        svg_text.replace(
            '"Fira Code", monospace',
            '"Menlo", "Apple Symbols", "Arial Unicode MS", "Monaco", monospace',
        )
        .replace("&#9654;", '<tspan font-family="Arial Unicode MS">&#9654;</tspan>')
        .replace("▶", '<tspan font-family="Arial Unicode MS">&#9654;</tspan>')
    )


def main() -> int:
    AFTER_DIR.mkdir(parents=True, exist_ok=True)
    inc_id = "inc-live-transaction-service-3b7751e91b"
    closed_inc_id = "inc-live-transaction-service-82bdecc894"
    metrics: dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        db_copy = tmp / "live_copy.db"
        shutil.copy2(_REPO_ROOT / "orchestrator_state.db", db_copy)
        store = WorkflowStateStore(str(db_copy))

        # Also add a synthetic finalized CLOSED incident with clean review history if needed,
        # while primarily using the real live DB incidents for exact apples-to-apples comparison!
        healthy_stub = ServiceHealthInspector(
            command=(
                sys.executable,
                "-c",
                'import json; print(json.dumps([{"Service":"transaction-service","State":"running","Health":"healthy"}]))',
            )
        )
        degraded_stub = ServiceHealthInspector(command=(sys.executable, "-c", "import sys; sys.exit(1)"))

        def cap(
            slug: str,
            width: int,
            height: int,
            setup_fn: Callable[[SREDashboard], None],
            desc: str,
            *,
            target_store: WorkflowStateStore = store,
            health_inspector: ServiceHealthInspector = healthy_stub,
        ) -> None:
            c = Console(record=True, width=width, height=height, force_terminal=True, color_system="truecolor")
            dash = SREDashboard(
                target_store,
                console=c,
                reviewer_ref="sre_reviewer",
                reviewer_role="L2_SRE",
                health=health_inspector,
                costs=CostMetricsReader(tmp / "missing.json"),
                telegram=TelegramDispatcher(bot_token="", chat_id=""),
                audit_path=tmp / "audit.jsonl",
                handover_root=tmp / "handover",
            )
            setup_fn(dash)
            c.print(dash.render(width=width, height=height))
            txt = c.export_text(clear=False)
            svg = _patch_svg_font_for_macos(c.export_svg(title=f"AFTER (P2-06R) - {slug} ({width}x{height})", clear=False))
            (AFTER_DIR / f"{slug}.txt").write_text(txt, encoding="utf-8")
            (AFTER_DIR / f"{slug}.svg").write_text(svg, encoding="utf-8")
            cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(AFTER_DIR / f"{slug}.png"))

            total_content_lines = None
            if dash.selected_incident_id and dash.repository.coordinator.current_snapshot:
                vm = dash.repository.coordinator.current_snapshot.by_incident_id.get(dash.selected_incident_id)
                if vm is not None:
                    content_w = max(44, width - 2)
                    mc = Console(width=content_w, force_terminal=False, color_system=None)
                    det_lines = mc.render_lines(
                        dash._render_incident_detail_vm(
                            vm,
                            width=content_w,
                            compact_height=(height <= 26),
                        ),
                        mc.options,
                        pad=False,
                        new_lines=True,
                    )
                    total_content_lines = len(det_lines)

            scroll_m = re.search(r"\[Scroll: line (\d+)-(\d+)/(\d+)", txt)
            box_tops = txt.count("┌")
            shortcuts = len(re.findall(r"\[[A-Za-z0-9/?\[\] -]{1,12}\]", txt))
            metrics[slug] = {
                "dimensions": f"{width}x{height}",
                "capture_method": "Actual SREDashboard Rich render + Menlo SVG-to-PNG rasterization",
                "description": desc,
                "rendered_lines": len(txt.splitlines()),
                "total_unclipped_content_lines": total_content_lines,
                "scroll_indicator": scroll_m.group(0) if scroll_m else None,
                "requires_vertical_scroll": scroll_m is not None,
                "simultaneous_boxed_panels": box_tops,
                "bracketed_shortcut_or_tag_tokens": shortcuts,
            }
            print(f"Captured {slug} ({width}x{height}): lines={len(txt.splitlines())} content={total_content_lines} scroll={scroll_m is not None} boxes={box_tops}")

        # 1. Incident list (120x40)
        cap("01_incident_list_120x40", 120, 40, lambda d: setattr(d, "focus", "list"),
            "Redesigned Incident List at 120x40 with compact header, concise sidebar, and single context footer")

        # 2. Default Overview (120x40)
        cap("02_default_overview_120x40", 120, 40, lambda d: setattr(d, "selected_incident_id", inc_id),
            "Default Overview on live transaction-service incident at 120x40 (zero scrolling)")

        # 3. Reference Wide Default Overview (207x49) — apples-to-apples with reference screenshot!
        cap("03_wide_overview_207x49", 207, 49, lambda d: setattr(d, "selected_incident_id", inc_id),
            "Wide 207x49 Default Overview matching reference screenshot viewport (bounded readable measure)")

        # 4. Hypotheses list (collapsed, 120x40)
        def _hyp_list(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "hypotheses"
            d.hypothesis_expanded = False
        cap("04_hypotheses_list_120x40", 120, 40, _hyp_list,
            "Hypotheses view (concise table, collapsed by default)")

        # 5. Expanded Hypothesis #1 (120x40) — shows PARTIAL vs SUPPORTED explanation clearly!
        def _hyp_exp(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "hypotheses"
            d.selected_hypothesis_idx = 0
            d.hypothesis_expanded = True
        cap("05_expanded_hypothesis_120x40", 120, 40, _hyp_exp,
            "Expanded Hypothesis #1 showing mechanism, PARTIAL vs internal SUPPORTED explanation, confidence basis, and short evidence IDs")

        # 6. Evidence list (120x40)
        def _ev_list(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "evidence"
            d.evidence_detail_open = False
        cap("06_evidence_list_120x40", 120, 40, _ev_list,
            "Evidence list table with short display IDs, sources, concise summaries, validation status, temporal relevance, and linked hypothesis")

        # 7. Evidence detail (120x40) — record #2 (ACCEPTED_SUPPORT)
        def _ev_detail(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "evidence"
            d.selected_evidence_idx = 1
            d.evidence_detail_open = True
        cap("07_evidence_detail_120x40", 120, 40, _ev_detail,
            "Evidence detail view exposing full canonical evidence_id, provenance, timestamps, query window, values/units, and SHA-256")

        # 8. SOP & RAG summary + citations (120x40)
        def _sop_view(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "sop"
            d.sop_citation_expanded = True
        cap("08_sop_and_rag_120x40", 120, 40, _sop_view,
            "SOP & RAG view separating retrieval/delivery summary (0 delivered, budget omitted) from expandable authorized citation excerpt and NOT_PERFORMED checks")

        # 9. Human Review view (120x40) — ONLY context displaying full review action controls!
        def _rev_view(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "review"
        cap("09_human_review_120x40", 120, 40, _rev_view,
            "Human Review view displaying revision, diagnosis status, uncertainties, trust mode, eligibility, and authorized review controls")

        # 10. Technical Details / Audit view (120x40)
        def _tech_view(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "technical"
        cap("10_technical_details_120x40", 120, 40, _tech_view,
            "Technical Details & Audit view housing full incident ID, provider/model, tokens, prompt hash, 9-stage pipeline, topology, and confidence formulas")

        # 11. Compact terminal 80x24 (Overview & List)
        cap("11a_compact_overview_80x24", 80, 24, lambda d: setattr(d, "selected_incident_id", inc_id),
            "Compact 80x24 Overview verifying zero clipping and accessible single-line lens bar")
        cap("11b_compact_list_80x24", 80, 24, lambda d: setattr(d, "focus", "list"),
            "Compact 80x24 Incident List with horizontal nav strip")

        # 12. Responsive mid/wide sizes: 100x30, 140x42, 160x50
        cap("12a_responsive_overview_100x30", 100, 30, lambda d: setattr(d, "selected_incident_id", inc_id),
            "Responsive 100x30 Default Overview")
        cap("12b_responsive_overview_140x42", 140, 42, lambda d: setattr(d, "selected_incident_id", inc_id),
            "Responsive 140x42 Default Overview")
        cap("12c_wide_list_160x50", 160, 50, lambda d: setattr(d, "focus", "list"),
            "Wide 160x50 Incident List with bounded readable width and inline symptoms")

        # 13. Empty state (100x30)
        empty_store = WorkflowStateStore(":memory:")
        cap("13_empty_state_100x30", 100, 30, lambda d: setattr(d, "focus", "list"),
            "Empty incident queue explaining cause and next operator action",
            target_store=empty_store)
        empty_store.close()

        # 14. Degraded / stale state (120x40)
        def _degraded(d: SREDashboard) -> None:
            d.focus = "list"
            d.repository.coordinator.get_cached_health(degraded_stub.inspect, force=True)
            d.refresh_snapshot()
            def _fail(**kw: Any) -> Any:
                raise RuntimeError("SQLite database is locked by external writer")
            d.repository.coordinator._read_atomic_snapshot = _fail  # type: ignore[method-assign]
            d.refresh_snapshot()
            d.repository.coordinator._read_atomic_snapshot = _fail  # type: ignore[method-assign]
        cap("14_degraded_stale_120x40", 120, 40, _degraded,
            "Degraded backend state surfacing STALE LAST-KNOWN DATA banner while keeping last-known queue readable",
            health_inspector=degraded_stub)

        # 15. Finalized review (CLOSED in Archive, 120x40)
        def _finalized(d: SREDashboard) -> None:
            d.view = "archive"
            d.selected_incident_id = closed_inc_id
            d.detail_section = "overview"
        cap("15a_finalized_overview_120x40", 120, 40, _finalized,
            "Finalized CLOSED incident Overview with explicit administrative handover disclaimer and locked next action")

        def _finalized_rev(d: SREDashboard) -> None:
            d.view = "archive"
            d.selected_incident_id = closed_inc_id
            d.detail_section = "review"
        cap("15b_finalized_review_120x40", 120, 40, _finalized_rev,
            "Finalized CLOSED incident Human Review view with locked review controls")

        # 16. Review confirmation modal (120x40) — confirms two-step non-automatic review submission
        def _rev_modal(d: SREDashboard) -> None:
            d.selected_incident_id = inc_id
            d.detail_section = "review"
            d.refresh_snapshot()
            d.open_review_modal("APPROVE")
        cap("16_review_confirmation_modal_120x40", 120, 40, _rev_modal,
            "Two-step Human Review confirmation modal preserving rationale, safety boundary, and explicit cancel/confirm")

        store.close()

    (AFTER_DIR / "after_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Saved {len(metrics)} after-state captures and after_metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
