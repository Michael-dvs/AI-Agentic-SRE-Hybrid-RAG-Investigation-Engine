"""C21 authorization and isolation checks using synthetic records only."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from evaluator import runner
from evaluator.runner import EvaluationBlocked, _closure_payload, join_dev, join_evaluator
from observability.audit_chain import AuditHashChain
from orchestrator.dossier import compute_canonical_dossier_hash
from orchestrator.state_machine import WorkflowStateStore


@pytest.fixture
def h4_case(tmp_path):
    source, output, runtime = (tmp_path / name for name in ("source", "output", "runtime"))
    for directory in (source, output, runtime):
        directory.mkdir(mode=0o700)
    record = {"run_id": "run-synthetic", "incident_id": "inc-synthetic",
              "split_id": "H-G4", "label": "synthetic-only"}
    path = source / "run-synthetic.json"
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    store = WorkflowStateStore(":memory:")
    store.create_incident("inc-synthetic", initial_state="CLOSED", status="CLOSED")
    dossier = {"incident_id": "inc-synthetic", "dossier_version": 1, "hypotheses": []}
    dossier["dossier_hash"] = compute_canonical_dossier_hash(dossier)
    store.save_dossier("inc-synthetic", 1, dossier["dossier_hash"], dossier, "")
    chain = AuditHashChain()
    chain.record_event(actor_ref="principal_reviewer", action="WORKFLOW_TRANSITION",
                       target_ref="inc-synthetic:v1", result_code="ALLOW", reason_code="OK",
                       request_payload=_closure_payload("inc-synthetic", 1, dossier["dossier_hash"]))
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps({
        "status": "C21_CANDIDATE_FROZEN_NOT_BENCHMARKED",
        "source_tree": {"files": {"evaluator/runner.py": hashlib.sha256(
            Path(runner.__file__).read_bytes()).hexdigest()}},
    }))
    args = dict(store=store, audit_events=chain.events, trusted_audit_head=chain.last_event_hash,
                incident_id="inc-synthetic", run_id="run-synthetic", split_id="H-G4",
                source_dir=source, output_dir=output, runtime_dir=runtime,
                allow_h_g4=True, c21_release_manifest_path=manifest,
                c21_release_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    yield args
    store.close()


def test_authorized_closed_join_is_private_and_runtime_empty(h4_case):
    result = join_evaluator(**h4_case)
    joined = json.loads(result.read_text())
    assert joined["ground_truth"]["label"] == "synthetic-only"
    assert result.stat().st_mode & 0o777 == 0o600
    assert not list(h4_case["runtime_dir"].iterdir())


def test_default_h4_guard_unchanged(h4_case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source must not be inspected")
    monkeypatch.setattr(runner, "_private_directory", forbidden)
    args = dict(h4_case)
    for key in ("allow_h_g4", "c21_release_manifest_path", "c21_release_manifest_sha256"):
        args.pop(key)
    with pytest.raises(EvaluationBlocked, match="H-G4 split remains strictly sealed until C21"):
        join_evaluator(**args)


@pytest.mark.parametrize("value", ["", "0" * 64, None, "invalid"])
def test_invalid_authorization_rejected_before_source_access(h4_case, monkeypatch, value):
    def forbidden(*args, **kwargs):
        raise AssertionError("source must not be inspected")
    monkeypatch.setattr(runner, "_private_directory", forbidden)
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**{**h4_case, "c21_release_manifest_sha256": value})


def test_changed_manifest_or_runner_hash_blocked(h4_case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source must not be inspected")
    monkeypatch.setattr(runner, "_private_directory", forbidden)
    manifest = h4_case["c21_release_manifest_path"]
    body = json.loads(manifest.read_text())
    body["source_tree"]["files"]["evaluator/runner.py"] = "0" * 64
    manifest.write_text(json.dumps(body))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**{**h4_case, "c21_release_manifest_sha256": digest})


def test_join_dev_rejects_h4_record(h4_case):
    args = {key: h4_case[key] for key in ("store", "audit_events", "trusted_audit_head",
            "incident_id", "run_id", "output_dir", "runtime_dir")}
    args["dev_source_dir"] = h4_case["source_dir"]
    with pytest.raises(EvaluationBlocked, match="matching DEV"):
        join_dev(**args)
    assert not list(h4_case["output_dir"].iterdir())


@pytest.mark.parametrize("split", ["dev", "H-G3"])
def test_h4_rejects_other_split(h4_case, split):
    path = h4_case["source_dir"] / "run-synthetic.json"
    record = json.loads(path.read_text())
    record["split_id"] = split
    path.write_text(json.dumps(record))
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**h4_case)
    assert not list(h4_case["output_dir"].iterdir())


@pytest.mark.parametrize("state,status", [("HUMAN_REVIEW", "ACTIVE"), ("CLOSED", "ACTIVE")])
def test_closure_required_before_source_access(h4_case, state, status):
    h4_case["store"].update_incident_state("inc-synthetic", state, status)
    args = {**h4_case, "source_dir": h4_case["source_dir"] / "missing"}
    with pytest.raises(EvaluationBlocked, match="PREMATURE"):
        join_evaluator(**args)


@pytest.mark.parametrize("kind", ["chain", "head", "dossier"])
def test_audit_and_dossier_required_before_source_access(h4_case, kind):
    args = dict(h4_case)
    args["source_dir"] = args["source_dir"] / "missing"
    if kind == "head":
        args["trusted_audit_head"] = "0" * 64
    elif kind == "chain":
        args["audit_events"] = []
    else:
        saved = args["store"].get_dossier("inc-synthetic")["dossier_json"]
        saved["hypotheses"] = [{"synthetic": True}]
        args["store"].save_dossier("inc-synthetic", 1, saved["dossier_hash"], saved, "")
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**args)


@pytest.mark.parametrize("kind", ["source", "output", "runtime"])
def test_overlapping_directories_blocked(h4_case, kind):
    args = dict(h4_case)
    if kind == "source":
        args["source_dir"] = args["output_dir"]
    elif kind == "output":
        args["output_dir"] = args["runtime_dir"]
    else:
        args["runtime_dir"] = args["source_dir"]
    with pytest.raises(EvaluationBlocked, match="disjoint"):
        join_evaluator(**args)


@pytest.mark.parametrize("kind", ["loose_dir", "loose_file", "hardlink", "symlink", "symlink_dir"])
def test_unsafe_source_blocked(h4_case, tmp_path, kind):
    source = h4_case["source_dir"]
    path = source / "run-synthetic.json"
    args = dict(h4_case)
    if kind == "loose_dir":
        source.chmod(0o755)
    elif kind == "loose_file":
        path.chmod(0o644)
    elif kind == "hardlink":
        os.link(path, tmp_path / "extra-link")
    elif kind == "symlink":
        target = tmp_path / "target"
        path.rename(target)
        path.symlink_to(target)
    else:
        link = tmp_path / "source-link"
        link.symlink_to(source, target_is_directory=True)
        args["source_dir"] = link
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**args)
    assert not list(h4_case["output_dir"].iterdir())


@pytest.mark.parametrize("key,mode", [("source_dir", 0o500), ("output_dir", 0o500),
                                      ("output_dir", 0o755)])
def test_h4_requires_exact_private_directory_mode(h4_case, key, mode):
    h4_case[key].chmod(mode)
    with pytest.raises(EvaluationBlocked):
        join_evaluator(**h4_case)


@pytest.fixture
def partition_case(h4_case, tmp_path):
    from scripts.run_c21_preflight import partition_closed_incident

    record = {"run_id": "run-synthetic", "incident_id": "inc-synthetic",
              "split_id": "H-G4", "label": "synthetic-only"}
    raw = json.dumps(record).encode()
    registry = h4_case["source_dir"] / "synthetic.jsonl"
    registry.write_bytes(raw + b"\n")
    registry.chmod(0o600)
    output = tmp_path / "partition"
    output.mkdir(mode=0o700)
    args = {key: h4_case[key] for key in ("store", "audit_events", "trusted_audit_head",
            "incident_id", "run_id", "runtime_dir")}
    args.update(source_file=registry, output_dir=output, offset=0, length=len(raw),
                expected_source_sha256=hashlib.sha256(registry.read_bytes()).hexdigest())
    return partition_closed_incident, args


def test_partition_after_closed_uses_only_selected_record(partition_case):
    partition, args = partition_case
    path = partition(**args)
    assert json.loads(path.read_text())["label"] == "synthetic-only"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(args["runtime_dir"].iterdir())


def test_partition_denies_open_incident_before_source_access(partition_case):
    partition, args = partition_case
    args["store"].update_incident_state("inc-synthetic", "HUMAN_REVIEW", "ACTIVE")
    args["source_file"] = args["source_file"].parent / "absent"
    with pytest.raises(EvaluationBlocked, match="PREMATURE"):
        partition(**args)
    assert not list(args["output_dir"].iterdir())


@pytest.mark.parametrize("change", ["hash", "range", "identity", "audit", "output_overlap"])
def test_partition_fails_closed(partition_case, change):
    partition, original = partition_case
    args = dict(original)
    if change == "hash":
        args["expected_source_sha256"] = "0" * 64
    elif change == "range":
        args["length"] += 10000
    elif change == "identity":
        args["run_id"] = "run-other"
    elif change == "audit":
        args["trusted_audit_head"] = "0" * 64
    else:
        args["output_dir"] = args["runtime_dir"]
    with pytest.raises(EvaluationBlocked):
        partition(**args)
    assert not list(original["output_dir"].iterdir())


@pytest.fixture
def preflight_case(tmp_path, monkeypatch):
    import copy
    from scripts import run_c21_preflight as preflight

    (tmp_path / "evidence").mkdir()
    seals = {}
    for index, relative in enumerate(preflight.SEAL_HASHES):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic-seal-{index}".encode())
        seals[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    directories = {name: {"present": True, "file_count": 1, "dir_sha256": "1" * 64}
                   for name in preflight.PROTECTED_DIRS}
    baseline = {
        "release_freeze_id": "synthetic-c20",
        "source_tree": {"directories": directories, "source_tree_sha256": "2" * 64, "files": {}},
        "contracts": {"contract_count": 1, "contracts_sha256": "3" * 64, "files": {}},
        "versions": {field: "synthetic" for field in preflight.VERSION_FIELDS},
        "gates_and_prereqs": {"rollback_drills_passed": 1, "rollback_drills_total": 1,
                              "actual_cash_spend_usd": 0},
    }
    baseline["manifest_self_sha256"] = preflight._sha256_json(baseline)
    baseline_file = tmp_path / preflight.C20_MANIFEST
    baseline_file.parent.mkdir(parents=True)
    baseline_file.write_text(json.dumps(baseline))
    candidate = copy.deepcopy(baseline)
    monkeypatch.setattr(preflight, "build_final_release_manifest", lambda *args, **kwargs: copy.deepcopy(candidate))
    return preflight, tmp_path, baseline, candidate, seals


def test_preflight_evidence_reports_limitations(preflight_case):
    preflight, root, baseline, _, seals = preflight_case
    target = preflight.run_preflight(root, tests_completed=True,
        baseline_self_sha256=baseline["manifest_self_sha256"], seal_hashes=seals)
    holdout = json.loads((target / "holdout-g4-manifest.json").read_text())
    assert holdout["access_history"] == "NOT_VERIFIED"
    assert holdout["gt_actual_partition"] == "NOT_CREATED"
    assert holdout["benchmark"] == "NOT_RUN"
    assert json.loads((target / "final-release-manifest.json").read_text())["status"] == \
        "C21_CANDIDATE_FROZEN_NOT_BENCHMARKED"


@pytest.mark.parametrize("change", ["seal", "protected", "baseline", "tests"])
def test_preflight_mismatch_creates_no_evidence(preflight_case, change):
    preflight, root, baseline, candidate, seals = preflight_case
    completed = True
    if change == "seal":
        (root / next(iter(seals))).write_bytes(b"tampered")
    elif change == "protected":
        candidate["source_tree"]["directories"]["gateway"]["dir_sha256"] = "9" * 64
    elif change == "baseline":
        baseline["manifest_self_sha256"] = "0" * 64
    else:
        completed = False
    with pytest.raises(preflight.PreflightError):
        preflight.run_preflight(root, tests_completed=completed,
            baseline_self_sha256=baseline["manifest_self_sha256"], seal_hashes=seals)
    assert not list((root / "evidence").glob("c21-preflight-*"))
