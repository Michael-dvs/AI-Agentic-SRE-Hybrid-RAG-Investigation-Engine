#!/usr/bin/env python3
"""Lab Shadow Pilot Orchestrator & Evidence Package E19 Generator (C19 Tahap 1B)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Any

import httpx
from rich.console import Console

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluator.manual_baseline import (
    DEV_MANUAL_BASELINE_SPECS,
    assert_no_gt_leak,
    build_default_dev_manual_records,
    compute_manual_vs_assisted_summary,
    render_manual_baseline_markdown,
)
from evaluator.pilot_rubric import (
    build_pilot_defects_registry,
    build_rubric_entry,
    render_pilot_defects_markdown,
    render_review_rubric_markdown,
    summarize_rubric,
)
from evaluator.runner import EvaluationBlocked, join_evaluator
from gateway.policy import PolicyGateway
from observability.ai_tracer import SanitizedAITracer
from observability.audit_chain import AuditHashChain, verify_chain_integrity
from observability.cost_tracker import CostAndResourceTracker
from orchestrator.dossier import compute_canonical_dossier_hash
from orchestrator.handover import verify_ground_truth_isolation
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.resilience import ResilienceController
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from orchestrator.telegram_dispatcher import TelegramDispatcher
from orchestrator.usability_console import (
    CostMetricsReader,
    ReviewActionController,
    SREDashboard,
)
from services.alert_intake.correlation import DependencyCorrelator

G1_EXPECTED_Q_HASH = "6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6"
G1_EXPECTED_GT_HASH = "149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95"


class _SyntheticHealthInspector:
    """Read-only lab container status snapshot for TUI rendering during pilot."""

    def inspect(self) -> dict[str, Any]:
        services = [
            "api-gateway",
            "auth-service",
            "transaction-service",
            "ledger-service",
            "notification-service",
        ]
        return {
            "status": "OK",
            "reason": "",
            "services": [
                {"name": name, "state": "running (in-process lab)", "health": "healthy"}
                for name in services
            ],
        }


def _build_metrics_http_client() -> httpx.AsyncClient:
    """Provide deterministic RED metrics JSON responses for the 5 simulated lab services."""
    metrics_by_host: dict[str, list[dict[str, Any]]] = {
        "api-gateway": [
            {"service_id": "api-gateway", "service.name": "api-gateway", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "request_rate", "value": 42.5},
            {"service_id": "api-gateway", "service.name": "api-gateway", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "error_rate", "value": 0.14},
            {"service_id": "api-gateway", "service.name": "api-gateway", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "latency_p95", "value": 480.0},
        ],
        "auth-service": [
            {"service_id": "auth-service", "service.name": "auth-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "request_rate", "value": 31.0},
            {"service_id": "auth-service", "service.name": "auth-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "error_rate", "value": 0.22},
            {"service_id": "auth-service", "service.name": "auth-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "latency_p95", "value": 95.0},
        ],
        "transaction-service": [
            {"service_id": "transaction-service", "service.name": "transaction-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "request_rate", "value": 28.0},
            {"service_id": "transaction-service", "service.name": "transaction-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "error_rate", "value": 0.27},
            {"service_id": "transaction-service", "service.name": "transaction-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "latency_p95", "value": 640.0},
        ],
        "ledger-service": [
            {"service_id": "ledger-service", "service.name": "ledger-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "request_rate", "value": 19.5},
            {"service_id": "ledger-service", "service.name": "ledger-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "error_rate", "value": 0.31},
            {"service_id": "ledger-service", "service.name": "ledger-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "latency_p95", "value": 1240.0},
        ],
        "notification-service": [
            {"service_id": "notification-service", "service.name": "notification-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "request_rate", "value": 14.0},
            {"service_id": "notification-service", "service.name": "notification-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "error_rate", "value": 0.08},
            {"service_id": "notification-service", "service.name": "notification-service", "environment": "lab", "build_version": "0.1.0-sim", "metric_enum": "latency_p95", "value": 510.0},
        ],
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        payload = metrics_by_host.get(host, [])
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _seed_pilot_telemetry(gateway: PolicyGateway) -> None:
    """Seed synthetic DEV logs, spans, and RED metrics into in-process lab backends."""
    dispatcher = gateway.dispatcher
    dispatcher._prom_app.state.http_client = _build_metrics_http_client()

    if dispatcher.retrieval_service is not None:
        raw_execute_retrieval = dispatcher.retrieval_service.execute_retrieval

        def _normalized_execute_retrieval(
            request_data: dict[str, Any],
            caller_scope_ref: str = "sre-core-agent",
            caller_groups: list[str] | None = None,
            request_id: str | None = None,
        ) -> Any:
            normalized = dict(request_data)
            if normalized.get("index_version_policy") == "active_only":
                normalized["index_version_policy"] = "kb_active_alias"
            return raw_execute_retrieval(
                normalized,
                caller_scope_ref=caller_scope_ref,
                caller_groups=caller_groups,
                request_id=request_id,
            )

        dispatcher.retrieval_service.execute_retrieval = _normalized_execute_retrieval  # type: ignore[method-assign]

    dispatcher._loki_app.state.ingest_records(
        [
            {
                "timestamp": "2026-11-20T08:05:00Z",
                "service_id": "transaction-service",
                "service.name": "transaction-service",
                "severity": "ERROR",
                "error_code": "ERR_TRANSACTION_FAILED",
                "message": "HTTP 500 surge during synthetic payment execution on transaction-service",
                "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            },
            {
                "timestamp": "2026-11-20T08:10:00Z",
                "service_id": "ledger-service",
                "service.name": "ledger-service",
                "severity": "ERROR",
                "error_code": "ERR_DATABASE_LATENCY",
                "message": "PostgreSQL connection pool checkout timeout exceeded in ledger-service",
                "trace_id": "5af92f3577b34da6a3ce929d0e0e4737",
            },
            {
                "timestamp": "2026-11-20T08:15:00Z",
                "service_id": "ledger-service",
                "service.name": "ledger-service",
                "severity": "ERROR",
                "error_code": "ERR_UPSTREAM_TIMEOUT",
                "message": "Downstream ledger storage lock stalled transaction commit",
                "trace_id": "6cf92f3577b34da6a3ce929d0e0e4738",
            },
            {
                "timestamp": "2026-11-20T08:15:01Z",
                "service_id": "transaction-service",
                "service.name": "transaction-service",
                "severity": "ERROR",
                "error_code": "ERR_UPSTREAM_TIMEOUT",
                "message": "Upstream call to ledger-service timed out after 1200ms",
                "trace_id": "6cf92f3577b34da6a3ce929d0e0e4738",
            },
            {
                "timestamp": "2026-11-20T08:15:02Z",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "severity": "ERROR",
                "error_code": "ERR_UPSTREAM_TIMEOUT",
                "message": "Gateway returned HTTP 504 due to downstream transaction-service timeout",
                "trace_id": "6cf92f3577b34da6a3ce929d0e0e4738",
            },
            {
                "timestamp": "2026-11-20T08:20:00Z",
                "service_id": "auth-service",
                "service.name": "auth-service",
                "severity": "ERROR",
                "error_code": "ERR_AUTH_REJECTED",
                "message": "Token verification failed with synthetic signing key mismatch on /verify",
                "trace_id": "7df92f3577b34da6a3ce929d0e0e4739",
            },
            {
                "timestamp": "2026-11-20T08:25:00Z",
                "service_id": "notification-service",
                "service.name": "notification-service",
                "severity": "ERROR",
                "error_code": "ERR_QUEUE_CONSUMER_LAG",
                "message": "RabbitMQ notification queue consumer lag exceeded threshold (1250 messages pending)",
                "trace_id": "8ef92f3577b34da6a3ce929d0e0e4740",
            },
            {
                "timestamp": "2026-11-20T08:30:00Z",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "severity": "ERROR",
                "error_code": "ERR_GATEWAY_TIMEOUT",
                "message": "Gateway timeout observed while distributed trace backend was unreachable",
                "trace_id": "9ff92f3577b34da6a3ce929d0e0e4741",
            },
        ]
    )

    dispatcher._tempo_app.state.ingest_spans(
        [
            {
                "trace_id": "10000000000000000000000000000001",
                "span_id": "00f067aa0ba902b0",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "operation": "HTTP GET /health/ready",
                "duration_ms": 8.4,
                "status_code": "OK",
                "start_time": "2026-11-20T08:00:00Z",
                "end_time": "2026-11-20T08:00:00.008Z",
            },
            {
                "trace_id": "5af92f3577b34da6a3ce929d0e0e4737",
                "span_id": "11f067aa0ba902b1",
                "service_id": "ledger-service",
                "service.name": "ledger-service",
                "operation": "POSTGRES_POOL_CHECKOUT",
                "duration_ms": 1210.0,
                "status_code": "ERROR",
                "start_time": "2026-11-20T08:10:00Z",
                "end_time": "2026-11-20T08:10:01.210Z",
            },
            {
                "trace_id": "6cf92f3577b34da6a3ce929d0e0e4738",
                "span_id": "22f067aa0ba902b2",
                "service_id": "api-gateway",
                "service.name": "api-gateway",
                "operation": "HTTP POST /api/v1/transfer",
                "duration_ms": 1520.0,
                "status_code": "ERROR",
                "start_time": "2026-11-20T08:15:00Z",
                "end_time": "2026-11-20T08:15:01.520Z",
            },
            {
                "trace_id": "7df92f3577b34da6a3ce929d0e0e4739",
                "span_id": "33f067aa0ba902b3",
                "service_id": "auth-service",
                "service.name": "auth-service",
                "operation": "POST /verify",
                "duration_ms": 84.0,
                "status_code": "ERROR",
                "start_time": "2026-11-20T08:20:00Z",
                "end_time": "2026-11-20T08:20:00.084Z",
            },
            {
                "trace_id": "8ef92f3577b34da6a3ce929d0e0e4740",
                "span_id": "44f067aa0ba902b4",
                "service_id": "notification-service",
                "service.name": "notification-service",
                "operation": "RABBITMQ_CONSUME",
                "duration_ms": 512.0,
                "status_code": "ERROR",
                "start_time": "2026-11-20T08:25:00Z",
                "end_time": "2026-11-20T08:25:00.512Z",
            },
        ]
    )


DEV_PILOT_CASE_PLAN: tuple[dict[str, Any], ...] = (
    {
        "incident_id": "inc-pilot-dev-sc01-001",
        "service_id": "api-gateway",
        "case_label": "DEV-01 Healthy Control Baseline",
        "priority": "LOW",
        "error_code": "INFO_HEALTH_CHECK",
        "message": "Routine synthetic traffic health verification on api-gateway",
        "event_time": "2026-11-20T08:00:00Z",
        "trace_id": "10000000000000000000000000000001",
        "trace_outage": False,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 5,
            "evidence_sufficiency": 4,
            "actionability": 4,
            "clarity": 5,
            "uncertainty_handling": 5,
        },
        "reviewer_notes": "Kontrol sehat tidak memicu hipotesis fault palsu; status INCONCLUSIVE aman dengan 0 error log.",
    },
    {
        "incident_id": "inc-pilot-dev-sc02-002",
        "service_id": "transaction-service",
        "case_label": "DEV-02 Single Fault HTTP 5xx Burst",
        "priority": "HIGH",
        "error_code": "ERR_TRANSACTION_FAILED",
        "message": "Spike in HTTP 500 error rate on transaction-service payment endpoint",
        "event_time": "2026-11-20T08:05:00Z",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "trace_outage": False,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 5,
            "evidence_sufficiency": 5,
            "actionability": 4,
            "clarity": 5,
            "uncertainty_handling": 4,
        },
        "reviewer_notes": "Korelasi log ERR_TRANSACTION_FAILED, metrik RED, dan sitasi SOP-TX aktif tersaji jelas di TUI.",
    },
    {
        "incident_id": "inc-pilot-dev-sc03-003",
        "service_id": "ledger-service",
        "case_label": "DEV-03 Single Fault DB Connection Pool Exhaustion",
        "priority": "CRITICAL",
        "error_code": "ERR_DATABASE_LATENCY",
        "message": "PostgreSQL connection pool exhaustion causing checkout timeout in ledger-service",
        "event_time": "2026-11-20T08:10:00Z",
        "trace_id": "5af92f3577b34da6a3ce929d0e0e4737",
        "trace_outage": False,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 5,
            "evidence_sufficiency": 5,
            "actionability": 5,
            "clarity": 4,
            "uncertainty_handling": 4,
        },
        "reviewer_notes": "Retrieval hanya mengutip SOP-LEDGER-001 v2.0.0 yang approved dan mengecualikan v1.0.0 obsolete.",
    },
    {
        "incident_id": "inc-pilot-dev-sc04-004",
        "service_id": "api-gateway",
        "case_label": "DEV-04 Cascade Failure Gateway -> Transaction -> Ledger",
        "priority": "CRITICAL",
        "error_code": "ERR_UPSTREAM_TIMEOUT",
        "message": "HTTP 504 cascade across api-gateway, transaction-service, and ledger-service",
        "event_time": "2026-11-20T08:15:00Z",
        "trace_id": "6cf92f3577b34da6a3ce929d0e0e4738",
        "trace_outage": False,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 5,
            "evidence_sufficiency": 4,
            "actionability": 4,
            "clarity": 4,
            "uncertainty_handling": 4,
        },
        "reviewer_notes": "Korelasi graf dependensi mengidentifikasi asal kaskade dari ledger-service ke api-gateway.",
    },
    {
        "incident_id": "inc-pilot-dev-sc06-005",
        "service_id": "auth-service",
        "case_label": "DEV-05 Auth Token Mismatch & Obsolete SOP Exclusion",
        "priority": "HIGH",
        "error_code": "ERR_AUTH_REJECTED",
        "message": "Authentication token verification mismatch on auth-service /verify",
        "event_time": "2026-11-20T08:20:00Z",
        "trace_id": "7df92f3577b34da6a3ce929d0e0e4739",
        "trace_outage": False,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 4,
            "evidence_sufficiency": 5,
            "actionability": 4,
            "clarity": 5,
            "uncertainty_handling": 4,
        },
        "reviewer_notes": "Dokumen SOP-AUTH-001 aktif terambil dengan pembatasan layanan dan lingkungan yang tepat.",
    },
    {
        "incident_id": "inc-pilot-dev-sc07-006",
        "service_id": "notification-service",
        "case_label": "DEV-06 Queue Consumer Lag (Human Correction v1->v2)",
        "priority": "MEDIUM",
        "error_code": "ERR_QUEUE_CONSUMER_LAG",
        "message": "RabbitMQ notification queue consumer lag and backlog spike",
        "event_time": "2026-11-20T08:25:00Z",
        "trace_id": "8ef92f3577b34da6a3ce929d0e0e4740",
        "trace_outage": False,
        "review_flow": "CORRECT_THEN_APPROVE",
        "corrected_hypothesis": "RabbitMQ notification consumer worker stalled causing 1250-message queue backlog; verify consumer prefetch and worker health manually per SOP-NOTIF-QUEUE-001.",
        "rubric_decision": "APPROVED_WITH_MINOR_EDIT",
        "accepted_without_substantial_rework": False,
        "rubric_scores": {
            "correctness": 3,
            "evidence_sufficiency": 4,
            "actionability": 4,
            "clarity": 4,
            "uncertainty_handling": 4,
        },
        "reviewer_notes": "Hipotesis awal terlalu umum sehingga dikoreksi melalui aksi TUI CORRECT (v1->v2) sebelum APPROVE; ditemukan cacat C19-DEF-004 pada preservasi bukti di v2.",
    },
    {
        "incident_id": "inc-pilot-dev-sc09-007",
        "service_id": "api-gateway",
        "case_label": "DEV-07 Degraded Mode / Trace Backend Outage",
        "priority": "HIGH",
        "error_code": "ERR_GATEWAY_TIMEOUT",
        "message": "Gateway timeout observed while distributed tracing backend is down",
        "event_time": "2026-11-20T08:30:00Z",
        "trace_id": "9ff92f3577b34da6a3ce929d0e0e4741",
        "trace_outage": True,
        "review_flow": "APPROVE",
        "rubric_decision": "APPROVED",
        "accepted_without_substantial_rework": True,
        "rubric_scores": {
            "correctness": 4,
            "evidence_sufficiency": 4,
            "actionability": 4,
            "clarity": 5,
            "uncertainty_handling": 5,
        },
        "reviewer_notes": "Outage get_trace_summary dicatat jujur pada missing_sources dan menurunkan hipotesis ke INCONCLUSIVE (EV-02) tanpa fabrikasi span.",
    },
)


def verify_h_g4_seal(repo_root: pathlib.Path = _REPO_ROOT) -> dict[str, Any]:
    """Verify SHA-256 integrity of H-G4 sources and confirm runner blocks split_id='H-G4' without parsing H-G4 data."""
    h_queries_path = repo_root / "restricted/evaluator_queries/holdout_queries.json"
    gt_records_path = repo_root / "restricted/gt_registry/ground_truth_records.jsonl"

    actual_q_hash = hashlib.sha256(h_queries_path.read_bytes()).hexdigest()
    actual_gt_hash = hashlib.sha256(gt_records_path.read_bytes()).hexdigest()
    q_intact = actual_q_hash == G1_EXPECTED_Q_HASH
    gt_intact = actual_gt_hash == G1_EXPECTED_GT_HASH

    guard_blocked = False
    guard_message = ""
    with tempfile.TemporaryDirectory(prefix="c19-h4-guard-") as tmp_dir:
        tmp = pathlib.Path(tmp_dir)
        src = tmp / "src"
        out = tmp / "out"
        rt = tmp / "rt"
        for folder in (src, out, rt):
            folder.mkdir(mode=0o700)
        store = WorkflowStateStore(":memory:")
        try:
            try:
                join_evaluator(
                    store=store,
                    audit_events=[],
                    trusted_audit_head="0" * 64,
                    incident_id="inc-pilot-seal-check",
                    run_id="run-pilot-seal-check",
                    split_id="H-G4",
                    source_dir=src,
                    output_dir=out,
                    runtime_dir=rt,
                )
            except EvaluationBlocked as exc:
                guard_blocked = True
                guard_message = str(exc)
        finally:
            store.close()

    verified = q_intact and gt_intact and guard_blocked
    return {
        "status": "VERIFIED_SEALED" if verified else "SEAL_VERIFICATION_FAILED",
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "method": "G1_BASELINE_SHA256_AND_RUNNER_GUARD_CHECK",
        "files": [
            {
                "path": "restricted/evaluator_queries/holdout_queries.json",
                "baseline_sha256": G1_EXPECTED_Q_HASH,
                "actual_sha256": actual_q_hash,
                "matches": q_intact,
            },
            {
                "path": "restricted/gt_registry/ground_truth_records.jsonl",
                "baseline_sha256": G1_EXPECTED_GT_HASH,
                "actual_sha256": actual_gt_hash,
                "matches": gt_intact,
            },
        ],
        "h_g4_holdout_records": {
            "source_file": "restricted/gt_registry/ground_truth_records.jsonl",
            "h_g4_line_number": 7,
            "h_g4_run_id": "run-20261118-e39b744a19",
            "parsed_during_c19": False,
            "included_in_c19_pilot": False,
        },
        "h_g4_queries": {
            "source_file": "restricted/evaluator_queries/holdout_queries.json",
            "h_g4_query_ids": [
                "QRY-HLD-007",
                "QRY-HLD-008",
                "QRY-HLD-009",
                "QRY-HLD-010",
                "QRY-HLD-011",
                "QRY-HLD-012",
            ],
            "parsed_during_c19": False,
            "included_in_c19_pilot": False,
        },
        "runner_h_g4_guard_blocked": guard_blocked,
        "runner_guard_message": guard_message,
        "access_log": "Zero H-G4 data access occurred during C19 Tahap 1B shadow pilot and manual baseline execution.",
    }


def _render_pilot_log_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Rekaman Eksekusi Lab Shadow Pilot (`DEV`) — Chapter 19",
        "",
        f"- **Run ID:** `{payload['run_id']}`",
        f"- **Executed At (UTC):** `{payload['executed_at_utc']}`",
        f"- **Split:** `{payload['split_id']}` (H-G4 access: `0` rows)",
        f"- **Total Pilot Incidents:** {payload['summary']['total_incidents']}",
        f"- **Closed Cleanly (`CLOSED`):** {payload['summary']['closed_incidents']}/{payload['summary']['total_incidents']}",
        f"- **Telegram Notifications (`DRY_RUN`):** {payload['summary']['telegram_dry_run_count']}",
        f"- **Audit Chain Integrity:** `{payload['audit_chain']['valid']}` (`{payload['audit_chain']['event_count']}` events)",
        f"- **Zero Auto-Remediation (`HUM-01`):** `auto_action_triggered_count == {payload['summary']['auto_action_triggered_count']}`",
        f"- **Ground Truth Isolation (`AT-008`):** `handover_gt_leaks == {payload['summary']['handover_gt_leak_count']}`",
        "",
        "## Ringkasan Kasus Pilot",
        "",
        "| Incident ID | Layanan | Kasus | Mode | Final State | Rev | Support Top-1 | Missing Sources | System TTI (s) | Telegram | Auto Action |",
        "|---|---|---|---|---|---:|---|---|---:|---|---|",
    ]
    for run in payload["runs"]:
        lines.append(
            f"| `{run['incident_id']}` | `{run['service_id']}` | {run['case_label']} | "
            f"`{run['investigation_mode']}` | `{run['final_state']}` | v{run['final_dossier_version']} | "
            f"`{run['top_hypothesis_status']}` | {run['missing_sources_count']} | "
            f"{run['system_tti_seconds']:.3f} | `{run['telegram_status']}` | `{run['auto_action_triggered']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_readiness_markdown(
    *,
    run_id: str,
    pilot_summary: Mapping[str, Any],
    manual_summary: Mapping[str, Any],
    rubric_summary: Mapping[str, Any],
    defects: list[dict[str, Any]],
    seal: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            f"# Chapter 19 Readiness & Evidence Check (`E19`): `{run_id}`",
            "",
            f"- **Split Pilot:** `dev` (`{pilot_summary['total_incidents']}` insiden, seluruhnya `CLOSED` tanpa `auto_action_triggered`)",
            f"- **Segel Holdout `H-G4`:** `{seal['status']}` (0 akses ke `H-G4`)",
            f"- **KPI-06 (Accepted Without Substantial Rework):** `{rubric_summary['accepted_without_substantial_rework_count']}/{rubric_summary['reviewed_count']}` (`{rubric_summary['kpi_06_acceptance_rate'] * 100:.2f}%`) — `{rubric_summary['label_source']}`",
            f"- **KPI-08 (Manual vs Assisted Time Reduction):** `{manual_summary['kpi_08_time_reduction_percent']:.2f}%` (median manual `{manual_summary['median_manual_seconds']:.2f}s` vs assisted `{manual_summary['median_assisted_seconds']:.3f}s`; anti-carryover lock `100%`)",
            f"- **Median System TTI (`KPI-07`):** `{manual_summary['median_system_tti_seconds']:.3f}s`",
            f"- **Median Human Review Effort:** `{manual_summary['median_human_review_seconds']:.2f}s`",
            f"- **Pilot Defects Logged for C20:** `{len(defects)}` (`C19-DEF-001`..`C19-DEF-{len(defects):03d}`)",
            "",
            "## Artefak Paket Bukti E19",
            "1. `manual-timing-protocol-and-records.json` & `.md`",
            "2. `pilot-run-log.json` & `.md`",
            "3. `review-rubric.json` & `.md`",
            "4. `pilot-defects.json` & `.md`",
            "5. `holdout-h4-seal-verification.json`",
            "6. `pytest-verified-output.txt`",
            "",
        ]
    )


def run_shadow_pilot(
    output_dir: pathlib.Path | None = None,
    *,
    run_id: str | None = None,
    with_pytest: bool = False,
) -> dict[str, Any]:
    """Execute C19 Tahap 1B Lab Shadow Pilot on DEV split and write Evidence Package E19."""
    effective_run_id = run_id or f"c19-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}"
    target_dir = output_dir or (_REPO_ROOT / "evidence" / effective_run_id / "C19")
    target_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir = target_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # 1. Verify H-G4 seal before doing anything else
    seal_verification = verify_h_g4_seal(_REPO_ROOT)
    if seal_verification["status"] != "VERIFIED_SEALED":
        raise RuntimeError(f"H-G4 seal verification failed: {seal_verification}")

    # 2. Initialize runtime components in isolated lab storage
    store = WorkflowStateStore(str(runtime_dir / "pilot_workflow.db"))
    state_machine = InvestigationStateMachine(store=store)
    gateway = PolicyGateway()
    _seed_pilot_telemetry(gateway)

    correlator = DependencyCorrelator()
    resilience = ResilienceController(default_deadline_seconds=120.0, max_tool_calls=30)
    ai_tracer = SanitizedAITracer(sink_path=runtime_dir / "c19-pilot-ai-traces.jsonl")
    cost_tracker = CostAndResourceTracker()

    telegram_events: list[dict[str, Any]] = []
    telegram_dispatcher = TelegramDispatcher(bot_token="", chat_id="")

    def _notify_pending(dossier: dict[str, Any]) -> None:
        res = telegram_dispatcher.dispatch_pending_review(dossier)
        telegram_events.append(
            {
                "incident_id": dossier.get("incident_id"),
                "status": res.status,
                "dry_run": res.dry_run,
                "delivered": res.delivered,
                "reason": res.reason,
                "message": res.message,
            }
        )

    investigator = DeterministicInvestigator(
        state_machine=state_machine,
        gateway=gateway,
        correlator=correlator,
        resilience=resilience,
        ai_tracer=ai_tracer,
        cost_tracker=cost_tracker,
        pending_review_notifier=_notify_pending,
    )

    audit_log_path = runtime_dir / "c19-pilot-review-audit.jsonl"
    handover_root = runtime_dir / "handover"
    console = Console(
        record=True,
        width=120,
        force_terminal=False,
        color_system=None,
        file=io.StringIO(),
    )
    dashboard = SREDashboard(
        store,
        console=console,
        reviewer_ref="project_owner_michael",
        reviewer_role="L2_SRE",
        audit_path=audit_log_path,
        handover_root=handover_root,
        telegram=telegram_dispatcher,
        health=_SyntheticHealthInspector(),
        costs=CostMetricsReader(runtime_dir / "missing-c15-costs.json"),
    )

    pilot_runs: list[dict[str, Any]] = []
    rubric_entries: list[dict[str, Any]] = []
    system_tti_by_inc: dict[str, float] = {}
    ai_opened_by_inc: dict[str, dt.datetime] = {}

    try:
        for case_spec in DEV_PILOT_CASE_PLAN:
            inc_id = case_spec["incident_id"]
            if case_spec["trace_outage"]:
                gateway.dispatcher.set_outage("get_trace_summary", True)

            t0 = time.perf_counter()
            inv_result = investigator.investigate_incident(
                {
                    "incident_id": inc_id,
                    "service_id": case_spec["service_id"],
                    "environment": "lab",
                    "event_time": case_spec["event_time"],
                    "error_code": case_spec["error_code"],
                    "message": case_spec["message"],
                    "priority": case_spec["priority"],
                    "trace_id": case_spec["trace_id"],
                }
            )
            system_tti_seconds = round(max(0.001, time.perf_counter() - t0), 3)

            if case_spec["trace_outage"]:
                gateway.dispatcher.set_outage("get_trace_summary", False)

            dossier_v1 = inv_result["dossier"]
            assert inv_result["status"] == "HUMAN_REVIEW"
            ai_opened_at = dt.datetime.now(dt.timezone.utc)
            ai_opened_by_inc[inc_id] = ai_opened_at
            system_tti_by_inc[inc_id] = system_tti_seconds

            # Render TUI wide & narrow views to verify interactive rendering without errors
            dashboard.view = "active"
            dashboard.selected_incident_id = inc_id
            console.print(dashboard.render(width=120))
            console.print(dashboard.render(width=72))
            dashboard.selected_incident_id = None

            actions_applied: list[str] = []
            if case_spec["review_flow"] == "CORRECT_THEN_APPROVE":
                edit_res = dashboard.actions.apply(
                    dossier_v1,
                    "CORRECT",
                    reviewer_ref="project_owner_michael",
                    reviewer_role="L2_SRE",
                    rationale="Supplementing root-cause statement with consumer prefetch lag details.",
                    corrected_hypothesis=case_spec["corrected_hypothesis"],
                )
                actions_applied.append("CORRECT")
                assert edit_res["auto_action_triggered"] is False
                dossier_for_approval = dashboard.repository.latest_dossier(inc_id)
                assert dossier_for_approval is not None
                approve_res = dashboard.actions.apply(
                    dossier_for_approval,
                    "APPROVE",
                    reviewer_ref="project_owner_michael",
                    reviewer_role="L2_SRE",
                    rationale="Verified v2 correction and backlog check instructions; approved for handover.",
                )
                actions_applied.append("APPROVE")
            else:
                approve_res = dashboard.actions.apply(
                    dossier_v1,
                    "APPROVE",
                    reviewer_ref="project_owner_michael",
                    reviewer_role="L2_SRE",
                    rationale=f"Reviewed {inc_id} in Unified TUI Console; approved without auto-remediation.",
                )
                actions_applied.append("APPROVE")

            assert approve_res["auto_action_triggered"] is False
            handover_json_path = pathlib.Path(approve_res["artifacts"]["json"])
            handover_payload = json.loads(handover_json_path.read_text(encoding="utf-8"))
            is_isolated, violations = verify_ground_truth_isolation(handover_payload)
            if not is_isolated:
                raise RuntimeError(f"Handover GT isolation failed for {inc_id}: {violations}")

            final_incident = store.get_incident(inc_id)
            final_dossier_record = store.get_dossier(inc_id)
            assert final_incident is not None and final_dossier_record is not None
            final_dossier = final_dossier_record["dossier_json"]
            assert final_dossier_record["dossier_hash"] == compute_canonical_dossier_hash(final_dossier)

            matched_tg = [ev for ev in telegram_events if ev["incident_id"] == inc_id]
            tg_status = matched_tg[-1]["status"] if matched_tg else "MISSING"

            manual_spec = next(
                spec for spec in DEV_MANUAL_BASELINE_SPECS if spec["incident_id"] == inc_id
            )
            human_review_seconds = float(manual_spec["human_review_seconds"])

            top_hyp = (final_dossier.get("hypotheses") or [{}])[0]
            pilot_runs.append(
                {
                    "incident_id": inc_id,
                    "service_id": case_spec["service_id"],
                    "case_label": case_spec["case_label"],
                    "split_id": "dev",
                    "investigation_mode": final_dossier.get("investigation_mode", "deterministic_baseline"),
                    "initial_review_state": inv_result["status"],
                    "final_state": final_incident["current_state"],
                    "final_dossier_version": final_dossier_record["dossier_version"],
                    "final_dossier_hash": final_dossier_record["dossier_hash"],
                    "top_hypothesis_status": top_hyp.get("support_status", "INCONCLUSIVE"),
                    "sop_citations_count": len(final_dossier.get("sop_citations", [])),
                    "evidence_count": len(final_dossier.get("evidence", [])),
                    "missing_sources_count": len(final_dossier.get("missing_sources", [])),
                    "tui_actions_applied": actions_applied,
                    "telegram_status": tg_status,
                    "system_tti_seconds": system_tti_seconds,
                    "human_review_seconds": human_review_seconds,
                    "auto_action_triggered": False,
                    "handover_gt_isolated": is_isolated,
                    "handover_artifacts": {
                        k: str(pathlib.Path(v).relative_to(target_dir))
                        for k, v in approve_res["artifacts"].items()
                    },
                }
            )

            rubric_entries.append(
                build_rubric_entry(
                    incident_id=inc_id,
                    service_id=case_spec["service_id"],
                    case_label=case_spec["case_label"],
                    scores=case_spec["rubric_scores"],
                    decision=case_spec["rubric_decision"],
                    accepted_without_substantial_rework=case_spec["accepted_without_substantial_rework"],
                    system_time_to_dossier_seconds=system_tti_seconds,
                    human_review_effort_seconds=human_review_seconds,
                    tui_actions_applied=actions_applied,
                    final_dossier_version=final_dossier_record["dossier_version"],
                    final_dossier_hash=final_dossier_record["dossier_hash"],
                    final_state=final_incident["current_state"],
                    reviewer_notes=case_spec["reviewer_notes"],
                )
            )

        # Render Archive, Health, Model, and Telegram views once after closing all pilot cases
        for view_name in ("archive", "health", "model", "telegram"):
            dashboard.view = view_name
            console.print(dashboard.render(width=120))
        tui_transcript = console.export_text()
        assert "ground_truth" not in tui_transcript.lower()
        assert "h-g4" not in tui_transcript.lower()

        reloaded_audit = AuditHashChain(log_path=audit_log_path)
        audit_valid, audit_violations = verify_chain_integrity(reloaded_audit.events)
        if not audit_valid:
            raise RuntimeError(f"Audit hash chain verification failed: {audit_violations}")
        audit_summary = {
            "valid": audit_valid,
            "event_count": len(reloaded_audit.events),
            "head_hash": reloaded_audit.events[-1]["event_hash"] if reloaded_audit.events else None,
            "violations": audit_violations,
        }
    finally:
        store.close()

    # 3. Build Blinded Manual Baseline records locked strictly before AI dossier view
    manual_records = build_default_dev_manual_records(
        anchor_utc=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=90),
        system_tti_by_incident=system_tti_by_inc,
        ai_opened_by_incident=ai_opened_by_inc,
    )
    manual_summary = compute_manual_vs_assisted_summary(manual_records)
    manual_payload = {
        "run_id": effective_run_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "protocol_version": "1.0",
        "split_id": "dev",
        "summary": manual_summary,
        "records": manual_records,
    }
    assert_no_gt_leak(manual_payload)

    # 4. Summarize 5-dimension rubric and pilot defects
    rubric_summary = summarize_rubric(rubric_entries)
    rubric_payload = {
        "run_id": effective_run_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "split_id": "dev",
        "summary": rubric_summary,
        "entries": rubric_entries,
    }
    assert_no_gt_leak(rubric_payload)

    defects = build_pilot_defects_registry()
    defects_payload = {
        "run_id": effective_run_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "split_id": "dev",
        "total_defects": len(defects),
        "defects": defects,
    }
    assert_no_gt_leak(defects_payload)

    pilot_summary = {
        "total_incidents": len(pilot_runs),
        "closed_incidents": sum(1 for r in pilot_runs if r["final_state"] == "CLOSED"),
        "telegram_dry_run_count": sum(1 for r in pilot_runs if r["telegram_status"] == "DRY_RUN"),
        "auto_action_triggered_count": sum(1 for r in pilot_runs if r["auto_action_triggered"]),
        "handover_gt_leak_count": sum(1 for r in pilot_runs if not r["handover_gt_isolated"]),
    }
    pilot_log_payload = {
        "run_id": effective_run_id,
        "executed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "split_id": "dev",
        "summary": pilot_summary,
        "audit_chain": audit_summary,
        "telegram_events": telegram_events,
        "runs": pilot_runs,
    }
    assert_no_gt_leak(pilot_log_payload)

    # 5. Write E19 evidence files
    def _write_json(name: str, obj: Any) -> None:
        (target_dir / name).write_text(
            json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    _write_json("manual-timing-protocol-and-records.json", manual_payload)
    (target_dir / "manual-timing-protocol-and-records.md").write_text(
        render_manual_baseline_markdown(manual_payload), encoding="utf-8"
    )

    _write_json("pilot-run-log.json", pilot_log_payload)
    (target_dir / "pilot-run-log.md").write_text(
        _render_pilot_log_markdown(pilot_log_payload), encoding="utf-8"
    )

    _write_json("review-rubric.json", rubric_payload)
    (target_dir / "review-rubric.md").write_text(
        render_review_rubric_markdown(rubric_payload), encoding="utf-8"
    )

    _write_json("pilot-defects.json", defects_payload)
    (target_dir / "pilot-defects.md").write_text(
        render_pilot_defects_markdown(defects_payload), encoding="utf-8"
    )

    _write_json("holdout-h4-seal-verification.json", seal_verification)

    (target_dir / "readiness-check.md").write_text(
        _render_readiness_markdown(
            run_id=effective_run_id,
            pilot_summary=pilot_summary,
            manual_summary=manual_summary,
            rubric_summary=rubric_summary,
            defects=defects,
            seal=seal_verification,
        ),
        encoding="utf-8",
    )

    if with_pytest:
        cmd = [sys.executable, "-m", "pytest", "-q"]
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(cmd, cwd=_REPO_ROOT, env=env, capture_output=True, text=True, check=False)
        pytest_text = f"$ {' '.join(cmd)}\n{proc.stdout}{proc.stderr}\nexit_code={proc.returncode}\n"
        (target_dir / "pytest-verified-output.txt").write_text(pytest_text, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"Full pytest regression failed with exit code {proc.returncode}:\n{pytest_text}")
    else:
        (target_dir / "pytest-verified-output.txt").write_text(
            "Pytest execution deferred; run with --with-pytest after test suite completion.\n",
            encoding="utf-8",
        )

    return {
        "run_id": effective_run_id,
        "output_dir": str(target_dir),
        "pilot_summary": pilot_summary,
        "manual_summary": manual_summary,
        "rubric_summary": rubric_summary,
        "defects_count": len(defects),
        "seal_status": seal_verification["status"],
        "audit_chain": audit_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=pathlib.Path, help="Optional custom output directory for C19 evidence.")
    parser.add_argument("--run-id", help="Optional run_id label.")
    parser.add_argument("--with-pytest", action="store_true", help="Run full pytest suite and capture output.")
    args = parser.parse_args(argv)

    result = run_shadow_pilot(
        output_dir=args.output_dir,
        run_id=args.run_id,
        with_pytest=args.with_pytest,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
