# ADR-S01: Runtime Layanan Sintetis, Topologi Minimum, dan Kontrak State Store

- **ID Keputusan:** `ADR-S01`
- **Status:** `ACCEPTED` (Bagian Runtime Layanan Sintetis C03 & Kontrak State Store); `CANDIDATE` untuk Engine Koordinator (menunggu spike C08 `TBD-05`)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael` (Project Owner / Initiator — Independent Simulation PoC)
- **Chapter Terkait:** `C02`, `C03`, `C04`, `C08`, `C11`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/architecture.md`, `evidence/c02-20261109T070500Z/C02/service-api-design.md`

---

## 1. Konteks & Permasalahan

Proyek membutuhkan minimal 3 layanan microservices sintetis yang saling bergantung (`FR-SIM-001`) beserta mekanisme penyimpanan state workflow investigasi yang persisten (`FR-AGT-001`, `FR-AGT-008`) di atas perangkat keras lokal **macOS Apple Silicon 16 GB RAM** dengan anggaran memori Docker Lab maksimal **8 GiB** dan anggaran biaya **`$0.00`**.

---

## 2. Opsi yang Dipertimbangkan

1. **Opsi 1 (Terpilih untuk Layanan C03): Python 3.12 + FastAPI (`uvicorn --workers 1`) di dalam Docker Compose (`linux/arm64`) dengan 5 layanan sintetis (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service` [menggantikan alias kandidat awal `db-dummy`], dan `notification-service`) + komponen pendukung ringan (`postgres:16-alpine` untuk persistensi Ledger dan `rabbitmq:3.13-alpine` untuk antrean event asinkron).**
2. **Opsi 2: Polyglot Microservices (Go + Java Spring Boot + Node.js) dengan Message Broker Kafka/ZooKeeper berat.** Ditolak karena overhead JVM dan klaster Kafka melampaui anggaran 1.2 GiB RAM untuk layer simulasi (`P1_sim_and_traffic`).
3. **Opsi 3: In-Memory Single Process Mock tanpa Container Isolation.** Ditolak karena tidak menghasilkan sinyal telemetri jaringan/kontainer dan batas kepercayaan (`TB-01`..`TB-05`) yang realistis untuk pengujian C03–C21.

---

## 3. Keputusan

1. **Bahasa, Framework, dan 5 Layanan Sintetis (`CONFIRMED`):** Gunakan **Python 3.12** dan **FastAPI** untuk tepat lima layanan microservices sintetis (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`) yang dideploy melalui **Docker Compose (`linux/arm64`)**, didukung oleh dua komponen infrastruktur pendukung non-microservice (`postgres:16-alpine` untuk persistensi `ledger-service` dan `rabbitmq:3.13-alpine` untuk pengiriman event asinkron dari `transaction-service` ke `notification-service`) dengan plafon memori gabungan `<= 1.2 GiB` (`P1_sim_and_traffic`). Alias `db-dummy` tetap dipertahankan dalam skema kontrak v1 untuk kompatibilitas mundur dengan contoh uji C02.
2. **Kontrak Katalog, Health, dan Propagasi Konteks (`ACCEPTED`):**
   - Setiap layanan wajib terdaftar di `service-catalog.v1.schema.json`.
   - Setiap layanan menyediakan endpoint terpisah `GET /health/live` (dan `/healthz`), `GET /health/ready` (dan `/readyz`), serta `GET /metrics`.
   - Propagasi trace dan korelasi menggunakan header W3C `traceparent` dan `X-Correlation-ID`.
3. **Kontrak Persistence State Workflow (`ACCEPTED`):**
   - Transisi state mengikuti `workflow-event.v1.schema.json` dengan `idempotency_key` wajib.
   - Pemilihan engine orkestrasi akhir (Dify vs LangGraph/Custom Python + SQLite/PostgreSQL) ditangguhkan ke capability spike **Chapter C08** (`ADR-TBD05` / `plans/c08-orchestrator-spike.md`).

---

## 4. Konsekuensi

- **Positif:** Jejak memori ringan (~60–100 MiB per kontainer FastAPI, ~45 MiB untuk `postgres:16-alpine`, ~110 MiB untuk `rabbitmq:3.13-alpine`), mendukung alur sinkron (`api-gateway -> auth-service -> transaction-service -> ledger-service -> postgres`) dan asinkron (`transaction-service -> rabbitmq -> notification-service`) secara autentik, serta memungkinkan C03 langsung dijalankan di dalam batas RAM 16 GB.
- **Batasan:** Komponen pendukung (`postgres` dan `rabbitmq`) berada di jaringan internal Docker Compose (`sim_internal_net`) tanpa eksposur port publik ke host secara default.

