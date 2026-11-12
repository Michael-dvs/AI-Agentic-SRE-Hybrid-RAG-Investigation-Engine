# Rekaman Keputusan Gate G1 (Foundation Gate Approval Record)

- **Gate ID:** `G1 — Foundation Gate Approval`
- **Fase:** `F1 — Foundation`
- **Tanggal Evaluasi:** `2026-11-12T00:00:00Z`
- **Execution Run ID:** `c08-20261112T000000Z`
- **Status Akhir Gate:** **`PASSED`**
- **Otoritas Penilai:** Project Initiator / SRE Architecture Board / Security Reviewer
- **Tujuan:** Mengesahkan kelulusan fondasi teknis Fase 1 (C01 s/d C08) sebagai prasyarat wajib sebelum memulai integrasi terkendali Fase 2 ([C09](../../docs/roadmap/phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).

---

## 1. Verifikasi 5 Kriteria Kelulusan Wajib Gate G1 (Roadmap §7)

| Kriteria G1 | Persyaratan Formal | Artefak Bukti | Hasil Verifikasi Empiris | Status |
|---|---|---|---|---|
| **Kriteria 1: Layanan Simulasi & Telemetri** | Minimal 3 layanan terhubung (5 layanan tervalidasi) berjalan stabil dengan generator trafik ber-seed (`E03`), serta penangkapan telemetri lengkap: *RED metrics* Prometheus, *structured logs* Loki, *distributed traces* Tempo, dan Service Catalog (`AT-001`, `E05`). | `evidence/c03-20261109T084600Z/C03/smoke-results.json`<br>`evidence/c05-20261111T113000Z/C05/collector-smoke-report.json` | 5 microservices (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`) aktif dan sehat. Correlation ID & W3C Trace Context terpropagasi 100%. | `PASS` |
| **Kriteria 2: Fault Injection & Isolasi Ground Truth** | *Fault harness* dapat menginjeksi dan mereset gangguan secara bersih; *ground truth* terisolasi penuh dari runtime investigator (`AT-002`, `AT-008`, `E04`). | `evidence/c04-20261110T102500Z/C04/injection-harness-summary.json`<br>`restricted/gt_registry/ground_truth_records.jsonl` | 14 skenario gangguan (`SC-01` s/d `SC-14`) teruji dengan pemulihan bersih 100%. Registry GT berada di folder terisolasi tanpa mount ke agent investigator. | `PASS` |
| **Kriteria 3: Korpus Pengetahuan & Baseline RAG** | Korpus KB sintetis memuat dokumen `current`, `obsolete`, dan `restricted` dengan siklus hidup ingestion tervalidasi. Baseline Hybrid RAG pada split `DEV` dapat direproduksi (`AT-006`, `AT-007`, `RAG-01`, `RAG-02`, `E06`, `E07`). | `evidence/c06-20261111T150000Z/C06/corpus-manifest.json`<br>`evidence/c07-20261111T160000Z/C07/baseline-metrics.json` | 71 chunks pengetahuan terbit; pencegahan SOP kedaluwarsa (`RAG-01`) dan isolasi lintas layanan (`RAG-02`) terbukti 100%. Hybrid RRF mengungguli BM25 & dense baselines. | `PASS` |
| **Kriteria 4: Secure Read-Only Policy Gateway** | Authenticated gateway aktif dan lulus pengujian batas negatif: penolakan alat mutasi (`MCP-01`, `AT-005`), penolakan window berlebih tanpa clamping (`MCP-02`), isolasi GT (`AT-008`), redaksi fail-closed (`SEC-03`), dan audit log hash-chained (`E08`). | `evidence/c08-20261112T000000Z/C08/auth-policy-tests.json`<br>`evidence/c08-20261112T000000Z/C08/sanitizer-report.json`<br>`evidence/c08-20261112T000000Z/C08/gateway-audit.jsonl` | 17/17 uji batas negatif lulus 100%. Redaksi fail-closed teruji tanpa kebocoran rahasia. Rantai hash audit log SHA-256 valid 100%. | `PASS` |
| **Kriteria 5: Penutupan Keputusan G1 & Pembekuan Evaluasi** | Seluruh keputusan wajib Gate G1 (`TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, `ADR-S04` s/d `ADR-S08`) ditutup resmi; protokol evaluasi formal dibekukan (`RULE-012`, `AT-014`). | `evidence/c08-20261112T000000Z/C08/orchestrator-capability-report.md`<br>`docs/decisions/` | Seluruh 5 TBD dan 5 ADR disahkan. Hash split `DEV`, `H-G3`, `H-G4` dibekukan secara kriptografis. | `PASS` |

---

## 2. Pemeriksaan Blocking Failures (Kondisi Penahan Gate)

| Kondisi Blocking Failure | Status Pemantauan | Hasil Audit |
|---|---|---|
| Investigator memiliki akses langsung/tidak langsung ke path/file *ground truth* | **TIDAK DITEMUKAN** | Gateway memblokir path `restricted/` dan argumen `scenario_id` dengan status `FORBIDDEN_SCOPE` / `SCHEMA_INVALID`. |
| Investigator berhasil memanggil fungsi *write*, *restart*, *deploy*, *scale*, atau *shell* | **TIDAK DITEMUKAN** | 100% permintaan fungsi mutasi ditolak sebelum mencapai backend (`TOOL_NOT_ALLOWED`). |
| Data rahasia sintetis/token/PII lolos dari redaktor atau redaktor bersifat *fail-open* | **TIDAK DITEMUKAN** | 0 rahasia lolos uji redaksi; kegagalan redaktor memblokir transmisi payload total (`REDACTION_FAILED`). |
| Kueri dengan `query_window` berlebih diterima atau dipotong secara diam-diam (*silent clamping*) | **TIDAK DITEMUKAN** | Kueri 7200s (> 3600s) ditolak tegas dengan kode `WINDOW_EXCEEDED`. |
| Ukuran sampel, ambang KPI, atau pemisahan dataset `H-G3`/`H-G4` belum dibekukan | **TIDAK DITEMUKAN** | Protokol evaluasi, ukuran korpus, dan kunci hash dataset evaluasi telah dibekukan resmi pada C08. |

---

## 3. Penutupan Resmi Keputusan Arsitektur Wajib Gate G1

| ID Keputusan | Subjek & Pilihan yang Diambil | Status Baru | Ringkasan Justifikasi & Bukti |
|---|---|---|---|
| `TBD-05` / `ADR-TBD05` | **Workflow Orchestration Engine:** Ratifikasi **Opsi C / Option B (Deterministic Python State Machine Coordinator + SQLite / Thin Runner)** | **CONFIRMED** | Dify self-hosted didiskualifikasi karena mengonsumsi >3.4 GiB RAM tambahan (melebihi batas Docker 8 GiB), rentan OOM pada Mac 16GB, dan tidak mendukung native hash-bound review gate. Python Coordinator memenuhi seluruh 7 kasus uji spike (`SPK-C08-01`..`07`) dengan jejak memori hanya ~38 MiB. |
| `TBD-06` / `ADR-S08` | **Evaluator Framework & Ground Truth Protocol:** Pengujian offline post-dossier dengan pemisahan holdout `H-G3` dan `H-G4` | **CONFIRMED** | Evaluator beroperasi terpisah dari runtime investigator. Hasil investigasi dinilai secara offline setelah dossier berstatus terminal (`CLOSED`). |
| `TBD-08` / `ADR-S02` | **Alert Transport & Ingestion:** RabbitMQ topic exchange `telemetry.alerts` dengan mekanisme deduplikasi 60 detik (`OPS-01`) | **CONFIRMED** | Menjamin deduplikasi 100 alert berturut-turut tanpa kehilangan event atau overhead resource berlebih. |
| `TBD-10` / `ADR-S02` | **Telemetry Format & Protocol:** OpenTelemetry Traces ke Tempo, Prometheus RED Metrics, Loki JSON structured logs | **CONFIRMED** | Memenuhi format kontrak `tool-result.v1.schema.json` dan standar industri cloud-native. |
| `TBD-11` / `ADR-S04` | **KB Chunking, Dense Embedding & Fusion Strategy:** Model multilingual resmi `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, L2 normalized) + BM25 sparse + Reciprocal Rank Fusion ($k=60$) | **CONFIRMED** | Model dense multilingual disahkan untuk mendukung pemahaman semantik Bahasa Indonesia perbankan dan istilah teknis Inggris; Hybrid RRF terbukti mencapai 100% Hit@5 pada benchmark DEV (`E07`), biaya $0.00, konsumsi RAM < 150 MiB. |
| `ADR-S05` | **Quotas, Deadlines & Correlation Bounds:** Max window 3600s, max points 1000, max hits 500, max tool calls 30/incident | **CONFIRMED** | Batas-batas operasional ditegakkan secara deterministik pada layer gateway. |
| `ADR-S06` | **Audit Trail & Sanitizer Architecture:** Pre-sink fail-closed redactor + SHA-256 hash-chained JSONL audit log | **CONFIRMED** | Memenuhi persyaratan audit independen (`NFR-003`, `NFR-005`). |
| `ADR-S07` | **Optional APM & Ticket Disposition:** Mock ticketing stub & APM stub berstatus read-only | **CONFIRMED** | Komponen opsional tidak memblokir alur investigasi inti. |

---

## 4. Pembekuan Protokol Evaluasi & Kunci Hash Holdout (`RULE-012`, `AT-014`)

1. **Korpus Evaluasi Retrieval & Investigasi:**
   - **DEV Queries (Training & Parameter Tuning):** 28 kueri berlabel pada `knowledge_base/eval_queries/dev_queries.json`.
   - **Holdout Queries Gate G3 (`H-G3`):** 15 kueri rahasia untuk validasi Gate G3 pada Fase 3.
   - **Holdout Queries Gate G4 (`H-G4`):** 15 kueri rahasia untuk validasi final Gate G4 pada Fase 4.
   - **File Holdout Frozen:** `restricted/evaluator_queries/holdout_queries.json`
   - **SHA-256 Hash Kunci Holdout:** `6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6`
2. **Registry Ground Truth Gangguan:**
   - **File Registry Frozen:** `restricted/gt_registry/ground_truth_records.jsonl`
   - **SHA-256 Hash Kunci Registry:** `149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95`
3. **Plafon Anggaran & Lingkungan Lab:**
   - Plafon Biaya: **$0.00** (100% open-source / lokal).
   - Plafon Memori Docker Lab: **8.0 GiB RSS** pada host macOS Apple Silicon 16 GB.

---

## 5. Pernyataan Keputusan Resmi Gate G1

Berdasarkan audit independen terhadap artefak bukti `E01` sampai dengan `E08`, pemenuhan seluruh kriteria masuk/keluar fondasi teknis, ketiadaan kondisi blocking failure, serta penutupan seluruh keputusan arsitektur wajib:

> **GATE G1 (FOUNDATION GATE APPROVAL) RESMI DINYATAKAN: `PASSED`**

Izin diberikan untuk melanjutkan pekerjaan ke **Fase 2 — Controlled Integration**, dimulai dari **Chapter C09 — Read-Only Telemetry Adapters**.

