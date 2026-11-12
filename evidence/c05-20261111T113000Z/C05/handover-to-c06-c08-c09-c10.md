# C05 Handover — To Chapters C06, C08, C09, and C10

- **Source Chapter:** `C05 — Telemetry and Service Catalog`
- **Evidence Package ID:** `E05` (`evidence/c05-20261111T113000Z/C05/`)
- **Implementation Status:** `VERIFIED` (`23/23` automated tests `PASS` across C03, C04, and C05)

## 1. Delivered C05 Capabilities & Endpoints

| Component | Container / Module | Internal URL | Localhost Port | Memory Cap / Actual RSS | Role |
|---|---|---|---|---|---|
| **OTel Collector** | `sre-sim-otel-collector` (`observability/backends.py`) | `http://otel-collector:4318` | `127.0.0.1:14318` | `192 MiB` / `63.94 MiB` | OTLP HTTP `/v1/logs` & `/v1/traces` receiver, GT attribute sanitizer, batch forwarder to Loki & Tempo |
| **Prometheus** | `sre-sim-prometheus` (`observability/backends.py`) | `http://prometheus:9090` | `127.0.0.1:19090` | `512 MiB` / `53.29 MiB` | Scrapes `/metrics` across all 5 microservices, serves `/api/v1/red_window`, `/api/v1/query`, `/api/v1/targets`, `/api/v1/alerts` |
| **Loki** | `sre-sim-loki` (`observability/backends.py`) | `http://loki:3100` | `127.0.0.1:13100` | `512 MiB` / `42.12 MiB` | Structured JSON log ingestion (`/loki/api/v1/push`) and bounded query (`/loki/api/v1/query_range`) |
| **Tempo** | `sre-sim-tempo` (`observability/backends.py`) | `http://tempo:3200` | `127.0.0.1:13200` | `384 MiB` / `40.90 MiB` | Distributed W3C trace store (`/v1/traces`, `/api/traces/{trace_id}`, `/api/search`) + reversible `POST /_sim/outage` for `SC-09` |
| **Grafana** | `sre-sim-grafana` (`observability/backends.py`) | `http://grafana:3000` | `127.0.0.1:13000` | `256 MiB` / `40.00 MiB` | Read-only human visualization dashboard (`sre-sim-overview-v1`) |
| **Service Catalog & Dependency Graph** | `observability/catalog.py` | `http://api-gateway:8000/api/v1/topology` | `127.0.0.1:18080` | Included in services | Produces 6 `service-catalog.v1` records (`5` services + `db-dummy`) and 5 `dependency-edge.v1` edges (`trace_observed` + `cascade_analysis` for `AT-016`) |
| **Alert Evaluator & Signer** | `observability/alerts.py` | `http://prometheus:9090/api/v1/alerts` | `127.0.0.1:19090` | Included in Prometheus | Evaluates `observability/alert-rules.yml` to emit `alert-event.v1` payloads signed with `X-Principal-ID: principal:alert-intake`, `X-Webhook-Token`, and `X-Alert-Signature` |

## 2. Downstream Handover Contracts

1. **To Chapter C06 (`Synthetic Knowledge Base & Corpus`):**
   - Service Catalog identifiers (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`, `db-dummy`), `environment: "lab"`, `build_version: "0.1.0-sim"`, and deterministic `error_code` / `alert_type` enums are frozen and ready for SOP/runbook/post-mortem metadata alignment.
2. **To Chapter C08 (`Gate G1 Foundation Verification`):**
   - `E05` provides verified evidence for `G1-03` (Observability & Service Catalog operational) and `G1-07` (`AT-001` foundation telemetry + `EV-02` / `AT-009` missing trace source behavior).
3. **To Chapter C09 (`MCP Read-Only Tool Gateway & Telemetry Adapters`):**
   - `ObservabilityClient` (`observability/client.py`) and the backend endpoints (`Prometheus :9090`, `Loki :3100`, `Tempo :3200`, `Gateway :8000/api/v1/topology`) provide the exact typed telemetry sources for `get_service_metrics`, `search_error_logs`, `get_trace_summary`, and `get_service_dependencies`, including `status: "unavailable"`, `data_quality: "unavailable"`, `error_code: "SOURCE_UNAVAILABLE"` on `SC-09`.
4. **To Chapter C10 (`Alert Intake, Deduplication & Correlation`):**
   - `observability/alerts.py` and `GET /api/v1/alerts` produce schema-valid `alert-event.v1.schema.json` payloads and HMAC-SHA256 webhook headers (`X-Principal-ID: principal:alert-intake`, `X-Webhook-Token`, `X-Alert-Signature`) ready for C10 deduplication, correlation windowing, and centralized `incident_id` generation (`OPS-01`, `AT-003`).

