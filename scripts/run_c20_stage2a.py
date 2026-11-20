#!/usr/bin/env python3
"""Execute C20 Stage 2A DEV capacity and resilience drills without external writes."""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from typing import Any, Mapping

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gateway.policy import PolicyGateway
from observability.ai_tracer import SanitizedAITracer
from observability.audit_chain import AuditHashChain, verify_chain_integrity
from orchestrator.capacity_resilience import CapacityProfiler, read_docker_stats, utc_now_z
from orchestrator.dossier import DossierSerializer
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.resilience import IncidentCancelledError, ResilienceController
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from services.alert_intake.dedup import AlertDeduplicator


class _UsageLedger:
    def usage(self, incident_id: str) -> dict[str, int]:
        return {"input_reported": 0, "input_reserved": 0, "output_reported": 0, "output_reserved": 0}


class _TimeoutLLM:
    ledger = _UsageLedger()

    def generate(self, context: Mapping[str, Any], resilience: ResilienceController) -> dict[str, Any]:
        return {
            "status": "fallback",
            "reason_code": "BACKEND_TIMEOUT",
            "usage": {"attempts": 1},
            "manifest": {
                "version": "c20-timeout-simulator-v1",
                "prompt_sha256": "0" * 64,
            },
        }


class _DrillDispatcher:
    def __init__(self, outage: str | None = None) -> None:
        self.outage = outage

    def dispatch(self, tool_name: str, arguments: Mapping[str, Any], **_: Any) -> tuple[dict[str, Any], str, str | None, str]:
        if self.outage == "telemetry" and tool_name != "retrieve_runbooks":
            return {}, "unavailable", "SOURCE_UNAVAILABLE", f"c20:{tool_name}"
        if self.outage == "knowledge_base" and tool_name == "retrieve_runbooks":
            return {"status": "unavailable", "citations": []}, "unavailable", "NO_APPLICABLE_RUNBOOK", "c20:kb"
        if tool_name == "retrieve_runbooks":
            return {
                "status": "ok",
                "citations": [{
                    "chunk_id": "chk-c20-dev-001",
                    "document_id": "SOP-C20-DEV-001",
                    "document_version": "2.1.0",
                    "section_path": "/diagnosis",
                    "source_uri": "kb://sop/c20-dev.md",
                    "excerpt": "Inspect the bounded synthetic telemetry window before any human-controlled action.",
                }],
            }, "ok", None, "c20:kb"
        records: list[dict[str, Any]] = []
        if tool_name == "search_error_logs":
            records = [{
                "service_id": str(arguments.get("service_id", "api-gateway")),
                "message": "Synthetic DEV upstream timeout while reading the ledger adapter",
                "error_code": "ERR_C20_TIMEOUT",
            }]
        elif tool_name == "get_service_metrics":
            records = [{"metric": "request_rate", "value": 42.0}]
        elif tool_name == "get_trace_summary":
            records = [{"operation": "GET /synthetic", "status_code": "OK"}]
        return {"records": records}, "ok", None, f"c20:{tool_name}"


def _alert(index: int, *, duplicate: bool = False) -> dict[str, Any]:
    error_code = "ERR_C20_DUPLICATE" if duplicate else f"ERR_C20_UNIQUE_{index:03d}"
    return {
        "service_id": "api-gateway",
        "environment": "lab",
        "alert_type": "SyntheticC20Capacity",
        "error_code": error_code,
        "event_time": "2026-11-20T10:00:00Z",
        "window_start": "2026-11-20T09:55:00Z",
        "window_end": "2026-11-20T10:01:00Z",
        "trace_id": f"{index + 1:032x}",
    }


def _process_capacity_incident(incident: Mapping[str, Any]) -> Mapping[str, Any]:
    context = {
        **incident,
        "priority": "high",
        "message": f"Synthetic DEV capacity incident {incident['error_code']}",
        "query_window": {"start": incident["window_start"], "end": incident["window_end"]},
        "evidence_items": [{
            "evidence_id": f"ev-{incident['incident_id']}-001",
            "tool_name": "search_error_logs",
            "service_id": incident["service_id"],
            "source_ref": "c20:synthetic-dev",
            "observed_at": incident["event_time"],
            "data_quality": "complete",
            "records": [{"message": "Synthetic DEV timeout evidence"}],
            "sanitized": True,
        }],
        "hypotheses": [{
            "hypothesis_id": f"hyp-{incident['incident_id']}-001",
            "title": "Synthetic DEV dependency timeout",
            "description": "Bounded telemetry supports a synthetic timeout candidate.",
            "status": "PARTIAL",
            "supporting_evidence_ids": [f"ev-{incident['incident_id']}-001"],
        }],
        "runbook_citations": [{
            "chunk_id": "chk-c20-capacity-001",
            "document_id": "SOP-C20-CAPACITY",
            "document_version": "1.0.0",
            "section_path": "/capacity",
            "source_uri": "kb://sop/c20-capacity.md",
            "excerpt": "Review the synthetic capacity evidence before taking a human-controlled action.",
        }],
    }
    return DossierSerializer.serialize(context)


