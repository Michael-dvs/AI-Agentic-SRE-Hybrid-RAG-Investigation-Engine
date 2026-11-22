# Lab Operations Guide & Standard Operating Procedures (`C22` / `NFR-002`, `NFR-015`, `NFR-017`)

- **Generated At (UTC):** `2026-11-22T06:45:50.414973Z`
- **Frozen Release Manifest:** `evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json` (`self_sha256: fc7e6a702b73f5185d09aca19c5c55a9fb56ead3864531c6c8d46970d1131b9e`)
- **Host Docker Daemon Status During C22 Run:** `DOCKER_INACTIVE`

---

## 1. Resource Envelope & Lab Capacity (`TBD-03`)

- **Target Host:** macOS Apple Silicon (`arm64`, 8 CPU, 16 GiB RAM) or Linux `x86_64` equivalent
- **Approved Docker Allocation Envelope:** Max `4–6 CPU`, `8 GiB RAM` (`8192 MiB`), `15 GiB Disk`
- **Observed Memory Footprint:**
  - Full 12-container Docker Compose stack (`E20`): `652.99 MiB` (idle) to `683.03 MiB` (active) `< 8192 MiB`
  - In-process Python verification runtime (`E21`): `260.23 MiB` RSS

---

## 2. Port Allocation & Network Trust Boundaries (`NFR-001`)

All host bindings are strictly bound to `127.0.0.1` (loopback only). Internal services communicate on `sim_internal_net`.

| Component | Container Port | Host Loopback Binding | Proposal Ref Port | Implementation Mode |
|---|---:|---|---|---|
| `api-gateway` (FastAPI) | `8000` | `127.0.0.1:18080` (`GATEWAY_HOST_PORT`) | `8000` / `8080` | Docker container (`sim_internal_net`) |
| `auth-service` (FastAPI) | `8000` | Internal Docker only | `8001` | Docker container (`sim_internal_net`) |
| `transaction-service` (FastAPI) | `8000` | Internal Docker only | `8002` | Docker container (`sim_internal_net`) |
| `ledger-service` (FastAPI) | `8000` | Internal Docker only | `8003` | Docker container (`sim_internal_net`) |
| `notification-service` (FastAPI) | `8000` | Internal Docker only | `8004` | Docker container (`sim_internal_net`) |
| `prometheus` (Facade) | `9090` | `127.0.0.1:19090` (`PROMETHEUS_HOST_PORT`) | `9090` | Docker container (`127.0.0.1` only) |
| `loki` (Facade) | `3100` | `127.0.0.1:13100` (`LOKI_HOST_PORT`) | `3100` | Docker container (`127.0.0.1` only) |
| `tempo` (Facade) | `3200` | `127.0.0.1:13200` (`TEMPO_HOST_PORT`) | `3200` | Docker container (`127.0.0.1` only) |
| `otel-collector` | `4318` | `127.0.0.1:14318` (`OTEL_HOST_PORT`) | `4318` | Docker container (`127.0.0.1` only) |
| `grafana` (`11.2.0`) | `3000` | `127.0.0.1:13000` (`GRAFANA_HOST_PORT`) | `3000` | Docker container (`127.0.0.1` only) |
| `postgres` (`16-alpine`) | `5432` | Internal Docker only | `5432` | Volume `sre_sim_postgres_data` |
| `rabbitmq` | `5672` | Internal Docker only | `5672` | Internal broker & DLQ |
| `PolicyGateway` & `HybridRetriever` | In-Process | Embedded Python (no open host port) | `8080` / `6333` | Embedded per `ADR-S04` & `ADR-TBD05` |

---

## 3. Environment Template & Secret Hygiene (`NFR-017`, `RULE-001`)

1. Copy `.env.example` to `.env` locally before starting Docker Compose:
   ```bash
   cp .env.example .env
   ```
2. Keep `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` empty for `$0.00` cash spend deterministic baseline & dry-run mode.
3. Never commit `.env` to Git (`git ls-files .env` must remain empty) and never connect real banking credentials or PII.

---

## 4. Standard One-Command Lifecycle Operations (`NFR-002`, `NFR-015`)

| Operation | Command | Purpose & Verification |
|---|---|---|
| **Clean Pre-Wipe** | `./scripts/lab_down.sh --volumes && rm -f orchestrator_state.db*` | Removes containers, networks, PostgreSQL volume, and SQLite state |
| **One-Command Startup** | `./scripts/lab_up.sh` | Starts all 12 containers (`docker compose up -d --build --wait`) |
| **Healthcheck & Seeded Smoke** | `./scripts/lab_smoke.sh` | Verifies `http://127.0.0.1:18080/health/ready` (`200`) and runs `traffic.generator --seed 20261109 --count 6` |
| **Emergency Fault Reset** | `./scripts/fault_reset.sh` | Calls `python3 -m fault_harness.runner --emergency-stop` to clear all synthetic faults |
| **Clean Replay Suite (`AT-013`)** | `python3 scripts/run_c22_clean_replay.py --mode deterministic_baseline` | Executes Replay A, total wipe, Replay B, negative checks, and handover packaging |
| **Graceful Teardown** | `./scripts/lab_down.sh --volumes` | Stops all containers and wipes persistent lab volumes |

---

## 5. Troubleshooting & Honest Fallback Rules

- **Docker Daemon Unavailable:** If Docker Desktop is inactive (`DOCKER_INACTIVE`), report `BLOCKED (DOCKER_DAEMON_UNAVAILABLE)` for live container probes (`--verify-docker` exits `5`) — never fabricate container output.
- **Port Conflict (`C22-NEG-02`):** Inspect occupied ports with `lsof -iTCP -sTCP:LISTEN -P -n` and clear conflicting processes before startup (`run_c22_clean_replay.py` exits with code `2`).
- **Residual SQLite State (`C22-NEG-01`):** Delete `orchestrator_state.db*` and run `./scripts/lab_down.sh --volumes` before starting a clean replay (`run_c22_clean_replay.py` exits with code `3`).
