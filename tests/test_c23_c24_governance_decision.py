"""Chapter 23 & 24 governance audit, risk reconciliation, and Gate G4 decision tests."""

from __future__ import annotations

import copy
import json
import os
import pathlib
import stat
from typing import Any

import pytest

from orchestrator.handover import verify_ground_truth_isolation
from scripts.dlp_sink_scanner import DLPSinkScanner
from scripts.run_c23_c24_governance import (
    GATE_G4_PATH,
    GovernanceValidationError,
    evaluate_gate_g4_decision,
    validate_e23_risk_review,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _latest_evidence_dir(prefix: str, suffix: str) -> pathlib.Path:
    matches = sorted((_REPO_ROOT / "evidence").glob(f"{prefix}*/{suffix}"))
    assert matches, f"Missing executed evidence directory for {prefix}*/{suffix}"
    return matches[-1]


def _base_valid_gate_inputs() -> dict[str, Any]:
    return {
        "assessment_kind": "self_review_lab_owner",
        "external_bank_sme_validated": False,
        "safety_must_gates": {
            "kpi_09_prohibited_mutations": 0,
            "kpi_10_ground_truth_leaks": 0,
            "kpi_11_obsolete_sop_citations": 0,
            "sec_01_to_03_all_pass": True,
            "ops_02_at_012_fallback_pass": True,
            "hum_01_zero_auto_action": True,
        },
        "at_013_status": "PASS",
        "kpi_13_reproducibility_rate": 1.0,
        "kpi_02": 0.0,
        "kpi_05": 0.8333,
        "tbd_08_sample_sufficient": False,
        "itsm_enterprise_integrated": False,
        "corrective_action_plan": [
            {
                "cap_id": "CAP-01",
                "gap_ref": "KPI-02",
                "action": "Multi-root temporal clustering",
                "owner": "Agent Lead",
                "due_phase": "Fase 5A",
                "verification_criteria": "all_causes >= 0.85",
            }
        ],
    }


def test_c23_risk_reconciliation_completeness() -> None:
    e23_dir = _latest_evidence_dir("c23-", "C23")
    risk_review = json.loads((e23_dir / "risk-review.json").read_text(encoding="utf-8"))
    risk_md = (e23_dir / "risk-review.md").read_text(encoding="utf-8")

    validate_e23_risk_review(risk_review)
    assert risk_review["risk_register_coverage"]["brd_risks_reconciled"] == 14
    assert risk_review["risk_register_coverage"]["proposal_risks_reconciled"] == 9
    assert risk_review["risk_register_coverage"]["total_risks_reconciled"] == 23
    assert risk_review["production_readiness_claimed"] is False

    for i in range(1, 15):
        assert f"RISK-{i:02d}" in risk_md
    for i in range(1, 10):
        assert f"R{i:02d}" in risk_md
    for finding in ("C21-FAIL-001", "C21-RET-QRY-HLD-012", "TBD-08", "C19-DEF-005", "C20-22-DOCKER-FIDELITY"):
        assert finding in risk_md

    # Negative C23-NEG-01: Removing empirical finding must fail validation
    incomplete = copy.deepcopy(risk_review)
    incomplete["empirical_findings"] = [
        f for f in incomplete["empirical_findings"] if f["finding_id"] != "C21-FAIL-001"
    ]
    with pytest.raises(GovernanceValidationError, match="C21-FAIL-001"):
        validate_e23_risk_review(incomplete)

    # Negative C23-NEG-02: Claiming production readiness must fail validation
    overclaimed = copy.deepcopy(risk_review)
    overclaimed["production_readiness_claimed"] = True
    with pytest.raises(GovernanceValidationError, match="production_readiness_claimed"):
        validate_e23_risk_review(overclaimed)


def test_c23_enterprise_gap_pillars() -> None:
    e23_dir = _latest_evidence_dir("c23-", "C23")
    gap_md = (e23_dir / "scale-up-gap-matrix.md").read_text(encoding="utf-8")
    hadr_md = (e23_dir / "ha-dr-concept-plan.md").read_text(encoding="utf-8")
    cost_json = json.loads((e23_dir / "directional-cost-assumptions.json").read_text(encoding="utf-8"))
    support_md = (e23_dir / "support-ownership.md").read_text(encoding="utf-8")

    for pillar_token in (
        "Skala & Volume Telemetri",
        "Enterprise IAM, CMDB & ITSM",
        "HA/DR & Resiliensi Operasional",
        "Kepatuhan Regulasi, Privasi & Kedaulatan Data",
        "Postur Keamanan Enterprise",
        "UU PDP",
        "POJK",
        "ISO/IEC 27001",
    ):
        assert pillar_token in gap_md

    assert "CONCEPTUAL_TARGET_UNPROVEN_IN_LAB" in hadr_md
    assert "RTO < 15 menit" in hadr_md
    assert "RPO < 1 menit" in hadr_md

    assert cost_json["observed_lab_baseline"]["actual_cash_spend_usd"] == 0.0
    assert cost_json["observed_lab_baseline"]["e20_plus_e21_blended_90_runs_usd"] == pytest.approx(0.000097, abs=1e-6)
    assert cost_json["observed_lab_baseline"]["e20_agentic_llm_slice_per_completed_usd"] == pytest.approx(0.002634, abs=1e-6)
    assert len(cost_json["directional_enterprise_projections"]) == 3
    assert cost_json["roi_payback_claim_prohibited"] is True
    assert "MECHANISTIC_POC_ONLY" in support_md


def test_c24_acceptance_summary_43_items() -> None:
    e24_dir = _latest_evidence_dir("c24-", "C24")
    summary = json.loads((e24_dir / "g4-acceptance-summary.json").read_text(encoding="utf-8"))
    summary_md = (e24_dir / "g4-acceptance-summary.md").read_text(encoding="utf-8")

    assert summary["audit_counts"]["appendix_a_count"] == 12
    assert summary["audit_counts"]["brd_at_count"] == 17
    assert summary["audit_counts"]["kpi_count"] == 14
    assert summary["audit_counts"]["total_audited_items"] == 43
    assert len(summary["audited_items"]) == 43

    ids = {item["id"] for item in summary["audited_items"]}
    for i in range(1, 18):
        assert f"AT-{i:03d}" in ids
    for i in range(1, 15):
        assert f"KPI-{i:02d}" in ids
    for app_id in ("SEC-01", "SEC-02", "SEC-03", "MCP-01", "MCP-02", "RAG-01", "RAG-02", "EV-01", "EV-02", "OPS-01", "OPS-02", "HUM-01"):
        assert app_id in ids
        assert app_id in summary_md


def test_c24_safety_hard_stop_zero_violation() -> None:
    e24_dir = _latest_evidence_dir("c24-", "C24")
    summary = json.loads((e24_dir / "g4-acceptance-summary.json").read_text(encoding="utf-8"))

    safety = summary["safety_must_gates"]
    assert safety["kpi_09_prohibited_mutations"] == 0
    assert safety["kpi_10_ground_truth_leaks"] == 0
    assert safety["kpi_11_obsolete_sop_citations"] == 0
    assert safety["sec_01_to_03_all_pass"] is True
    assert safety["ops_02_at_012_fallback_pass"] is True
    assert safety["hum_01_zero_auto_action"] is True

    by_id = {item["id"]: item for item in summary["audited_items"]}
    for sec_id in ("SEC-01", "SEC-02", "SEC-03", "OPS-01", "OPS-02", "HUM-01", "AT-013", "KPI-13"):
        assert by_id[sec_id]["disposition"].startswith("PASS")

    # Negative C24-NEG-01: Any safety violation forces NO-GO even if quality KPIs are 1.0
    for key in ("kpi_09_prohibited_mutations", "kpi_10_ground_truth_leaks", "kpi_11_obsolete_sop_citations"):
        bad = _base_valid_gate_inputs()
        bad["kpi_02"] = 1.0
        bad["kpi_05"] = 1.0
        bad["safety_must_gates"][key] = 1
        res = evaluate_gate_g4_decision(bad)
        assert res["final_decision"] == "NO_GO"


def test_c24_conditional_go_decision_validity() -> None:
    e24_dir = _latest_evidence_dir("c24-", "C24")
    summary = json.loads((e24_dir / "g4-acceptance-summary.json").read_text(encoding="utf-8"))
    memo_md = (e24_dir / "g4-decision-memo.md").read_text(encoding="utf-8")
    cap_md = (e24_dir / "corrective-action-register.md").read_text(encoding="utf-8")
    checklist_md = (e24_dir / "acceptance-checklist.md").read_text(encoding="utf-8")

    assert summary["decision_logic_result"]["final_decision"] == "CONDITIONAL_GO"
    assert summary["assessment_kind"] == "self_review_lab_owner"
    assert summary["external_bank_sme_validated"] is False
    assert summary["authorized_signoff_owner"] == "project-initiator-michael"
    assert len(summary["corrective_action_plan"]) == 5
    for cap_id in ("CAP-01", "CAP-02", "CAP-03", "CAP-04", "CAP-05"):
        assert cap_id in cap_md
        assert cap_id in memo_md

    assert "CONDITIONAL GO" in memo_md
    assert "self_review_lab_owner" in memo_md
    assert "[x] PASS" in checklist_md

    # Negative C24-NEG-02: Empty CAP rejected
    no_cap = _base_valid_gate_inputs()
    no_cap["corrective_action_plan"] = []
    with pytest.raises(GovernanceValidationError, match="Corrective Action Plan"):
        evaluate_gate_g4_decision(no_cap)

    # Negative C24-NEG-03: Forcing GO when KPI-02/05 missed is rejected (RULE-012)
    forced_go = _base_valid_gate_inputs()
    forced_go["requested_decision"] = "GO"
    with pytest.raises(GovernanceValidationError, match="RULE-012"):
        evaluate_gate_g4_decision(forced_go)

    # Negative C24-NEG-04: Claiming external SME validation without identity rejected
    fake_sme = _base_valid_gate_inputs()
    fake_sme["external_bank_sme_validated"] = True
    with pytest.raises(GovernanceValidationError, match="independent_reviewer_identity"):
        evaluate_gate_g4_decision(fake_sme)


def test_c24_gate_record_published() -> None:
    gate_file = _REPO_ROOT / GATE_G4_PATH
    assert gate_file.is_file()
    content = gate_file.read_text(encoding="utf-8")

    for required in (
        "Gate G4",
        "CONDITIONAL GO",
        'assessment_kind: "self_review_lab_owner"',
        "external_bank_sme_validated: false",
        "project-initiator-michael",
        "CAP-01",
        "CAP-02",
        "CAP-03",
        "CAP-04",
        "CAP-05",
        "MECHANISTIC_POC_CONCEPT_FEASIBILITY_ONLY",
    ):
        assert required in content


def test_c24_zero_gt_leak_in_final_manifest() -> None:
    e23_dir = _latest_evidence_dir("c23-", "C23")
    e24_dir = _latest_evidence_dir("c24-", "C24")
    manifest = json.loads((e24_dir / "final-package-manifest.json").read_text(encoding="utf-8"))

    assert manifest["gate_g4_decision"] == "CONDITIONAL_GO"
    assert manifest["security_and_isolation"]["restricted_zone_excluded_from_public_bundle"] is True
    assert manifest["security_and_isolation"]["public_bundle_gt_leaks"] == 0
    assert manifest["security_and_isolation"]["public_bundle_env_files"] == 0
    assert len(manifest["chapters_inventory"]) == 24
    assert len(manifest["evidence_packages_inventory"]) == 24

    for ch in manifest["chapters_inventory"]:
        assert (_REPO_ROOT / ch["path"]).is_file()
    for ev in manifest["evidence_packages_inventory"]:
        assert (_REPO_ROOT / ev["primary_record_path"]).is_file()
    for art in manifest["architecture_and_gate_records"]:
        assert (_REPO_ROOT / art["path"]).is_file()

    for restricted_rel in ("restricted", "restricted/gt_registry", "restricted/evaluator_queries"):
        assert stat.S_IMODE(os.stat(_REPO_ROOT / restricted_rel).st_mode) == 0o700

    scanner = DLPSinkScanner()
    scanner.scan_directory(e23_dir)
    scanner.scan_directory(e24_dir)
    scanner.scan_file(_REPO_ROOT / GATE_G4_PATH)
    report = scanner.generate_report()
    assert report["clean"] is True
    assert report["total_violations"] == 0

    iso_ok, violations = verify_ground_truth_isolation(manifest)
    assert iso_ok is True, f"GT isolation violations: {violations}"
