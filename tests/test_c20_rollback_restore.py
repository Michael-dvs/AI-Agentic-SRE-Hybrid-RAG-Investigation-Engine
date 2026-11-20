"""Chapter 20 Stage 2B tests for deterministic rollback/restore, AT-015 unit cost basis, and final release freeze."""

from __future__ import annotations

import json
import pathlib

import pytest

from scripts.run_rollback_restore import (
    _REPO_ROOT,
    _sha256_json,
    drill_kb_index_alias_rollback,
    drill_local_state_and_audit_restore,
    drill_model_and_prompt_rollback,
    drill_workflow_and_tool_schema_rollback,
    reconcile_unit_cost_basis,
    run_c20_stage2b,
    verify_h_g4_seal_c20,
)


def test_workflow_and_tool_schema_rollback_determinism(tmp_path: pathlib.Path) -> None:
    res = drill_workflow_and_tool_schema_rollback(tmp_path / "wf")
    assert res["status"] == "PASS"
    assert res["hash_identical_after_rollback"] is True
    assert res["baseline_hash"] == res["restored_hash"]
    assert res["baseline_hash"] != res["canary_hash"]
    assert res["canary_2400s_window_error"] == "WINDOW_EXCEEDED"
    assert res["restored_2400s_window_status"] == "ok"
    assert res["post_rollback_mcp02_3601s_error"] == "WINDOW_EXCEEDED"
    assert res["auto_remediation_triggered"] is False


def test_model_and_prompt_rollback_preserves_active_state(tmp_path: pathlib.Path) -> None:
    res = drill_model_and_prompt_rollback(tmp_path / "model")
    assert res["status"] == "PASS"
    assert res["canary_fallback_mode"] == "manual_fallback"
    assert res["restored_investigation_mode"] == "agentic_llm"
    assert res["baseline_prompt_sha256"] == res["restored_prompt_sha256"]
    assert res["pre_existing_incident_state_intact"] is True
    assert res["auto_remediation_triggered"] is False


def test_kb_index_alias_rollback_and_cache_purge() -> None:
    res = drill_kb_index_alias_rollback(_REPO_ROOT)
    assert res["status"] == "PASS"
    assert res["active_alias"] == "kb_active_alias"
    assert res["hash_identical_after_rollback"] is True
    assert res["baseline_manifest_hash"] == res["restored_manifest_hash"]
    assert res["baseline_manifest_hash"] != res["staging_manifest_hash"]
    assert res["obsolete_v1_excluded"] is True
    assert res["cache_cleared_on_rotation_and_rollback"] is True
    assert res["auto_remediation_triggered"] is False


def test_local_state_and_audit_chain_backup_corrupt_restore(tmp_path: pathlib.Path) -> None:
    res = drill_local_state_and_audit_restore(tmp_path / "state")
    assert res["status"] == "PASS"
    assert res["sqlite_corruption_detected"] is True
    assert res["audit_corruption_detected"] is True
    assert res["sqlite_integrity_check_after_restore"] == "ok"
    assert res["dossier_canonical_hash_intact"] is True
    assert res["audit_chain_valid_after_restore"] is True
    assert res["audit_chain_valid_after_post_restore_append"] is True
    assert res["post_restore_event_count"] == 4
    assert res["auto_remediation_triggered"] is False


def test_unit_cost_basis_separates_successful_and_failed_runs(tmp_path: pathlib.Path) -> None:
    cost = reconcile_unit_cost_basis(_REPO_ROOT, tmp_path / "cost", run_id="c20-cost-test")
    assert cost["actual_cash_spend_usd"] == 0.0
    assert cost["budget_cap_compliant"] is True
    assert cost["compute_and_resource_envelope"]["memory_ceiling_compliant"] is True

    succ = cost["successful_runs"]
    fail = cost["failed_or_timed_out_runs"]
    comb = cost["combined_kpi_14"]
    assert succ["completed_count"] >= 80
    assert fail["failed_count"] >= 3
    assert fail["shadow_cost_usd"] > 0.0
    assert comb["total_shadow_cost_all_attempts_usd"] == pytest.approx(
        succ["shadow_cost_usd"] + fail["shadow_cost_usd"], abs=1e-6
    )
    assert comb["kpi_14_all_runs_per_completed_usd"] == pytest.approx(
        comb["total_shadow_cost_all_attempts_usd"] / succ["completed_count"], abs=1e-6
    )
    assert comb["agentic_llm_slice"]["completed_llm_runs"] == 2
    assert comb["agentic_llm_slice"]["failed_llm_attempts"] == 1


def test_h_g4_seal_verified_and_runner_blocked() -> None:
    seal = verify_h_g4_seal_c20(_REPO_ROOT)
    assert seal["status"] == "VERIFIED_SEALED"
    assert seal["runner_h_g4_guard_blocked"] is True
    assert seal["h_g4_holdout_records"]["parsed_during_c20"] is False
    assert seal["h_g4_queries"]["parsed_during_c20"] is False
    assert all(f["matches"] is True for f in seal["files"])


def test_unified_e20_packaging_and_manifest_self_hash(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "C20"
    summary = run_c20_stage2b(output_dir=target, run_id="c20-pytest-e20", with_pytest=False)
    assert summary["rollback_summary"]["all_passed"] is True
    assert summary["seal_status"] == "VERIFIED_SEALED"
    assert summary["actual_cash_spend_usd"] == 0.0

    required_files = (
        "capacity-series.json",
        "capacity-series.md",
        "outage-and-kill-switch.json",
        "outage-and-kill-switch.md",
        "pilot-defect-closure.json",
        "pilot-defect-closure.md",
        "rollback-restore-record.json",
        "rollback-restore-record.md",
        "unit-cost-basis.json",
        "unit-cost-basis.md",
        "final-release-manifest.json",
        "final-release-manifest.md",
        "holdout-h4-seal-verification.json",
        "readiness-check.md",
        "pytest-verified-output.txt",
    )
    for fname in required_files:
        assert (target / fname).is_file(), f"Missing E20 artifact: {fname}"

    manifest = json.loads((target / "final-release-manifest.json").read_text(encoding="utf-8"))
    recorded_self_hash = manifest.pop("manifest_self_sha256")
    assert len(recorded_self_hash) == 64
    assert _sha256_json(manifest) == recorded_self_hash
    assert manifest["gates_and_prereqs"]["open_critical_defects"] == 0
    assert manifest["gates_and_prereqs"]["h_g4_seal_status"] == "VERIFIED_SEALED"
    assert manifest["source_tree"]["total_files_hashed"] > 50
