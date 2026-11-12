# C02 Step 12 — Paket Serah Terima ke Chapter C03 (Handover to C03: Lab, Services, and Synthetic Traffic)

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/handover-to-c03.md`  
> **From Chapter:** C02 — Architecture, Contracts, and Evaluation Design  
> **To Chapter:** C03 — Lab, Services, and Synthetic Traffic (`docs/roadmap/phase-1-foundation/03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md`)  
> **Handover Timestamp:** `2026-11-09T07:33:00Z`  
> **Handover Status:** `AUTHORIZED_TO_START_C03` (Prasyarat G0 dan Baseline Kontrak C02 Terpenuhi)

---

## 1. Input Baseline yang Diserahkan ke C03

Chapter C03 menerima artefak yang telah dibekukan dan tervalidasi secara offline pada `evidence/c02-20261109T070500Z/C02/`:

| Kategori Input | File / Kontrak Acuan di `E02` & `docs/decisions/` | Mandat Implementasi untuk C03 |
|---|---|---|
| **Keputusan Runtime & Topologi (`ADR-S01`)** | `docs/decisions/ADR-S01-service-runtime-and-state-store.md`, `architecture.md` §2 & §6.1 | Bangun 5 layanan sintetis menggunakan **Python 3.12 + FastAPI** di dalam Docker Compose (`linux/arm64`) dengan profil `P1_sim_and_traffic` (`<= 1.2 GiB` total RAM): `api-gateway`, `auth-service`, `transaction-service`, `notification-service`, dan `db-dummy`. |
| **Kontrak Katalog Layanan** | `contracts/service-catalog.v1.schema.json`, `service-api-design.md` §1 | Sediakan katalog layanan statis ber-versi yang memuat ke-5 `service_id` kanonik beserta `dependency_refs` dan `health_endpoints` (`/health/live`, `/health/ready`, `/metrics`). |
| **Kontrak API, Error & Health** | `service-api-design.md` §2 | Implementasikan operasi bisnis sintetis (`POST /api/v1/transactions/transfer`, `POST /internal/v1/auth/verify`, `POST /internal/v1/transactions/execute`, `POST /internal/v1/notifications/dispatch`, `POST /internal/v1/storage/query`) dengan amplop respons/error terstruktur dan propagasi W3C `traceparent` + `X-Correlation-ID`. |
| **Kontrak Sinyal Telemetri Dasar** | `contracts/telemetry-log.v1.schema.json`, `contracts/telemetry-metric.v1.schema.json` | Pastikan setiap layanan memancarkan structured JSON log (dengan `timestamp` UTC `Z`, `service_id`, `service.name`, `environment`, `correlation_id`, `trace_id`, `error_code`) serta metrik RED (`request_rate`, `error_rate`, `latency_p95`). |
| **Batas Keamanan & Isolasi GT (`ADR-S03`)** | `trust-boundaries.md`, `identity-access.csv` | Pastikan layanan sintetis (`TB-01`) menggunakan data akun/transaksi murni dummy, tidak mengekspos variabel lingkungan/rahasia pada endpoint health, dan **tidak** menyertakan `scenario_id` atau label fault di dalam payload HTTP, log, maupun atribut span (`RULE-03`). |
| **Skenario Baseline Sehat (`SC-01`)** | `plans/scenario-oracles.csv` (`SC-01`) | Sediakan generator trafik sintetis ber-seed (`CMP-SIM-03`) yang menghasilkan beban kerja normal (`SC-01`) secara deterministik dan dapat di-reset secara bersih. |

---

## 2. Invarian & Larangan yang Wajib Dipertahankan pada C03

1. **Jangan Mengimplementasikan Fault Injection di Dalam Kode Bisnis Tetap:** Hook injeksi gangguan dikendalikan secara eksternal oleh Fault Injection Harness (`CMP-SIM-04` pada **Chapter C04**), bukan di-hardcode sebagai perilaku permanen layanan C03.
2. **Jangan Membuka Endpoint Mutasi untuk Investigator:** Layanan C03 tidak boleh menyediakan endpoint `restart`, `reconfigure`, atau eksekusi shell yang dapat dipanggil oleh agen investigator (`RULE-02`).
3. **Patuhi Anggaran Memori 16 GB Apple Silicon:** Batasi worker `uvicorn` (`--workers 1` per kontainer di lab) dan tetapkan `mem_limit` pada `docker-compose.yml` agar gabungan 5 layanan sintetis + generator trafik tetap di bawah **1.2 GiB RAM** (`P1_sim_and_traffic`).
4. **Jangan Mengubah Kontrak `v1` Tanpa Revisi:** Apabila implementasi C03 menemukan kebutuhan field baru pada `service-catalog.v1` atau `telemetry-log.v1`, ajukan revisi kontrak dan jalankan ulang validator C02 §8.2; dilarang melakukan perubahan skema diam-diam (*silent drift*).

---

## 3. Daftar Keputusan Hilir yang Tetap Terbuka (Tidak Menghalangi C03)

| ID Keputusan | Chapter Pemilik Penyelesaian | Tenggat Gate | Catatan untuk Pelaksana C03 |
|---|---|---|---|
| `ADR-S02` (Kapasitas Observability) | C05 & C08 | G1 | C03 cukup memancarkan log JSON ke stdout/OTLP dan metrik `/metrics`; koleksi penuh Prometheus/Loki/Tempo dirakit di C05. |
| `ADR-S04` & `TBD-06` (Parameter Hybrid RAG) | C06 & C07 | G1 | Tidak memengaruhi layanan C03. |
| `TBD-05` (Capability Spike Koordinator Dify) | C08 | G1 | Diuji menggunakan `plans/c08-orchestrator-spike.md` di C08. |
| `ADR-S05` & `ADR-S06` (Angka Kuota & Sink AI Trace) | C08 | G1 | Tidak memengaruhi layanan C03. |
| `ADR-S07` (Opsional Mock APM & Dummy ITSM) | C08 / C16 | G1 / G3 | Tidak diimplementasikan di C03. |
| `ADR-S08` (`TBD-08`/`10` — Ukuran Sampel Holdout) | C04–C08 (Freeze di G1) | G1 | C03 hanya menyiapkan trafik baseline `SC-01`. |

