# Catatan Handover Chapter C03 menuju Chapter C04 & C05

- **ID Bukti:** `E03` (`handover-to-c04-and-c05`)
- **Run ID:** `c03-20261109T084600Z`
- **Dari Chapter:** `C03 — Synthetic Microservices Lab & Traffic Baseline`
- **Menuju Chapter:**
  - `C04 — Fault Injection Harness & Ground Truth Isolation`
  - `C05 — Observability Pipeline & Service Catalog`
- **Tanggal:** `2026-11-09`

---

## 1. Ringkasan Penyelesaian C03

1. **Lima Layanan FastAPI Berjalan (`FR-SIM-001`):**
   - `api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, dan `notification-service` telah diimplementasikan, dikontainerisasi (`linux/arm64`), dan diverifikasi pada jaringan internal Docker Compose (`sim_internal_net`).
2. **Integrasi Penyimpanan & Antrean Asinkron:**
   - `ledger-service` menyimpan transaksi secara persisten ke `postgres:16-alpine` (`volume: sim_postgres_data`) dengan pencegahan duplikasi atomik (`ON CONFLICT (idempotency_key) DO NOTHING`).
   - `transaction-service` menerbitkan event `transaction.completed` ke `rabbitmq:3.13-alpine` (`notifications.transaction.completed`), dan `notification-service` mengonsumsinya secara asinkron dengan `basic_ack`, *bounded retry* (`MAX_RETRIES=3`), serta *Dead-Letter Queue* (`notifications.transaction.dlq`).
3. **Generator Trafik Sintetis Deterministik (`FR-SIM-002`):**
   - Modul `traffic/generator.py` mendukung profil `normal` dan `spike`, `seed` tetap (`20261109`), pembatasan `rate`/`duration`/`concurrency`, serta penolakan keras terhadap target non-lokal (`RULE-009`).

---

## 2. Titik Integrasi untuk Chapter C04 (Fault Injection & Ground Truth)

- **Jangan mencampur kode fault control ke dalam tool plane agen (`RULE-003`):** Harness C04 harus berjalan sebagai kontrol terpisah yang menyuntikkan gangguan pada layer layanan/jaringan/dependensi tanpa membocorkan `scenario_id` atau label *ground truth* ke stdout log layanan (`telemetry-log.v1.schema.json`), header HTTP, ataupun payload error.
- **Perilaku Kegagalan Dependensi yang Siap Diuji di C04:**
  - Kegagalan `postgres` atau `ledger-service` menghasilkan `503 ERR_DB_UNAVAILABLE` / `503 ERR_LEDGER_UPSTREAM_UNAVAILABLE`.
  - Kegagalan `auth-service` menghasilkan `503 ERR_AUTH_UPSTREAM_UNAVAILABLE` atau lonjakan `401`/`403`.
  - Kegagalan/gangguan `rabbitmq` menghasilkan `503 ERR_QUEUE_UNAVAILABLE` atau penumpukan pesan pada `notifications.transaction.completed` / `notifications.transaction.dlq`.

---

## 3. Titik Integrasi untuk Chapter C05 (Observability Pipeline & Service Catalog)

- **Structured Logs (`FR-OBS-001`):** Kelima layanan menulis satu objek JSON per baris ke `stdout` yang mematuhi `urn:sre-sim:contract:telemetry-log:1` (`schema_version`, `timestamp` UTC `Z`, `severity`, `service.name`, `service_id`, `environment`, `instance_id`, `build_version`, `event_type`, `correlation_id`, `trace_id`, `span_id`, `trace_absent_reason`, `error_code`, `message`, `sanitized: true`). Siap dikoleksi oleh Promtail/Alloy menuju Loki pada C05.
- **RED Metrics (`FR-OBS-002`):** Setiap layanan menyediakan endpoint `GET /metrics` dalam format teks Prometheus (`sim_red_request_rate_rps`, `sim_red_error_rate_ratio`, `sim_red_latency_p95_ms`, `sim_http_requests_total`, `sim_http_errors_total`) maupun JSON (`GET /metrics?format=json` sesuai `telemetry-metric.v1.schema.json`). Siap di-*scrape* oleh Prometheus pada C05.
- **Trace Context & Service Catalog (`FR-OBS-003`, `FR-DEP-001`):**
  - Header W3C `traceparent` dan `X-Correlation-ID` telah diteruskan di seluruh hop sinkron dan asinkron; ekspor span OTLP ke backend Tempo akan diselesaikan pada C05 (sehingga `AT-001` bagian backend trace baru akan diklaim pada C05).
  - Endpoint `GET /catalog` di tiap layanan dan `GET /api/v1/topology` di `api-gateway` menghasilkan entri katalog (`service-catalog.v1.schema.json`) dan *dependency edges* (`dependency-edge.v1.schema.json`).

