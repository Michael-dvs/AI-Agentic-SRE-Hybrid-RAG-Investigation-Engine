"""Generate C14 evidence from offline synthetic cases and the C14 pytest run."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.claim_validator_contract import ClaimValidator
from tests.test_c14_integration import run_workflow


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"c14-{stamp}"
    target = ROOT / "evidence" / run_id / "C14"
    target.mkdir(parents=True, exist_ok=False)
    validator = ClaimValidator()
    failures = []

    def save(name, records):
        (target / f"{name}.json").write_text(json.dumps(records, indent=2, default=str) + "\n")
        (target / f"{name}.jsonl").write_text("".join(json.dumps(row, default=str) + "\n" for row in records))

    timestamp = "2026-11-16T10:00:00Z"
    ev = {"evidence_id": "ev-metric", "tool_name": "get_service_metrics", "source_ref": "synthetic-prometheus",
          "observed_at": timestamp, "data_quality": "complete", "records": [{"value": 120.0}]}
    context = {"evidence_items": [ev], "query_window": {"start": "2026-11-16T09:55:00Z", "end": "2026-11-16T10:05:00Z"}}
    claims = []
    for value in (120.0, 500.0):
        claim = validator.validate_claim("Observed latency", "ev-metric", context, claimed_value=value)
        claims.append({"run_id": run_id, "scenario_id": "synthetic-value-check", **asdict(claim)})
    save("claim-validation", claims)

    multifault = {"service_id": "api-gateway", "evidence_items": [
        {"service_id": "auth-service", "records": [{"service_id": "auth-service", "status_code": 401}]},
        {"service_id": "ledger-service", "records": [{"service_id": "ledger-service", "status_code": 500}]}]}
    contradictions = [{"run_id": run_id, "scenario_id": "SC-08-synthetic", "result": validator.evaluate_cascade_and_multifault([], multifault)}]
    dossiers = []
    with tempfile.TemporaryDirectory(prefix="c14-evidence-") as temp:
        for name, kwargs in (("EV-01", {"conflict": True}), ("EV-02-SC-09", {"outage": True})):
            try:
                folder = Path(temp) / name
                folder.mkdir()
                result = run_workflow(folder, **kwargs)
                dossier = result.get("dossier", {})
                summary = result.get("validation_summary")
                row = {"run_id": run_id, "scenario_id": name, "workflow_status": result.get("status"),
                       "abort_reason": result.get("abort_reason"), "dossier": dossier,
                       "validation_summary": summary, "dossier_markdown": result.get("dossier_markdown"),
                       "evidence_items": result.get("evidence_items", [])}
                expected = "PARTIAL" if name == "EV-01" else "INCONCLUSIVE"
                hypotheses = dossier.get("hypotheses", [])
                if (result.get("status") != "HUMAN_REVIEW" or dossier.get("investigation_mode") != "agentic_llm"
                        or not hypotheses or hypotheses[0]["support_status"] != expected):
                    failures.append(f"{name}: expected agentic workflow and {expected}, got {dossier.get('investigation_mode')} and {hypotheses}")
                (contradictions if name == "EV-01" else dossiers).append(row)
            except Exception:
                failures.append(f"{name}: {traceback.format_exc()}")
    save("contradiction-cases", contradictions)
    save("missing-source-dossiers", dossiers)

    citations = [
        {"chunk_id": "active", "document_id": "SOP-AUTH", "service_id": "auth-service", "environment": "lab", "status": "approved", "effective_from": "2020-01-01T00:00:00Z", "effective_to": None},
        {"chunk_id": "obsolete", "document_id": "SOP-AUTH", "service_id": "auth-service", "environment": "lab", "status": "obsolete", "effective_from": "2020-01-01T00:00:00Z", "effective_to": "2021-01-01T00:00:00Z"},
        {"chunk_id": "wrong-service", "document_id": "SOP-LEDGER", "service_id": "ledger-service", "environment": "lab", "status": "approved", "effective_from": "2020-01-01T00:00:00Z", "effective_to": None},
    ]
    valid, rejected, reasons = validator.validate_sop_citations(citations, "auth-service", "lab", timestamp)
    save("sop-applicability-results", [{"run_id": run_id, "scenario_id": "synthetic-sop", "valid": valid, "rejected": rejected, "reason_codes": reasons}])

    tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_c14_*.py"))
    command = [sys.executable, "-m", "pytest", *tests]
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (target / "pytest-verified-output.txt").write_text("$ " + " ".join(command) + "\n" + proc.stdout + f"\nexit_code={proc.returncode}\n")
    if proc.returncode:
        failures.append(f"C14 pytest exited {proc.returncode}")
    status = "FAIL" if failures else "PASS (synthetic C14 checks only)"
    (target / "readiness-check.md").write_text(
        f"# C14 evidence: {run_id}\n\n"
        f"- Run time UTC: {stamp}\n- Environment: local synthetic DEV replay, no live backend or holdout.\n"
        f"- Pytest exit code: {proc.returncode}; see pytest-verified-output.txt.\n- Bundle status: {status}\n"
        "- EV-01, EV-02, AT-007, AT-009, AT-016, RAG-01, RAG-02: see individual test output; no full acceptance decision inferred.\n"
        "- RULE-005, RULE-007, NFR-004: synthetic cases only; reviewer and full coverage pending.\n"
        "- KPI-03, KPI-04, KPI-11: NOT_RUN as formal benchmarks; no claim based on this small sample.\n"
        "- Code commit/model/prompt/KB version, seed and reviewer: not captured; this is not a formal acceptance run.\n"
        + ("\n## Failures\n" + "\n".join(f"- {f}" for f in failures) + "\n" if failures else "")
    )
    print(target)
    print(f"C14 bundle: {status}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
