"""P0-02 Hardening & Final Verification Test Suite (H1-H5).

Covers:
- H1: SQLite transaction atomicity across record_review, save_dossier, state_machine.transition, and COMMIT/connection failures.
- H2: Deterministic concurrency & idempotency across threads, separate SQLite connections, DB unique indexes, and separate OS processes.
- H3: Reviewer identity trust boundary, unknown/invalid/malformed actors, AI/system impersonation, role & edit-field privilege escalation.
- H4: Fail-closed audit/DB consistency, post-audit commit rollback compensation, orphan detection via reconcile_review_audit, and safe retries.
- H5: Administrative closure semantics (ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED) across Dossier, Ticket, Handover (MD/HTML/JSON), CLI, TUI, and Offline Evaluator.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import multiprocessing
import pathlib
import sqlite3
import threading
from typing import Any

import pytest
from rich.console import Console

from evaluator.runner import EvaluationBlocked, join_dev
from gateway.auth import Authenticator
from observability.audit_chain import AuditHashChain, AuditWriteError, verify_chain_integrity
from orchestrator.dossier import DossierMarkdownRenderer, DossierSerializer, compute_canonical_dossier_hash
from orchestrator.handover import HandoverExporter
from orchestrator.review import (
    AuthorizedReviewManager,
    InvalidDossierError,
    ReviewStateConflictError,
    StaleDossierVersionError,
    UnauthorizedReviewerError,
    build_human_correction_payload,
    reconcile_review_audit,
)
from orchestrator.state_machine import (
    InvalidStateTransitionError,
    InvestigationStateMachine,
    WorkflowStateStore,
)
from orchestrator.ticketing import DummyTicketManager, InvalidDossierStateError
from orchestrator.usability_console import SREDashboard
from scripts.review_console import display_dossier_summary, run_review_action


def _build_dossier(
    incident_id: str,
    *,
    support_status: str = "PARTIAL",
    validation_status: str | None = None,
    with_sop: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sup = [f"ev-{incident_id}-001"] if support_status in ("SUPPORTED", "PARTIAL") else []
    con = [f"ev-{incident_id}-002"] if (validation_status == "CONTRADICTED") else []
    val_stat = validation_status or support_status
    citations = (
        [
            {
                "chunk_id": "chk-gw-001",
                "doc_id": "SOP-GW-001",
                "document_version": "1.0.0",
                "section_path": "/dependency-errors",
                "source_uri": "kb://sop/sop-gw-001.md",
                "applicability_verified": True,
                "excerpt": "Inspect downstream service health before manual intervention.",
                "sanitized": True,
            }
        ]
        if with_sop
        else []
    )
    missing_sources = (
        []
        if with_sop
        else [
            {
                "tool_name": "retrieve_runbooks",
                "error_code": "NO_APPLICABLE_RUNBOOK",
                "recorded_at": "2026-11-23T03:44:28Z",
                "impact_note": "No active SOP matched api-gateway symptom.",
            }
        ]
    )
    ctx: dict[str, Any] = {
        "incident_id": incident_id,
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-23T03:44:14Z",
        "priority": "high",
        "investigation_scope": ["api-gateway", "transaction-service"],
        "query_window": {"start": "2026-11-23T03:39:14Z", "end": "2026-11-23T03:45:14Z"},
        "evidence_items": [
            {
                "evidence_id": f"ev-{incident_id}-001",
                "tool_name": "search_error_logs",
                "service_id": "api-gateway",
                "source_ref": "loki",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "sanitized": True,
                "records": [
                    {
                        "service_id": "api-gateway",
                        "status_code": 503,
                        "error_code": "ERR_DEPENDENCY_UNAVAILABLE",
                        "message": "Downstream dependency refused connection",
                    }
                ],
            },
            {
                "evidence_id": f"ev-{incident_id}-002",
                "tool_name": "get_service_metrics",
                "service_id": "api-gateway",
                "source_ref": "prometheus",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "sanitized": True,
                "records": [{"service_id": "api-gateway", "metric_enum": "request_rate", "value": 0.48}],
            },
        ],
        "runbook_citations": citations,
        "missing_sources": missing_sources,
        "no_applicable_runbook": not with_sop,
        "hypotheses": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "title": "api-gateway downstream dependency failure",
                "description": "Downstream dependency refused connection causing 503.",
                "status": support_status,
                "validation_status": val_stat,
                "supporting_evidence_ids": sup,
                "contradicting_evidence_ids": con,
                "unknowns": ["Downstream instance restart state unknown."],
            }
        ],
        "unknowns": [
            "Downstream instance restart state unknown.",
            "api-gateway rate limit configuration values unavailable.",
        ],
        "validation_reports": [
            {
                "hypothesis_id": f"hyp-{incident_id}-001",
                "status": val_stat,
                "reason_codes": ["NO_APPLICABLE_RUNBOOK"] if not with_sop else ["CLAIM_CORROBORATED"],
                "claims": [],
                "contradictions": [],
                "unknowns": ["Downstream instance restart state unknown."],
                "supporting_evidence_ids": sup,
                "contradicting_evidence_ids": con,
                "rejected_sop_citations": [],
                "valid_sop_citations": citations,
            }
        ],
        "version_manifest": {
            "workflow_version": "1.0.0",
            "policy_version": "1.0.0",
            "model_version": "synthetic-replay",
            "prompt_version": "prompt-p0-02",
            "tool_schema_version": "1.0",
            "kb_version": "kb-idx-20261111-v1",
        },
    }
    dossier = DossierSerializer.serialize(ctx, revision=1, investigation_mode="agentic_llm")
    return dossier, ctx


def _setup_env(
    tmp_path: pathlib.Path,
    incident_id: str,
    *,
    support_status: str = "PARTIAL",
    validation_status: str | None = None,
    with_sop: bool = False,
    **rm_kwargs: Any,
) -> tuple[pathlib.Path, WorkflowStateStore, InvestigationStateMachine, AuditHashChain, AuthorizedReviewManager, dict[str, Any]]:
    db_path = tmp_path / f"{incident_id}.db"
    store = WorkflowStateStore(str(db_path))
    sm = InvestigationStateMachine(store=store)
    audit = AuditHashChain(log_path=tmp_path / f"{incident_id}-audit.jsonl")
    rm = AuthorizedReviewManager(state_machine=sm, store=store, audit_chain=audit, **rm_kwargs)
    dossier, ctx = _build_dossier(
        incident_id,
        support_status=support_status,
        validation_status=validation_status,
        with_sop=with_sop,
    )
    store.create_incident(
        incident_id=incident_id,
        service_id="api-gateway",
        environment="lab",
        initial_state="HUMAN_REVIEW",
        status="ACTIVE",
    )
    store.save_checkpoint(incident_id, "HUMAN_REVIEW", ctx)
    store.save_dossier(
        incident_id=incident_id,
        dossier_version=1,
        dossier_hash=dossier["dossier_hash"],
        dossier_json=dossier,
        dossier_markdown=DossierMarkdownRenderer.render(dossier),
    )
    return db_path, store, sm, audit, rm, dossier


def _prepare_dev_eval_dirs(
    tmp_path: pathlib.Path,
    incident_id: str,
    run_id: str,
) -> dict[str, pathlib.Path]:
    source = tmp_path / f"{run_id}-dev"
    output = tmp_path / f"{run_id}-eval"
    runtime = tmp_path / f"{run_id}-runtime"
    for p in (source, output, runtime):
        p.mkdir(mode=0o700, exist_ok=True)
    gt_file = source / f"{run_id}.json"
    gt_file.write_text(
        json.dumps({"run_id": run_id, "incident_id": incident_id, "split_id": "dev", "cause": "downstream"}),
        encoding="utf-8",
    )
    gt_file.chmod(0o600)
    return {"dev_source_dir": source, "output_dir": output, "runtime_dir": runtime}


# ==============================================================================
# Top-level Multiprocessing Workers (spawn-safe for H2 cross-process tests)
# ==============================================================================


def _mp_audit_worker(
    audit_path: str,
    worker_name: str,
    barrier: Any,
    out_queue: Any,
) -> None:
    audit = AuditHashChain(log_path=audit_path)
    try:
        barrier.wait(timeout=15)
        ev = audit.record_event(
            actor_ref="principal_reviewer",
            action="HUMAN_REVIEW_DECISION",
            target_ref=f"inc-h4-flock-{worker_name}:v1",
            result_code="ALLOW",
            reason_code="OK",
            request_payload={"worker": worker_name},
            incident_id=f"inc-h4-flock-{worker_name}",
        )
        out_queue.put(("OK", ev["audit_event_id"]))
    except Exception as exc:
        out_queue.put(("ERROR", type(exc).__name__, str(exc)))


def _mp_review_worker(
    db_path: str,
    audit_path: str,
    incident_id: str,
    dossier_dict: dict[str, Any],
    decision: str,
    reviewer_ref: str,
    barrier: Any,
    out_queue: Any,
) -> None:
    store = WorkflowStateStore(db_path)
    sm = InvestigationStateMachine(store=store)
    audit = AuditHashChain(log_path=audit_path)
    rm = AuthorizedReviewManager(state_machine=sm, store=store, audit_chain=audit)
    try:
        barrier.wait(timeout=15)
        res = rm.submit_review(
            incident_id=incident_id,
            dossier_dict=dossier_dict,
            reviewer_ref=reviewer_ref,
            reviewer_role="L2_SRE",
            decision=decision,
            rationale=f"Cross-process {decision} attempt by {reviewer_ref}.",
        )
        out_queue.put(("OK", decision, res["review_event"]["review_event_id"]))
    except Exception as exc:
        out_queue.put(("REJECTED", type(exc).__name__, str(exc)))
    finally:
        store.close()


# ==============================================================================
# WORK PACKAGE H1 — SQLITE TRANSACTION ATOMICITY
# ==============================================================================


def test_h1_rollback_on_record_review_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H1: Failure in store.record_review leaves DB untouched, emits 0 ALLOW audits, and permits clean retry."""
    inc_id = "inc-h1-rev-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_hash = dossier["dossier_hash"]
    orig_record_review = store.record_review

    def fail_record_review(ev: dict[str, Any]) -> None:
        raise sqlite3.OperationalError("injected record_review failure")

    monkeypatch.setattr(store, "record_review", fail_record_review)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected record_review failure"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        stored_d = store.get_dossier(inc_id, version=1)
        assert stored_d["dossier_hash"] == orig_hash
        assert stored_d["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert audit.events == []

        # Clear fault and verify retry succeeds cleanly
        monkeypatch.setattr(store, "record_review", orig_record_review)
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert res["updated_dossier"]["review_summary"]["status"] == "APPROVED"
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert len(store.get_reviews(inc_id)) == 1
        assert len(audit.events) == 2
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
    finally:
        store.close()


def test_h1_rollback_on_save_dossier_v1_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H1: Failure in save_dossier rolls back preceding record_review and keeps incident in HUMAN_REVIEW."""
    inc_id = "inc-h1-save-v1-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_hash = dossier["dossier_hash"]
    orig_save_dossier = store.save_dossier

    def fail_save(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("injected save_dossier v1 failure")

    monkeypatch.setattr(store, "save_dossier", fail_save)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected save_dossier v1 failure"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_dossier(inc_id, version=1)["dossier_hash"] == orig_hash
        assert store.get_dossier(inc_id, version=1)["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert audit.events == []

        monkeypatch.setattr(store, "save_dossier", orig_save_dossier)
        rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert len(store.get_reviews(inc_id)) == 1
    finally:
        store.close()


def test_h1_rollback_on_save_dossier_v2_correct_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1: On CORRECT, failure saving v2 rolls back v1 EDITED update AND record_review."""
    inc_id = "inc-h1-save-v2-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_hash = dossier["dossier_hash"]
    orig_save = store.save_dossier
    call_count = 0

    def fail_on_v2(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        ver = kwargs.get("dossier_version", args[1] if len(args) > 1 else None)
        if ver == 2 or call_count == 2:
            raise sqlite3.OperationalError("injected save_dossier v2 failure")
        orig_save(*args, **kwargs)

    monkeypatch.setattr(store, "save_dossier", fail_on_v2)
    try:
        corr = build_human_correction_payload(dossier, "Candidate corrected root cause.", "sre_dan", "L2_SRE")
        with pytest.raises(sqlite3.OperationalError, match="injected save_dossier v2 failure"):
            rm.correct(inc_id, dossier, "sre_dan", "L2_SRE", "Correcting candidate.", corrections=corr)

        assert store.get_latest_dossier_version(inc_id) == 1
        assert store.get_dossier(inc_id, version=1)["dossier_hash"] == orig_hash
        assert store.get_dossier(inc_id, version=1)["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert audit.events == []

        # Retry succeeds cleanly once fault clears
        monkeypatch.setattr(store, "save_dossier", orig_save)
        res = rm.correct(inc_id, dossier, "sre_dan", "L2_SRE", "Correcting candidate.", corrections=corr)
        assert res["new_dossier_revision"]["dossier_version"] == 2
        assert store.get_latest_dossier_version(inc_id) == 2
        assert len(store.get_reviews(inc_id)) == 1
    finally:
        store.close()


@pytest.mark.parametrize("fail_point", ["update_incident_state", "record_transition", "sm_transition"])
def test_h1_rollback_on_transition_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_point: str,
) -> None:
    """H1: Transition failures roll back record_review and save_dossier; retry succeeds."""
    inc_id = f"inc-h1-tr-{fail_point.replace('_', '-')}"
    _, store, sm, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_hash = dossier["dossier_hash"]
    orig_update = store.update_incident_state
    orig_rec_tr = store.record_transition
    orig_sm_tr = sm.transition

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError(f"injected {fail_point} failure")

    if fail_point == "update_incident_state":
        monkeypatch.setattr(store, "update_incident_state", boom)
    elif fail_point == "record_transition":
        monkeypatch.setattr(store, "record_transition", boom)
    else:
        monkeypatch.setattr(sm, "transition", boom)

    try:
        with pytest.raises(sqlite3.OperationalError, match=fail_point):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_incident(inc_id)["status"] == "ACTIVE"
        assert store.get_reviews(inc_id) == []
        assert store.get_transitions(inc_id) == []
        stored = store.get_dossier(inc_id, version=1)
        assert stored["dossier_hash"] == orig_hash
        assert stored["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert audit.events == []

        # Restore and retry cleanly
        monkeypatch.setattr(store, "update_incident_state", orig_update)
        monkeypatch.setattr(store, "record_transition", orig_rec_tr)
        monkeypatch.setattr(sm, "transition", orig_sm_tr)
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert res["updated_dossier"]["review_summary"]["status"] == "APPROVED"
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert len(store.get_reviews(inc_id)) == 1
        assert len(store.get_transitions(inc_id)) == 1
    finally:
        store.close()


def test_h1_rollback_on_sqlite_commit_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H1: Failure inside store._commit rolls back all staged SQLite mutations and allows safe retry."""
    inc_id = "inc-h1-commit-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    eval_dirs = _prepare_dev_eval_dirs(tmp_path, inc_id, "run-h1-commit")
    orig_hash = dossier["dossier_hash"]
    orig_commit = store._commit

    def fail_commit() -> None:
        raise sqlite3.OperationalError("injected COMMIT failure")

    monkeypatch.setattr(store, "_commit", fail_commit)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected COMMIT failure"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        # Complete SQLite rollback verified
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_transitions(inc_id) == []
        stored = store.get_dossier(inc_id, version=1)
        assert stored["dossier_hash"] == orig_hash
        assert stored["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert store._conn.in_transaction is False

        # Evaluator blocked because DB rolled back
        with pytest.raises(EvaluationBlocked, match="PREMATURE_EVALUATION_BLOCKED"):
            join_dev(
                store=store,
                audit_events=list(audit.events),
                trusted_audit_head=audit.last_event_hash or ("0" * 64),
                incident_id=inc_id,
                run_id="run-h1-commit",
                **eval_dirs,
            )

        # Retry after COMMIT fault clears
        monkeypatch.setattr(store, "_commit", orig_commit)
        rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert len(store.get_reviews(inc_id)) == 1
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
        joined = join_dev(
            store=store,
            audit_events=list(audit.events),
            trusted_audit_head=audit.last_event_hash,
            incident_id=inc_id,
            run_id="run-h1-commit",
            **eval_dirs,
        )
        assert joined.exists()
    finally:
        store.close()


def test_h1_db_connection_and_readonly_file_failures(tmp_path: pathlib.Path) -> None:
    """H1: Closed connection and read-only DB errors remain observable and leave 0 phantom audit/DB state."""
    # 1. Read-only / query_only DB
    inc_ro = "inc-h1-readonly"
    _, store_ro, _, audit_ro, rm_ro, dossier_ro = _setup_env(tmp_path, inc_ro)
    try:
        store_ro._conn.execute("PRAGMA query_only = ON")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            rm_ro.approve(inc_ro, dossier_ro, "sre_lead_alex", "L2_SRE")
        store_ro._conn.execute("PRAGMA query_only = OFF")
        assert store_ro.get_incident(inc_ro)["current_state"] == "HUMAN_REVIEW"
        assert store_ro.get_reviews(inc_ro) == []
        assert [e for e in audit_ro.events if e["result_code"] == "ALLOW"] == []
    finally:
        store_ro.close()

    # 2. Closed DB connection
    inc_closed = "inc-h1-closed-conn"
    _, store_c, _, audit_c, rm_c, dossier_c = _setup_env(tmp_path, inc_closed)
    store_c.close()
    with pytest.raises(sqlite3.ProgrammingError):
        rm_c.approve(inc_closed, dossier_c, "sre_lead_alex", "L2_SRE")
    assert [e for e in audit_c.events if e["result_code"] == "ALLOW"] == []


def test_h1_state_machine_standalone_transition_atomicity(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1: Standalone sm.transition rolls back update_incident_state if record_transition fails."""
    store = WorkflowStateStore(str(tmp_path / "sm_atomic.db"))
    sm = InvestigationStateMachine(store=store)
    try:
        sm.transition("inc-sm-atomic", "RECEIVED", "idem-001")
        monkeypatch.setattr(
            store,
            "record_transition",
            lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("record_transition boom")),
        )
        with pytest.raises(sqlite3.OperationalError, match="record_transition boom"):
            sm.transition("inc-sm-atomic", "CORRELATED", "idem-002")

        inc = store.get_incident("inc-sm-atomic")
        assert inc["current_state"] == "RECEIVED"
        assert len(store.get_transitions("inc-sm-atomic")) == 1
    finally:
        store.close()


# ==============================================================================
# WORK PACKAGE H2 — CONCURRENCY & IDEMPOTENCY
# ==============================================================================


def test_h2_duplicate_approval_no_duplicate_side_effects(tmp_path: pathlib.Path) -> None:
    """H2: Repeated APPROVE does not create duplicate reviews, transitions, closure audits, or tickets."""
    inc_id = "inc-h2-dup-app"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        first = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert first["approval_semantics"]["resulting_lifecycle_state"] == "CLOSED"

        with pytest.raises(ReviewStateConflictError) as exc_info:
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert exc_info.value.code == "ALREADY_FINALIZED"

        with pytest.raises(ReviewStateConflictError):
            rm.approve(inc_id, first["updated_dossier"], "sre_lead_alex", "L2_SRE")

        assert len(store.get_reviews(inc_id)) == 1
        allow_closures = [
            e for e in audit.events if e["action"] == "WORKFLOW_TRANSITION" and e["result_code"] == "ALLOW"
        ]
        assert len(allow_closures) == 1
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
    finally:
        store.close()


def test_h2_conflicting_approve_and_reject_separate_connections_deterministic(
    tmp_path: pathlib.Path,
) -> None:
    """H2: Separate SQLite connections racing APPROVE vs REJECT produce exactly 1 winner and consistent state."""
    inc_id = "inc-h2-conn-race"
    db_path, store1, _, audit1, rm1, dossier = _setup_env(tmp_path, inc_id)
    store2 = WorkflowStateStore(str(db_path))
    sm2 = InvestigationStateMachine(store=store2)
    audit2 = AuditHashChain(log_path=tmp_path / f"{inc_id}-audit-conn2.jsonl")
    rm2 = AuthorizedReviewManager(state_machine=sm2, store=store2, audit_chain=audit2)

    barrier = threading.Barrier(2)

    def run_decision(manager: AuthorizedReviewManager, decision: str) -> tuple[str, str]:
        barrier.wait(timeout=10)
        try:
            res = manager.submit_review(
                incident_id=inc_id,
                dossier_dict=copy.deepcopy(dossier),
                reviewer_ref=f"sre_{decision}",
                reviewer_role="L2_SRE",
                decision=decision,
                rationale=f"Concurrent {decision} test across connections.",
            )
            return ("OK", res["review_event"]["decision"])
        except (ReviewStateConflictError, InvalidStateTransitionError, sqlite3.IntegrityError) as exc:
            return ("REJECTED", type(exc).__name__)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run_decision, rm1, "APPROVE")
            f2 = pool.submit(run_decision, rm2, "REJECT")
            r1, r2 = f1.result(), f2.result()

        statuses = [r1[0], r2[0]]
        assert statuses.count("OK") == 1
        assert statuses.count("REJECTED") == 1

        reviews = store1.get_reviews(inc_id)
        assert len(reviews) == 1
        winner = reviews[0]["decision"]
        inc_state = store1.get_incident(inc_id)["current_state"]
        if winner == "approve":
            assert inc_state == "CLOSED"
        else:
            assert winner == "reject"
            assert inc_state == "REJECTED"
    finally:
        store1.close()
        store2.close()


def test_h2_concurrent_correct_separate_connections_no_v2_overwrite(tmp_path: pathlib.Path) -> None:
    """H2: Concurrent CORRECT on v1 creates exactly one v2 without overwriting a winner's revision."""
    inc_id = "inc-h2-corr-race"
    db_path, store1, _, audit1, rm1, dossier = _setup_env(tmp_path, inc_id)
    store2 = WorkflowStateStore(str(db_path))
    sm2 = InvestigationStateMachine(store=store2)
    audit2 = AuditHashChain(log_path=tmp_path / f"{inc_id}-audit-conn2.jsonl")
    rm2 = AuthorizedReviewManager(state_machine=sm2, store=store2, audit_chain=audit2)

    barrier = threading.Barrier(2)

    def run_edit(manager: AuthorizedReviewManager, author: str, stmt: str) -> tuple[str, Any]:
        corr = build_human_correction_payload(dossier, stmt, author, "L2_SRE")
        barrier.wait(timeout=10)
        try:
            res = manager.correct(
                incident_id=inc_id,
                dossier_dict=copy.deepcopy(dossier),
                reviewer_ref=author,
                reviewer_role="L2_SRE",
                rationale=f"Concurrent correction by {author}.",
                corrections=corr,
            )
            return ("OK", res["new_dossier_revision"]["hypotheses"][0]["statement"])
        except (StaleDossierVersionError, ReviewStateConflictError, sqlite3.IntegrityError) as exc:
            return ("REJECTED", type(exc).__name__)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run_edit, rm1, "sre_alice", "Winner Alice root cause candidate")
            f2 = pool.submit(run_edit, rm2, "sre_bob", "Loser Bob root cause candidate")
            r1, r2 = f1.result(), f2.result()

        assert [r1[0], r2[0]].count("OK") == 1
        assert [r1[0], r2[0]].count("REJECTED") == 1

        winning_stmt = r1[1] if r1[0] == "OK" else r2[1]
        assert store1.get_latest_dossier_version(inc_id) == 2
        v2 = store1.get_dossier(inc_id, version=2)["dossier_json"]
        assert v2["hypotheses"][0]["statement"] == winning_stmt
        assert len(store1.get_reviews(inc_id)) == 1
    finally:
        store1.close()
        store2.close()