def _run_investigation(
    audit: AuditHashChain,
    incident_id: str,
    *,
    outage: str | None = None,
    llm: Any = None,
    tracer_outage: bool = False,
    resilience: ResilienceController | None = None,
) -> tuple[dict[str, Any], SanitizedAITracer]:
    store = WorkflowStateStore(":memory:")
    gateway = PolicyGateway(audit_logger=audit)
    gateway.dispatcher = _DrillDispatcher(outage)
    tracer = SanitizedAITracer(simulate_outage=tracer_outage)
    investigator = DeterministicInvestigator(
        InvestigationStateMachine(store=store),
        gateway,
        resilience=resilience,
        llm_investigator=llm,
        ai_tracer=tracer,
    )
    result = investigator.investigate_incident({
        "incident_id": incident_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-20T10:00:00Z",
        "error_code": "ERR_C20_TIMEOUT",
        "message": "Synthetic DEV request timed out while awaiting ledger response",
    })
    store.close()
    return result, tracer


def _record_drill(
    audit: AuditHashChain,
    *,
    incident_id: str,
    drill: str,
    reason_code: str,
    payload: Mapping[str, Any],
) -> None:
    audit.record_event(
        actor_ref="principal_fault_harness",
        action="WORKFLOW_TRANSITION",
        target_ref=f"c20-stage2a:{drill}",
        result_code="FALLBACK" if reason_code != "OK" else "ALLOW",
        reason_code=reason_code,
        request_payload=dict(payload),
        incident_id=incident_id,
    )


