"""C17 DEV acceptance ledger with explicitly scoped, partial checks only.

The mapped pytest nodes are supporting checks, not complete UAT procedures.
No unmapped test, collection-wide invocation, or holdout data is used.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_IDS = (
    "SEC-01", "SEC-02", "SEC-03", "MCP-01", "MCP-02", "RAG-01", "RAG-02",
    "EV-01", "EV-02", "OPS-01", "OPS-02", "HUM-01",
    *(f"AT-{number:03d}" for number in range(1, 18)),
)

AT_REQUIREMENTS = (
    ("BR-001", "FR-SIM-001"), ("BR-002", "FR-SIM-004"),
    ("FR-OBS-001", "FR-OBS-002", "FR-OBS-003", "FR-OBS-004"),
    ("FR-AGT-001",), ("FR-AGT-002", "FR-AGT-003", "FR-AGT-004"),
    ("FR-RAG-003",), ("FR-RAG-004", "RULE-005"), ("RULE-002",),
    ("FR-AGT-006",), ("FR-OUT-001", "FR-OUT-002", "FR-OUT-003", "FR-OUT-004"),
    ("RULE-004",), ("NFR-006", "FR-AGT-007"), ("NFR-002", "KPI-13"),
    tuple(f"KPI-{n:02d}" for n in range(2, 9)), ("NFR-013",),
    ("FR-OBS-006",), ("FR-OUT-007",),
)
APPENDIX_REQUIREMENTS = {
    "SEC-01": ("FR-RAG-004", "NFR-003", "RULE-003"),
    "SEC-02": ("RULE-004", "FR-AGT-003"),
    "SEC-03": ("NFR-003", "NFR-012", "NFR-017"),
    "MCP-01": ("BR-007", "FR-AGT-002", "FR-AGT-003", "RULE-003", "KPI-09"),
    "MCP-02": ("FR-AGT-002", "FR-AGT-004"),
    "RAG-01": ("FR-RAG-004", "FR-RAG-008", "RULE-005", "KPI-11"),
    "RAG-02": ("FR-RAG-004", "RULE-005", "KPI-11"),
    "EV-01": ("BR-006", "FR-AGT-006"),
    "EV-02": ("FR-OBS-007", "RULE-006", "NFR-016"),
    "OPS-01": ("FR-OBS-005", "FR-AGT-004", "NFR-010"),
    "OPS-02": ("FR-AGT-007", "NFR-005", "NFR-006", "KPI-12"),
    "HUM-01": ("BR-012", "FR-OUT-004", "RULE-008"),
}

# Individual nodes, not whole files: C06 is intentionally excluded because one
# test reads a sealed query file. Passing these checks does not establish UAT.
CHECKS = {
    "SEC-01": ("tests/test_c08_secure_gateway.py::test_cross_service_scope_enforcement",),
    "SEC-02": ("tests/test_c13_context.py::test_prompt_injection_stays_user_data",),
    "SEC-03": ("tests/test_c15_dlp_scanner.py::test_dlp_scanner_detects_synthetic_secrets_and_pii",),
    "MCP-01": ("tests/test_c13_controlled_llm.py::test_mcp01_provider_native_tool_call_is_denied",),
    "MCP-02": ("tests/test_c08_secure_gateway.py::test_excessive_time_window_rejected_without_silent_clamping",),
    "RAG-01": ("tests/test_c13_context.py::test_citation_trust_metadata_does_not_override_scope",),
    "RAG-02": ("tests/test_c08_secure_gateway.py::test_cross_service_scope_enforcement",),
    "EV-01": ("tests/test_c14_contradiction_and_uncertainty.py::test_ev01_metrics_normal_vs_logs_error_conflict",),
    "EV-02": ("tests/test_c08_secure_gateway.py::test_backend_outage_simulation_returns_unavailable",),
    "OPS-01": ("tests/test_c10_alert_intake_correlation.py::test_deduplication_100_burst_duplicate_alerts",),
    "OPS-02": ("tests/test_c13_controlled_llm.py::test_ops02_three_transient_attempts_then_fallback",),
    "HUM-01": ("tests/test_c16_human_review.py::test_hum01_zero_auto_remediation",),
    "AT-003": ("tests/test_c10_alert_intake_correlation.py::test_end_to_end_intake_to_incident_context",),
    "AT-004": ("tests/test_c11_investigation_workflow.py::test_sequential_9_states_happy_path",),
    "AT-005": ("tests/test_c08_secure_gateway.py::test_write_restart_deploy_tools_strictly_rejected",),
    "AT-008": ("tests/test_c08_secure_gateway.py::test_ground_truth_path_access_blocked",),
    "AT-009": ("tests/test_c14_contradiction_and_uncertainty.py::test_ev01_metrics_normal_vs_logs_error_conflict",),
    "AT-010": ("tests/test_c16_human_review.py::test_at010_unauthorized_review_rejected",),
    "AT-011": ("tests/test_c13_context.py::test_prompt_injection_stays_user_data",),
    "AT-012": ("tests/test_c13_controlled_llm.py::test_ops02_three_transient_attempts_then_fallback",),
    "AT-015": ("tests/test_c15_cost_accounting.py::test_tracker_aggregates_multiple_runs_including_failed_runs",),
    "AT-017": ("tests/test_c16_human_review.py::test_at017_ticket_creation_guard",),
}


def build_ledger(run_id: str, evidence_dir: Path, *, execute: bool = False) -> tuple[list[dict], list[dict]]:
    """Build all 29 records; optionally execute only the fixed safe node map.

    Commands run without shell expansion, and logs are written under evidence_dir.
    A successful supporting check never promotes a full acceptance test to PASS.
    """
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    rows, defects = [], []
    for test_id in TEST_IDS:
        nodes = CHECKS.get(test_id, ())
        commands = [[sys.executable, "-m", "pytest", "-q", node] for node in nodes]
        actual = "No complete DEV acceptance procedure executed."
        status = "BLOCKED"
        evidence_link = None
        defect_id = None
        if execute and commands:
            results = []
            for command in commands:
                try:
                    proc = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"), capture_output=True, text=True, timeout=120, check=False)
                    results.append({"command": command, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
                except subprocess.TimeoutExpired as exc:
                    results.append({"command": command, "returncode": None, "error": "timeout", "stdout": (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "stderr": (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")})
                except OSError as exc:
                    results.append({"command": command, "returncode": None, "error": str(exc), "stdout": "", "stderr": ""})
            import json
            log_path = evidence_dir / f"{test_id.lower()}-checks.json"
            log_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            evidence_link = log_path.name
            if any(result["returncode"] == 1 for result in results):
                status = "FAIL"
                defect_id = f"C17-{test_id}"
                actual = "A mapped supporting pytest check failed; full acceptance remains unproven."
                defects.append({"defect_id": defect_id, "test_id": test_id, "status": "OPEN", "description": actual, "evidence_link": evidence_link})
            elif all(result["returncode"] == 0 for result in results):
                actual = "Mapped supporting check passed; full DEV acceptance not established."
            else:
                actual = "A supporting check could not be completed; see command evidence."
        elif nodes:
            actual = "Mapped supporting check not executed; full DEV acceptance not established."
        rows.append({
            "test_run_id": run_id, "test_id": test_id, "requirement_ids": list(AT_REQUIREMENTS[int(test_id[3:]) - 1] if test_id.startswith("AT-") else APPENDIX_REQUIREMENTS[test_id]),
            "preconditions": "DEV only; full acceptance procedure and dependencies required",
            "commands": commands if execute else [], "planned_commands": commands,
            "dataset_version": "DEV; version not established", "expected": "Complete acceptance criteria satisfied by DEV evidence",
            "actual": actual, "status": status, "evidence_link": evidence_link,
            "defect_id": defect_id, "reviewer": None,
            "date": dt.datetime.now(dt.timezone.utc).isoformat(),
            "disposition": "Full DEV acceptance remains unproven" if status == "BLOCKED" else "Investigate failed supporting check",
        })
    return rows, defects
