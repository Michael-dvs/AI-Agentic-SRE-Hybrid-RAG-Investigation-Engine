"""Delayed join tests using synthetic, per-run records."""
import copy
import json
import os

import pytest

from evaluator.runner import EvaluationBlocked, _closure_payload, join_dev, join_evaluator
from observability.audit_chain import AuditHashChain
from orchestrator.dossier import compute_canonical_dossier_hash
from orchestrator.state_machine import WorkflowStateStore


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "dev"
    output = tmp_path / "eval"
    runtime = tmp_path / "runtime"
    for path in (source, output, runtime):
        path.mkdir(mode=0o700)
    store = WorkflowStateStore(":memory:")
    store.create_incident("inc-test", initial_state="CLOSED", status="CLOSED")
    dossier = {"incident_id": "inc-test", "dossier_version": 1, "hypotheses": []}
    dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)
    store.save_dossier("inc-test", 1, dossier["dossier_hash"], dossier, "")
    chain = AuditHashChain()
    chain.record_event(actor_ref="principal_reviewer", action="WORKFLOW_TRANSITION",
                       target_ref="inc-test:v1", result_code="ALLOW", reason_code="OK",
                       request_payload=_closure_payload("inc-test", 1, dossier["dossier_hash"]))
    path = source / "run-test.json"
    path.write_text(json.dumps({"run_id": "run-test", "incident_id": "inc-test",
                                "split_id": "dev", "label": "synthetic"}))
    path.chmod(0o600)
    args = dict(store=store, audit_events=chain.events, trusted_audit_head=chain.last_event_hash,
                incident_id="inc-test", run_id="run-test", dev_source_dir=source,
                output_dir=output, runtime_dir=runtime)
    yield args
    store.close()


def test_join_writes_private_evaluator_artifact(setup):
    path = join_dev(**setup)
    result = json.loads(path.read_text())
    assert result["ground_truth"]["label"] == "synthetic"
    assert result["dossier"]["incident_id"] == "inc-test"
    assert path.stat().st_mode & 0o077 == 0
    assert list(setup["runtime_dir"].iterdir()) == []
    with pytest.raises(FileExistsError):
        join_dev(**setup)


@pytest.mark.parametrize("state", ["HYPOTHESES", "HUMAN_REVIEW", "FAILED_SAFE"])
def test_open_or_failed_cannot_touch_source(setup, state):
    setup["store"].update_incident_state("inc-test", state, "ACTIVE")
    setup["dev_source_dir"] = setup["dev_source_dir"] / "missing"
    with pytest.raises(EvaluationBlocked, match="PREMATURE"):
        join_dev(**setup)


def test_closed_without_bound_event_is_blocked_before_source_read(setup):
    chain = AuditHashChain()
    review_event = {
        "schema_version": "1.0", "review_event_id": "rev-test",
        "incident_id": "inc-test", "target_dossier_version": 1,
        "target_dossier_hash": "0" * 64, "reviewer_ref": "reviewer",
        "reviewer_role": "PROJECT_OWNER_LAB", "reviewed_at": "2026-01-01T00:00:00Z",
        "decision": "approve", "rationale": "Approved", "edited_dossier_version": None,
        "escalation_target": None, "auto_action_triggered": False,
    }
    chain.record_event(actor_ref="principal_reviewer", action="HUMAN_REVIEW_DECISION",
                       target_ref="inc-test:v1", result_code="ALLOW", reason_code="OK",
                       request_payload=review_event)
    setup.update(audit_events=chain.events, trusted_audit_head=chain.last_event_hash,
                 dev_source_dir=setup["dev_source_dir"] / "missing")
    with pytest.raises(EvaluationBlocked, match="closure audit"):
        join_dev(**setup)


@pytest.mark.parametrize("change", ["tamper", "wrong_head", "wrong_payload", "wrong_target"])
def test_untrusted_or_mismatched_audit_blocks_source(setup, change):
    if change == "wrong_head":
        setup["trusted_audit_head"] = "a" * 64
    elif change == "tamper":
        setup["audit_events"] = copy.deepcopy(setup["audit_events"])
        setup["audit_events"][0]["target_ref"] = "inc-other:v1"
    else:
        chain = AuditHashChain()
        dossier = setup["store"].get_dossier("inc-test")["dossier_json"]
        payload = _closure_payload("inc-test", 1, dossier["dossier_hash"])
        if change == "wrong_payload":
            payload["dossier_hash"] = "a" * 64
        chain.record_event(actor_ref="principal_reviewer", action="WORKFLOW_TRANSITION",
                           target_ref="inc-other:v1" if change == "wrong_target" else "inc-test:v1",
                           result_code="ALLOW", reason_code="OK", request_payload=payload)
        setup.update(audit_events=chain.events, trusted_audit_head=chain.last_event_hash)
    setup["dev_source_dir"] = setup["dev_source_dir"] / "missing"
    with pytest.raises(EvaluationBlocked):
        join_dev(**setup)


