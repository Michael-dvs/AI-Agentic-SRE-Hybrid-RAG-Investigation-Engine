#!/usr/bin/env python3
"""Generate reproducible P2-06 After-State visual captures (TXT + SVG + PNG) and real PTY interaction trace."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import pathlib
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from typing import Any, Callable

import cairosvg
from rich.console import Console, Group
from rich.text import Text

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.console_config import EnvConfigManager
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import (
    CostMetricsReader,
    SREDashboard,
    ServiceHealthInspector,
)

EVIDENCE_ROOT = pathlib.Path(__file__).resolve().parent
AFTER_DIR = EVIDENCE_ROOT / "after"
PTY_DIR = EVIDENCE_ROOT / "pty"


def _patch_svg_font_for_macos(svg_text: str) -> str:
    """Use macOS system monospace font Menlo + explicit Arial Unicode MS tspan for U+25B6 in CairoSVG."""
    patched = svg_text.replace(
        '"Fira Code", monospace',
        '"Menlo", "Apple Symbols", "Arial Unicode MS", "Monaco", monospace',
    )
    patched = patched.replace(
        "&#9654;",
        '<tspan font-family="Arial Unicode MS">&#9654;</tspan>',
    )
    patched = patched.replace(
        "▶",
        '<tspan font-family="Arial Unicode MS">&#9654;</tspan>',
    )
    return patched


def _seed_synthetic_scenarios(store: WorkflowStateStore) -> dict[str, str]:
    """Populate realistic synthetic banking PoC scenarios covering all 16 N2 states."""
    sm = InvestigationStateMachine(store=store)

    # 1. Supported Critical Incident with RAG delivery diagnostics & multi-signal evidence
    inc_sup = "inc-sim-ledger-pool-001"
    for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED", "RETRIEVED", "HYPOTHESES", "VALIDATED", "DRAFTED", "HUMAN_REVIEW"):
        sm.transition(inc_sup, st, f"idem-{inc_sup}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        ("ledger-service", "lab", inc_sup),
    )
    sup_ctx: dict[str, Any] = {
        "incident_id": inc_sup,
        "service_id": "ledger-service",
        "environment": "lab",
        "event_time": "2026-11-26T02:00:00Z",
        "dossier_ready_at": "2026-11-26T02:00:14Z",
        "assessment_time": "2026-11-26T02:00:14Z",
        "priority": "critical",
        "message": "PostgreSQL connection pool checkout timeout on ledger-service (HTTP 503 burst).",
        "investigation_scope": ["ledger-service", "transaction-service", "api-gateway"],
        "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{inc_sup}-001",
                "rank": 1,
                "title": "PostgreSQL connection pool saturation on ledger-service",
                "statement": "PostgreSQL connection pool saturation on ledger-service causing upstream 503 timeouts.",
                "reason_summary": "Correlated ERR_CONNECTION_POOL_EXHAUSTED logs and 0.42 error_rate ratio align within 2026-11-26T01:55..02:00Z.",
                "supporting_evidence_ids": ["ev-ledger-log-01", "ev-ledger-metric-01"],
                "contradicting_evidence_ids": [],
                "confidence_score": 0.78,
                "confidence_rationale": "Supported by 2 modalities (logs + metrics) inside incident window; capped at heuristic ceiling.",
                "status": "SUPPORTED",
                "unknowns": ["Database server-side max_connections parameter requires read-only DBA inspection."],
            },
            {
                "hypothesis_id": f"hyp-{inc_sup}-002",
                "rank": 2,
                "statement": "Network packet loss between transaction-service and ledger-service.",
                "reason_summary": "Downstream timeout observed, but direct pool saturation logs contradict pure network drop.",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": ["ev-ledger-log-01"],
                "confidence_score": 0.12,
                "confidence_rationale": "Contradicted by direct pool checkout error logs on ledger-service.",
                "status": "CONTRADICTED",
            },
        ],
        "evidence_items": [
            {
                "evidence_id": "ev-ledger-log-01",
                "incident_id": inc_sup,
                "service_id": "ledger-service",
                "environment": "lab",
                "tool_name": "search_error_logs",
                "status": "ok",
                "data_quality": "complete",
                "truncated": False,
                "source_ref": "loki:ledger-service",
                "observed_at": "2026-11-26T01:59:42Z",
                "collected_at": "2026-11-26T02:00:04Z",
                "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
                "sampling": {"method": None, "returned": 14},
                "records": [
                    {
                        "timestamp": "2026-11-26T01:59:42Z",
                        "error_code": "ERR_CONNECTION_POOL_EXHAUSTED",
                        "status_code": 503,
                        "message": "QueuePool limit of size 10 overflow 0 reached, connection timed out",
                    }
                ],
            },
            {
                "evidence_id": "ev-ledger-metric-01",
                "incident_id": inc_sup,
                "service_id": "ledger-service",
                "environment": "lab",
                "tool_name": "get_service_metrics",
                "status": "ok",
                "data_quality": "complete",
                "truncated": False,
                "source_ref": "prometheus:ledger-service:error_rate",
                "observed_at": "2026-11-26T01:59:45Z",
                "collected_at": "2026-11-26T02:00:05Z",
                "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
                "sampling": {"method": None, "returned": 5},
                "records": [
                    {
                        "metric_name": "error_rate",
                        "value": 0.42,
                        "unit": "ratio",
                        "aggregation": "rate_5m",
                        "sample_at": "2026-11-26T01:59:45Z",
                    }
                ],
            },
        ],
        "sop_availability": "APPLICABLE_SOP_FOUND",
        "rag_diagnostics": {
            "retrieved_count": 4,
            "eligible_count": 2,
            "delivered_sop_count": 2,
            "omitted_sop_count": 0,
            "omission_reasons": [],
            "compaction_rung": "rung_0_full",
        },
        "runbook_citations": [
            {
                "chunk_id": "chunk-sop-ledger-002-04",
                "document_id": "SOP-LEDGER-002",
                "document_version": "2.1.0",
                "title": "Ledger Connection Pool Saturation",
                "service_id": "ledger-service",
                "environment": "lab",
                "status": "approved",
                "applicability_verified": True,
                "sanitized": True,
                "effective_from": "2026-11-01T00:00:00Z",
                "effective_to": None,
                "score": 0.0328,
                "score_type": "rrf_fusion",
                "source_branch": "hybrid",
                "section_path": "4.2 Connection Pool Exhaustion Diagnostics",
                "source_uri": "kb://runbooks/sop-ledger-002.md",
                "sanitized_excerpt": "Compare active checkout wait count against error_rate before escalating to DBA.",
                "content_hash": "b" * 64,
            }
        ],
        "impact_graph": {
            "primary_service": "ledger-service",
            "upstream_callers": ["api-gateway", "transaction-service"],
            "downstream_dependencies": ["postgres-ledger"],
            "uncertainty": "Topology edges reflect static catalog; runtime circuit-breaker state requires human check.",
        },
        "tool_calls_used": 4,
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "provider": "openrouter",
            "model_version": "nvidia/nemotron-3.5-lightning:free",
            "prompt_version": "p1-05-grounded-v2",
            "tool_schema_version": "1.0",
            "kb_version": "kb-idx-20261111-v1",
            "input_tokens": 980,
            "output_tokens": 310,
            "total_tokens": 1290,
        },
    }
    sup_dossier = DossierSerializer.serialize(sup_ctx, investigation_mode="agentic_llm")
    sup_dossier["reproducibility"].update({
        "provider": "openrouter",
        "input_tokens": 980,
        "output_tokens": 310,
        "total_tokens": 1290,
    })
    sup_dossier["dossier_hash"] = DossierSerializer.serialize(sup_ctx, investigation_mode="agentic_llm")["dossier_hash"]
    # Recompute canonical hash cleanly
    from orchestrator.dossier import compute_canonical_dossier_hash
    sup_dossier["dossier_hash"] = compute_canonical_dossier_hash(sup_dossier)
    store.save_checkpoint(inc_sup, "HUMAN_REVIEW", sup_ctx)
    store.save_dossier(inc_sup, 1, sup_dossier["dossier_hash"], sup_dossier, DossierMarkdownRenderer.render(sup_dossier))

    # 2. Unsupported / Weak Hypothesis + Competing SOPs + Stale/Out-of-Window/Unresolved Evidence
    inc_weak = "inc-sim-auth-competing-002"
    for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED", "RETRIEVED", "HYPOTHESES", "VALIDATED", "DRAFTED", "HUMAN_REVIEW"):
        sm.transition(inc_weak, st, f"idem-{inc_weak}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        ("auth-service", "lab", inc_weak),
    )
    weak_ctx: dict[str, Any] = {
        "incident_id": inc_weak,
        "service_id": "auth-service",
        "environment": "lab",
        "event_time": "2026-11-26T01:40:00Z",
        "dossier_ready_at": "2026-11-26T02:20:00Z",
        "assessment_time": "2026-11-26T02:20:00Z",
        "priority": "high",
        "message": "Intermittent HTTP 401/500 spike on auth-service token validation.",
        "investigation_scope": ["auth-service", "api-gateway"],
        "query_window": {"start": "2026-11-26T01:35:00Z", "end": "2026-11-26T01:40:00Z"},
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{inc_weak}-001",
                "rank": 1,
                "statement": "JWKS signing key rotation mismatch across auth-service replicas.",
                "reason_summary": "[UNSUPPORTED] Candidate mechanism lacks corroborated window telemetry; Tempo traces unavailable.",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "confidence_score": 0.14,
                "confidence_rationale": "Zero accepted supporting signals; trace backend unavailable (-0.15 penalty).",
                "confidence_breakdown": {
                    "excluded_supporting": [
                        {"evidence_id": "ev-auth-stale-99", "reason": "OUTSIDE_INCIDENT_WINDOW (observed 3h prior)"},
                    ],
                    "partial_supporting_ids": ["ev-auth-log-partial"],
                },
                "status": "INCONCLUSIVE",
                "unknowns": ["Tempo trace backend returned SOURCE_UNAVAILABLE during incident window."],
            }
        ],
        "evidence_items": [
            {
                "evidence_id": "ev-auth-log-partial",
                "incident_id": inc_weak,
                "service_id": "auth-service",
                "environment": "lab",
                "tool_name": "search_error_logs",
                "status": "ok",
                "data_quality": "partial",
                "truncated": True,
                "source_ref": "loki:auth-service",
                "observed_at": "2026-11-26T01:38:10Z",
                "collected_at": "2026-11-26T01:40:05Z",
                "query_window": {"start": "2026-11-26T01:35:00Z", "end": "2026-11-26T01:40:00Z"},
                "sampling": {"method": "head_limit", "returned": 50},
                "records": [{"timestamp": "2026-11-26T01:38:10Z", "error_code": "ERR_AUTH_TOKEN", "message": "Token verify warning"}],
            },
            {
                "evidence_id": "ev-auth-stale-99",
                "incident_id": inc_weak,
                "service_id": "auth-service",
                "environment": "lab",
                "tool_name": "get_service_metrics",
                "status": "ok",
                "data_quality": "complete",
                "truncated": False,
                "source_ref": "prometheus:auth-service:latency_p95",
                "observed_at": "2026-11-25T22:10:00Z",
                "collected_at": "2026-11-26T01:40:06Z",
                "query_window": {"start": "2026-11-25T22:05:00Z", "end": "2026-11-25T22:10:00Z"},
                "records": [{"metric_name": "latency_p95", "value": 810.0, "unit": "ms", "aggregation": "p95"}],
            },
        ],
        "missing_sources": [
            {
                "tool_name": "get_trace_summary",
                "error_code": "SOURCE_UNAVAILABLE",
                "recorded_at": "2026-11-26T01:40:07Z",
                "impact_note": "Tempo trace backend unreachable (connection refused); zero spans fabricated.",
            }
        ],
        "sop_availability": "CONFLICTING_OR_COMPETING_SOPS",
        "rag_diagnostics": {
            "retrieved_count": 5,
            "eligible_count": 2,
            "delivered_sop_count": 1,
            "omitted_sop_count": 1,
            "omission_reasons": ["prompt_byte_budget_4096_rung_2"],
            "compaction_rung": "rung_2_trim_secondary_sops",
        },
        "runbook_citations": [
            {
                "chunk_id": "chk-auth-101",
                "document_id": "SOP-AUTH-001",
                "document_version": "1.2.0",
                "title": "JWKS Signing Key Rotation Runbook",
                "service_id": "auth-service",
                "environment": "lab",
                "status": "approved",
                "applicability_verified": True,
                "sanitized": True,
                "effective_from": "2026-10-01T00:00:00Z",
                "effective_to": None,
                "score": 0.0291,
                "score_type": "rrf_fusion",
                "source_branch": "hybrid",
                "section_path": "2.1 JWKS Key Cache Skew",
                "source_uri": "kb://runbooks/sop-auth-001.md",
                "sanitized_excerpt": "Inspect JWKS kid header alignment across replicas in read-only metrics.",
                "content_hash": "c" * 64,
            },
            {
                "chunk_id": "chk-auth-202",
                "document_id": "SOP-AUTH-004",
                "document_version": "1.0.0",
                "title": "OIDC Token Audience Drift Runbook",
                "service_id": "auth-service",
                "environment": "lab",
                "status": "approved",
                "applicability_verified": True,
                "sanitized": True,
                "effective_from": "2026-10-15T00:00:00Z",
                "effective_to": None,
                "score": 0.0284,
                "score_type": "rrf_fusion",
                "source_branch": "hybrid",
                "section_path": "3.4 Upstream OIDC Audience Drift",
                "source_uri": "kb://runbooks/sop-auth-004.md",
                "sanitized_excerpt": "Compare token audience claim config before escalating to Identity team.",
                "content_hash": "d" * 64,
            },
        ],
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "model_version": "deterministic_rule_engine_v1",
            "prompt_version": "fallback_rules_v1",
            "tool_schema_version": "1.0",
            "kb_version": "kb-idx-20261111-v1",
        },
    }
    weak_dossier = DossierSerializer.serialize(weak_ctx, investigation_mode="manual_fallback")
    # Inject an unresolved hypothesis reference into checkpoint/dossier view test without breaking schema
    weak_dossier_view = dict(weak_dossier)
    store.save_checkpoint(inc_weak, "HUMAN_REVIEW", weak_ctx)
    store.save_dossier(inc_weak, 1, weak_dossier_view["dossier_hash"], weak_dossier_view, DossierMarkdownRenderer.render(weak_dossier_view))

    # 3. Investigation Currently In Progress (EVIDENCE_COLLECTED - Stage 4/9, no dossier yet)
    inc_run = "inc-sim-notif-lag-running-003"
    for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED"):
        sm.transition(inc_run, st, f"idem-{inc_run}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        ("notification-service", "lab", inc_run),
    )
    store.save_checkpoint(
        inc_run,
        "EVIDENCE_COLLECTED",
        {
            "incident_id": inc_run,
            "service_id": "notification-service",
            "environment": "lab",
            "priority": "medium",
            "event_time": "2026-11-26T02:18:00Z",
            "message": "RabbitMQ consumer queue lag rising on notification-service; collecting telemetry.",
            "investigation_mode": "in_progress",
            "tool_calls_used": 2,
        },
    )

    # 4. Retrieval Unavailable Incident
    inc_rag_down = "inc-sim-tx-rag-down-004"
    for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED", "RETRIEVED", "HYPOTHESES", "VALIDATED", "DRAFTED", "HUMAN_REVIEW"):
        sm.transition(inc_rag_down, st, f"idem-{inc_rag_down}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        ("transaction-service", "lab", inc_rag_down),
    )
    rag_down_ctx: dict[str, Any] = {
        "incident_id": inc_rag_down,
        "service_id": "transaction-service",
        "environment": "lab",
        "event_time": "2026-11-26T02:10:00Z",
        "priority": "high",
        "message": "Elevated HTTP 502 responses on transaction-service /transfer.",
        "investigation_scope": ["transaction-service"],
        "query_window": {"start": "2026-11-26T02:05:00Z", "end": "2026-11-26T02:10:00Z"},
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{inc_rag_down}-001",
                "rank": 1,
                "statement": "Downstream ledger-service HTTP 503 propagation into transaction-service.",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "confidence_score": 0.22,
                "status": "INCONCLUSIVE",
            }
        ],
        "evidence_items": [],
        "sop_availability": "RETRIEVAL_UNAVAILABLE",
        "runbook_citations": [],
        "version_manifest": {"workflow_version": "1.0.0"},
    }
    rag_down_dossier = DossierSerializer.serialize(rag_down_ctx)
    store.save_checkpoint(inc_rag_down, "HUMAN_REVIEW", rag_down_ctx)
    store.save_dossier(inc_rag_down, 1, rag_down_dossier["dossier_hash"], rag_down_dossier, DossierMarkdownRenderer.render(rag_down_dossier))

    # 5. Administratively Closed Historical Incident (via real AuthorizedReviewManager)
    inc_closed = "inc-sim-gw-closed-hist-005"
    for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED", "RETRIEVED", "HYPOTHESES", "VALIDATED", "DRAFTED", "HUMAN_REVIEW"):
        sm.transition(inc_closed, st, f"idem-{inc_closed}-{st}")
    store._conn.execute(
        "UPDATE incidents SET service_id = ?, environment = ? WHERE incident_id = ?",
        ("api-gateway", "lab", inc_closed),
    )
    closed_ctx = dict(sup_ctx)
    closed_ctx["incident_id"] = inc_closed
    closed_ctx["service_id"] = "api-gateway"
    closed_ctx["priority"] = "high"
    closed_ctx["investigation_scope"] = ["api-gateway", "auth-service"]
    closed_ctx["impact_graph"] = {
        "primary_service": "api-gateway",
        "upstream_callers": ["mobile-banking-edge"],
        "downstream_dependencies": ["auth-service", "transaction-service"],
        "uncertainty": "Topology edges reflect static catalog; runtime rate-limiter counters require human check.",
    }
    closed_ctx["message"] = "Historical API Gateway rate-limit spike; administratively handed over."
    closed_ctx["hypotheses"] = [
        {
            "hypothesis_id": f"hyp-{inc_closed}-001",
            "rank": 1,
            "statement": "Burst rate-limit threshold triggered HTTP 429 responses on api-gateway.",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "confidence_score": 0.35,
            "status": "PARTIAL",
        }
    ]
    closed_ctx["evidence_items"] = []
    closed_ctx["runbook_citations"] = []
    closed_ctx["sop_availability"] = "NO_APPLICABLE_RUNBOOK"
    closed_dossier = DossierSerializer.serialize(closed_ctx)
    store.save_checkpoint(inc_closed, "HUMAN_REVIEW", closed_ctx)
    store.save_dossier(inc_closed, 1, closed_dossier["dossier_hash"], closed_dossier, DossierMarkdownRenderer.render(closed_dossier))

    from orchestrator.review import AuthorizedReviewManager
    rm = AuthorizedReviewManager(state_machine=sm, store=store)
    rm.approve(
        incident_id=inc_closed,
        dossier_dict=closed_dossier,
        reviewer_ref="sre_lead_rina",
        reviewer_role="L2_SRE",
        rationale="Accepted dossier for handover to API platform squad; live throttle check pending.",
    )

    return {
        "supported": inc_sup,
        "weak_competing": inc_weak,
        "running": inc_run,
        "rag_down": inc_rag_down,
        "closed": inc_closed,
    }


def main() -> int:
    AFTER_DIR.mkdir(parents=True, exist_ok=True)
    PTY_DIR.mkdir(parents=True, exist_ok=True)

    captures_manifest: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        db_path = tmp_path / "p2_06_visuals.db"
        clean_env = tmp_path / ".env"
        clean_env.write_text(
            "LLM_PROVIDER=openrouter\nLLM_MODEL=nvidia/nemotron-3.5-lightning:free\n",
            encoding="utf-8",
        )
        env_mgr = EnvConfigManager(env_path=clean_env, example_path=tmp_path / ".env.example")

        store = WorkflowStateStore(str(db_path))
        ids = _seed_synthetic_scenarios(store)

        healthy_stub = ServiceHealthInspector(
            command=(
                sys.executable,
                "-c",
                'import json; print(json.dumps(['
                '{"Service":"api-gateway","State":"running","Health":"healthy"},'
                '{"Service":"auth-service","State":"running","Health":"healthy"},'
                '{"Service":"transaction-service","State":"running","Health":"healthy"},'
                '{"Service":"ledger-service","State":"running","Health":"healthy"},'
                '{"Service":"notification-service","State":"running","Health":"healthy"}'
                ']))',
            )
        )
        degraded_stub = ServiceHealthInspector(command=(sys.executable, "-c", "import sys; sys.exit(1)"))

        def capture(
            slug: str,
            width: int,
            height: int,
            scenario_desc: str,
            setup_fn: Callable[[SREDashboard], None],
            *,
            target_store: WorkflowStateStore = store,
            health_inspector: ServiceHealthInspector = healthy_stub,
        ) -> None:
            c = Console(record=True, width=width, height=height, force_terminal=True, color_system="truecolor")
            dash = SREDashboard(
                target_store,
                console=c,
                reviewer_ref="sre_operator_maya",
                reviewer_role="L2_SRE",
                env_manager=env_mgr,
                health=health_inspector,
                costs=CostMetricsReader(tmp_path / "missing-costs.json"),
                telegram=TelegramDispatcher(bot_token="", chat_id=""),
                audit_path=tmp_path / "audit.jsonl",
                handover_root=tmp_path / "handover",
            )
            dash.repository.coordinator.get_cached_health(health_inspector.inspect, force=True)
            setup_fn(dash)
            footer = Text(
                "Controls: Up/Dn or j/k=Move | Left/Right/Tab=Switch | Enter=Open | 1-5=Tab | ?=Help | B/Esc=Back | Q=Quit",
                style="#94a3b8",
            )
            c.print(Group(dash.render(width=width, height=height), footer))
            txt = c.export_text(clear=False)
            svg = _patch_svg_font_for_macos(
                c.export_svg(title=f"AFTER - {slug} ({width}x{height})", clear=False)
            )
            txt_p = AFTER_DIR / f"{slug}.txt"
            svg_p = AFTER_DIR / f"{slug}.svg"
            png_p = AFTER_DIR / f"{slug}.png"
            txt_p.write_text(txt, encoding="utf-8")
            svg_p.write_text(svg, encoding="utf-8")
            cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_p))
            captures_manifest.append({
                "id": slug,
                "dimensions": f"{width}x{height}",
                "capture_method": "Rich Console render + Menlo SVG-to-PNG rasterization",
                "scenario": scenario_desc,
                "files": {
                    "png": str(png_p.relative_to(_REPO_ROOT)),
                    "svg": str(svg_p.relative_to(_REPO_ROOT)),
                    "txt": str(txt_p.relative_to(_REPO_ROOT)),
                },
            })
            print(f"Captured: {slug} ({width}x{height})")

        # N2.1 Normal incident overview (120x40)
        capture(
            "01_normal_overview_120x40",
            120,
            40,
            "Normal incident overview with global status strip, priority triage sorting, and symptom preview",
            lambda d: setattr(d, "focus", "list"),
        )

        # N2.2 Multiple active incidents wide layout (160x50)
        capture(
            "02_multiple_active_wide_160x50",
            160,
            50,
            "Wide 160x50 incident queue showing CRITICAL/HIGH/MEDIUM active & running incidents with inline symptoms",
            lambda d: setattr(d, "focus", "list"),
        )

        # N2.3 Investigation in progress (120x40)
        def _setup_running(d: SREDashboard) -> None:
            d.selected_incident_id = ids["running"]
            d.detail_section = "overview"

        capture(
            "03_investigation_in_progress_120x40",
            120,
            40,
            "Active investigation at stage EVIDENCE_COLLECTED (4/9) before dossier generation",
            _setup_running,
        )

        # N2.4 Supported hypothesis & confidence (120x40)
        def _setup_supported(d: SREDashboard) -> None:
            d.selected_incident_id = ids["supported"]
            d.detail_section = "hypotheses"

        capture(
            "04_supported_hypothesis_120x40",
            120,
            40,
            "Supported #1 hypothesis (78% HIGH heuristic, uncalibrated) and contradicted #2 hypothesis",
            _setup_supported,
        )

        # N2.5 Unsupported / inconclusive hypothesis (120x40)
        def _setup_weak(d: SREDashboard) -> None:
            d.selected_incident_id = ids["weak_competing"]
            d.detail_section = "hypotheses"

        capture(
            "05_unsupported_hypothesis_120x40",
            120,
            40,
            "Unsupported/inconclusive low-confidence hypothesis (14% LOW) with rejected & partial evidence disclosures",
            _setup_weak,
        )

        # N2.6 Evidence detail & provenance (120x40)
        def _setup_ev_detail(d: SREDashboard) -> None:
            d.selected_incident_id = ids["supported"]
            d.detail_section = "evidence"

        capture(
            "06_evidence_detail_lineage_120x40",
            120,
            40,
            "Evidence Lineage view showing Loki/Prometheus provenance, units, windows, and SHA-256 consistency hashes",
            _setup_ev_detail,
        )

        # N2.7 Historical/partial vs rejected outside-window evidence (120x40)
        def _setup_ev_stale(d: SREDashboard) -> None:
            d.selected_incident_id = ids["weak_competing"]
            d.detail_section = "evidence"

        capture(
            "07_historical_partial_and_rejected_evidence_120x40",
            120,
            40,
            "Evidence Lineage distinguishing [HISTORICAL_VALID][PARTIAL] from REJECTED [OUTSIDE_WINDOW] telemetry",
            _setup_ev_stale,
        )

        # N2.8 SOP retrieval success & LLM prompt delivery diagnostics (120x40)
        def _setup_sop_ok(d: SREDashboard) -> None:
            d.selected_incident_id = ids["supported"]
            d.detail_section = "sop"

        capture(
            "08_sop_retrieval_and_delivery_120x40",
            120,
            40,
            "Applicable SOP citation with P1-04 retrieval vs LLM prompt delivery counts and RRF score disclaimer",
            _setup_sop_ok,
        )

        # N2.9 Competing SOPs & prompt compaction disclosure (120x40)
        def _setup_sop_competing(d: SREDashboard) -> None:
            d.selected_incident_id = ids["weak_competing"]
            d.detail_section = "sop"

        capture(
            "09_competing_sops_and_compaction_120x40",
            120,
            40,
            "CONFLICTING_OR_COMPETING_SOPS escalation warning and prompt byte-budget compaction disclosure",
            _setup_sop_competing,
        )

        # N2.10 Retrieval unavailable & pending NOT_PERFORMED manual verification (120x40)
        def _setup_rag_down(d: SREDashboard) -> None:
            d.selected_incident_id = ids["rag_down"]
            d.detail_section = "sop"

        capture(
            "10_retrieval_unavailable_manual_checks_120x40",
            120,
            40,
            "RETRIEVAL_UNAVAILABLE distinguished from NO_APPLICABLE_RUNBOOK with NOT_PERFORMED human checks",
            _setup_rag_down,
        )

        # N2.11 Human Review readiness summary (120x40)
        def _setup_review_summary(d: SREDashboard) -> None:
            d.selected_incident_id = ids["supported"]
            d.detail_section = "review"

        capture(
            "11_human_review_readiness_120x40",
            120,
            40,
            "Human Review readiness panel showing reviewer role, caller-asserted trust boundary, and closure semantics",
            _setup_review_summary,
        )

        # N2.12 Two-step Human Review confirmation modal (120x40)
        def _setup_review_modal(d: SREDashboard) -> None:
            d.selected_incident_id = ids["supported"]
            d.refresh_snapshot()
            d.open_review_modal("APPROVE")
            if d.review_modal is not None:
                d.review_modal["rationale"] = "Pool checkout saturation corroborated by Loki 503 logs and Prometheus error_rate."
                d.review_modal["focus_idx"] = 1  # focus Confirm button

        capture(
            "12_review_confirmation_modal_120x40",
            120,
            40,
            "Version-bound APPROVE confirmation modal displaying administrative handover disclaimers and Cancel(Esc)",
            _setup_review_modal,
        )

        # N2.13 Finalized / locked historical incident (120x40)
        def _setup_closed(d: SREDashboard) -> None:
            d.view = "archive"
            d.selected_incident_id = ids["closed"]
            d.detail_section = "overview"

        capture(
            "13_finalized_locked_archive_120x40",
            120,
            40,
            "Administratively CLOSED historical dossier with locked review controls and technical_resolved=False",
            _setup_closed,
        )

        # N2.14 Degraded backend / stale last-known snapshot (120x40)
        def _setup_degraded(d: SREDashboard) -> None:
            d.focus = "list"
            d.refresh_snapshot()
            # Simulate transient SQLite lock/failure after valid snapshot was loaded
            orig_read = d.repository.coordinator._read_atomic_snapshot
            def _fail_read(**kwargs: Any) -> Any:
                raise RuntimeError("SQLite database is locked by external writer")
            d.repository.coordinator._read_atomic_snapshot = _fail_read  # type: ignore[method-assign]
            d.refresh_snapshot()
            # Keep broken reader for the render pass to capture banner
            d.repository.coordinator._read_atomic_snapshot = _fail_read  # type: ignore[method-assign]

        capture(
            "14_degraded_stale_last_known_120x40",
            120,
            40,
            "Degraded backend banner marking retained view as STALE LAST-KNOWN DATA alongside unavailable Docker probe",
            _setup_degraded,
            health_inspector=degraded_stub,
        )

        # N2.15 Empty incident list at standard 100x30
        empty_store = WorkflowStateStore(":memory:")
        capture(
            "15_empty_incident_queue_100x30",
            100,
            30,
            "Empty incident queue at 100x30 explaining cause and next operator actions",
            lambda d: setattr(d, "focus", "list"),
            target_store=empty_store,
        )
        empty_store.close()

        # N2.16 Compact terminal layout 80x24 + Help overlay + Minimum-size guard
        capture(
            "16_compact_layout_80x24",
            80,
            24,
            "Compact 80x24 stacked navigation and incident queue preserving priority and unique ID suffixes",
            lambda d: setattr(d, "focus", "list"),
        )
        capture(
            "17_keyboard_help_overlay_120x40",
            120,
            40,
            "Discoverable [?] Keyboard & Safety Semantics Reference modal",
            lambda d: setattr(d, "help_open", True),
        )
        capture(
            "18_minimum_size_guard_60x14",
            60,
            14,
            "Recoverable minimum-dimension guard below 68x16 preserving operator state",
            lambda d: setattr(d, "selected_incident_id", ids["supported"]),
        )

        store.close()

        # Real PTY end-to-end interactive session driving scripts/sre_dashboard.py
        pty_db = tmp_path / "pty_session.db"
        shutil.copy2(db_path, pty_db)
        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = "120"
        env["LINES"] = "40"
        env.pop("OPENROUTER_API_KEY", None)
        env.pop("TELEGRAM_BOT_TOKEN", None)

        proc = subprocess.Popen(
            [
                sys.executable,
                str(_REPO_ROOT / "scripts" / "sre_dashboard.py"),
                "--state-db",
                str(pty_db),
                "--reviewer-ref",
                "sre_pty_operator",
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
            close_fds=True,
        )
        os.close(slave_fd)
        pty_bytes = bytearray()

        def _drain(sec: float = 0.28, until: bytes | None = None) -> None:
            end = time.monotonic() + sec
            while time.monotonic() < end:
                r, _, _ = select.select([master_fd], [], [], 0.04)
                if r:
                    try:
                        chunk = os.read(master_fd, 65536)
                        if not chunk:
                            break
                        pty_bytes.extend(chunk)
                        if until is not None and until in pty_bytes:
                            return
                    except OSError:
                        break

        # Wait deterministically until cbreak mode is active and first frame renders
        _drain(5.0, until=b"SRE INVESTIGATION CONSOLE")
        _drain(0.15)
        os.write(master_fd, b"?")        # Open Help modal
        _drain(2.0, until=b"KEYBOARD NAVIGATION")
        os.write(master_fd, b"\x1b")     # Esc closes Help modal
        _drain(0.25)
        os.write(master_fd, b"\t")       # Focus incident list
        _drain(0.25)
        os.write(master_fd, b"\r")       # Open #1 incident detail
        _drain(2.0, until=b"View Lens")
        os.write(master_fd, b"\t")       # Lens -> Overview
        _drain(0.20)
        os.write(master_fd, b"\t")       # Lens -> Hypotheses
        _drain(0.20)
        os.write(master_fd, b"i")        # Jump Hypothesis -> Evidence Lineage
        _drain(0.25)
        os.write(master_fd, b"b")        # Return Evidence -> Hypotheses
        _drain(0.20)
        # Dynamic PTY resize to 80x24 then back to 120x40
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        os.write(master_fd, b"u")        # Refresh at 80x24
        _drain(0.25)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        os.write(master_fd, b"a")        # Open APPROVE confirmation modal
        _drain(2.0, until=b"CONFIRM HUMAN REVIEW ACTION")
        os.write(master_fd, b"\x1b")     # Cancel review modal via Esc (zero mutation!)
        _drain(0.25)
        os.write(master_fd, b"a")        # Re-open APPROVE modal
        _drain(0.30)
        os.write(master_fd, b"Pool saturation confirmed in Loki and Prometheus metrics.")
        _drain(0.25)
        os.write(master_fd, b"\r")       # Enter moves from rationale -> Confirm button
        _drain(0.25)
        os.write(master_fd, b"\r")       # Enter on Confirm submits APPROVE!
        _drain(2.0, until=b"REVIEW LOCKED - FINALIZED")
        os.write(master_fd, b"q")        # Clean exit
        _drain(1.5, until=b"closed without automated actions")
        rc = proc.wait(timeout=8)
        os.close(master_fd)

        (PTY_DIR / "pty_after_interactive_session.ansi").write_bytes(bytes(pty_bytes))
        verify_store = WorkflowStateStore(str(pty_db))
        pty_inc = verify_store.get_incident(ids["supported"])
        pty_revs = verify_store.get_reviews(ids["supported"])
        verify_store.close()
        assert rc == 0, f"PTY session exited with {rc}"
        assert pty_inc is not None and pty_inc["current_state"] == "CLOSED", f"Expected CLOSED after PTY APPROVE, got {pty_inc}"
        assert len(pty_revs) == 1 and pty_revs[0]["decision"] == "approve"
        print(f"PTY interactive verification PASSED: exit={rc}, bytes={len(pty_bytes)}, state={pty_inc['current_state']}")

    manifest_payload = {
        "issue": "P2-06 — Dashboard Usability & State Consistency",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "before_captures_dir": "evidence/p2-06-dashboard-usability-20261126T022200Z/before",
        "after_captures_dir": "evidence/p2-06-dashboard-usability-20261126T022200Z/after",
        "pty_traces_dir": "evidence/p2-06-dashboard-usability-20261126T022200Z/pty",
        "execution_command": ".venv/bin/python evidence/p2-06-dashboard-usability-20261126T022200Z/capture_after_state.py",
        "after_captures": captures_manifest,
    }
    (EVIDENCE_ROOT / "visual_evidence_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
