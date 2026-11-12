# Synthetic Microservices, Telemetry Signals, Service Catalog, and Alert Intake Design — Chapter C02

- **Run ID:** `c02-20261109T070500Z`
- **Decision References:** `ADR-S01`, `ADR-S02`, `TBD-07`, `D-C02-01`, `D-C02-02`
- **Timestamp (UTC):** `2026-11-09T07:17:00Z` (`2026-11-09T14:17:00+07:00` WIB)
- **Author / Approver (`owner_ref`):** `project-initiator-michael`
- **Check ID:** `C02-CON-005` (`PASS`)

---

## 1. Arsitektur 5 Layanan Simulasi Python + FastAPI (`TBD-07` & `ADR-S01`)

Untuk memenuhi `FR-SIM-001` (minimal 3 layanan terhubung dengan $\ge 2$ ketergantungan) sekaligus menyediakan sumber sinyal autentik bagi seluruh 14 skenario (`SC-01` s/d `SC-14`) di dalam batas memori Docker Compose `8 GiB RAM`, topologi layanan simulasi terdiri atas **5 layanan FastAPI ringan**:

```mermaid
flowchart LR
  TG["Traffic Generator<br/>(Seeded httpx)"] -->|POST /api/v1/orders<br/>traceparent + X-Correlation-ID| AGW["1. api-gateway<br/>(FastAPI :8001)"]
  AGW -->|POST /internal/auth/verify<br/>Hop 1a (Sync HTTP)| AUTH["2. auth-service<br/>(FastAPI :8002)"]
  AGW -->|POST /internal/transactions/execute<br/>Hop 1b (Sync HTTP)| TX["3. transaction-service<br/>(FastAPI :8003)"]
  TX -->|POST /internal/db/query<br/>Hop 2a (Sync HTTP + Pool)| DB["5. db-dummy<br/>(FastAPI + SQLite :8005)"]
  TX -->|POST /internal/queue/enqueue<br/>Hop 2b (Async Queue Event)| NOTIF["4. notification-service<br/>(FastAPI Queue Consumer :8004)"]
```

### 1.1 Spesifikasi Peran, Endpoint Kandidat, & Mode Kegagalan per Layanan

> **Catatan Status (`[S-C02]`):** Port dan route di bawah ini adalah spesifikasi kontrak untuk diimplementasikan pada **Chapter `C03`** dan **`C04`**; belum ada layanan yang dijalankan pada Chapter `C02`.