def test_h2_escalate_cannot_overwrite_finalized_and_vice_versa(tmp_path: pathlib.Path) -> None:
    """H2: ESCALATE cannot overwrite CLOSED/REJECTED, and CLOSED/REJECTED cannot overwrite ESCALATED."""
    inc_a = "inc-h2-esc-after-app"
    _, store_a, _, _, rm_a, dos_a = _setup_env(tmp_path, inc_a)
    try:
        app_res = rm_a.approve(inc_a, dos_a, "sre_alex", "L2_SRE")
        with pytest.raises(ReviewStateConflictError, match="HUMAN_REVIEW"):
            rm_a.escalate(inc_a, app_res["updated_dossier"], "sre_maya", "L2_SRE", "Late escalate.")
        assert store_a.get_incident(inc_a)["current_state"] == "CLOSED"
        assert len(store_a.get_reviews(inc_a)) == 1
    finally:
        store_a.close()

    inc_b = "inc-h2-app-after-esc"
    _, store_b, _, _, rm_b, dos_b = _setup_env(tmp_path, inc_b)
    try:
        esc_res = rm_b.escalate(inc_b, dos_b, "sre_maya", "L1_SRE", "Escalate to IC.")
        with pytest.raises(ReviewStateConflictError, match="MANUAL_TRIAGE_REQUIRED"):
            rm_b.approve(inc_b, esc_res["updated_dossier"], "sre_alex", "LEAD_SRE")
        assert store_b.get_incident(inc_b)["current_state"] == "MANUAL_TRIAGE_REQUIRED"
        assert len(store_b.get_reviews(inc_b)) == 1
    finally:
        store_b.close()


