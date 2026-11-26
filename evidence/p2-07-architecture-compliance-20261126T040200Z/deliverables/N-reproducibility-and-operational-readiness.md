# Deliverable N — Reproducibility, Packaging, and Operational Readiness Report
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Scope:** Independent audit of dependency locking, Python/SSL/async environment reproducibility, Docker Compose operational scripts, operator handbook accuracy, clean-state replay (`AT-013`), and rollback/restore readiness (`Work Package P`).

---

## 1. Runtime & Dependency Lock Audit (`P1`)

| Dimension | Observed State | Reproducibility Verdict | Action / Recommendation |
|---|---|---|---|
| **Host OS & Architecture** | macOS 26.3.1 (`arm64`, Apple M2, 8 cores, 16 GiB RAM) | Matches baseline target (`NFR-001`) | Verified |
| **Python & Virtualenv** | Python `3.12.14` in `.venv` (`pytest 8.3.4`, `anyio 4.16.0`, `httpx 0.28.1`, `rich 14.3.3`, `jsonschema 4.26.0`, `fastapi 0.135.1`) | Operational locally | Verified |
| **Dependency Pinning (`requirements.txt`)** | `requirements.txt` declares **12 top-level packages using minimum `>=` specifiers** (not exact `==` pins or a `requirements.lock` / `uv.lock`), whereas `.venv` currently contains **283 installed packages** | **`PARTIAL` (`FIND-P207-07`)** | Generate a frozen `requirements.lock` (`pip freeze`) upon owner release re-freeze so clean machines reproduce exact transitive versions |
| **Optional Dense Embedding Packages** | Neither `sentence-transformers` nor `fastembed` is in `requirements.txt` or `.venv` | **`PARTIAL` (`FIND-P207-03`)** | Runtime deterministically uses `deterministic_local_384d` (`0` network downloads, `HF_HUB_OFFLINE=1` safe). Documented honestly in Deliverables C, E, J, O |
| **SSL / CA Bundle Behavior** | Host OpenSSL `3.6.4` loads `123` CAs from `/etc/ssl/cert.pem` (`SSL_CERT_FILE`) and `113` CAs from `certifi==2026.11.20` (`httpx.create_ssl_context(trust_env=False)`) | **Resolved / Explained** | Historical `P2-06` `[X509: NO_CERTIFICATE_OR_CRL_FOUND]` was caused by restricted sandbox MAC blocking `/etc/ssl/cert.pem` when `SSL_CERT_FILE=/etc/ssl/cert.pem` was inherited; `certifi` or standard host execution works cleanly |
| **Async Test Execution (`anyio`)** | `tests/test_banking_simulator.py` has 3 `@pytest.mark.anyio` tests. Default `.venv/bin/python -m pytest` autoloads `anyio` (`6/6 PASS`); when `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set without `-p anyio`, those 3 tests skip | **Verified (`0` skips with `-p anyio`)** | Updated `README.md` and `HANDBOOK_OPERASIONAL.md` to specify `pytest -p anyio` |

---

## 2. Docker & Operational Script Readiness (`P2`, `P3`)

1. **Live Container Stack (`docker-compose.yml`):**
   - Docker `29.8.2` + Docker Compose `v5.5.1` active.
   - All **12 `sre-sim-*` containers** (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`, `postgres`, `rabbitmq`, `otel-collector`, `prometheus`, `loki`, `tempo`, `grafana`) verified `Up (healthy)` at **`818.81 MiB` total RAM** (`27.8%` of their `2,944 MiB` combined container limits, and `10.0%` of the `8 GiB` PoC lab cap).
2. **Lifecycle Scripts Verified:**
   - `scripts/lab_up.sh`: wraps `docker compose up -d --build --wait` cleanly.
   - `scripts/lab_smoke.sh`: verifies `/health/ready` and seeded transactions cleanly.
   - `scripts/fault_reset.sh` & `fault_harness.runner.emergency_stop_all`: verified across all 14 live fault scenarios (`14/14` clean recovery).
   - `scripts/lab_down.sh`: scopes teardown strictly to the Compose project (`docker compose down`) without touching unrelated Docker containers on the host.
3. **Operator Handbook Corrections Applied (`DEF-P207-03`):**
   - Fixed invalid `--target` flag -> `--gateway-url` on `python3 -m fault_harness.runner` (`docs/HANDBOOK_OPERASIONAL.md:178-184`).
   - Clarified `SC-03` (DB query latency spike) vs `SC-05` (connection pool exhaustion).
   - Fixed nonexistent `artifacts/handover/inc-sc03/dossier.json` -> `dossier_final.json` for `--view-only` and documented pending `HUMAN_REVIEW` input for `--action APPROVE`.
   - Fixed missing `--tests-completed` on `run_c21_preflight.py`, removed nonexistent `--split H-G4` on `run_c21_benchmark.py`, and fixed nonexistent `--scan-dir`/`--fail-on-violation` flags on `dlp_sink_scanner.py`.

---

## 3. Clean-State Replay & Rollback Readiness (`AT-013`, `NFR-014`)

- **Clean Replay (`AT-013` / `KPI-13`):** Historical `E22` dual clean-environment replay (`clean-replay-a` vs `clean-replay-b`, `KPI-13 = 1.0`, `6/6` scenarios identical after total state wipe) verified intact, and complemented in `P2-07` by live `14/14` `SC-01`–`SC-14` execution against the running Docker stack.
- **Component Rollback & Backup Restore (`O2` / `NFR-014`):** All `4/4` deterministic drills in `scripts/run_rollback_restore.py` (`workflow_and_tool_schema`, `model_and_prompt`, `kb_index_alias_and_cache`, and `local_state_and_audit_chain` SQLite corruption + restore) re-executed and passed (`100% PASS`, `auto_remediation_triggered = False`).
