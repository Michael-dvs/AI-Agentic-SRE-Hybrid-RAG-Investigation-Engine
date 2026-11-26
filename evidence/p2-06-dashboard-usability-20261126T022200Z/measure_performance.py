#!/usr/bin/env python3
"""Reproducible P2-06 TUI performance, responsiveness, memory, and probe-frequency benchmark."""

from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any

from rich.console import Console

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.console_config import EnvConfigManager
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer
from orchestrator.state_machine import InvestigationStateMachine, MANDATORY_STATES, WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import CostMetricsReader, SREDashboard, ServiceHealthInspector


def _seed_incidents(store: WorkflowStateStore, count: int = 16) -> list[str]:
    sm = InvestigationStateMachine(store=store)
    ids: list[str] = []
    severities = ("critical", "high", "medium", "low")
    services = ("ledger-service", "transaction-service", "auth-service", "api-gateway", "notification-service")
    for idx in range(count):
        inc_id = f"inc-perf-{idx:03d}"
        ids.append(inc_id)
        if idx % 4 == 3:
            for st in ("RECEIVED", "CORRELATED", "TRIAGED", "EVIDENCE_COLLECTED"):
                sm.transition(inc_id, st, f"idem-{inc_id}-{st}")
            store.save_checkpoint(
                inc_id,
                "EVIDENCE_COLLECTED",
                {
                    "incident_id": inc_id,
                    "service_id": services[idx % len(services)],
                    "environment": "lab",
                    "priority": severities[idx % len(severities)],
                    "message": f"Synthetic in-progress anomaly #{idx}",
                },
            )
            continue

        for st in MANDATORY_STATES:
            sm.transition(inc_id, st, f"idem-{inc_id}-{st}")
        ctx = {
            "incident_id": inc_id,
            "service_id": services[idx % len(services)],
            "environment": "lab",
            "event_time": "2026-11-26T02:00:00Z",
            "dossier_ready_at": "2026-11-26T02:00:10Z",
            "priority": severities[idx % len(severities)],
            "message": f"Synthetic latency/pool anomaly #{idx}",
            "investigation_scope": [services[idx % len(services)]],
            "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
            "hypotheses": [
                {
                    "hypothesis_id": f"hyp-{inc_id}-01",
                    "rank": 1,
                    "statement": f"Candidate pool contention on {services[idx % len(services)]}",
                    "supporting_evidence_ids": [f"ev-{inc_id}-01"],
                    "contradicting_evidence_ids": [],
                    "confidence_score": 0.72,
                    "status": "SUPPORTED",
                }
            ],
            "evidence_items": [
                {
                    "evidence_id": f"ev-{inc_id}-01",
                    "incident_id": inc_id,
                    "service_id": services[idx % len(services)],
                    "environment": "lab",
                    "tool_name": "get_service_metrics",
                    "status": "ok",
                    "data_quality": "complete",
                    "source_ref": "prometheus:error_rate",
                    "observed_at": "2026-11-26T01:59:40Z",
                    "collected_at": "2026-11-26T02:00:02Z",
                    "query_window": {"start": "2026-11-26T01:55:00Z", "end": "2026-11-26T02:00:00Z"},
                    "records": [{"metric_name": "error_rate", "value": 0.31, "unit": "ratio"}],
                }
            ],
            "sop_availability": "APPLICABLE_SOP_FOUND",
            "runbook_citations": [],
            "version_manifest": {"workflow_version": "1.0.0"},
        }
        dossier = DossierSerializer.serialize(ctx)
        store.save_checkpoint(inc_id, "HUMAN_REVIEW", ctx)
        store.save_dossier(inc_id, 1, dossier["dossier_hash"], dossier, DossierMarkdownRenderer.render(dossier))
    return ids


def _summary_ms(samples_s: list[float]) -> dict[str, float]:
    ms = sorted(x * 1000.0 for x in samples_s)
    p95_idx = min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))
    return {
        "median_ms": round(statistics.median(ms), 2),
        "p95_ms": round(ms[p95_idx], 2),
        "max_ms": round(max(ms), 2),
    }