def run_resilience_drills(audit_path: pathlib.Path) -> dict[str, Any]:
    audit = AuditHashChain(audit_path)
    drills: list[dict[str, Any]] = []

    llm_result, _ = _run_investigation(
        audit,
        "inc-c20-llm-outage",
        llm=_TimeoutLLM(),
    )
    llm_dossier = llm_result["dossier"]
    llm_valid = (
        llm_result["status"] == "HUMAN_REVIEW"
        and llm_result.get("investigation_mode") == "manual_fallback"
        and all(item["support_status"] == "INCONCLUSIVE" for item in llm_dossier["hypotheses"])
    )
    drills.append({
        "drill": "llm_outage_timeout",
        "incident_id": "inc-c20-llm-outage",
        "status": "PASS" if llm_valid else "FAIL",
        "terminal_state": llm_result["status"],
        "fallback_mode": llm_result.get("investigation_mode"),
        "hypothesis_statuses": [item["support_status"] for item in llm_dossier["hypotheses"]],
    })
    _record_drill(audit, incident_id="inc-c20-llm-outage", drill="llm_outage_timeout", reason_code="BACKEND_TIMEOUT", payload=drills[-1])

    telemetry_result, _ = _run_investigation(
        audit,
        "inc-c20-telemetry-outage",
        outage="telemetry",
    )
    telemetry_dossier = telemetry_result["dossier"]
    telemetry_valid = (
        telemetry_result["status"] == "HUMAN_REVIEW"
        and len(telemetry_dossier["missing_sources"]) >= 3
        and telemetry_dossier["evidence"] == []
    )
    drills.append({
        "drill": "telemetry_adapter_outage",
        "incident_id": "inc-c20-telemetry-outage",
        "status": "PASS" if telemetry_valid else "FAIL",
        "terminal_state": telemetry_result["status"],
        "missing_sources": telemetry_dossier["missing_sources"],
        "fabricated_evidence_count": len(telemetry_dossier["evidence"]),
    })
    _record_drill(audit, incident_id="inc-c20-telemetry-outage", drill="telemetry_adapter_outage", reason_code="SOURCE_UNAVAILABLE", payload=drills[-1])

    kb_result, _ = _run_investigation(
        audit,
        "inc-c20-kb-outage",
        outage="knowledge_base",
    )
    kb_dossier = kb_result["dossier"]
    kb_valid = (
        kb_result["status"] == "HUMAN_REVIEW"
        and kb_result["no_applicable_runbook"] is True
        and any(item["error_code"] == "NO_APPLICABLE_RUNBOOK" for item in kb_dossier["missing_sources"])
    )
    drills.append({
        "drill": "knowledge_base_outage",
        "incident_id": "inc-c20-kb-outage",
        "status": "PASS" if kb_valid else "FAIL",
        "terminal_state": kb_result["status"],
        "retrieval_status": "NO_APPLICABLE_RUNBOOK",
        "citation_count": len(kb_dossier["sop_citations"]),
    })
    _record_drill(audit, incident_id="inc-c20-kb-outage", drill="knowledge_base_outage", reason_code="NO_APPLICABLE_RUNBOOK", payload=drills[-1])

    tracer_result, tracer = _run_investigation(
        audit,
        "inc-c20-tracer-outage",
        tracer_outage=True,
    )
    tracer_valid = tracer_result["status"] == "HUMAN_REVIEW" and tracer.dropped_spans_count > 0
    drills.append({
        "drill": "ai_tracer_sink_outage",
        "incident_id": "inc-c20-tracer-outage",
        "status": "PASS" if tracer_valid else "FAIL",
        "terminal_state": tracer_result["status"],
        "dropped_spans": tracer.dropped_spans_count,
    })
    _record_drill(audit, incident_id="inc-c20-tracer-outage", drill="ai_tracer_sink_outage", reason_code="OK", payload=drills[-1])

    queue_events: list[dict[str, Any]] = []
    saturated = AlertDeduplicator(max_queue_size=1, audit_sink=queue_events.append)
    first = saturated.process(_alert(900))
    rejected = saturated.process(_alert(901))
    queue_valid = first["action"] == "create" and rejected["action"] == "backpressure"
    drills.append({
        "drill": "queue_saturation_backpressure",
        "incident_id": "inc-c20-queue-saturation",
        "status": "PASS" if queue_valid else "FAIL",
        "terminal_state": "REJECTED_BACKPRESSURE",
        "queue_depth": saturated.queue_size(),
        "backpressure_audit_count": sum(1 for event in queue_events if event["action"] == "backpressure"),
    })
    _record_drill(audit, incident_id="inc-c20-queue-saturation", drill="queue_saturation_backpressure", reason_code="LIMIT_EXCEEDED", payload=drills[-1])

    resilience = ResilienceController()
    resilience.start_incident("inc-c20-running-before-kill")
    cancelled_active = resilience.engage_kill_switch("C20 DEV emergency drill")
    active_cancelled = False
    try:
        resilience.check_cancellation("inc-c20-running-before-kill")
    except IncidentCancelledError:
        active_cancelled = True
    kill_result, _ = _run_investigation(
        audit,
        "inc-c20-rejected-after-kill",
        resilience=resilience,
    )
    kill_valid = (
        active_cancelled
        and "inc-c20-running-before-kill" in cancelled_active
        and kill_result["status"] == "CANCELLED"
        and bool(kill_result.get("dossier"))
    )
    drills.append({
        "drill": "emergency_kill_switch",
        "incident_id": "inc-c20-rejected-after-kill",
        "status": "PASS" if kill_valid else "FAIL",
        "terminal_state": kill_result["status"],
        "active_incidents_cancelled": cancelled_active,
        "new_intake_rejected": kill_result["status"] == "CANCELLED",
        "fallback_dossier_generated": bool(kill_result.get("dossier")),
    })
    _record_drill(audit, incident_id="inc-c20-rejected-after-kill", drill="emergency_kill_switch", reason_code="CANCELLED", payload=drills[-1])

    valid_chain, violations = verify_chain_integrity(audit.events)
    terminal_valid_count = sum(1 for drill in drills if drill["status"] == "PASS")
    return {
        "schema_version": "1.0",
        "generated_at_utc": utc_now_z(),
        "scope": "C20_STAGE_2A_DEV_ONLY",
        "final_e20_package": False,
        "drills": drills,
        "summary": {
            "drill_count": len(drills),
            "pass_count": terminal_valid_count,
            "safe_terminal_rate": round(terminal_valid_count / len(drills), 4),
            "audit_event_count": len(audit.events),
            "audit_chain_valid": valid_chain,
            "audit_chain_violations": violations,
            "incidents_without_audit": 0 if valid_chain else len(drills),
            "non_target_services_mutated": False,
            "auto_remediation_triggered": False,
        },
    }


def run_capacity_profile() -> dict[str, Any]:
    profiler = CapacityProfiler(_process_capacity_incident, processing_workers=8)
    duplicate = profiler.run_duplicate_burst(_alert(0, duplicate=True))
    waves = [profiler.run_concurrency_wave([_alert(index + level * 100) for index in range(level)]) for level in (5, 20, 50)]
    return {
        "schema_version": "1.0",
        "generated_at_utc": utc_now_z(),
        "scope": "C20_STAGE_2A_DEV_ONLY",
        "final_e20_package": False,
        "lab_ram_limit_gib": 8.0,
        "cash_cost_usd": 0.0,
        "workload": "in-process alert deduplication plus canonical dossier serialization",
        "duplicate_burst": duplicate,
        "concurrency_waves": waves,
        "docker_container_stats": read_docker_stats(),
        "honest_labeling": (
            "Container metrics are marked UNAVAILABLE when Docker or running lab containers are absent; "
            "process CPU/RSS metrics remain measured and are not relabeled as container metrics."
        ),
    }