def test_h2_stale_version_rejected_across_connections(tmp_path: pathlib.Path) -> None:
    """H2: Connection 2 holding cached v1 receives StaleDossierVersionError after Connection 1 spawns v2."""
    inc_id = "inc-h2-stale-conn"
    db_path, store1, _, _, rm1, dossier_v1 = _setup_env(tmp_path, inc_id)
    store2 = WorkflowStateStore(str(db_path))
    rm2 = AuthorizedReviewManager(state_machine=InvestigationStateMachine(store=store2), store=store2)
    try:
        rm1.correct(inc_id, dossier_v1, "sre_alice", "L2_SRE", "Updated hypothesis to v2.")
        with pytest.raises(StaleDossierVersionError) as exc_info:
            rm2.approve(inc_id, copy.deepcopy(dossier_v1), "sre_bob", "LEAD_SRE")
        assert exc_info.value.code == "VERSION_CONFLICT"
        assert store2.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert len(store2.get_reviews(inc_id)) == 1
    finally:
        store1.close()
        store2.close()


def test_h2_db_unique_index_defense_in_depth(tmp_path: pathlib.Path) -> None:
    """H2: Partial unique indexes reject conflicting DB review rows even if AuthorizedReviewManager were bypassed."""
    inc_id = "inc-h2-uidx"
    _, store, _, _, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        rm.approve(inc_id, dossier, "sre_alice", "L2_SRE")
        with pytest.raises(sqlite3.IntegrityError):
            store.record_review(
                {
                    "review_event_id": "rev-bypass-conflict-1",
                    "incident_id": inc_id,
                    "target_dossier_version": 1,
                    "target_dossier_hash": dossier["dossier_hash"],
                    "reviewer_ref": "sre_bob",
                    "reviewer_role": "L2_SRE_REVIEWER",
                    "reviewed_at": "2026-11-23T12:00:00Z",
                    "decision": "reject",
                    "rationale": "Bypassed conflict attempt.",
                    "edited_dossier_version": None,
                    "escalation_target": None,
                    "auto_action_triggered": False,
                }
            )
    finally:
        store.close()


