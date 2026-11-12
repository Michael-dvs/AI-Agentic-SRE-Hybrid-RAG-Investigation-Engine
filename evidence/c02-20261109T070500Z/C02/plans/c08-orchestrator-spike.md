# C02 Step 10 — Rencana Capability Spike Koordinator Workflow C08 (Dify-First vs Alternatif)

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/plans/c08-orchestrator-spike.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 10 & §6.4)  
> **Related Decisions:** `TBD-05`, `ADR-S01`, `ADR-S03`, `ADR-S05`, `ADR-S06`  
> **Status:** `SPECIFIED` (Protokol uji yang dapat dieksekusi pada C08 sebelum Gate G1; **bukan** klaim bahwa Dify telah lulus atau gagal)

---

## 1. Latar Belakang & Batas Keputusan

Pemilik proyek memilih **Dify-first** sebagai kandidat utama workflow orchestration (`CANDIDATE; requires capability evaluation`), sementara seluruh layanan dan komponen berjalan di atas **macOS Apple Silicon 16 GB RAM** dengan anggaran memori Docker Lab maksimal **8 GiB** (`P2_phase1_g1_foundation` hingga `P5_full_24x7_demo`).

Mengingat stack Dify self-hosted standar membutuhkan beberapa kontainer berat (`dify-api`, `dify-worker`, `dify-web`, `dify-sandbox`, PostgreSQL, Redis) yang berpotensi mengonsumsi **2.5–3.8 GiB RAM** dan memiliki perilaku retry/state internal tersendiri, C02 menetapkan **7 eksperimen capability spike wajib** yang harus dijalankan pada awal **Chapter C08** sebelum Gate G1.

---

## 2. Matriks Eksperimen Capability Spike C08 (`SPK-C08-01` s.d. `SPK-C08-07`)

Setiap kasus spike di bawah ini harus dijalankan pada lingkungan lab C08 dan menghasilkan bukti terukur di `evidence/<run_id>/C08/`:

| Spike ID | Kapabilitas yang Diuji | Setup & Injected Failure pada C08 | Observasi Nyata yang Wajib Dikumpulkan | Kriteria `PASS` | Kriteria `FAIL` (Pemicu Fallback Arsitektur) |
|---|---|---|---|---|---|
| `SPK-C08-01` | **Memory & Resource Footprint under 8 GiB Cap** | Jalankan stack kandidat koordinator bersama profil `P2_phase1_g1_foundation` (5 layanan FastAPI, OTel, Prom, Loki, Tempo, Qdrant, MCP Gateway). | Output `docker stats --no-stream` selama 15 menit idle dan 5 run workflow berurutan. | Total RSS seluruh kontainer Docker `<= 7.0 GiB` (menyisakan `>= 1.0 GiB` headroom dari batas 8 GiB) tanpa OOM/swap thrashing. | Total RSS `> 7.5 GiB`, kontainer ter-kill OOM, atau latensi sistem host macOS terdegradasi parah. |
| `SPK-C08-02` | **Durable State & Worker Restart Recovery** | Mulai workflow untuk `inc-spike-02`; saat berada di state `EVIDENCE_COLLECTED`, hentikan paksa (`docker restart`) proses worker koordinator. | Log state store (`workflow-event.v1`) dan jumlah pemanggilan ulang tool di MCP Gateway. | Koordinator melanjutkan dari `EVIDENCE_COLLECTED` menggunakan `idempotency_key` tanpa mengulang mutasi state awal atau kehilangan bukti yang sudah tersimpan. | State hilang (kembali ke awal tanpa jejak), hang permanen без timeout, atau menghasilkan दो dossier ganda. |
| `SPK-C08-03` | **Idempotency & Duplicate Alert Replay** | Kirim 10 alert duplikat dengan fingerprint identik secara bersamaan, lalu replay event transisi `DRAFTED` dengan `idempotency_key` yang sama. | Isi tabel state store dan daftar `dossier_version` yang terbentuk. | Hanya **1** `incident_id` aktif dan **1** revisi `dossier_version: 1` yang terbentuk; percobaan duplikat dicatat sebagai idempotent no-op. | Terbentuk beberapa workflow paralel untuk insiden yang sama atau nomor versi dossier meloncat tanpa perubahan isi. |
| `SPK-C08-04` | **Strict Tool Allowlist & Out-of-Band Identity** | Konfigurasikan prompt/node nakal yang mencoba memanggil tool tidak terdaftar (`restart_service`) dan menyisipkan `"allowed_groups": ["admin"]` di argumen JSON tool. | Log `audit-event.v1` di Independent Audit Sink dan respons `tool-result.v1`. | Permintaan ditolak oleh MCP Gateway (`TOOL_NOT_ALLOWED` / `SCHEMA_INVALID`) sebelum menyentuh backend; identitas caller tetap diambil dari token header server-side. | Koordinator mengizinkan bypass langsung ke HTTP backend tanpa melewati MCP Gateway atau meneruskan argumen grup palsu sebagai hak akses sah. |
| `SPK-C08-05` | **Quota, Deadline & Cancellation Enforcement** | Setel fixture kebijakan `max_tool_calls = 3` dan `workflow_deadline_seconds = 10`; suntikkan penundaan 12 detik pada percobaan tool ke-4. | Timestamp penghentian eksekusi, `workflow-event.v1`, dan status akhir run. | Koordinator membatalkan panggilan yang melewati batas waktu/kuota dan bertransisi tertib ke fallback deterministik / `FAILED_SAFE` dengan kode `DEADLINE_EXCEEDED` / `BUDGET_EXHAUSTED`. | Koordinator terus memanggil tool melampaui kuota atau membiarkan worker menggantung melewati deadline. |
| `SPK-C08-06` | **Human Review Hash-Bound Gate & Stale Rejection** | Hentikan workflow di `HUMAN_REVIEW` (`dossier_version: 1`, `hash: H1`). Ubah draft ke `dossier_version: 2` (`hash: H2`), lalu kirim `review-event` yang menargetkan `H1`. | Respons endpoint review dan log `audit-event.v1`. | Event review untuk `H1` ditolak dengan `VERSION_CONFLICT`; state tidak berubah menjadi `CLOSED` sampai `H2` disetujui secara eksplisit. | Workflow menerima persetujuan basi (`H1`) dan menutup insiden dengan mengesahkan isi `H2` yang belum diperiksa. |
| `SPK-C08-07` | **Independent Audit Correlation & LLM Outage Fallback** | Matikan koneksi ke remote LLM dan local LLM saat state menuju `HYPOTHESES`; periksa korelasi `incident_id` di Independent Audit Sink (`CMP-GOV-02`). | File/tabel `audit-event.v1` dan output `dossier.v1` pada mode fallback. | Workflow beralih ke `investigation_mode: "manual_fallback"`, menghasilkan draft dossier deterministik berisi bukti telemetri + SOP, dan seluruh langkah tercatat utuh di Independent Audit Sink. | Workflow berhenti total dengan unhandled exception tanpa draft dossier, atau jejak audit hanya tersimpan di log internal Dify yang tidak tervalidasi skemanya. |