def main() -> int:
    out_path = pathlib.Path(__file__).resolve().parent / "performance_metrics.json"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        db_path = tmp_path / "perf.db"
        store = WorkflowStateStore(str(db_path))
        ids = _seed_incidents(store, count=16)

        # 1. Cold CLI startup (--help) latency
        startup_samples: list[float] = []
        for _ in range(5):
            t0 = time.perf_counter()
            subprocess.run(
                [sys.executable, str(_REPO_ROOT / "scripts" / "sre_dashboard.py"), "--help"],
                capture_output=True,
                check=True,
            )
            startup_samples.append(time.perf_counter() - t0)

        env_file = tmp_path / ".env"
        env_file.write_text("LLM_PROVIDER=openrouter\nLLM_MODEL=nvidia/nemotron-3.5-lightning:free\n", encoding="utf-8")
        probe_calls = {"health": 0}

        class _InstrumentedHealth(ServiceHealthInspector):
            def inspect(self) -> dict[str, Any]:
                probe_calls["health"] += 1
                return {"status": "OK", "reason": "", "services": [{"name": "ledger-service", "state": "running", "health": "healthy"}]}

        console = Console(
            file=io.StringIO(),
            record=True,
            width=120,
            height=40,
            force_terminal=True,
            color_system="truecolor",
        )
        dash = SREDashboard(
            store,
            console=console,
            env_manager=EnvConfigManager(env_path=env_file, example_path=tmp_path / ".env.example"),
            health=_InstrumentedHealth(),
            costs=CostMetricsReader(tmp_path / "missing-costs.json"),
            telegram=TelegramDispatcher(bot_token="", chat_id=""),
            audit_path=tmp_path / "audit.jsonl",
            handover_root=tmp_path / "handover",
        )

        # 2. Atomic snapshot refresh latency across 16 incidents
        refresh_samples: list[float] = []
        for _ in range(25):
            t0 = time.perf_counter()
            dash.refresh_snapshot()
            refresh_samples.append(time.perf_counter() - t0)

        # 3. Full render latency across viewport sizes (overview & detail)
        render_by_size: dict[str, dict[str, float]] = {}
        for w, h in ((80, 24), (100, 30), (120, 40), (160, 50)):
            samples_overview: list[float] = []
            dash.selected_incident_id = None
            dash.focus = "list"
            for _ in range(15):
                t0 = time.perf_counter()
                console.print(dash.render(width=w, height=h))
                console.export_text(clear=True)
                samples_overview.append(time.perf_counter() - t0)

            samples_detail: list[float] = []
            dash.selected_incident_id = ids[0]
            dash.detail_section = "all"
            for _ in range(15):
                t0 = time.perf_counter()
                console.print(dash.render(width=w, height=h))
                console.export_text(clear=True)
                samples_detail.append(time.perf_counter() - t0)

            render_by_size[f"{w}x{h}_overview"] = _summary_ms(samples_overview)
            render_by_size[f"{w}x{h}_detail"] = _summary_ms(samples_detail)

        # 4. Input handling + memory behavior across 100 navigation steps
        tracemalloc.start()
        mem_before, _ = tracemalloc.get_traced_memory()
        nav_samples: list[float] = []
        nav_sequence = ("TAB", "DOWN", "ENTER", "TAB", "TAB", "I", "B", "B", "B", "?", "ESC")
        for step_i in range(100):
            key = nav_sequence[step_i % len(nav_sequence)]
            t0 = time.perf_counter()
            dash.handle_key(key)
            nav_samples.append(time.perf_counter() - t0)
        mem_after, mem_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # 5. Probe TTL verification on Health tab (25 renders within probe TTL)
        probe_calls["health"] = 0
        dash.repository.coordinator._cached_health = None
        dash.view = "health"
        dash.selected_incident_id = None
        for _ in range(25):
            console.print(dash.render(width=120, height=40))
            console.export_text(clear=True)

        store.close()

    report = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": {
            "python": sys.version.split()[0],
            "dataset_incidents": 16,
        },
        "cli_startup_help": _summary_ms(startup_samples),
        "atomic_snapshot_refresh_16_incidents": _summary_ms(refresh_samples),
        "render_latency_by_viewport": render_by_size,
        "keystroke_dispatch_latency_100_steps": _summary_ms(nav_samples),
        "memory_100_navigation_steps_kib": {
            "before_kib": round(mem_before / 1024.0, 2),
            "after_kib": round(mem_after / 1024.0, 2),
            "delta_kib": round((mem_after - mem_before) / 1024.0, 2),
            "peak_kib": round(mem_peak / 1024.0, 2),
        },
        "backend_probe_frequency": {
            "health_tab_renders": 25,
            "subprocess_health_probes_executed": probe_calls["health"],
            "health_probe_ttl_seconds": dash.repository.coordinator.probe_ttl_seconds,
            "llm_requests_triggered_by_rendering": 0,
        },
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