def test_h2_cross_process_conflicting_approve_reject(tmp_path: pathlib.Path) -> None:
    """H2: Separate OS processes racing APPROVE vs REJECT on the same SQLite DB produce 1 winner & 1 rejection."""
    inc_id = "inc-h2-mp-final"
    db_path, store, _, _, _, dossier = _setup_env(tmp_path, inc_id)
    store.close()

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    q: Any = ctx.Queue()
    p1 = ctx.Process(
        target=_mp_review_worker,
        args=(str(db_path), str(tmp_path / "mp1-audit.jsonl"), inc_id, dossier, "APPROVE", "sre_proc_one", barrier, q),
    )
    p2 = ctx.Process(
        target=_mp_review_worker,
        args=(str(db_path), str(tmp_path / "mp2-audit.jsonl"), inc_id, dossier, "REJECT", "sre_proc_two", barrier, q),
    )
    p1.start()
    p2.start()
    p1.join(timeout=20)
    p2.join(timeout=20)
    assert p1.exitcode == 0 and p2.exitcode == 0

    results = [q.get(timeout=5), q.get(timeout=5)]
    outcomes = [r[0] for r in results]
    assert outcomes.count("OK") == 1
    assert outcomes.count("REJECTED") == 1

    verify_store = WorkflowStateStore(str(db_path))
    try:
        reviews = verify_store.get_reviews(inc_id)
        assert len(reviews) == 1
        assert verify_store.get_incident(inc_id)["current_state"] in {"CLOSED", "REJECTED"}
    finally:
        verify_store.close()