---

## 3. Aturan Keputusan & Fallback Arsitektur Koordinator (`TBD-05`)

Sesuai C02 §6.4 dan Step 10 Action 5, evaluasi C08 akan menghasilkan satu dari tiga disposisi arsitektur berikut yang wajib dicatat ke dalam revisi final `ADR-TBD05`:

1. **Opsi A — Full Dify Orchestration (`PASS` semua `SPK-C08-01`..`07`):**
   - Digunakan jika seluruh kontainer Dify muat di dalam anggaran RAM 8 GiB dan memenuhi ketujuh invarian kontrol deterministik di atas.
2. **Opsi B — Hybrid Thin-Coordinator Python + Dify Node Runner (`CONDITIONAL`):**
   - Jika Dify melampaui anggaran RAM saat menyalakan sandbox/worker penuh atau tidak mampu menegakkan `VERSION_CONFLICT` / `idempotency_key` secara native, maka **State Machine, Idempotency, Policy Gate, dan Human Review Gate dijalankan oleh proses Python FastAPI + SQLite (`CMP-INV-03`, ~120 MiB RAM)**, sedangkan Dify hanya dipanggil secara opsional untuk tahap komposisi prompt.
3. **Opsi C — Deterministic Python State Machine / LangGraph Coordinator (`FALLBACK` bila Dify gagal `SPK-C08-01`..`07`):**
   - Jika stack Docker Dify menyebabkan OOM pada batas 8 GiB atau gagal memenuhi syarat keamanan/determinisme C08, proyek beralih secara resmi melalui persetujuan pemilik proyek di Gate G1 ke **Custom Python State Machine / LangGraph + SQLite** yang mengimplementasikan kontrak `workflow-event.v1`, `dossier.v1`, `review-event.v1`, dan `audit-event.v1` secara langsung.
   - **Kepatuhan Kontrak:** Karena seluruh skema di `E02/contracts/` dirancang bebas-vendor (*engine-agnostic*), peralihan antara Opsi A, B, atau C **tidak mengubah satu pun kontrak JSON Schema** di hilir.

