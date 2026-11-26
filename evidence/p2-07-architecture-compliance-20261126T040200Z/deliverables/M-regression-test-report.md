# Deliverable M — Regression Test Execution Report (`S1` – `S4`)
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Machine-Readable Summary:** [`../regression_summary.json`](../regression_summary.json)
- **Runtime Environment:** Python `3.12.14` (`.venv`), `pytest 8.3.4`, `anyio 4.16.0`, macOS `arm64`, Docker `29.8.2` (`12/12` `sre-sim-*` containers healthy).

---

## 1. Executed Test Suites Summary (Non-Overlapping Reporting per `S5`)

| Suite ID & Scope | Exact Executed Command | Exit Code | Passed | Failed | Errors | Skipped | Warnings | Duration | Disposition |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| **`S1` — Pre-Fix Baseline Offline Suite** *(captured before P2-07 edits)* | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -q tests --ignore=tests/test_c03_compose_live.py --tb=short` | `1` | `811` | `1` | `4` | `3` | `1` | `46.51s` | Baseline captured: `3` skips due to missing `-p anyio`; `1` fail + `4` errors on intentional Stage 3A freeze guards |
| **`S2-P207` — New P2-07 Architecture Compliance File** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -v tests/test_p2_07_architecture_compliance.py --tb=short` | `0` | **`6`** | `0` | `0` | `0` | `1` | `4.46s` | **`100% PASS`** (`DEF-P207-01`, `DEF-P207-02`, `bd24f1cd30`, `INV-01..26`, `O2` rollback) |
| **`S2` — Focused Remediation & Compliance Suite (`P0-01`..`P2-07`)** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -q tests/test_p*.py tests/test_c14_claim_validation.py tests/test_c14_contradiction_and_uncertainty.py tests/test_c14_integration.py tests/test_c14_sop_applicability.py --tb=short` | `0` | **`287`** | `0` | `0` | `0` | `1` | `21.78s` | **`100% PASS`** across all 7 remediation workstreams |
| **`S3` — Full Applicable Offline + Hybrid Suite (Post-Fix, with `-p anyio`)** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -q tests --ignore=tests/test_c03_compose_live.py --tb=short` | `1` | **`820`** | **`1`** | **`4`** | **`0`** | `1` | `69.66s` | `+9` newly passing tests vs `S1` (`6` new `P2-07` + `3` `anyio` async simulator tests); **ONLY** failures/errors are the 5 intentional Stage 3A freeze guards (see §2) |
| **`S3-Active` — Full Suite Excluding Stage 3A Freeze-Guard Files** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -q tests --ignore=tests/test_c03_compose_live.py --ignore=tests/test_c21_benchmark.py --ignore=tests/test_c22_reproducibility_handover.py --tb=short` | `0` | **`812`** | **`0`** | **`0`** | **`0`** | `1` | `58.58s` | **`100% PASS` (`0` failures, `0` errors, `0` skipped)** |
| **`S4` — Live Docker Compose Integration Suite** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_c03_compose_live.py --tb=short` | `0` | **`4`** | **`0`** | **`0`** | **`0`** | `0` | `7.69s` | **`100% PASS`** against live 12-container stack *(plus `test_live_docker_compose_c04_isolation_and_fault_recovery` inside `S3`/`S3-Active`)* |

*(Note: Per `S4`/`S5` runtime-dependency disclosure, `tests/test_c04_fault_harness.py::test_live_docker_compose_c04_isolation_and_fault_recovery` resides inside `tests/` and executed live against `http://127.0.0.1:18080` + `docker exec sre-sim-api-gateway` during `S3`/`S3-Active`, passing `100%`.)*

---

## 2. Classification of the 5 Expected Freeze-Guard Failures/Errors in `S3` (`Work Package S6`)

| Test Node | Exception Raised | Root Cause | Classification |
|---|---|---|---|
| `tests/test_c21_benchmark.py::test_preflight_freeze_reverification_matches_stage_3a` | `RuntimeError: Protected directory modified after Stage 3A preflight: orchestrator` | Verifies directory hashes against frozen Nov 22 Stage 3A `evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json` (`b7fcc548...`) | **EXPECTED INTENTIONAL FREEZE GUARD** (proves tamper detection works; `32` modified + `13` added files documented in Deliverable P) |
| `tests/test_c22_reproducibility_handover.py::test_c22_pos01_reproducibility_at013` | `ManifestDriftError: Frozen release file drift detected (32 file(s))` | Fixture `c22_run_artifacts` calls `verify_release_manifest_preflight` against historical Stage 3A manifest | **EXPECTED INTENTIONAL FREEZE GUARD** (preserved per `RLS-1` / `INV-19` until owner-authorized re-freeze) |
| `tests/test_c22_reproducibility_handover.py::test_c22_pos02_operations_guide_contract` | `ManifestDriftError: Frozen release file drift detected (32 file(s))` | Same shared module fixture `c22_run_artifacts` | **EXPECTED INTENTIONAL FREEZE GUARD** |
| `tests/test_c22_reproducibility_handover.py::test_c22_pos03_handover_manifest_inventory` | `ManifestDriftError: Frozen release file drift detected (32 file(s))` | Same shared module fixture `c22_run_artifacts` | **EXPECTED INTENTIONAL FREEZE GUARD** |
| `tests/test_c22_reproducibility_handover.py::test_c22_pos04_demo_rehearsal_protocol` | `ManifestDriftError: Frozen release file drift detected (32 file(s))` | Same shared module fixture `c22_run_artifacts` | **EXPECTED INTENTIONAL FREEZE GUARD** |

**Unexplained or Functional Product Test Failures:** **`0`**.