def test_h2_cross_process_concurrent_correct(tmp_path: pathlib.Path) -> None:
    """H2: Separate OS processes racing CORRECT on v1 create exactly one v2 cleanly."""
    inc_id = "inc-h2-mp-edit"
    db_path, store, _, _, _, dossier = _setup_env(tmp_path, inc_id)
    store.close()

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    q: Any = ctx.Queue()
    p1 = ctx.Process(
        target=_mp_review_worker,
        args=(str(db_path), str(tmp_path / "mp-e1-audit.jsonl"), inc_id, dossier, "CORRECT", "sre_proc_one", barrier, q),
    )
    p2 = ctx.Process(
        target=_mp_review_worker,
        args=(str(db_path), str(tmp_path / "mp-e2-audit.jsonl"), inc_id, dossier, "CORRECT", "sre_proc_two", barrier, q),
    )
    p1.start()
    p2.start()
    p1.join(timeout=20)
    p2.join(timeout=20)
    assert p1.exitcode == 0 and p2.exitcode == 0

    results = [q.get(timeout=5), q.get(timeout=5)]
    outcomes = [r[0] for r in results]
    assert outcomes.count("OK") == 1
    assert outcomes.count("REJECTED") == 1

    verify_store = WorkflowStateStore(str(db_path))
    try:
        assert verify_store.get_latest_dossier_version(inc_id) == 2
        assert len(verify_store.get_reviews(inc_id)) == 1
    finally:
        verify_store.close()


# ==============================================================================
# WORK PACKAGE H3 — REVIEWER IDENTITY & AUTHORIZATION
# ==============================================================================


def test_h3_authorized_human_reviewer_poc_unauthenticated_disclosure(tmp_path: pathlib.Path) -> None:
    """H3: Default PoC review discloses that local reviewer_ref is unauthenticated caller-asserted identity."""
    inc_id = "inc-h3-poc-auth"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        auth_ctx = res["authorization_context"]
        assert auth_ctx["identity_mode"] == "POC_CALLER_ASSERTED_UNAUTHENTICATED"
        assert auth_ctx["human_identity_authenticated"] is False
        assert auth_ctx["principal_context_verified"] is False
        assert auth_ctx["directory_role_verified"] is False
        assert auth_ctx["claimed_reviewer_ref"] == "sre_lead_alex"
        assert "not SSO/OIDC-authenticated" in auth_ctx["trust_boundary_note"]
        assert res["approval_semantics"]["authorization_context"] == auth_ctx
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


def test_h3_authorized_human_reviewer_with_directory_and_scoped_principal(tmp_path: pathlib.Path) -> None:
    """H3: Scoped principal_reviewer token + directory allowlist bind authorization without false auth claims."""
    inc_id = "inc-h3-dir-auth"
    _, store, _, _, rm, dossier = _setup_env(
        tmp_path,
        inc_id,
        reviewer_directory={"sre_lead_alex": {"L2_SRE"}},
        require_registered_reviewer=True,
        require_authenticated_context=True,
    )
    auth_ctx = Authenticator().authenticate("sre-sim-reviewer-token-secret-2026", incident_id=inc_id)
    try:
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE", auth_context=auth_ctx)
        meta = res["authorization_context"]
        assert meta["identity_mode"] == "SCOPED_PRINCIPAL_CONTEXT_WITH_LOCAL_REF"
        assert meta["principal_context_verified"] is True
        assert meta["directory_role_verified"] is True
        assert meta["principal_actor_ref"] == "principal_reviewer"
        assert meta["human_identity_authenticated"] is False  # Never claim human SSO authentication in PoC
    finally:
        store.close()


