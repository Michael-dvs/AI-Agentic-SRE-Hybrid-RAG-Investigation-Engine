"""C20 Stage 2A defect, capacity, outage, and kill-switch regression tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import pathlib

from rich.console import Console

from evaluator.manual_baseline import build_manual_baseline_record, compute_manual_vs_assisted_summary
from knowledge_base.retrieval.models import RetrievalRequest
from knowledge_base.retrieval.prefilter import StrictPreFilter
from observability.audit_chain import AuditHashChain, verify_chain_integrity
from orchestrator.dossier import DossierSerializer
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.review import AuthorizedReviewManager
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.usability_console import DashboardViewport, SREDashboard, _bounded_sanitized_excerpt
from scripts.run_c20_stage2a import run_capacity_profile, run_resilience_drills


def _revision_context(incident_id: str = "inc-c20-revision") -> dict:
    return {
        "incident_id": incident_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-20T10:00:00Z",
        "priority": "high",
        "message": "Synthetic timeout",
        "query_window": {
            "start": "2026-11-20T09:55:00Z",
            "end": "2026-11-20T10:01:00Z",
        },
        "evidence_items": [{
            "evidence_id": f"ev-{incident_id}-001",
            "tool_name": "search_error_logs",
            "service_id": "api-gateway",
            "source_ref": "c20:dev",
            "observed_at": "2026-11-20T10:00:00Z",
            "data_quality": "complete",
            "records": [{"message": "password=synthetic-secret timeout " + "x" * 400}],
            "sanitized": True,
        }],
        "hypotheses": [{
            "hypothesis_id": f"hyp-{incident_id}-001",
            "title": "Synthetic timeout candidate",
            "description": "Bounded evidence supports a timeout candidate.",
            "status": "PARTIAL",
            "supporting_evidence_ids": [f"ev-{incident_id}-001"],
        }],
        "sop_availability": "APPLICABLE_SOP_FOUND",
        "runbook_citations": [{
            "chunk_id": "chk-c20-revision-001",
            "document_id": "SOP-C20-REVISION",
            "document_version": "3.2.1",
            "title": "Synthetic C20 Revision Runbook",
            "section_path": "/timeout",
            "source_uri": "kb://sop/c20-revision.md",
            "service_id": "api-gateway",
            "environment": "lab",
            "status": "approved",
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_to": None,
            "content_hash": sha256(("secret=synthetic-runbook-secret inspect bounded telemetry " + "y" * 700).encode("utf-8")).hexdigest(),
            "score": 0.15,
            "score_type": "rrf_fusion",
            "source_branch": "hybrid",
            "sanitized_excerpt": "secret=synthetic-runbook-secret inspect bounded telemetry " + "y" * 700,
            "applicability_verified": True,
            "sanitized": True,
        }],
    }


def test_def001_viewport_reflows_against_current_console_width(tmp_path: pathlib.Path) -> None:
    store = WorkflowStateStore(":memory:")
    dashboard = SREDashboard(
        store,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
    )
    viewport = DashboardViewport(dashboard)
    wide = Console(width=120, record=True, force_terminal=False)
    narrow = Console(width=72, record=True, force_terminal=False)
    wide.print(viewport)
    narrow.print(viewport)
    wide_text = wide.export_text(clear=False)
    narrow_text = narrow.export_text(clear=False)
    assert "Active Incidents" in wide_text
    assert "Active Incidents" in narrow_text
    assert wide_text != narrow_text
    store.close()


def test_def002_bounded_sanitized_evidence_and_sop_version_render(tmp_path: pathlib.Path) -> None:
    dossier = DossierSerializer.serialize(_revision_context())
    assert dossier["sop_citations"][0]["version"] == "3.2.1"
    assert dossier["sop_citations"][0]["sanitized"] is True
    assert len(dossier["sop_citations"][0]["excerpt"]) <= 512
    assert "synthetic-runbook-secret" not in dossier["sop_citations"][0]["excerpt"]
    assert "synthetic-secret" not in dossier["evidence"][0]["summary"]
    excerpt = _bounded_sanitized_excerpt("password=synthetic-secret " + "z" * 500)
    assert len(excerpt) <= 240
    assert "synthetic-secret" not in excerpt

    store = WorkflowStateStore(":memory:")
    dashboard = SREDashboard(
        store,
        audit_path=tmp_path / "audit.jsonl",
        handover_root=tmp_path / "handover",
    )
    console = Console(width=100, record=True, force_terminal=False)
    console.print(dashboard._dossier_detail(dossier))
    rendered = console.export_text()
    assert "SOP-C20-REVISION v3.2.1" in rendered
    assert "[REDACTED:SEC-03:CREDENTIAL]" in rendered
    store.close()


def test_def003_audit_tail_initialization_and_concurrent_chain_integrity(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    path = tmp_path / "audit.jsonl"
    chain = AuditHashChain(path)
    for index in range(20):
        chain.record_event(
            actor_ref="principal_fault_harness",
            action="WORKFLOW_TRANSITION",
            target_ref=f"c20-seed-{index}",
            result_code="ALLOW",
            reason_code="OK",
            incident_id=f"inc-c20-seed-{index}",
        )

    original_read_text = pathlib.Path.read_text

    def reject_full_log_read(self: pathlib.Path, *args, **kwargs):
        if self == path:
            raise AssertionError("audit log must not be fully read during cached initialization")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", reject_full_log_read)
    resumed = AuditHashChain(path)
    assert resumed.initialization_mode == "tail"

    def append(index: int) -> None:
        resumed.record_event(
            actor_ref="principal_fault_harness",
            action="WORKFLOW_TRANSITION",
            target_ref=f"c20-concurrent-{index}",
            result_code="ALLOW",
            reason_code="OK",
            incident_id=f"inc-c20-concurrent-{index}",
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(append, range(50)))
    monkeypatch.setattr(pathlib.Path, "read_text", original_read_text)
    events = list(resumed.events)
    valid, violations = verify_chain_integrity(events)
    assert len(events) == 70
    assert valid, violations


def test_def004_correct_revision_inherits_evidence_citations_and_alert_time() -> None:
    store = WorkflowStateStore(":memory:")
    dossier = DossierSerializer.serialize(_revision_context())
    store.create_incident(dossier["incident_id"], initial_state="HUMAN_REVIEW")
    store.save_dossier(
        dossier["incident_id"],
        1,
        dossier["dossier_hash"],
        dossier,
        "v1",
    )
    result = AuthorizedReviewManager(store=store).submit_review(
        incident_id=dossier["incident_id"],
        dossier_dict=dossier,
        reviewer_ref="c20-reviewer",
        reviewer_role="L2_SRE",
        decision="edit",
        rationale="Correct the bounded diagnosis wording",
        edited_dossier_data={
            "hypotheses": [{
                **dossier["hypotheses"][0],
                "statement": "Corrected synthetic timeout candidate",
            }],
            "evidence": [],
            "sop_citations": [],
            "alert_received_at": "2030-01-01T00:00:00Z",
        },
    )
    revised = result["new_dossier_revision"]
    assert revised["dossier_version"] == 2
    assert revised["evidence"] == dossier["evidence"]
    assert revised["sop_citations"] == dossier["sop_citations"]
    assert revised["alert_received_at"] == dossier["alert_received_at"]
    store.close()


def test_def005_manual_baseline_retains_solo_developer_bias_disclosure() -> None:
    record = build_manual_baseline_record(
        incident_id="inc-c20-baseline",
        service_id="api-gateway",
        case_label="Synthetic DEV baseline",
        alert_received_at="2026-11-20T09:00:00Z",
        manual_started_at="2026-11-20T09:00:01Z",
        manual_completed_at="2026-11-20T09:01:01Z",
        manual_locked_at="2026-11-20T09:01:02Z",
        ai_dossier_opened_at="2026-11-20T09:01:03Z",
        ai_review_completed_at="2026-11-20T09:01:13Z",
        manual_seconds=60,
        system_tti_seconds=1,
        human_review_seconds=10,
        manual_steps_count=4,
        document_search_friction="Synthetic document search required manual navigation.",
        manual_hypothesis_summary="Synthetic timeout candidate",
        manual_sop_lookup_used=["SOP-C20-DEV"],
    )
    declaration = compute_manual_vs_assisted_summary([record])["validity_declaration"]
    assert declaration["solo_developer_caveat"] is True
    assert declaration["independent_sme_validated"] is False
    assert "bias familiaritas" in declaration["disclosure"]
    assert declaration["label_source"] == "SELF_EVALUATED_DEVELOPER_LABELS"


def test_def006_index_aliases_and_telemetry_enriched_query() -> None:
    chunk = {
        "service_id": "api-gateway",
        "environment": "lab",
        "status": "approved",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": None,
        "classification": "synthetic-internal",
        "allowed_groups": ["l1-operator"],
        "index_version": "kb-idx-20261111-v1",
    }
    base = dict(
        service_id="api-gateway",
        environment="lab",
        query_text="timeout",
        reference_time="2026-11-20T10:00:00Z",
        retrieval_mode="hybrid_rrf",
        caller_groups=["l1-operator"],
        top_k=3,
        max_context_tokens=1024,
    )
    for policy in ("kb_active_alias", "active_only", "kb-idx-20261111-v1"):
        allowed, reason = StrictPreFilter.is_chunk_applicable(
            chunk,
            RetrievalRequest(**base, index_version_policy=policy),
        )
        assert allowed, reason
    denied, reason = StrictPreFilter.is_chunk_applicable(
        chunk,
        RetrievalRequest(**base, index_version_policy=""),
    )
    assert denied is False
    assert reason == "INDEX_VERSION_POLICY_REQUIRED"

    query = DeterministicInvestigator._retrieval_query_text({
        "service_id": "api-gateway",
        "error_code": "ERR_TIMEOUT",
        "evidence_items": [{
            "tool_name": "search_error_logs",
            "records": [{"message": "password=synthetic-secret upstream ledger timeout"}],
        }],
    })
    assert "upstream ledger timeout" in query
    assert "synthetic-secret" not in query


def test_ops01_duplicate_burst_and_5_20_50_concurrency_profile() -> None:
    report = run_capacity_profile()
    duplicate = report["duplicate_burst"]
    assert duplicate["status"] == "PASS"
    assert duplicate["alerts_submitted"] == 100
    assert duplicate["unique_incidents"] == 1
    assert duplicate["dossiers_generated"] == 1
    assert duplicate["final_hit_count"] == 100
    assert duplicate["action_counts"] == {"create": 1, "merge": 99, "split": 0, "backpressure": 0}
    assert [wave["level"] for wave in report["concurrency_waves"]] == [5, 20, 50]
    for wave in report["concurrency_waves"]:
        assert wave["status"] in {"PASS", "NOT_RUN (Capacity/Quota Ceiling Reached)"}
        assert wave["queue_depth_peak"] <= wave["level"]
        assert wave["process_peak_rss_mib_after"] <= wave["lab_ram_limit_mib"]
        if wave["status"] == "PASS":
            assert wave["dossiers_generated"] == wave["level"]
            assert wave["rejected_incidents"] == 0


def test_ops02_multi_outage_backpressure_and_kill_switch(tmp_path: pathlib.Path) -> None:
    report = run_resilience_drills(tmp_path / "stage2a-audit.jsonl")
    assert report["summary"]["pass_count"] == report["summary"]["drill_count"] == 6
    assert report["summary"]["safe_terminal_rate"] == 1.0
    assert report["summary"]["audit_chain_valid"] is True
    assert report["summary"]["incidents_without_audit"] == 0
    assert report["summary"]["non_target_services_mutated"] is False
    assert report["summary"]["auto_remediation_triggered"] is False
    by_name = {item["drill"]: item for item in report["drills"]}
    assert by_name["llm_outage_timeout"]["hypothesis_statuses"] == ["INCONCLUSIVE"]
    assert by_name["telemetry_adapter_outage"]["fabricated_evidence_count"] == 0
    assert by_name["knowledge_base_outage"]["retrieval_status"] == "RETRIEVAL_UNAVAILABLE"
    assert by_name["ai_tracer_sink_outage"]["dropped_spans"] > 0
    assert by_name["queue_saturation_backpressure"]["terminal_state"] == "REJECTED_BACKPRESSURE"
    assert by_name["emergency_kill_switch"]["new_intake_rejected"] is True
    assert by_name["emergency_kill_switch"]["fallback_dossier_generated"] is True
