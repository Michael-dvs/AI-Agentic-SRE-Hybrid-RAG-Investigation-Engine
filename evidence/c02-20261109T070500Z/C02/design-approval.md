# C02 Step 12 — Persetujuan Baseline Arsitektur & Kontrak (Design Baseline Freeze Record)

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/design-approval.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 12)  
> **Decision Timestamp:** `2026-11-09T07:33:00Z`  
> **Approval Authority:** `project-initiator-michael` (Project Owner / Initiator — Independent Simulation PoC)  
> **Design Baseline Status:** `APPROVED_FOR_C03_HANDOVER` (Bukan kelulusan Gate G1 dan bukan bukti implementasi runtime selesai)

---

## 1. Pernyataan Pembekuan Baseline Desain & Kontrak C02

Berdasarkan hasil verifikasi prasyarat Step 01 (`G0 PASS` pada `evidence/c01-20261109T043813Z/C01/g0-record.md`) serta kelulusan seluruh 14 pemeriksaan kualifikasi kontrak dan desain C02 (`C02-CON-001` s.d. `C02-CON-014` berstatus `PASS`), baseline arsitektur dan 20 kontrak JSON Schema Draft 2020-12 pada `evidence/c02-20261109T070500Z/C02/` dengan ini **dibekukan (frozen) dan disahkan** sebagai acuan kerja untuk Chapter C03 dan chapter-chapter Fase 1 selanjutnya.

---

## 2. Status Keputusan Arsitektur (ADR) & Konvensi Kontrak (`D-C02`)

| ID Keputusan | Judul / Cakupan | Status Saat Freeze C02 | Keterangan & Batas Otorisasi |
|---|---|---|---|
| `D-C02-01`..`06` | Konvensi Penamaan Kanonik, Waktu UTC `Z`, Error Enums, Lifecycle KB, Isolasi Manifest Evaluasi, & Dialect JSON Schema Draft 2020-12 | **`ACCEPTED` (Frozen)** | Berlaku mengikat untuk seluruh 20 skema di `E02/contracts/`. |
| `ADR-S01` | Runtime Layanan Sintetis (Python 3.12 + FastAPI di Docker Compose `linux/arm64`) & Kontrak State Store | **`ACCEPTED` (Untuk C03)** | Mengizinkan C03 membangun 5 layanan sintetis dan workload generator; pilihan engine koordinator tetap dievaluasi pada spike C08 (`TBD-05`). |
| `ADR-S02` | Pipeline Observability (OTel + Prometheus + Loki + Tempo + Grafana) & Kontrak Alert Intake | **`ACCEPTED` (Desain C05; Validasi Kapasitas Pending)** | Mengizinkan C05 mengimplementasikan pipeline telemetri; validasi jejak memori aktual di bawah plafon 8 GiB dibuktikan pada C05/C08. |
| `ADR-S03` | Isolasi 7 Identitas Prinsipal, 5 Trust Boundaries, & Kontrak MCP Read-Only Gateway | **`ACCEPTED` (Desain; Pembuktian Runtime di C08)** | Mengikat desain keamanan C06–C09; pembuktian penolakan runtime wajib diuji di C08 قبل Gate G1. |
| `ADR-S04` (`TBD-06`) | Arsitektur Hybrid RAG Qdrant-Native Dense + Sparse, Chunking, Fusion, & Reranker | **`PROPOSED` (Arah Terpilih; Parameter Dikunci di C06–C08 / G1)** | Arah Qdrant-native dense+sparse dikonfirmasi; model embedding/sparse spesifik dan opsi reranker dievaluasi secara empiris di C06–C07. |
| `ADR-S05` | Kuota Tool, Batas Jendela Waktu, Deadline, Retry/Backoff, & TTL Deduplikasi | **`PROPOSED` (Mekanisme Kontrak Disetujui; Angka Runtime Dikunci di C08)** | Mekanisme penolakan deterministik (`WINDOW_EXCEEDED`, `LIMIT_EXCEEDED`, `BUDGET_EXHAUSTED`) disahkan; angka batas runtime dikalibrasi di C08 (fixture `900s`/`100 points` adalah `TEST-ONLY`). |
| `ADR-S06` | Sink Audit Keamanan Independen, Sanitasi AI Observability, & Strategi Hybrid LLM Router | **`PROPOSED` (Kebijakan Disetujui; Evaluasi Jejak Memori di C08)** | Pemisahan Independent Security Audit Sink dan kebijakan `Remote Free-Tier -> Local Fallback -> Deterministic Manual Fallback` disahkan; opsi Langfuse vs local trace store dievaluasi terhadap batas RAM 8 GiB di C08. |
| `ADR-S07` | Disposisi Fitur Opsional Mock APM (`get_apm_health`) & Dummy ITSM Ticket (`AT-017`) | **`PROPOSED` (Keputusan Final di C08/G1)** | Kontrak ekstensi disiapkan tanpa memaksa implementasi di C03–C05; disposisi akhir ditetapkan paling lambat C08/G1. |
| `ADR-S08` (`TBD-08`/`10`) | Isolasi 3-Split Dataset (`dev`, `H-G3`, `H-G4`), Post-CLOSED GT Join, & Aturan Scoring KPI | **`PROPOSED` (Protokol Disetujui; Ukuran Sampel Dikunci di G1)** | Pemisahan `runtime-manifest` vs `evaluation-manifest` dan larangan pre-CLOSED join disahkan; ukuran sampel final dikunci di Gate G1. |
| `TBD-05` | Evaluasi Kapabilitas Dify-First vs Koordinator Alternatif (LangGraph / Custom Python State Machine) | **`CANDIDATE` (Dieksekusi via Spike C08)** | Diuji menggunakan protokol 7 eksperimen `SPK-C08-01`..`07` pada `plans/c08-orchestrator-spike.md` sebelum Gate G1. |

---

## 3. Batasan Otorisasi & Pernyataan Kepatuhan (`AGENTS.md`)

1. **Otorisasi Lab Independen:** Persetujuan ini diberikan oleh `project-initiator-michael` selaku pemilik proyek untuk keperluan PoC simulasi independen. Dokumen ini **bukan** persetujuan SME perbankan independen atau izin deployment produksi.
2. **Pemisahan Status:**
   - Status Dokumentasi & Kontrak C02: **`APPROVED` / `QUALIFIED_OFFLINE`**.
   - Status Implementasi Kode Aplikasi: **`NOT_STARTED`** (belum ada layanan FastAPI, kontainer Docker, atau model yang dijalankan pada C02).
   - Status Gate G1: **`NOT_EVALUATED`** (menunggu bukti nyata pembangunan dan pengujian runtime C03–C08).
   - Status 12 Tes Proposal (`SEC-01`..`HUM-01`) & 17 Tes BRD (`AT-001`..`AT-017`): **`SPECIFIED / NOT_RUN`**.
3. **Otorisasi Langkah Berikutnya:** **Chapter C03 (`03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md`) dengan ini diotorisasi untuk dimulai** ketika pengguna memberikan instruksi eksekusi C03.