| `service_id` / `service.name` | Peran Bisnis Sintetis | Endpoint Bisnis & Kesehatan (`C03`) | Ketergantungan Hilir (`dependency_refs`) | Hook Skenario Fault (`C04` — Khusus `principal:operator-harness`) |
|---|---|---|---|---|
| **`api-gateway`** | Entrypoint HTTP publik lab, validasi skema request, orkestrasi panggilan ke `auth-service` lalu `transaction-service`, dan propagasi konteks trace W3C | `POST /api/v1/transactions` <br>`GET /healthz` <br>`GET /readyz` <br>`GET /metrics` | `auth-service`, `transaction-service` | Timeout propagasi hulu (`SC-03`, `SC-04`), burst alert (`SC-12`) |
| **`auth-service`** | Verifikasi token bearer sintetis (`SYNTH-JWT-*`) dan evaluasi aturan otorisasi peran dummy | `POST /internal/auth/verify` <br>`GET /healthz` <br>`GET /readyz` <br>`GET /metrics` | Tidak ada (leaf service untuk cabang auth) | `SC-06` (Auth config mismatch yang meningkatkan 401/403 abnormal vs normal client bad-token; atau 500 internal auth error), `SC-08` (independent fault #1) |
| **`transaction-service`** | Pemrosesan transaksi buku besar sintetis tanpa dana nyata; memanggil `db-dummy` secara sinkron dan menerbitkan event notifikasi ke `notification-service` | `POST /internal/transactions/execute` <br>`GET /healthz` <br>`GET /readyz` <br>`GET /metrics` | `db-dummy`, `notification-service` | `SC-02` (HTTP 5xx exception), `SC-03` (downstream DB latency cascade), `SC-04` (downstream DB unavailable cascade), `SC-05` (connection pool exhaustion), `SC-11` (adversarial prompt injection payload di dalam log error) |
| **`notification-service`** | Antrean in-memory/SQLite ringan dan worker asinkron yang memproses event notifikasi transaksi | `POST /internal/notifications/enqueue` <br>`GET /internal/notifications/queue-stats` <br>`GET /healthz`, `GET /readyz`, `GET /metrics` | Tidak ada (leaf consumer service) | `SC-07` (artificial consumer throttling / queue backlog growth), `SC-08` (independent fault #2), `SC-14` (noise log/deployment event berdekatan waktu untuk uji korelasi mengecoh) |
| **`db-dummy`** | Penyimpanan state transaksi sintetis berbasis FastAPI + SQLite/in-memory dengan simulator *connection pool* dan penundaan kueri terprogram | `POST /internal/db/execute` <br>`GET /healthz` <br>`GET /readyz` <br>`GET /metrics` | Tidak ada (leaf storage service) | `SC-03` (artificial query latency `700–1500 ms`), `SC-04` (connection refused / `503 Service Unavailable`), `SC-05` (semaphore pool limit saturated $\rightarrow$ `POOL_EXHAUSTED`) |

### 1.2 Kontrak Liveness (`/healthz`), Readiness (`/readyz`), & Error Envelope

1. **Liveness (`GET /healthz`):**
   - Mengembalikan HTTP `200 OK`:
     ```json
     {
       "status": "alive",
       "service_id": "transaction-service",
       "environment": "lab",
       "instance_id": "transaction-service-1",
       "build_version": "0.1.0-sim",
       "timestamp": "2026-11-09T09:00:00Z"
     }
     ```
   - Tidak pernah mengembalikan dump variabel lingkungan atau secret (`NFR-017`).
2. **Readiness (`GET /readyz`):**
   - Mengembalikan HTTP `200 OK` jika layanan siap melayani kontrak, atau HTTP `503 Service Unavailable` dengan `reason_code` terketik (`DEPENDENCY_UNREADY`, `POOL_EXHAUSTED`, `FAULT_INJECTED_UNAVAILABLE`).
3. **Standard Service Error Envelope:**
   - Setiap respons error HTTP (`4xx`/`5xx`) menggunakan struktur deterministik yang juga dicatat ke structured log tanpa membocorkan `scenario_id`:
     ```json
     {
       "error_code": "DB_UPSTREAM_TIMEOUT",
       "message": "Upstream storage request exceeded deadline of 1000ms",
       "service_id": "transaction-service",
       "environment": "lab",
       "correlation_id": "corr-tx-9001",
       "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
       "timestamp": "2026-11-09T09:01:12Z"
     }
     ```

---

## 2. Kontrak Sinyal Telemetri & Service Catalog (`Step 05 Schemas`)

1. **Service Catalog (`contracts/service-catalog.v1.schema.json`):**
   - Menyimpan entri per layanan dengan field wajib: `schema_version`, `service_id`, `service.name`, `environment`, `application`, `component`, `instance_id`, `build_version`, `owner_ref`, `dependency_refs`, `health_endpoints`, dan `updated_at`.
2. **Structured Log (`contracts/telemetry-log.v1.schema.json`):**
   - Field wajib: `schema_version`, `timestamp` (UTC `Z`), `severity` (`DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`), `service.name`, `service_id`, `environment`, `instance_id`, `build_version`, `event_type`, `correlation_id`, `trace_id` (nullable hanya jika terdapat `trace_absent_reason` eksplisit), `span_id` (nullable), `error_code` (nullable), `message` (*untrusted string*), dan `attributes` (tanpa field `scenario_id` atau `expected_root_cause`).
3. **RED Metric Observation (`contracts/telemetry-metric.v1.schema.json`):**
   - Field wajib: `schema_version`, `service_id`, `service.name`, `environment`, `build_version`, `metric_enum` (`request_rate`, `error_rate`, `latency_p95`), `value` (number), `unit` (`requests/s`, `ratio`, `ms`), `sample_at` (UTC `Z`), `window_seconds`, `aggregation` (`rate`, `ratio`, `p95`), `source_ref`, dan `data_quality` (`complete`, `partial`).
4. **Dependency Edge (`contracts/dependency-edge.v1.schema.json`):**
   - Membedakan secara tegas antara edge topologi statis (`source_kind: "catalog_declared"`) dan edge yang teramati dari span/log aktual (`source_kind: "trace_observed"`).
   - Field wajib: `schema_version`, `edge_id`, `from_service_id`, `to_service_id`, `environment`, `deployment_version`, `relation_type` (`sync_http`, `async_queue`, `storage_call`), `source_kind`, `source_ref`, `observed_at`, `freshness_status` (`fresh`, `stale`), `confidence` (`[0.0 .. 1.0]`), dan `error_propagation_observed` (boolean).

---

## 3. Kontrak Alert Intake, Verifikasi Signature, & Deduplikasi (`FR-OBS-004`, `FR-OBS-005`, `OPS-01`)

1. **Verifikasi Keaslian Sebelum Kanonikalisasi:**
   - Webhook alert ke `Alert Intake` wajib menyertakan header `X-Alert-Signature` (HMAC-SHA256 atas raw request body). Signature **tidak** ditaruh sebagai field body yang dipercaya begitu saja.
2. **Skema Payload Alert (`contracts/alert-event.v1.schema.json`):**
   - Field wajib: `schema_version`, `alert_id`, `source_id`, `service_id`, `environment`, `alert_type`, `severity` (`low`, `medium`, `high`, `critical`), `event_time`, `window_start`, `window_end`, `build_version` (nullable), `error_code` (nullable), `trace_id` (nullable), `summary`, dan `source_ref`.
   - **Pencegahan Kebocoran GT:** Skema menetapkan `additionalProperties: false` sehingga jika sebuah alert uji tidak sengaja menyertakan `"scenario_id": "SC-02"` atau `"expected_root_cause": "db-dummy"`, alert tersebut **langsung ditolak (`SCHEMA_INVALID`)** pada pintu masuk.
3. **Formula Fingerprint Deterministik & Aturan Merge/Split (`OPS-01` & `SC-08`):**
   - Kunci deduplikasi dihitung secara deterministik:
     $$\text{fingerprint} = \text{SHA256}\left(\text{service\_id} \parallel \text{environment} \parallel \text{alert\_type} \parallel \text{coalesce(error\_code, "NONE")} \parallel \lfloor \text{event\_time} / \text{bucket\_seconds} \rfloor\right)$$
   - Jika 100 alert identik tiba dalam jendela `dedup_ttl_seconds` (`SC-12` / `OPS-01`), alert pertama membuka `incident_id` baru dan 99 alert berikutnya meningkatkan `duplicate_count` pada `incident_id` tersebut (`dedup_action = "deduplicated_existing_incident"`) tanpa memicu 99 workflow baru.
   - Jika dua alert berasal dari layanan yang tidak memiliki jalur ketergantungan aktif atau memiliki error domain yang terpisah (`SC-08`: mis. `auth-service` config mismatch bersamaan dengan `notification-service` consumer lag), Correlator mempertahankan dua `incident_id` independen (atau mencatat `correlation_action = "kept_independent"`) dan **tidak** memaksakan penggabungan menjadi satu root cause tunggal.

