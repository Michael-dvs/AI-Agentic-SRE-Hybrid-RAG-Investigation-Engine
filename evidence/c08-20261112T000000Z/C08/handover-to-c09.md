# Dokumen Serah Terima C08 ke C09 (Handover to Phase 2 — Controlled Integration)

- **Dari:** `Chapter C08 — Secure Gateway and Foundation G1` (Fase 1 — Foundation)
- **Kepada:** `Chapter C09 — Read-Only Telemetry Adapters` (Fase 2 — Controlled Integration)
- **Tanggal:** `2026-11-12T00:00:00Z`
- **Status Gate G1:** **`PASSED`** (Otorisasi Masuk Fase 2 Diberikan)
- **Paket Bukti Terkait:** `evidence/c08-20261112T000000Z/C08/`

---

## 1. Status Fondasi yang Diserahterimakan

Fase 1 (Fondasi Teknis) telah selesai secara menyeluruh dengan seluruh 8 chapter (`C01` s/d `C08`) tervalidasi dan disahkan melalui kelulusan **Gate G1**:

1. **Laboratorium Microservices Sintetis (`C03` / `E03`):**
   - 5 microservices FastAPI (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`) berjalan stabil di Docker Compose.
   - Generator trafik sintetis menghasilkan beban transaksi ber-seed dengan correlation ID dan W3C trace context.
2. **Fault Injection Harness & Isolasi Ground Truth (`C04` / `E04`):**
   - 14 skenario gangguan teruji (`SC-01` s/d `SC-14`) dengan kemampuan injeksi dan pemulihan bersih 100%.
   - Registry Ground Truth terisolasi ketat di `restricted/gt_registry/` dengan kunci SHA-256 yang telah dibekukan.
3. **Infrastruktur Telemetri Lab (`C05` / `E05`):**
   - Prometheus (RED metrics), Loki (structured JSON logs), Tempo (distributed tracing), dan Grafana berjalan sehat.
   - Service Catalog memetakan topologi dependensi statis 5 microservices.
4. **Knowledge Base Sintetis & Hybrid RAG (`C06`, `C07` / `E06`, `E07`):**
   - 71 chunks pengetahuan (SOP, Runbook, Known Errors, Catatan Arsitektur) terindeks.
   - Mesin *Hybrid Retrieval* (BM25 + FastEmbed Dense + RRF $k=60$) aktif dengan pencegahan SOP usang (`RAG-01`) dan penolakan kueri di luar korpus (`status: "no_match"`).
5. **Secure Read-Only Policy Gateway (`C08` / `E08`):**
   - Paket `gateway/` aktif menegakkan 8 tahap evaluasi deterministik: otentikasi token, pembatasan jendela waktu (`MCP-02`), penolakan mutasi (`MCP-01`), blokade path GT (`AT-008`), redaksi fail-closed (`SEC-03`), dan audit log hash-chained (`NFR-005`).
6. **Keputusan Orkestrasi (`TBD-05`):**
   - Disahkan mengadopsi **Deterministic Python State Machine Coordinator + SQLite** (`CMP-INV-03`) yang hemat memori (~38 MiB RAM vs >3.4 GiB Dify) dan menjamin penegakan invarian state machine 100%.

---

## 2. Instruksi & Kontrak Kerja untuk Chapter C09

Chapter C09 bertujuan mengimplementasikan **Read-Only Telemetry Adapters** penuh yang menghubungkan *Tool Dispatcher* gateway ke backend telemetri nyata di lab:

1. **Komponen yang Harus Dibangun di C09:**
   - Adapter Prometheus PromQL untuk `get_service_metrics` (menghubungi `http://localhost:9090`).
   - Adapter Loki LogQL untuk `search_error_logs` (menghubungi `http://localhost:3100`).
   - Adapter Tempo HTTP API untuk `get_trace_summary` (menghubungi `http://localhost:3200`).
   - Adapter Service Catalog untuk `get_service_dependencies`.
2. **Kepatuhan Batas Keamanan Mutlak di C09:**
   - Seluruh adapter telemetri wajib berada di belakang `PolicyGateway` (`gateway/`).
   - Adapter **dilarang keras** menyediakan fungsi penulisan, penghapusan, atau mutasi konfigurasi telemetri.
   - Kueri PromQL / LogQL harus menggunakan template statis yang aman dari injeksi string arbitrer (*no raw query pass-through*).
   - Seluruh respons telemetri wajib dibungkus dalam format amplop kontrak `tool-result.v1.schema.json`.
   - Ketika backend telemetri (misalnya Tempo pada `SC-09`) dimatikan, adapter wajib mengembalikan status `unavailable` dengan kode `SOURCE_UNAVAILABLE` secara jujur tanpa mengarang data trace (`EV-02`, `RULE-006`).

---

## 3. Inventaris Berkas Bukti C08 (`E08`)

Seluruh berkas bukti C08 tersimpan lengkap pada direktori `evidence/c08-20261112T000000Z/C08/`:
- `readiness-check.md`: Verifikasi prasyarat dan kelaikan fondasi.
- `auth-policy-tests.json`: Hasil uji 17 kasus batas keamanan gateway (100% PASS).
- `gateway-audit.jsonl`: Log audit keamanan nyata berformat `audit-event.v1` dengan validasi rantai hash SHA-256.
- `sanitizer-report.json`: Laporan redaksi rahasia sintetis dan pembuktian kebijakan `FAIL_CLOSED`.
- `orchestrator-capability-report.md`: Laporan komparatif 7 kasus uji spike dan justifikasi penutupan `TBD-05`.
- `test-results.txt`: Log eksekusi 51 pengujian otomatis pytest (10 C08 + 41 uji regresi fondasi).
- `g1-record.md`: Rekaman keputusan resmi kelulusan Gate G1 (`PASSED`).
- `handover-to-c09.md`: Dokumen serah terima ini.

