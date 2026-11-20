"""Chapter 19 Stage 1B tests for Lab Shadow Pilot, Blinded Manual Baseline, Rubric, and H-G4 Seal."""

from __future__ import annotations

import json
import pathlib

import pytest

from evaluator.manual_baseline import (
    ManualBaselineError,
    build_default_dev_manual_records,
    build_manual_baseline_record,
    compute_manual_vs_assisted_summary,
    validate_anti_carryover_record,
)
from evaluator.pilot_rubric import (
    PilotRubricError,
    build_pilot_defects_registry,
    build_rubric_entry,
    summarize_rubric,
    to_scorer_review_fields,
    validate_pilot_defects,
    validate_rubric_entry,
)
from evaluator.scorer import score_cases
from scripts.manual_baseline_collector import main as collector_main
from scripts.run_shadow_pilot import run_shadow_pilot


def _sample_manual_kwargs() -> dict:
    return {
        "incident_id": "inc-pilot-dev-sample-001",
        "service_id": "ledger-service",
        "case_label": "DEV Sample Case",
        "alert_received_at": "2026-11-20T06:00:00Z",
        "manual_started_at": "2026-11-20T06:00:10Z",
        "manual_completed_at": "2026-11-20T06:05:10Z",
        "manual_locked_at": "2026-11-20T06:05:15Z",
        "ai_dossier_opened_at": "2026-11-20T06:06:00Z",
        "ai_review_completed_at": "2026-11-20T06:06:45Z",
        "manual_seconds": 300.0,
        "system_tti_seconds": 0.25,
        "human_review_seconds": 45.0,
        "manual_steps_count": 8,
        "document_search_friction": "Manual grep across SOP markdown files.",
        "manual_hypothesis_summary": "Database pool saturation suspected.",
        "manual_sop_lookup_used": ["SOP-LEDGER-001"],
    }


def test_anti_carryover_protocol_validation_and_rejections() -> None:
    valid = build_manual_baseline_record(**_sample_manual_kwargs())
    validate_anti_carryover_record(valid)
    assert valid["assisted_seconds"] == 45.25

    # Violation 1: AI dossier opened before manual lock
    bad_order = _sample_manual_kwargs()
    bad_order["ai_dossier_opened_at"] = "2026-11-20T06:04:00Z"
    with pytest.raises(ManualBaselineError, match="Anti-carryover timestamp"):
        build_manual_baseline_record(**bad_order)

    # Violation 2: Lock flag false
    bad_lock = _sample_manual_kwargs()
    bad_lock["locked_before_ai_view"] = False
    with pytest.raises(ManualBaselineError, match="locked_before_ai_view"):
        build_manual_baseline_record(**bad_lock)

    # Violation 3: H-G4 and H-G3 splits rejected
    bad_h4_split = _sample_manual_kwargs()
    bad_h4_split["split_id"] = "H-G4"
    with pytest.raises(ManualBaselineError, match="h-g4"):
        build_manual_baseline_record(**bad_h4_split)

    bad_h3_split = _sample_manual_kwargs()
    bad_h3_split["split_id"] = "H-G3"
    with pytest.raises(ManualBaselineError, match="split_id='dev'"):
        build_manual_baseline_record(**bad_h3_split)

    # Violation 4: Ground truth marker leaked
    leaked = dict(valid)
    leaked["notes"] = "Leaked expected_root_cause here"
    with pytest.raises(ManualBaselineError, match="ground-truth"):
        validate_anti_carryover_record(leaked)

    # Violation 5: Tampered manual_seconds fails lock hash check
    tampered = dict(valid)
    tampered["manual_seconds"] = 999.0
    with pytest.raises(ManualBaselineError, match="lock_sha256"):
        validate_anti_carryover_record(tampered)


def test_manual_baseline_summary_matches_scorer_kpi08() -> None:
    records = build_default_dev_manual_records()
    summary = compute_manual_vs_assisted_summary(records)
    assert summary["matched_pair_count"] == 7
    assert summary["all_records_locked_before_ai_view"] is True
    assert summary["validity_declaration"]["label_source"] == "SELF_EVALUATED_DEVELOPER_LABELS"

    scorer_cases = [
        {
            "incident_id": rec["incident_id"],
            "completed": True,
            "ground_truth": {"scenario_id": "SC-02", "actual_root_cause": {"is_healthy_control": False, "expected_causes": [rec["service_id"]]}},
            "diagnoses": [{"cause": rec["service_id"], "status": "SUPPORTED"}],
            "claims": [{"valid_source": True, "unsupported": False}],
            "retrieval_queries": [],
            "critical_failure": False,
            "prohibited_successes": 0,
            "gt_retrievals": 0,
            "forbidden_citations": 0,
            "cost": {"token_cost": 0.0, "compute_cost": 0.01, "total_tokens": 0},
            "manual_seconds": rec["manual_seconds"],
            "assisted_seconds": rec["assisted_seconds"],
        }
        for rec in records
    ]
    kpi_report = score_cases(scorer_cases)["metrics"]
    assert kpi_report["KPI-08"]["status"] == "MEASURED"
    assert kpi_report["KPI-08"]["matched_count"] == 7
    assert kpi_report["KPI-08"]["value"] == pytest.approx(summary["kpi_08_time_reduction_ratio"], abs=1e-4)
    assert collector_main(["--validate-only"]) == 0