def test_h3_unknown_reviewer_rejected_when_directory_configured(tmp_path: pathlib.Path) -> None:
    """H3: Unknown reviewer rejected before DB write when directory or strict registration is enabled."""
    inc_id = "inc-h3-unknown"
    _, store, _, audit, rm, dossier = _setup_env(
        tmp_path,
        inc_id,
        reviewer_directory={"sre_lead_alex": {"L2_SRE"}},
    )
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(inc_id, dossier, "unregistered_operator", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
        assert audit.events[-1]["reason_code"] == "FORBIDDEN_SCOPE"
    finally:
        store.close()

    # Empty directory + require_registered_reviewer=True must fail closed
    inc_strict = "inc-h3-nodir"
    _, store_s, _, _, rm_s, dos_s = _setup_env(tmp_path, inc_strict, require_registered_reviewer=True)
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm_s.approve(inc_strict, dos_s, "sre_lead_alex", "L2_SRE")
        assert store_s.get_reviews(inc_strict) == []
    finally:
        store_s.close()


@pytest.mark.parametrize("bad_role", ["GUEST", "ADMIN", "SUPERUSER", "", None, 123])
def test_h3_invalid_roles_rejected_and_audited(tmp_path: pathlib.Path, bad_role: Any) -> None:
    """H3: Invalid or unrecognized reviewer roles are denied and audited without state mutation."""
    inc_id = "inc-h3-bad-role"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(inc_id, dossier, "sre_lead_alex", bad_role)
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
        assert audit.events[-1]["reason_code"] == "FORBIDDEN_SCOPE"
    finally:
        store.close()


@pytest.mark.parametrize(
    "non_human_actor",
    [
        "principal_investigator",
        "principal:investigator-coord",
        "CMP-INV-01",
        "ai_agent_01",
        "sre_bot",
        "copilot_sre",
        "autonomous_helper",
        "daemon_worker",
        "anonymous_user",
        "principal_reviewer",
    ],
)
def test_h3_ai_and_system_identities_rejected(tmp_path: pathlib.Path, non_human_actor: str) -> None:
    """H3: AI/system/service principal identities cannot submit human review decisions."""
    inc_id = "inc-h3-ai-id"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(inc_id, dossier, non_human_actor, "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"

        # Non-reviewer scoped principal context (e.g. principal_investigator) masquerading as human reviewer
        inv_ctx = Authenticator().authenticate("sre-sim-coord-token-secret-2026", incident_id=inc_id)
        with pytest.raises(UnauthorizedReviewerError, match="Scoped principal"):
            rm.approve(inc_id, dossier, "sre_alice", "L2_SRE", auth_context=inv_ctx)
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
    finally:
        store.close()


def test_h3_caller_supplied_privileged_role_and_edit_field_escalation_rejected(
    tmp_path: pathlib.Path,
) -> None:
    """H3: Privilege escalation via higher claimed role or edited_dossier_data control fields is blocked."""
    inc_id = "inc-h3-privesc"
    _, store, _, audit, rm, dossier = _setup_env(
        tmp_path,
        inc_id,
        reviewer_directory={"sre_l1_bob": {"L1_SRE"}},
    )
    try:
        # 1. L1 operator claiming LEAD_SRE
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(inc_id, dossier, "sre_l1_bob", "LEAD_SRE")
        assert audit.events[-1]["result_code"] == "DENY"

        # 2. Override privilege/control fields in edited_dossier_data
        for bad_payload in (
            {"reviewer_role": "LEAD_SRE"},
            {"is_admin": True},
            {"approval_semantics": {"diagnosis_verified": True}},
            {"auto_action_triggered": True},
            {"current_state": "CLOSED"},
        ):
            with pytest.raises(UnauthorizedReviewerError):
                rm.correct(
                    inc_id,
                    dossier,
                    "sre_l1_bob",
                    "L1_SRE",
                    "Attempting privilege override via edit.",
                    corrections=bad_payload,
                )
            assert audit.events[-1]["result_code"] == "DENY"

        # 3. Override auto_execution_allowed in edited recommended_checks
        with pytest.raises(InvalidDossierError, match="INV-01"):
            rm.correct(
                inc_id,
                dossier,
                "sre_l1_bob",
                "L1_SRE",
                "Attempting check auto-exec override.",
                corrections={
                    "recommended_checks": [
                        {
                            "check_id": "chk-evil",
                            "description": "Auto restart service.",
                            "risk_level": "high",
                            "requires_human_approval": False,
                            "auto_execution_allowed": True,
                        }
                    ]
                },
            )
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_latest_dossier_version(inc_id) == 1
    finally:
        store.close()


@pytest.mark.parametrize(
    "malformed_ref",
    ["", "   ", "ab", "sre\nalice", "sre\x00admin", "../etc/passwd", "sre; DROP", "123sre", "a" * 200, 12345, {"admin": True}],
)
def test_h3_malformed_reviewer_ref_rejected_before_persistence(tmp_path: pathlib.Path, malformed_ref: Any) -> None:
    """H3: Malformed, control-char, path-like, or non-string reviewer_ref fails before persistence."""
    inc_id = "inc-h3-malformed"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    try:
        with pytest.raises(UnauthorizedReviewerError):
            rm.approve(inc_id, dossier, malformed_ref, "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert audit.events[-1]["result_code"] == "DENY"
        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs
    finally:
        store.close()


# ==============================================================================
# WORK PACKAGE H4 — AUDIT / DB CONSISTENCY
# ==============================================================================


def test_h4_audit_failure_before_db_commit_rolls_back_sqlite(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: Audit sink failure on 1st write rolls back staged SQLite review, dossier, and state transition."""
    inc_id = "inc-h4-aud-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_record_event = audit.record_event

    def fail_audit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AuditWriteError("FAIL_CLOSED: Simulated audit write failure")

    monkeypatch.setattr(audit, "record_event", fail_audit)
    try:
        with pytest.raises(AuditWriteError):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_dossier(inc_id, version=1)["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"
        assert audit.events == []
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True

        # Retry succeeds once audit sink recovers
        monkeypatch.setattr(audit, "record_event", orig_record_event)
        rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
    finally:
        store.close()


def test_h4_db_write_failure_emits_zero_phantom_allow_audit(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: DB failure during staging occurs BEFORE audit ALLOW writes -> zero phantom ALLOW audit events."""
    inc_id = "inc-h4-db-fail-no-phantom"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    monkeypatch.setattr(
        store,
        "record_review",
        lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("disk error")),
    )
    try:
        with pytest.raises(sqlite3.OperationalError, match="disk error"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert [e for e in audit.events if e.get("result_code") == "ALLOW"] == []
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
    finally:
        store.close()


def test_h4_second_audit_write_failure_rolls_back_db_and_compensates(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: Failure on 2nd audit write (WORKFLOW_TRANSITION) rolls back SQLite and appends compensating ERROR."""
    inc_id = "inc-h4-aud2-fail"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    eval_dirs = _prepare_dev_eval_dirs(tmp_path, inc_id, "run-h4-aud2")
    orig_record_event = audit.record_event

    def fail_on_closure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action") or (args[1] if len(args) > 1 else None)
        if action == "WORKFLOW_TRANSITION":
            raise AuditWriteError("FAIL_CLOSED: Simulated closure audit failure")
        return orig_record_event(*args, **kwargs)

    monkeypatch.setattr(audit, "record_event", fail_on_closure)
    try:
        with pytest.raises(AuditWriteError, match="closure audit failure"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        # DB rolled back completely
        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert store.get_dossier(inc_id, version=1)["dossier_json"]["review_summary"]["status"] == "PENDING_REVIEW"

        # Historical ALLOW event was NOT deleted/rewritten; compensating ERROR event appended
        assert len(audit.events) == 2
        assert audit.events[0]["action"] == "HUMAN_REVIEW_DECISION"
        assert audit.events[0]["result_code"] == "ALLOW"
        assert audit.events[1]["action"] == "HUMAN_REVIEW_DECISION"
        assert audit.events[1]["result_code"] == "ERROR"
        assert audit.events[0]["audit_event_id"] in audit.events[1]["evidence_refs"]

        ok, errs = verify_chain_integrity(list(audit.events))
        assert ok, errs

        rec = reconcile_review_audit(store, list(audit.events), inc_id)
        assert rec["consistent"] is True
        assert rec["unreconciled_orphans"] == []
        assert len(rec["compensated_rollbacks"]) == 1

        # Evaluator strictly blocked
        with pytest.raises(EvaluationBlocked, match="PREMATURE_EVALUATION_BLOCKED"):
            join_dev(
                store=store,
                audit_events=list(audit.events),
                trusted_audit_head=audit.last_event_hash,
                incident_id=inc_id,
                run_id="run-h4-aud2",
                **eval_dirs,
            )

        # Clear fault and retry cleanly
        monkeypatch.setattr(audit, "record_event", orig_record_event)
        rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
        assert join_dev(
            store=store,
            audit_events=list(audit.events),
            trusted_audit_head=audit.last_event_hash,
            incident_id=inc_id,
            run_id="run-h4-aud2",
            **eval_dirs,
        ).exists()
    finally:
        store.close()


def test_h4_commit_failure_after_audit_appends_compensating_error_and_allows_clean_retry(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: Failure at SQLite COMMIT after audit writes appends compensating ERROR, preserves chain, and allows retry."""
    inc_id = "inc-h4-post-aud-commit"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_commit = store._commit
    monkeypatch.setattr(
        store,
        "_commit",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("commit I/O error")),
    )
    try:
        with pytest.raises(sqlite3.OperationalError, match="commit I/O error"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        assert store.get_incident(inc_id)["current_state"] == "HUMAN_REVIEW"
        assert store.get_reviews(inc_id) == []
        assert len(audit.events) == 3  # ALLOW decision + ALLOW closure + compensating ERROR
        assert audit.events[-1]["result_code"] == "ERROR"
        assert verify_chain_integrity(list(audit.events))[0] is True

        rec = reconcile_review_audit(store, list(audit.events), inc_id)
        assert rec["consistent"] is True
        assert len(rec["compensated_rollbacks"]) == 2
        assert rec["unreconciled_orphans"] == []

        # Retry succeeds
        monkeypatch.setattr(store, "_commit", orig_commit)
        rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert len(store.get_reviews(inc_id)) == 1
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
    finally:
        store.close()


def test_h4_interrupted_crash_orphan_and_unaudited_db_detected_by_reconcile(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: Uncompensated crash gap between audit and DB (or DB without audit) is explicitly surfaced."""
    # Case 1: Crash before compensating audit can be written -> orphaned ALLOW audit vs uncommitted DB
    inc_id = "inc-h4-crash-orphan"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    eval_dirs = _prepare_dev_eval_dirs(tmp_path, inc_id, "run-h4-orphan")
    monkeypatch.setattr(
        store,
        "_commit",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("hard commit fail")),
    )
    monkeypatch.setattr(rm, "_record_compensating_audit", lambda **kw: None)
    try:
        with pytest.raises(sqlite3.OperationalError, match="hard commit fail"):
            rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")

        rec = reconcile_review_audit(store, list(audit.events), inc_id)
        assert rec["consistent"] is False
        assert len(rec["unreconciled_orphans"]) == 2  # Both HUMAN_REVIEW_DECISION and WORKFLOW_TRANSITION orphaned
        with pytest.raises(EvaluationBlocked, match="PREMATURE_EVALUATION_BLOCKED"):
            join_dev(
                store=store,
                audit_events=list(audit.events),
                trusted_audit_head=audit.last_event_hash,
                incident_id=inc_id,
                run_id="run-h4-orphan",
                **eval_dirs,
            )
    finally:
        store.close()

    # Case 2: Unaudited DB review detected explicitly
    inc_noaud = "inc-h4-unaudited-db"
    _, store_u, _, audit_u, _, dos_u = _setup_env(tmp_path, inc_noaud)
    try:
        store_u.record_review(
            {
                "review_event_id": "rev-unaudited-1",
                "incident_id": inc_noaud,
                "target_dossier_version": 1,
                "target_dossier_hash": dos_u["dossier_hash"],
                "reviewer_ref": "sre_alex",
                "reviewer_role": "L2_SRE_REVIEWER",
                "reviewed_at": "2026-11-23T12:00:00Z",
                "decision": "approve",
                "rationale": "Direct DB write skipping audit.",
                "edited_dossier_version": None,
                "escalation_target": None,
                "auto_action_triggered": False,
            }
        )
        rec_u = reconcile_review_audit(store_u, list(audit_u.events), inc_noaud)
        assert rec_u["consistent"] is False
        assert len(rec_u["unaudited_db_reviews"]) == 1
        assert rec_u["unaudited_db_reviews"][0]["review_event_id"] == "rev-unaudited-1"
    finally:
        store_u.close()


def test_h4_repeated_submission_after_incomplete_processing_no_contradictory_finalization(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: After incomplete processing, repeated submission produces at most one finalized decision."""
    inc_id = "inc-h4-retry-idemp"
    _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
    orig_commit = store._commit
    monkeypatch.setattr(
        store,
        "_commit",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("transient commit drop")),
    )
    try:
        with pytest.raises(sqlite3.OperationalError):
            rm.approve(inc_id, dossier, "sre_alex", "L2_SRE")

        monkeypatch.setattr(store, "_commit", orig_commit)
        res = rm.approve(inc_id, dossier, "sre_alex", "L2_SRE")
        assert res["updated_dossier"]["review_summary"]["status"] == "APPROVED"

        with pytest.raises(ReviewStateConflictError):
            rm.reject(inc_id, dossier, "sre_bob", "L2_SRE", "Contradictory late reject.")
        assert len(store.get_reviews(inc_id)) == 1
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert reconcile_review_audit(store, list(audit.events), inc_id)["consistent"] is True
    finally:
        store.close()


def test_h4_audit_chain_cross_process_flock_prevents_interleaving(tmp_path: pathlib.Path) -> None:
    """H4: Cross-process writers sharing a JSONL log serialize under fcntl.flock without chain corruption."""
    audit_path = tmp_path / "shared-audit.jsonl"
    bootstrap = AuditHashChain(log_path=audit_path)
    bootstrap.record_event(
        actor_ref="principal_reviewer",
        action="HUMAN_REVIEW_DECISION",
        target_ref="inc-h4-flock-seed:v1",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-h4-flock-seed",
    )
    assert audit_path.with_name(f"{audit_path.name}.lock").exists()

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    q: Any = ctx.Queue()
    p1 = ctx.Process(target=_mp_audit_worker, args=(str(audit_path), "p1", barrier, q))
    p2 = ctx.Process(target=_mp_audit_worker, args=(str(audit_path), "p2", barrier, q))
    p1.start()
    p2.start()
    p1.join(timeout=20)
    p2.join(timeout=20)
    assert p1.exitcode == 0 and p2.exitcode == 0

    results = [q.get(timeout=5), q.get(timeout=5)]
    statuses = [r[0] for r in results]
    # Single-writer continuity: 1 writer appends cleanly under flock, 2nd detects external append & fails closed
    assert statuses.count("OK") == 1
    assert statuses.count("ERROR") == 1

    reloaded = AuditHashChain(log_path=audit_path)
    assert len(reloaded.events) == 2
    ok, errs = verify_chain_integrity(list(reloaded.events))
    assert ok, errs


# ==============================================================================
# WORK PACKAGE H5 — CLOSURE SEMANTICS & EVALUATOR
# ==============================================================================


@pytest.mark.parametrize("diag_status", ["PARTIAL", "INCONCLUSIVE", "UNSUPPORTED", "CONTRADICTED"])
def test_h5_approved_unconfirmed_and_missing_sop_closure_semantics(
    tmp_path: pathlib.Path,
    diag_status: str,
) -> None:
    """H5: APPROVE with unconfirmed diagnosis & missing SOP yields administrative handover closure only."""
    inc_id = f"inc-h5-{diag_status.lower()}"
    _, store, _, audit, rm, dossier = _setup_env(
        tmp_path,
        inc_id,
        support_status=diag_status if diag_status in ("PARTIAL", "INCONCLUSIVE") else "INCONCLUSIVE",
        validation_status=diag_status,
        with_sop=False,
    )
    try:
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        sem = res["approval_semantics"]
        assert res["updated_dossier"]["review_summary"]["status"] == "APPROVED"
        assert store.get_incident(inc_id)["current_state"] == "CLOSED"
        assert sem["dossier_review_status"] == "APPROVED"
        assert sem["dossier_accepted_for_handover"] is True
        assert sem["closure_meaning"] == "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED"
        assert sem["diagnosis_verified"] is False
        assert sem["root_cause_proven"] is False
        assert sem["technical_incident_resolved"] is False
        assert sem["remediation_authorized"] is False
        assert sem["sop_compliance_confirmed"] is False
        assert sem["auto_action_triggered"] is False
        assert sem["has_applicable_runbook"] is False
        assert "NO_APPLICABLE_RUNBOOK" in sem["missing_source_codes"]
        assert "VERIFIED" not in json.dumps(res["updated_dossier"]["hypotheses"]).upper()
    finally:
        store.close()


def test_h5_closed_never_upgrades_validation_or_authorizes_remediation(tmp_path: pathlib.Path) -> None:
    """H5: CLOSED never mutates hypothesis validation status, unknowns, or recommended_checks guardrails."""
    inc_id = "inc-h5-no-upgrade"
    _, store, _, _, rm, dossier = _setup_env(
        tmp_path, inc_id, support_status="PARTIAL", validation_status="UNSUPPORTED", with_sop=False
    )
    orig_hyps = copy.deepcopy(dossier["hypotheses"])
    orig_unknowns = copy.deepcopy(dossier["unknowns"])
    try:
        res = rm.approve(inc_id, dossier, "sre_lead_alex", "L2_SRE")
        closed_d = res["updated_dossier"]
        assert closed_d["hypotheses"] == orig_hyps
        assert closed_d["unknowns"] == orig_unknowns
        assert store.get_checkpoint(inc_id)["context"]["validation_reports"][0]["status"] == "UNSUPPORTED"
        assert all(c["auto_execution_allowed"] is False for c in closed_d["recommended_checks"])
        assert all(c["requires_human_approval"] is True for c in closed_d["recommended_checks"])
    finally:
        store.close()


def test_h5_evaluator_eligibility_follows_closure_contract(tmp_path: pathlib.Path) -> None:
    """H5: Offline Evaluator join unlocks ONLY on CLOSED with bound audit event; blocked on non-CLOSED."""
    # Non-CLOSED decisions remain blocked
    for state_case in ("HUMAN_REVIEW", "REJECT", "ESCALATE"):
        inc_id = f"inc-h5-eval-{state_case.lower().replace('_', '-')}"
        run_id = f"run-{state_case.lower().replace('_', '-')}"
        _, store, _, audit, rm, dossier = _setup_env(tmp_path, inc_id)
        eval_dirs = _prepare_dev_eval_dirs(tmp_path, inc_id, run_id)
        try:
            if state_case == "REJECT":
                rm.reject(inc_id, dossier, "sre_alex", "L2_SRE", "Insufficient evidence.")
            elif state_case == "ESCALATE":
                rm.escalate(inc_id, dossier, "sre_alex", "L1_SRE", "Needs L2 commander.")
            with pytest.raises(EvaluationBlocked, match="PREMATURE_EVALUATION_BLOCKED"):
                join_dev(
                    store=store,
                    audit_events=list(audit.events),
                    trusted_audit_head=audit.last_event_hash or ("0" * 64),
                    incident_id=inc_id,
                    run_id=run_id,
                    **eval_dirs,
                )
        finally:
            store.close()

    # Administrative CLOSED unlocks evaluator even when diagnosis is PARTIAL and SOP is missing
    inc_ok = "inc-h5-eval-closed"
    _, store_ok, _, audit_ok, rm_ok, dos_ok = _setup_env(tmp_path, inc_ok, support_status="PARTIAL", with_sop=False)
    eval_dirs_ok = _prepare_dev_eval_dirs(tmp_path, inc_ok, "run-h5-ok")
    try:
        rm_ok.approve(inc_ok, dos_ok, "sre_alex", "LEAD_SRE")
        joined = join_dev(
            store=store_ok,
            audit_events=list(audit_ok.events),
            trusted_audit_head=audit_ok.last_event_hash,
            incident_id=inc_ok,
            run_id="run-h5-ok",
            **eval_dirs_ok,
        )
        assert joined.exists()
        payload = json.loads(joined.read_text(encoding="utf-8"))
        assert payload["dossier"]["hypotheses"][0]["support_status"] == "PARTIAL"
    finally:
        store_ok.close()


def test_h5_reject_and_escalate_never_produce_administrative_closure(tmp_path: pathlib.Path) -> None:
    """H5: REJECT and ESCALATE neither set APPROVED/CLOSED nor allow DummyTicketManager ticket creation."""
    inc_r = "inc-h5-rej-sem"
    _, store_r, _, _, rm_r, dos_r = _setup_env(tmp_path, inc_r)
    try:
        res_r = rm_r.reject(inc_r, dos_r, "sre_alex", "L2_SRE", "Contradicted telemetry.")
        sem_r = res_r["approval_semantics"]
        assert sem_r["dossier_accepted_for_handover"] is False
        assert sem_r["closure_meaning"] == "DOSSIER_REJECTED"
        assert sem_r["resulting_lifecycle_state"] == "REJECTED"
        with pytest.raises(InvalidDossierStateError):
            DummyTicketManager().create_ticket_from_dossier(res_r["updated_dossier"])
    finally:
        store_r.close()

    inc_e = "inc-h5-esc-sem"
    _, store_e, _, _, rm_e, dos_e = _setup_env(tmp_path, inc_e)
    try:
        res_e = rm_e.escalate(inc_e, dos_e, "sre_alex", "L1_SRE", "Escalated for triage.")
        sem_e = res_e["approval_semantics"]
        assert sem_e["dossier_accepted_for_handover"] is False
        assert sem_e["closure_meaning"] == "ESCALATED_FOR_MANUAL_TRIAGE"
        assert sem_e["resulting_lifecycle_state"] == "MANUAL_TRIAGE_REQUIRED"
        with pytest.raises(InvalidDossierStateError):
            DummyTicketManager().create_ticket_from_dossier(res_e["updated_dossier"])
    finally:
        store_e.close()


def test_h5_handover_ticket_cli_and_dashboard_preserve_uncertainty_and_closure_meaning(
    tmp_path: pathlib.Path,
) -> None:
    """H5: Handover (JSON/MD/HTML), DummyTicketManager, CLI, and TUI all retain uncertainty and non-verification."""
    inc_id = "inc-h5-downstream"
    _, store, _, audit, rm, dossier = _setup_env(
        tmp_path, inc_id, support_status="PARTIAL", with_sop=False
    )
    try:
        cli_res = run_review_action(
            dossier,
            "APPROVE",
            reviewer_ref="sre_lead_alex",
            reviewer_role="L2_SRE",
            rationale="Accepting partial handover dossier for human follow-up.",
            store=store,
            review_manager=rm,
            audit_chain=audit,
            handover_root=tmp_path / "handover",
            ticket_storage_path=tmp_path / "tickets.json",
        )
        approved = cli_res["review_result"]["updated_dossier"]
        ticket = cli_res["artifacts"]["ticket"]
        assert ticket["closure_meaning"] == "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED"
        assert ticket["diagnosis_verified"] is False
        assert ticket["root_cause_proven"] is False
        assert ticket["technical_incident_resolved"] is False
        assert ticket["remediation_authorized"] is False
        assert ticket["sop_compliance_confirmed"] is False
        assert ticket["has_applicable_sop"] is False
        assert "NO_APPLICABLE_RUNBOOK" in ticket["missing_source_codes"]
        assert len(ticket["unknowns"]) >= 1

        md_text = pathlib.Path(cli_res["artifacts"]["handover_export"]["markdown"]).read_text(encoding="utf-8")
        html_text = pathlib.Path(cli_res["artifacts"]["handover_export"]["html"]).read_text(encoding="utf-8")
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in md_text
        assert "Technical Incident Resolved:** `false`" in md_text
        assert "SOP Compliance Confirmed:** `false`" in md_text
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in html_text
        assert "NO_APPLICABLE_RUNBOOK" in html_text
        assert "Technical Incident Resolved: <code>false</code>" in html_text

        # CLI summary output
        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            display_dossier_summary(approved)
        cli_stdout = buf.getvalue()
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in cli_stdout
        assert "Local PoC caller-asserted identifier (unauthenticated)" in cli_stdout

        # Dashboard detail & locked action bar when CLOSED
        console = Console(record=True, width=120, force_terminal=False, color_system=None)
        dash = SREDashboard(
            store,
            console=console,
            audit_path=tmp_path / "dash-audit.jsonl",
            handover_root=tmp_path / "dash-handover",
        )
        dash.selected_incident_id = inc_id
        console.print(dash.render(width=120))
        rendered = " ".join(console.export_text().replace("│", " ").split())
        assert "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED" in rendered
        assert "Local PoC caller-asserted identity (unauthenticated)" in rendered
        assert "REVIEW LOCKED - FINALIZED" in rendered
    finally:
        store.close()
