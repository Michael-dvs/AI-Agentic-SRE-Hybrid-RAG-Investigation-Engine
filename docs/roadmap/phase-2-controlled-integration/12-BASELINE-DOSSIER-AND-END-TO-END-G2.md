# C12 — Baseline Dossier and End-to-End G2

## 1. Chapter Information
- **Phase:** F2 — Controlled Integration (Gate `G2`)
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C04 — Fault Harness and Ground Truth Isolation](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md), [C07 — Hybrid Retrieval and Baselines](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md), [C09 — Read-Only Telemetry Adapters](09-READ-ONLY-TELEMETRY-ADAPTERS.md), [C10 — Alert Intake and Dependency Correlation](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md), [C11 — Durable Investigation Workflow](11-DURABLE-INVESTIGATION-WORKFLOW.md), `G1 PASS` ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md))
- **Next chapter:** [C13 — Controlled LLM Investigator](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)
- **Related requirements:** `BR-005`, `BR-012`, `FR-OBS-002`, `FR-RAG-005`, `FR-RAG-009`, `FR-AGT-001`, `FR-AGT-009`, `FR-OUT-001`, `FR-OUT-002`, `FR-OUT-003`, `FR-OUT-004`, `RULE-002`, `RULE-008`, `NFR-011`, `NFR-020`, `OBJ-01`, `SC-01`, `SC-02`, `SC-12`
- **Related acceptance tests:** `AT-003` (verifikasi *replay end-to-end*), `AT-004` (verifikasi transisi *state* lengkap sampai `HUMAN_REVIEW`/`CLOSED`), `AT-005` (verifikasi *zero-write* *end-to-end*), `AT-008` (test owner isolasi *ground truth end-to-end* pada *baseline replay*), `AT-010` (build & test owner tahap *baseline dossier & minimum human review*; diperluas di C16), `AT-012` (test owner jalur *tool/RAG outage fallback*), `AT-013` (*preliminary replay*; dua *clean replay* final tetap di C22), `EV-02` (test owner penanda *missing trace* di dossier baseline), `OPS-01` (test owner *end-to-end* idempotensi dossier pada 100 *duplicate alerts*), `HUM-01` (build & test owner tahap baseline *review gate*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *Incident Investigation Dossier Serializer & Renderer* (JSON terstruktur dan Markdown yang mudah dibaca manusia), menyediakan mekanisme *minimum authorized human review* (`approve`, `reject`, `edit/correction` secara *append-only*), membuktikan *end-to-end deterministic replay* dari pemicu gangguan hingga penutupan review manusia, serta menyelenggarakan **Review Gate G2 (Controlled Integration Gate)**. Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.2, Gate G2 membuktikan bahwa seluruh jalur integrasi, isolasi *ground truth*, sifat *read-only*, dan *fallback* bekerja secara nyata menggunakan baseline deterministik, tanpa mengklaim kualitas penalaran LLM yang baru akan dibangun di Fase 3 ([C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)).

Setelah chapter ini selesai, setiap insiden menghasilkan dokumen dossier yang lulus validasi skema [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) (`FR-OUT-001`–`003`), keputusan reviewer manusia terekam secara *immutable/append-only* tanpa memicu aksi remediasi otomatis (`FR-OUT-004`, `HUM-01`), skrip *replay* terintegrasi berhasil dijalankan untuk skenario normal, gangguan, ketiadaan SOP, kehilangan *trace*, *timeout*, dan *duplicate alert storm*, serta **Gate G2 (`PASS` / `FAIL` / `BLOCKED`)** memiliki bukti lengkap di `E12`.

## 3. Scope & Boundaries
### In Scope
- Implementasi perender dossier ke format JSON (sesuai JSON Schema [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md)) dan laporan Markdown (`BRD Appendix A`) yang memuat header insiden, dampak/cakupan, *timeline* sinyal, tabel bukti (`evidence_id`), hipotesis berperingkat beserta bukti pendukung/penyangkal, sitasi SOP, *unknowns/telemetry gaps*, rekomendasi langkah pemeriksaan manual bagi manusia, serta versi *workflow/prompt/KB* (`FR-OUT-001`–`003`).
- Implementasi antarmuka/API *minimum authorized human review* yang memverifikasi identitas reviewer, mengikat keputusan (`APPROVED`, `REJECTED`, `CORRECTED`) pada nomor revisi dossier yang spesifik (`D-C02-03`), dan menyimpan riwayat secara *append-only* (`FR-OUT-004`, `NFR-011`).
- Penyusunan dan eksekusi skrip *end-to-end deterministic replay* yang menguji alur *fault/traffic $\rightarrow$ telemetry $\rightarrow$ alert intake $\rightarrow$ workflow $\rightarrow$ tools + RAG $\rightarrow$ baseline dossier $\rightarrow$ human review* beserta jalur *manual fallback*.
- Penyelenggaraan evaluasi dan penandatanganan **Gate G2** berdasarkan paket bukti `E09`–`E12`.

### Out of Scope
- Klaim kelulusan kualitas penalaran LLM atau kelulusan penuh `OPS-02` (*LLM outage*) sebelum model nyata diintegrasikan di [C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md).
- Fitur penyempurnaan UI review, ekspor paket handover demo terpisah, dan *optional dummy ticketing* (`AT-017`) yang diselesaikan di [C16](../phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md).
- Klaim bahwa *preliminary replay* di C12 menggantikan kewajiban dua *clean environment replay* final `AT-013` di C22.

## 4. Prerequisites
- Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) berstatus `PASS`.
- Komponen *Fault Harness* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)), *Hybrid Retrieval* ([C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md)), *Read-Only Telemetry Adapters* ([C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md)), *Alert Intake & Correlation* ([C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)), dan *Durable Investigation Workflow* ([C11](11-DURABLE-INVESTIGATION-WORKFLOW.md)) telah berfungsi dan menghasilkan bukti `E09`–`E11`.
- Skema JSON dossier, skema *review record*, dan templat Markdown dari [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.

## 5. Implementation Roadmap
1. **Implementasi Serializer JSON dan Renderer Markdown Dossier (`FR-OUT-001`–`003`)**
   - *Apa yang harus dilakukan:* Bangun generator dossier pada tahap `DRAFTED` yang menghasilkan berkas JSON dan Markdown per `incident_id` + `revision_number`. Pastikan setiap atribut wajib terisi atau ditandai `missing`/`unavailable` secara jujur (tanpa tebakan), semua klaim merujuk pada `evidence_id` yang ada di tabel bukti, dan sitasi SOP menyertakan `document_id`, `document_version`, `section_path`, serta `source_uri` lokal (`FR-RAG-005`).
   - *Mengapa diperlukan:* Memenuhi kontrak keterbacaan manusia (`NFR-020`) sekaligus validasi mesin untuk evaluator offline.
   - *Expected output:* Modul serializer/renderer dossier dan validator skema output.
   - *Cara memverifikasi:* Validasi setiap dossier JSON yang dihasilkan terhadap JSON Schema [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) dan periksa bahwa semua tautan bukti/SOP lokal dapat dibuka.
2. **Implementasi Minimum Authorized Human Review dan Append-Only Revision (`FR-OUT-004`, `HUM-01`)**
   - *Apa yang harus dilakukan:* Sediakan mekanisme review terotorisasi (sesuai pilihan antarmuka `TBD-11` dari Gate G1) yang memungkinkan reviewer melakukan `approve`, `reject`, atau `edit/correction` atas revisi dossier tertentu, menolak persetujuan pada revisi yang sudah usang (`VERSION_CONFLICT`), serta menyimpan rekaman keputusan beserta `reviewer_ref` dan *timestamp* tanpa menimpa bukti asli dan tanpa memicu aksi otomatis apa pun.
   - *Mengapa diperlukan:* Menegakkan `RULE-008` dan `HUM-01` bahwa keputusan akhir berada di tangan manusia dan persetujuan dossier tidak pernah mengeksekusi remediasi.
   - *Expected output:* Endpoint/CLI/antarmuka review dasar dan penyimpanan `review-records` yang *append-only*.
   - *Cara memverifikasi:* Uji aksi `approve`, `reject`, `edit`, percobaan review oleh identitas tanpa izin, serta percobaan `approve` terhadap nomor revisi lama; pastikan seluruhnya divalidasi dan tercatat di audit.
3. **Penyusunan Prosedur Manual Fallback Terdokumentasi (`FR-AGT-007`, `AT-012`)**
   - *Apa yang harus dilakukan:* Implementasikan jalur *manual investigation fallback* yang menghasilkan *fallback dossier* berisi konteks *alert* awal, bukti parsial yang berhasil dikumpulkan sebelum gangguan, alasan kegagalan (`error_code`), dan daftar langkah pemeriksaan manual ketika *workflow* berhenti akibat *timeout* atau *backend outage*.
   - *Mengapa diperlukan:* Memenuhi syarat Gate G2 dari proposal (*documented manual fallback*) dan `NFR-006`.
   - *Expected output:* Generator `fallback-report` dan prosedur operasional triase manual.
   - *Cara memverifikasi:* Simulasikan kegagalan pada adapter telemetri dan indeks RAG di tengah investigasi; pastikan *fallback dossier* tetap terbentuk dan masuk ke antrean `HUMAN_REVIEW`.
4. **Eksekusi End-to-End Deterministic Replay Suite (`AT-003`, `AT-008`, `EV-02`, `OPS-01`)**
   - *Apa yang harus dilakukan:* Jalankan skrip *replay* otomatis untuk: (a) trafik sehat (`SC-01`, tidak ada insiden palsu), (b) gangguan HTTP 5xx (`SC-02`) dan latensi DB (`SC-03`), (c) kasus tanpa *runbook* yang cocok (`FR-RAG-009`), (d) sumber *trace* dimatikan (`SC-09`, `EV-02`), (e) *timeout* adapter/RAG (`AT-012`), (f) 100 *duplicate alerts* (`SC-12`, `OPS-01`), serta (g) interupsi *cancel/restart* ([C11](11-DURABLE-INVESTIGATION-WORKFLOW.md)).
   - *Mengapa diperlukan:* Membuktikan secara menyeluruh bahwa rantai *alert $\rightarrow$ evidence $\rightarrow$ retrieval $\rightarrow$ dossier $\rightarrow$ review* dapat diulang secara deterministik tanpa kebocoran *ground truth* (`AT-008`).
   - *Expected output:* Kumpulan `dossiers-json-and-report`, `replay-manifest`, dan log pemeriksaan isolasi *ground truth*.
   - *Cara memverifikasi:* Periksa bahwa seluruh dossier dapat ditelusuri dari klaim $\rightarrow$ `evidence_id` $\rightarrow$ log panggilan *tool* $\rightarrow$ sinyal backend, 0 *write action* terjadi (`AT-005`), dan 0 akses *ground truth* terjadi (`AT-008`).
5. **Penyelenggaraan Review Gate G2 (Controlled Integration Gate)**
   - *Apa yang harus dilakukan:* Audit seluruh bukti `E09` s/d `E12` terhadap kriteria keluar Gate G2, catat secara eksplisit bahwa output tahap ini berasal dari *deterministic baseline* (bukan klaim akurasi LLM Fase 3), dan rekam keputusan pada `g2-record.md` (serta `docs/gates/`).
   - *Mengapa diperlukan:* Menjadi titik kontrol wajib sebelum mengintegrasikan model LLM pada Fase 3 ([C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)).
   - *Expected output:* Paket bukti `E12` dan rekaman keputusan `g2-record.md`.
   - *Cara memverifikasi:* Pastikan tidak ada *blocking failure* pada daftar kriteria Gate G2.

## 6. Expected Deliverables
- Serializer JSON dan renderer Markdown untuk *Incident Investigation Dossier* yang sesuai skema [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md).
- Mekanisme *minimum authorized human review* (`approve`/`reject`/`edit`) dengan penyimpanan revisi *append-only*.
- Skrip *end-to-end deterministic replay* beserta mekanisme *manual fallback*.
- Paket bukti tersanitasi `E12` pada `evidence/<run_id>/C12/`: `dossiers-json-and-report`, `review-records`, `replay-manifest`, `fallback-report`, dan `g2-record`.

## 7. Validation & Exit Criteria (Termasuk Spesifikasi Gate G2)
- **Exit Criteria Gate G2 (Controlled Integration Gate):**
  1. Alur *end-to-end* dari *alert intake* $\rightarrow$ *bounded tool evidence* $\rightarrow$ *authorized Hybrid RAG* $\rightarrow$ *draft dossier* $\rightarrow$ *human review* berhasil dieksekusi dan dapat di-*replay* secara deterministik (`AT-003`, `AT-004`, `AT-010`, `E09`–`E12`).
  2. Seluruh *tool* terbukti *read-only* terhadap backend nyata dengan `KPI-09` (*prohibited state-changing calls*) = 0 (`AT-005`, `MCP-01`, `MCP-02`).
  3. Isolasi *ground truth* tetap terjaga sepanjang alur *end-to-end* dengan `KPI-10` (*GT exposure*) = 0 (`AT-008`).
  4. Kehilangan sumber *trace* (`SC-09`, `EV-02`), ketiadaan *runbook* (`FR-RAG-009`), semburan 100 *duplicate alerts* (`SC-12`, `OPS-01`), serta kegagalan/interupsi *tool* (`AT-012` jalur non-LLM) ditangani dengan *safe fallback* dan tercatat lengkap di audit.
  5. Rekomendasi kritis di dalam dossier wajib melewati *human review* tanpa memicu aksi otomatis (`HUM-01` tahap baseline).
- **Blocking Failures (Otomatis Menahan Gate G2 = `FAIL` / `BLOCKED`):**
  - Ditemukan satu saja aksi *write/restart/deploy* oleh investigator atau kebocoran *ground truth* ke dalam konteks/dossier/log.
  - Dossier mengarang bukti *trace*/metrik ketika backend dimatikan (`EV-02` gagal).
  - Semburan 100 *duplicate alerts* menyebabkan pembuatan dossier ganda untuk insiden yang sama atau membuat *worker* *crash*.
- **Assessment Dependencies:** Gate G2 membuktikan integrasi menggunakan *deterministic rule-based baseline*; pengujian `OPS-02` (*LLM outage*), `SEC-02`/`AT-011` (*prompt injection* terhadap LLM), dan evaluasi kualitas diagnosis AI (`AT-014`) baru dinilai secara penuh setelah integrasi LLM pada Fase 3 ([C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)–[C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md)).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Menyalahartikan keberhasilan *baseline deterministik* di Gate G2 sebagai bukti keberhasilan penalaran AI; mitigasi dengan mencantumkan label `baseline_mode: deterministic_rule_engine` secara eksplisit pada seluruh dossier `E12` dan `g2-record.md`.
- **Open Decisions:** Sebelum melangkah ke [C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md), versi eksak model/provider LLM gratis (`TBD-04`) dan batas anggaran token per insiden (`ADR-S05`) harus telah terkonfirmasi siap pakai.
- **Handover ke [C13 — Controlled LLM Investigator](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md) (Fase 3):** Gate G2 berstatus `PASS`, *pipeline* investigasi *end-to-end* yang stabil, *fallback engine* deterministik yang telah teruji, skema dossier/review yang tervalidasi, serta paket bukti `E12`.

