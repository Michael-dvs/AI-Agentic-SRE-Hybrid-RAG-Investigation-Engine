# Deliverable K — Live Integration, Observability, Capacity, and Resilience Report
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Primary Evidence Artifact:** [`../scenarios/sc01_sc14_live_verification.json`](../scenarios/sc01_sc14_live_verification.json)

---

## 1. Live Docker Environment & Container Footprint (`D3`, `O1`)

- **Host:** macOS `arm64` (Apple M2, 8 CPU cores, `16 GiB` RAM), Docker `29.8.2`, Docker Compose `v5.5.1`.
- **Container Health:** All **12 `sre-sim-*` containers** verified `Up (healthy)`:
  - Microservices & Data Plane (`sim_internal_net`, `internal: true`): `sre-sim-api-gateway` (`127.0.0.1:18080->8000`), `sre-sim-auth-service`, `sre-sim-transaction-service`, `sre-sim-ledger-service`, `sre-sim-notification-service`, `sre-sim-postgres` (`postgres:16-alpine`), `sre-sim-rabbitmq` (`rabbitmq:3.13-management-alpine`).
  - Observability Plane (`sim_obs_net`, loopback ports only): `sre-sim-otel-collector` (`:14318`), `sre-sim-prometheus` (`:19090`), `sre-sim-loki` (`:13100`), `sre-sim-tempo` (`:13200`), `sre-sim-grafana` (`grafana/grafana:11.2.0` on `:13000`).
- **Measured Live Memory Usage (`docker stats --no-stream`):**
  - Combined 12-container active RSS: **`818.81 MiB`** (within `2,944 MiB` total container limits and **`10.0%` of the `8,192 MiB` PoC lab cap**).
  - Investigation Python process peak RSS during `SC-01`–`SC-14` + capacity waves: **`235.70 MiB`**.

---

## 2. Live Observability & Grafana Proxy Verification (`Work Package E`)

All three telemetry modalities were verified both directly via `gateway/adapters/{metrics,logs,traces}.py` and through the live **Grafana `11.2.0` HTTP datasource proxy** during active fault injection (`SC-02`):
- `GET /api/health` -> `HTTP 200` (`database: "ok"`, `version: "11.2.0"`).
- `GET /api/datasources` -> `HTTP 200` (`prom-sim-lab`, `loki-sim-lab`, `tempo-sim-lab` provisioned).
- `GET /api/search?query=SRE` -> `HTTP 200` (`uid: "sre-sim-overview-v1"`).
- **Live Grafana Datasource Proxy Queries:**
  - Prometheus proxy (`/api/datasources/proxy/uid/prom-sim-lab/api/v1/query?query=sim_red_error_rate_ratio`) -> **`HTTP 200`**.
  - Loki proxy (`/api/datasources/proxy/uid/loki-sim-lab/loki/api/v1/query_range?query={service_name="transaction-service"}`) -> **`HTTP 200`**.
  - Tempo proxy (`/api/datasources/proxy/uid/tempo-sim-lab/api/traces/<trace_id>`) -> **`HTTP 200`**.

---

## 3. Capacity, Burst Deduplication, and Concurrency Measurements (`Work Package O1`)

| Workload Test | Input Load | Observed Result | Latency & Resource Metrics | Verdict |
|---|---|---|---|---|
| **`OPS-01` Simultaneous Duplicate Storm** | `100` concurrent identical alerts (barrier-synchronized threads) | `1` unique incident (`create=1`, `merge=99`, `split=0`, `backpressure=0`), `1` dossier generated (`final_hit_count=100`) | Throughput: `161.56 alerts/s`, P95 dossier latency: `611.97 ms`, Peak RSS: `235.70 MiB` | **PASS** |
| **Concurrency Wave — Level `5`** | `5` simultaneous distinct service alerts | `5/5` accepted, `5/5` dossiers generated, `0` rejected | Throughput: `1.83 incidents/s`, P50: `2,640.16 ms`, P95: `2,732.70 ms`, Peak RSS: `235.70 MiB` | **PASS** |
| **Concurrency Wave — Level `20`** | `20` simultaneous distinct service alerts | `20/20` accepted, `20/20` dossiers generated, `0` rejected | Throughput: `1.71 incidents/s`, P50: `4,436.86 ms`, P95: `5,741.80 ms`, Peak RSS: `235.70 MiB` (`<< 8,192 MiB`) | **PASS** |

---

## 4. Resilience & Deterministic Rollback/Restore Drills (`Work Package O2`)

All `4/4` deterministic component rollback and corruption-restore drills (`scripts/run_rollback_restore.py`) were executed in an isolated temporary workspace during `P2-07`:
1. **`workflow_and_tool_schema` (`NFR-014`):** Canary tighter window cap (`1800s`) rejected `2400s` query (`WINDOW_EXCEEDED`); 1-step rollback restored exact baseline SHA-256 hash while preserving hard `3601s` `MCP-02` enforcement -> **`PASS`**.
2. **`model_and_prompt` (`NFR-014`):** Malformed non-JSON canary model output safely triggered `manual_fallback` without corrupting SQLite state; rollback to `replay-stable-v1` restored `agentic_llm` synthesis and exact prompt template hash -> **`PASS`**.
3. **`kb_index_alias_and_cache` (`FR-RAG-008`):** Tombstoned staging manifest rolled back atomically to `kb-idx-20261111-v1` (`c9ee96da...`), cleared query cache, and kept `SOP-LEDGER-001@1.0.0` (`obsolete`) excluded -> **`PASS`**.
4. **`local_state_and_audit_chain` (`NFR-014`):** Simulated binary corruption of SQLite DB + tampered `security_audit.jsonl`; detected corruption, restored from online SQLite backup + audit checkpoint, verified canonical dossier hash and SHA-256 chain integrity across post-restore appends -> **`PASS`**.
- **Auto-Remediation Check Across All Drills:** `auto_remediation_triggered == False`.
