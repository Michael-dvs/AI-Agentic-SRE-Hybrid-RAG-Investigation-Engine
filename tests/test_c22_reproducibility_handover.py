"""Chapter 22 automated tests: dual clean replay (AT-013), operations guide, demo (UC-11), and handover (E22)."""

from __future__ import annotations

import json
import os
import pathlib
import socket
import stat

import pytest

from scripts.dlp_sink_scanner import DLPSinkScanner
from scripts.run_c22_clean_replay import (
    DEFAULT_RELEASE_MANIFEST,
    DEFAULT_SEED,
    ManifestDriftError,
    PortConflictOrEnvError,
    ResidualStateError,
    SecurityOrGTLeakError,
    check_environment_and_port_hygiene,
    execute_clean_replay,
    run_c22_pipeline,
    validate_public_bundle_clean,
    verify_release_manifest_preflight,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def c22_run_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Execute one clean isolated C22 pipeline run inside pytest temp space."""
    out_dir = tmp_path_factory.mktemp("c22_suite") / "C22"
    summary = run_c22_pipeline(
        repo_root=_REPO_ROOT,
        release_manifest=DEFAULT_RELEASE_MANIFEST,
        seed=DEFAULT_SEED,
        mode="deterministic_baseline",
        verify_docker=False,
        output_dir=out_dir,
    )
    return {
        "output_dir": out_dir,
        "summary": summary,
    }


def test_c22_pos01_reproducibility_at013(c22_run_artifacts: dict[str, object]) -> None:
    out_dir = pathlib.Path(str(c22_run_artifacts["output_dir"]))
    comparison = json.loads((out_dir / "replay-comparison.json").read_text(encoding="utf-8"))
    inv_a = json.loads((out_dir / "clean-replay-a" / "invariants.json").read_text(encoding="utf-8"))
    inv_b = json.loads((out_dir / "clean-replay-b" / "invariants.json").read_text(encoding="utf-8"))

    assert comparison["test_id"] == "AT-013"
    assert comparison["overall_at013_status"] == "PASS"
    assert comparison["wipe_between_runs_verified"] is True
    assert comparison["kpi_13_reproducibility_rate"] == 1.0
    assert comparison["kpi_13_reproducibility_rate"] >= 0.90

    inv_cmp = comparison["invariant_comparison"]
    assert inv_cmp["state_sequences_match"] is True
    assert inv_cmp["schema_validation_all_pass"] is True
    assert inv_cmp["evidence_ids_match"] is True
    assert inv_cmp["sop_citation_hashes_match"] is True
    assert inv_cmp["support_status_match"] is True
    assert inv_cmp["normalized_dossier_hashes_match"] is True
    assert inv_cmp["safety_invariants_zero_violation"] is True
    assert inv_cmp["ground_truth_stable"] is True

    for inv in (inv_a, inv_b):
        assert inv["wipe_before_run"] is True
        assert inv["kpi_09"] == 0
        assert inv["kpi_10"] == 0
        assert inv["kpi_11"] == 0
        assert inv["auto_action_triggered"] is False
        assert inv["support_status"]["SC-09"] == "INCONCLUSIVE"


def test_c22_pos02_operations_guide_contract(c22_run_artifacts: dict[str, object]) -> None:
    out_dir = pathlib.Path(str(c22_run_artifacts["output_dir"]))
    ops_md = (out_dir / "operations-guide.md").read_text(encoding="utf-8")

    for port in ("18080", "19090", "13100", "13200", "13000", "14318", "8000", "8080", "6333"):
        assert port in ops_md, f"Missing expected port {port} in operations-guide.md"

    assert "8 GiB RAM" in ops_md
    assert ".env.example" in ops_md

    for script_name in ("lab_up.sh", "lab_smoke.sh", "fault_reset.sh", "lab_down.sh"):
        assert script_name in ops_md
        assert (_REPO_ROOT / "scripts" / script_name).is_file()


def test_c22_pos03_handover_manifest_inventory(c22_run_artifacts: dict[str, object]) -> None:
    out_dir = pathlib.Path(str(c22_run_artifacts["output_dir"]))
    manifest = json.loads((out_dir / "handover-manifest.json").read_text(encoding="utf-8"))
    manifest_md = (out_dir / "handover-manifest.md").read_text(encoding="utf-8")

    assert manifest["total_inventory_categories"] == 15
    assert len(manifest["inventory_items"]) == 15
    assert manifest["all_local_links_valid"] is True
    assert manifest["broken_links"] == []
    assert manifest["public_bundle_gt_leaks"] == 0
    assert manifest["public_bundle_env_files"] == 0
    assert manifest["restricted_zone_excluded_from_public_bundle"] is True
    assert "15/15" in manifest_md

    for restricted_rel in ("restricted", "restricted/gt_registry", "restricted/evaluator_queries"):
        mode = stat.S_IMODE(os.stat(_REPO_ROOT / restricted_rel).st_mode)
        assert mode == 0o700, f"Expected 0o700 on {restricted_rel}, got {oct(mode)}"

    scanner = DLPSinkScanner()
    scanner.scan_directory(out_dir / "public_handover")
    scanner.scan_directory(out_dir)
    report = scanner.generate_report()
    assert report["clean"] is True
    assert report["total_violations"] == 0


def test_c22_pos04_demo_rehearsal_protocol(c22_run_artifacts: dict[str, object]) -> None:
    out_dir = pathlib.Path(str(c22_run_artifacts["output_dir"]))
    demo_md = (out_dir / "demo-rehearsal.md").read_text(encoding="utf-8")
    training_md = (out_dir / "training-record.md").read_text(encoding="utf-8")

    for required_token in (
        "Segment 1",
        "Segment 2",
        "Segment 3",
        "Segment 4",
        "SC-01",
        "SC-03",
        "SC-09",
        "SC-11",
        "SC-08",
        "auto_action_triggered: false",
        "PRE_RECORDED_FALLBACK_RUN",
    ):
        assert required_token in demo_md

    assert "PRE_RECORDED_FALLBACK_RUN" in training_md
    assert "PASS" in training_md


def test_c22_neg01_residual_state_rejected(tmp_path: pathlib.Path) -> None:
    work_dir = tmp_path / "dirty_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "orchestrator_state.db").write_text("leftover-sqlite-state", encoding="utf-8")
    replay_dir = tmp_path / "rejected_replay"

    with pytest.raises(ResidualStateError) as exc_info:
        execute_clean_replay(
            replay_id="neg01-test",
            replay_dir=replay_dir,
            work_dir=work_dir,
            repo_root=_REPO_ROOT,
            seed=DEFAULT_SEED,
        )

    assert exc_info.value.exit_code == 3
    assert not (replay_dir / "dossiers").exists()


def test_c22_neg02_port_conflict_handled() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        busy_port = listener.getsockname()[1]

        with pytest.raises(PortConflictOrEnvError) as exc_info:
            check_environment_and_port_hygiene(
                _REPO_ROOT,
                ports=(busy_port,),
                verify_docker=False,
                check_ports=True,
            )

        assert exc_info.value.exit_code == 2


def test_c22_neg03_gt_leak_handover_blocked(tmp_path: pathlib.Path) -> None:
    contaminated_dir = tmp_path / "contaminated_handover"
    contaminated_dir.mkdir(parents=True, exist_ok=True)
    (contaminated_dir / "ground_truth_records.jsonl").write_text('{"leak": true}\n', encoding="utf-8")

    with pytest.raises(SecurityOrGTLeakError) as exc_info:
        validate_public_bundle_clean(contaminated_dir)
    assert exc_info.value.exit_code == 4

    env_dir = tmp_path / "contaminated_env"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text("OPENROUTER_API_KEY=synthetic-leak\n", encoding="utf-8")

    with pytest.raises(SecurityOrGTLeakError) as exc_env:
        validate_public_bundle_clean(env_dir)
    assert exc_env.value.exit_code == 4


def test_c22_neg04_manifest_drift_rejected(tmp_path: pathlib.Path) -> None:
    manifest_src = _REPO_ROOT / DEFAULT_RELEASE_MANIFEST
    manifest_data = json.loads(manifest_src.read_text(encoding="utf-8"))
    target_key = next(iter(manifest_data["source_tree"]["files"]))
    orig_hash = manifest_data["source_tree"]["files"][target_key]
    manifest_data["source_tree"]["files"][target_key] = ("a" if orig_hash[0] != "a" else "b") + orig_hash[1:]
    body = {k: v for k, v in manifest_data.items() if k != "manifest_self_sha256"}

    import hashlib
    manifest_data["manifest_self_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()

    drifted_path = tmp_path / "drifted-release-manifest.json"
    drifted_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    with pytest.raises(ManifestDriftError) as exc_info:
        verify_release_manifest_preflight(_REPO_ROOT, drifted_path)

    assert exc_info.value.exit_code == 2