def test_rubric_5_dimensions_and_pilot_defects_validation() -> None:
    entry = build_rubric_entry(
        incident_id="inc-pilot-dev-rubric-001",
        service_id="ledger-service",
        case_label="DEV Rubric Check",
        scores={
            "correctness": 5,
            "evidence_sufficiency": 4,
            "actionability": 4,
            "clarity": 5,
            "uncertainty_handling": 4,
        },
        decision="APPROVED",
        accepted_without_substantial_rework=True,
        system_time_to_dossier_seconds=0.12,
        human_review_effort_seconds=35.0,
        tui_actions_applied=["APPROVE"],
        final_dossier_version=1,
        final_dossier_hash="a" * 64,
        final_state="CLOSED",
        reviewer_notes="Evidence aligned with SOP.",
    )
    validate_rubric_entry(entry)
    summary = summarize_rubric([entry])
    assert summary["kpi_06_acceptance_rate"] == 1.0
    assert summary["auto_action_triggered_count"] == 0

    scorer_cases = [
        {
            "incident_id": entry["incident_id"],
            "completed": True,
            "ground_truth": {"scenario_id": "SC-03", "actual_root_cause": {"is_healthy_control": False, "expected_causes": ["ledger-service"]}},
            "diagnoses": [{"cause": "ledger-service", "status": "SUPPORTED"}],
            "claims": [{"valid_source": True, "unsupported": False}],
            "retrieval_queries": [],
            "review": to_scorer_review_fields(entry),
            "critical_failure": False,
            "prohibited_successes": 0,
            "gt_retrievals": 0,
            "forbidden_citations": 0,
            "cost": {"token_cost": 0.0, "compute_cost": 0.01, "total_tokens": 0},
        }
    ]
    kpi06 = score_cases(scorer_cases)["metrics"]["KPI-06"]
    assert kpi06["value"] == 1.0
    assert kpi06["label_sources"] == ["SELF_EVALUATED_DEVELOPER_LABELS"]

    bad_auto = dict(entry)
    bad_auto["auto_action_triggered"] = True
    with pytest.raises(PilotRubricError, match="auto_action_triggered"):
        validate_rubric_entry(bad_auto)

    bad_score = dict(entry)
    bad_score["scores"] = {**entry["scores"], "clarity": 6}
    with pytest.raises(PilotRubricError, match="1..5"):
        validate_rubric_entry(bad_score)

    defects = build_pilot_defects_registry()
    validate_pilot_defects(defects)
    assert len(defects) == 6
    assert any(d["defect_id"] == "C19-DEF-006" for d in defects)
    assert {d["category"] for d in defects} >= {"USABILITY", "PERFORMANCE", "RAG_NAVIGATION", "BASELINE_BIAS"}


def test_shadow_pilot_end_to_end_and_e19_artifacts(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "C19"
    result = run_shadow_pilot(output_dir=target, run_id="c19-pytest-pilot", with_pytest=False)

    assert result["pilot_summary"]["total_incidents"] == 7
    assert result["pilot_summary"]["closed_incidents"] == 7
    assert result["pilot_summary"]["telegram_dry_run_count"] == 7
    assert result["pilot_summary"]["auto_action_triggered_count"] == 0
    assert result["pilot_summary"]["handover_gt_leak_count"] == 0
    assert result["seal_status"] == "VERIFIED_SEALED"
    assert result["audit_chain"]["valid"] is True
    assert result["defects_count"] >= 5

    required_files = (
        "manual-timing-protocol-and-records.json",
        "manual-timing-protocol-and-records.md",
        "pilot-run-log.json",
        "pilot-run-log.md",
        "review-rubric.json",
        "review-rubric.md",
        "pilot-defects.json",
        "pilot-defects.md",
        "holdout-h4-seal-verification.json",
        "readiness-check.md",
        "pytest-verified-output.txt",
    )
    for fname in required_files:
        assert (target / fname).is_file(), f"Missing E19 artifact: {fname}"

    pilot_log = json.loads((target / "pilot-run-log.json").read_text(encoding="utf-8"))
    runs_by_id = {r["incident_id"]: r for r in pilot_log["runs"]}
    assert runs_by_id["inc-pilot-dev-sc07-006"]["tui_actions_applied"] == ["CORRECT", "APPROVE"]
    assert runs_by_id["inc-pilot-dev-sc07-006"]["final_dossier_version"] == 2
    assert runs_by_id["inc-pilot-dev-sc09-007"]["top_hypothesis_status"] == "INCONCLUSIVE"
    assert runs_by_id["inc-pilot-dev-sc09-007"]["missing_sources_count"] >= 1
    assert runs_by_id["inc-pilot-dev-sc01-001"]["top_hypothesis_status"] == "INCONCLUSIVE"
    assert runs_by_id["inc-pilot-dev-sc03-003"]["sop_citations_count"] >= 1

    seal_doc = json.loads((target / "holdout-h4-seal-verification.json").read_text(encoding="utf-8"))
    assert seal_doc["status"] == "VERIFIED_SEALED"
    assert seal_doc["runner_h_g4_guard_blocked"] is True
    assert seal_doc["h_g4_holdout_records"]["parsed_during_c19"] is False
    assert seal_doc["h_g4_queries"]["parsed_during_c19"] is False

    rubric_doc = json.loads((target / "review-rubric.json").read_text(encoding="utf-8"))
    assert rubric_doc["summary"]["kpi_06_acceptance_rate"] == pytest.approx(6 / 7, abs=1e-4)
    assert rubric_doc["summary"]["label_source"] == "SELF_EVALUATED_DEVELOPER_LABELS"

    manual_doc = json.loads((target / "manual-timing-protocol-and-records.json").read_text(encoding="utf-8"))
    assert manual_doc["summary"]["all_records_locked_before_ai_view"] is True
    assert manual_doc["summary"]["kpi_08_time_reduction_ratio"] > 0.40