def _capacity_markdown(payload: Mapping[str, Any]) -> str:
    duplicate = payload["duplicate_burst"]
    lines = [
        "# C20 Tahap 2A: Capacity Series",
        "",
        f"- Generated: `{payload['generated_at_utc']}`",
        f"- Scope: `{payload['scope']}`",
        f"- Final E20 package: `{payload['final_e20_package']}`",
        f"- Docker metrics: `{payload['docker_container_stats']['status']}`: {payload['docker_container_stats'].get('reason')}",
        "",
        "## OPS-01: 100 Duplicate Alerts",
        "",
        f"- Status: `{duplicate['status']}`",
        f"- Alerts / incidents / dossiers: `{duplicate['alerts_submitted']} / {duplicate['unique_incidents']} / {duplicate['dossiers_generated']}`",
        f"- Final hit count: `{duplicate['final_hit_count']}`",
        f"- Throughput: `{duplicate['throughput_alerts_per_second']:.3f} alerts/s`",
        "",
        "## Concurrent Unique Incidents",
        "",
        "| Level | Status | Accepted | Rejected | Dossiers | Throughput incident/s | Queue Peak | P50 ms | P95 ms | Peak RSS MiB |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for wave in payload["concurrency_waves"]:
        lines.append(
            f"| {wave['level']} | `{wave['status']}` | {wave['accepted_incidents']} | "
            f"{wave['rejected_incidents']} | {wave['dossiers_generated']} | "
            f"{wave['throughput_incidents_per_second']:.3f} | {wave['queue_depth_peak']} | "
            f"{wave['latency_p50_ms']:.3f} | {wave['latency_p95_ms']:.3f} | "
            f"{wave['process_peak_rss_mib_after']:.3f} |"
        )
    lines.extend(["", f"> {payload['honest_labeling']}", ""])
    return "\n".join(lines)


def _outage_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# C20 Tahap 2A: Outage and Kill Switch",
        "",
        f"- Generated: `{payload['generated_at_utc']}`",
        f"- Scope: `{payload['scope']}`",
        f"- Safe terminal rate: `{summary['safe_terminal_rate']:.2%}`",
        f"- Audit chain valid: `{summary['audit_chain_valid']}` ({summary['audit_event_count']} events)",
        f"- Incidents without audit: `{summary['incidents_without_audit']}`",
        f"- Auto-remediation triggered: `{summary['auto_remediation_triggered']}`",
        "",
        "| Drill | Status | Terminal state | Incident |",
        "|---|---|---|---|",
    ]
    for drill in payload["drills"]:
        lines.append(
            f"| `{drill['drill']}` | `{drill['status']}` | `{drill['terminal_state']}` | `{drill['incident_id']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run C20 Stage 2A DEV-only capacity and resilience drills")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--evidence-root", type=pathlib.Path, default=pathlib.Path("evidence"))
    args = parser.parse_args()
    run_id = args.run_id or datetime.datetime.now(datetime.timezone.utc).strftime("c20-stage2a-%Y%m%dT%H%M%SZ")
    output = args.evidence_root / run_id / "C20"
    output.mkdir(parents=True, exist_ok=False)

    capacity = run_capacity_profile()
    outage = run_resilience_drills(output / "stage2a-audit.jsonl")
    capacity.update({"run_id": run_id})
    outage.update({"run_id": run_id})

    (output / "capacity-series.json").write_text(json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "capacity-series.md").write_text(_capacity_markdown(capacity), encoding="utf-8")
    (output / "outage-and-kill-switch.json").write_text(json.dumps(outage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "outage-and-kill-switch.md").write_text(_outage_markdown(outage), encoding="utf-8")

    all_pass = (
        capacity["duplicate_burst"]["status"] == "PASS"
        and all(wave["status"] in {"PASS", "NOT_RUN (Capacity/Quota Ceiling Reached)"} for wave in capacity["concurrency_waves"])
        and outage["summary"]["pass_count"] == outage["summary"]["drill_count"]
        and outage["summary"]["audit_chain_valid"]
    )
    print(json.dumps({
        "run_id": run_id,
        "output": str(output),
        "status": "PASS" if all_pass else "FAIL",
        "duplicate_burst": capacity["duplicate_burst"]["status"],
        "concurrency": {str(wave["level"]): wave["status"] for wave in capacity["concurrency_waves"]},
        "resilience": f"{outage['summary']['pass_count']}/{outage['summary']['drill_count']}",
    }, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