def test_dossier_tampering_blocked_before_source_read(setup):
    store = setup["store"]
    dossier = store.get_dossier("inc-test")["dossier_json"]
    dossier["hypotheses"] = [{"fabricated": True}]
    store.save_dossier("inc-test", 1, dossier["dossier_hash"], dossier, "")
    setup["dev_source_dir"] = setup["dev_source_dir"] / "missing"
    with pytest.raises(EvaluationBlocked, match="integrity"):
        join_dev(**setup)


def test_rejects_other_split_and_mismatched_identity(setup):
    path = setup["dev_source_dir"] / "run-test.json"
    for change in ({"split_id": "other"}, {"incident_id": "inc-other"}):
        record = {"run_id": "run-test", "incident_id": "inc-test", "split_id": "dev"}
        record.update(change)
        path.write_text(json.dumps(record))
        with pytest.raises(EvaluationBlocked, match="matching DEV"):
            join_dev(**setup)
    assert list(setup["output_dir"].iterdir()) == []


def test_isolation_rejects_runtime_paths_and_unsafe_sources(setup, tmp_path):
    with pytest.raises(EvaluationBlocked, match="disjoint"):
        join_dev(**{**setup, "output_dir": setup["runtime_dir"]})
    source = setup["dev_source_dir"] / "run-test.json"
    source.chmod(0o644)
    with pytest.raises(EvaluationBlocked, match="owner-only"):
        join_dev(**setup)
    source.chmod(0o600)
    hardlink = tmp_path / "link"
    os.link(source, hardlink)
    with pytest.raises(EvaluationBlocked, match="owner-only"):
        join_dev(**setup)
    hardlink.unlink()
    source.unlink()
    source.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        join_dev(**setup)


def _join_args(setup, split_id):
    args = dict(setup)
    args["source_dir"] = args.pop("dev_source_dir")
    args["split_id"] = split_id
    return args


def test_hg3_join_uses_matching_dedicated_record(setup):
    path = setup["dev_source_dir"] / "run-test.json"
    record = json.loads(path.read_text())
    record["split_id"] = "H-G3"
    path.write_text(json.dumps(record))
    result = join_evaluator(**_join_args(setup, "H-G3"))
    assert json.loads(result.read_text())["ground_truth"] == record
    assert result.stat().st_mode & 0o077 == 0
    assert list(setup["runtime_dir"].iterdir()) == []


@pytest.mark.parametrize("split_id", ["H-G4", "h-g3", "", "other", None])
def test_unsupported_split_blocked_before_source_access(setup, split_id, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source access attempted")

    monkeypatch.setattr("evaluator.runner._private_directory", forbidden)
    message = "H-G4 split remains strictly sealed until C21" if split_id == "H-G4" else "Unsupported evaluation split"
    with pytest.raises(EvaluationBlocked, match=message):
        join_evaluator(**_join_args(setup, split_id))


@pytest.mark.parametrize("source_split", ["dev", "H-G4"])
def test_hg3_rejects_mismatched_record(setup, source_split):
    path = setup["dev_source_dir"] / "run-test.json"
    record = json.loads(path.read_text())
    record["split_id"] = source_split
    path.write_text(json.dumps(record))
    with pytest.raises(EvaluationBlocked, match="matching H-G3"):
        join_evaluator(**_join_args(setup, "H-G3"))
    assert list(setup["output_dir"].iterdir()) == []


def test_hg3_preserves_closure_and_isolation_guards(setup):
    args = _join_args(setup, "H-G3")
    setup["store"].update_incident_state("inc-test", "HUMAN_REVIEW", "ACTIVE")
    args["source_dir"] = args["source_dir"] / "missing"
    with pytest.raises(EvaluationBlocked, match="PREMATURE"):
        join_evaluator(**args)
    setup["store"].update_incident_state("inc-test", "CLOSED", "CLOSED")
    args["source_dir"] = setup["dev_source_dir"]
    args["output_dir"] = setup["runtime_dir"]
    with pytest.raises(EvaluationBlocked, match="disjoint"):
        join_evaluator(**args)


def test_hg3_unanchored_audit_blocks_before_source_access(setup, monkeypatch):
    args = _join_args(setup, "H-G3")
    args["trusted_audit_head"] = "a" * 64

    def forbidden(*args, **kwargs):
        raise AssertionError("source access attempted")

    monkeypatch.setattr("evaluator.runner._private_directory", forbidden)
    with pytest.raises(EvaluationBlocked, match="unanchored"):
        join_evaluator(**args)
