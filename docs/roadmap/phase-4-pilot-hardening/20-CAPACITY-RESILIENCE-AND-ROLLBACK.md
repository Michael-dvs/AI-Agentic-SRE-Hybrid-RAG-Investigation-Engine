# C20 — Capacity, Resilience, and Rollback

## 1. Chapter Information
- **Phase:** F4 — Pilot & Hardening
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** `IN_PROGRESS` — Tahap 2A `VERIFIED` pada `DEV`; Tahap 2B (*publish/canary/rollback*, rekonsiliasi `AT-015`, dan *final release freeze*) `NOT_STARTED`
- **Dependencies:** [C15 — AI Observability, Audit, and Cost](../phase-3-reasoning-observability/15-AI-OBSERVABILITY-AUDIT-AND-COST.md), [C18 — Red-Team, Holdout, and G3](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md) (`G3 PASS`), [C19 — Lab Shadow Pilot and Manual Baseline](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md), batas kapasitas/anggaran (`TBD-03`, `TBD-09`, `ADR-S05`)
- **Next chapter:** [C21 — Final Holdout and Benchmark](21-FINAL-HOLDOUT-AND-BENCHMARK.md)
- **Related requirements:** `FR-OBS-005`, `FR-RAG-008`, `FR-AGT-004`, `FR-AGT-007`, `FR-AGT-009`, `RULE-009`, `NFR-006`, `NFR-007`, `NFR-009`, `NFR-010`, `NFR-013`, `NFR-014`, `KPI-07`, `KPI-12`, `KPI-14`, `OBJ-05`, `DEP-01`, `DEP-06`, `RISK-07`, `RISK-08`, `SC-12`, `SC-13`
- **Related acceptance tests:** `OPS-01` (test owner *end-to-end capacity & 100 duplicate alert burst* beserta profil konkuren `5/20/50`), `OPS-02` & `AT-012` (test owner *resilience drills* lengkap: LLM, tool, RAG, AI tracing outage, antrean jenuh, dan *kill switch*), `AT-015` (build & test owner rekonsiliasi *unit cost basis* dan konsumsi sumber daya; laporan final di C21)

## 2. Objective & Expected Outcome
Chapter ini bertujuan mengukur batas kapasitas aktual (*capacity ceiling*) maket di dalam alokasi lab локаl (`TBD-03`: maks 4–6 CPU, 8 GiB RAM, 15 GiB Disk), menjalankan latihan ketahanan (*resilience drills*) dan pemulihan versi (*canary/publish/rollback/restore*), merekonsiliasi basis biaya unit (`AT-015`), menyelesaikan cacat dari *shadow pilot* [C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md), serta **membekukan rilis kandidat final (`Final Release Freeze`)** sebelum evaluasi *final holdout* `H-G4` di [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md).

Setelah chapter ini selesai, profil *throughput*, latensi, antrean, dan CPU/RAM telah terukur untuk beban normal, semburan 100 *duplicate alerts* (`OPS-01`, `SC-12`), serta tingkat kejadian konkuren `5 / 20 / 50` (dengan pencatatan jujur atas batas langit-langit lab dan tingkat beban yang `NOT_RUN` jika melampaui kapasitas perangkat keras, `NFR-010`), seluruh skenario kegagalan komponen (`OPS-02`, `AT-012`) dan *kill switch* terbukti meninggalkan jejak audit yang utuh, prosedur *rollback* untuk *workflow/model/prompt/KB/tool-schema/config* terbukti berhasil, dan `final-release-manifest` telah dikunci untuk digunakan tanpa perubahan di [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md) dan `C22`.

## 3. Scope & Boundaries
### In Scope
- Pengujian profil beban bertahap: beban normal, semburan 100 *duplicate alerts* (`OPS-01`, `SC-12`), lalu `5`, `20`, dan `50` insiden unik konkuren sejauh kapasitas lab 8 GiB RAM dan kuota *Free-Tier/local LLM* mendukung (`NFR-010`, `DEP-01`, `DEP-06`), tanpa menyamakan 100 *duplicate alerts* dengan 100 insiden unik.
- Latihan *failure & resilience drills*: pemutusan paksa LLM (`SC-13`, `OPS-02`), adapter telemetri, indeks RAG, sink AI observability, respons lambat (*slow/hanging backend*), kejenuhan antrean (*queue saturation*), dan aktivasi *kill switch* (`AT-012`, `NFR-006`).
- Pengujian *publish/canary* dan *rollback* deterministik untuk versi *workflow*, *model/prompt*, indeks KB (`FR-RAG-008`), *tool schema*, dan konfigurasi, beserta *backup/restore* state lokal (`NFR-014`).
- Rekonsiliasi pemakaian token, *embedding*, komputasi CPU/RAM, penyimpanan, dan perhitungan *shadow unit cost* per insiden termasuk eksekusi gagal (`AT-015`, `NFR-013`, `KPI-14`).
- Penyelesaian cacat dari [C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) pada split `DEV`, eksekusi regresi keamanan/kritis, dan pembekuan `final-release-manifest`.

### Out of Scope
- Mengklaim ketersediaan *High Availability* (HA), *Disaster Recovery* (DR) lintas pusat data, atau SLA produksi enterprise (`NFR-009`, `BRD §4.2`).
- Menyembunyikan tingkat konkurensi (mis. `20` atau `50`) yang gagal atau tidak dapat dijalankan; tingkat yang melebihi kapasitas lab wajib dilaporkan sebagai *observed resource ceiling* / `NOT_RUN` beserta alasannya.
- Membuka atau menggunakan split `H-G4` selama pengujian kapasitas dan perbaikan cacat di C20 (`NFR-019`).

## 4. Prerequisites
- Gate G3 ([C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md)) berstatus `PASS`.
- Hasil dan daftar temuan dari *Lab Shadow Pilot* ([C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md), `E19`) serta metrik telemetri biaya/sumber daya dari [C15](../phase-3-reasoning-observability/15-AI-OBSERVABILITY-AUDIT-AND-COST.md) (`E15`) telah tersedia.
- Batas alokasi sumber daya Docker Compose (`TBD-03`: 8 GiB RAM), plafon anggaran `$0.00` (`TBD-09`), dan kuota *rate-limit* (`ADR-S05`) telah aktif.

## 5. Implementation Roadmap
1. **Pengujian Kapasitas, Burst 100 Duplicate Alerts, dan Concurrency Ceiling (`OPS-01`, `NFR-010`)**
   - *Apa yang harus dilakukan:* Jalankan uji beban terukur pada: (a) aliran insiden normal, (b) semburan 100 *duplicate alerts* (`SC-12`, `OPS-01`), dan (c) gelombang `5`, `20`, serta `50` insiden unik konkuren (hentikan secara aman melalui *backpressure/budget guard* jika memori 8 GiB RAM atau *rate-limit* model gratis mencapai batas). Rekam deret waktu *throughput*, panjang antrean, jumlah panggilan *tool*, latensi P50/P95 (`NFR-007`), CPU/RAM kontainer, dan tingkat error.
   - *Mengapa diperlukan:* Membuktikan deduplikasi `OPS-01` secara *end-to-end* dan mendokumentasikan batas kapasitas nyata maket (`NFR-010`, `RISK-07`).
   - *Expected output:* Laporan dan deret waktu `capacity-series`.
   - *Cara memverifikasi:* Pastikan 100 *duplicate alerts* tetap menghasilkan 1 dossier idempoten tanpa lonjakan memori tak terkendali, dan setiap level konkuren (`5/20/50`) memiliki hasil terukur atau status `NOT_RUN (Capacity/Quota Ceiling Reached)` yang transparan.
2. **Eksekusi Resilience Drills dan Kill Switch (`OPS-02`, `AT-012`, `NFR-006`)**
   - *Apa yang harus dilakukan:* Lakukan latihan kegagalan terarah untuk: (a) *LLM outage/timeout* di tengah eksekusi (`SC-13`), (b) kegagalan adapter telemetri, (c) kegagalan indeks Qdrant/RAG, (d) kegagalan sink AI observability, (e) kejenuhan antrean (*backpressure* & DLQ), serta (f) penekanan *emergency kill switch*.
   - *Mengapa diperlukan:* Membuktikan bahwa seluruh mode kegagalan berhenti secara aman (*safe fallback*), tidak merusak layanan lab di luar target (`RULE-009`), dan selalu meninggalkan jejak di *independent security audit*.
   - *Expected output:* Rekaman bukti `outage-and-kill-switch`.
   - *Cara memverifikasi:* Periksa bahwa 100% kasus kegagalan kritis menghasilkan *fallback dossier* atau status terminal yang valid (`KPI-12`) dan 0 kejadian hilang tanpa jejak audit.
3. **Pengujian Canary/Publish, Rollback, dan Local Backup/Restore (`FR-RAG-008`, `NFR-014`)**
   - *Apa yang harus dilakukan:* Uji prosedur pembaruan dan *rollback* satu langkah untuk versi konfigurasi *workflow*, versi *model/prompt*, indeks KB (termasuk pembersihan *cache* dokumen yang ditarik), dan skema *tool*, serta uji pencadangan dan pemulihan (*backup/restore*) penyimpanan *state* dan audit lokal.
   - *Mengapa diperlukan:* Memastikan operator dapat memulihkan maket dengan cepat jika rilis konfigurasi baru mengalami regresi.
   - *Expected output:* Prosedur terverifikasi dan rekaman `rollback-restore-record`.
   - *Cara memverifikasi:* Terapkan satu versi konfigurasi/indeks uji, lakukan *rollback* ke versi sebelumnya, dan verifikasi bahwa hash manifes serta perilaku sistem kembali identik.
4. **Rekonsiliasi Basis Biaya Unit (`AT-015`, `KPI-14`) dan Perbaikan Defect Pilot**
   - *Apa yang harus dilakukan:* Selesaikan perbaikan atas `pilot-defects` dari [C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) menggunakan split `DEV`, lalu hitung rata-rata dan distribusi pemakaian token, panggilan *tool/embedding*, waktu CPU/memori, penyimpanan, dan estimasi *shadow unit cost* per insiden selesai maupun gagal (`AT-015`).
   - *Mengapa diperlukan:* Menyediakan model biaya berbasis observasi aktual (`BRD §20.2`) tanpa melanggar plafon tunai `$0.00` (`TBD-09`).
   - *Expected output:* Laporan `unit-cost-basis` dan catatan penutupan cacat pilot.
   - *Cara memverifikasi:* Pastikan perhitungan biaya mencantumkan beban dari *failed/timed-out runs* secara terpisah maupun gabungan sesuai aturan [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §8.5.
5. **Regresi Keamanan Rilis Final dan Pembekuan `final-release-manifest` (`NFR-019`)**
   - *Apa yang harus dilakukan:* Jalankan regresi penuh suite keselamatan kritis (12 test Lampiran A dan AT kritis pada split `DEV`) di atas kode pasca-perbaikan C20. Jika ada perubahan yang memengaruhi logika keamanan/kualitas Gate G3, pastikan Gate G3 tetap valid; setelah seluruh cek lulus, kunci seluruh hash komitmen kode, konfigurasi, *workflow*, *prompt*, model, dan indeks KB ke dalam `final-release-manifest`.
   - *Mengapa diperlukan:* Menjamin bahwa rilis yang diuji pada *final holdout* `H-G4` di [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md) dan demo `C22` adalah rilis yang sama persis dan telah terbeku.
   - *Expected output:* Paket bukti `E20` (`capacity-series`, `outage-and-kill-switch`, `rollback-restore-record`, `unit-cost-basis`, `final-release-manifest`).
   - *Cara memverifikasi:* Pastikan tidak ada *critical defect* terbuka dan hash `final-release-manifest` tercatat secara *immutable*.

## 6. Expected Deliverables
- Laporan profil kapasitas dan batas *concurrency ceiling* lab (`capacity-series`).
- Bukti latihan ketahanan *multi-outage* dan *kill switch* (`outage-and-kill-switch`).
- Prosedur dan bukti uji *publish/rollback* serta *local backup/restore* (`rollback-restore-record`).
- Laporan rekonsiliasi penggunaan sumber daya dan *shadow unit cost* (`unit-cost-basis`) beserta manifes rilis final yang dibekukan (`final-release-manifest`).
- Paket bukti tersanitasi `E20` pada `evidence/<run_id>/C20/`.

## 7. Validation & Exit Criteria
- `OPS-01` & `NFR-010`: Semburan 100 *duplicate alerts* berhasil ditangani secara idempoten dengan sumber daya terbatas; profil konkuren `5 / 20 / 50` telah diukur sesuai kemampuan lab (maks 8 GiB RAM) dengan pelaporan jujur atas *resource ceiling* dan level yang `NOT_RUN`.
- `OPS-02`, `AT-012`, & `NFR-006`: Seluruh latihan *outage* (LLM, adapter tool, indeks RAG, sink AI tracing) dan *kill switch* berhenti dengan aman, menghasilkan *fallback* yang sah (`KPI-12`), dan mempertahankan jejak *independent security audit*.
- `NFR-014`: Prosedur *rollback* untuk *workflow*, *model/prompt*, indeks KB, dan *tool schema* terbukti mengembalikan sistem ke versi sebelumnya tanpa korupsi *state*.
- `AT-015`: Rincian konsumsi token, komputasi, dan estimasi *shadow cost* per insiden telah terdokumentasi lengkap.
- `final-release-manifest` telah dibekukan dengan 0 *critical defect* terbuka dan 0 akses ke split `H-G4`.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Pengujian konkurensi `20` atau `50` insiden unik secara simultan pada laptop 16 GiB RAM (alokasi Docker 8 GiB) atau *Free-Tier LLM API* kemungkinan besar akan menyentuh batas memori atau *rate limit* (`DEP-01`, `DEP-06`); sesuai aturan proyek, kondisi ini **bukan** kegagalan yang harus disembunyikan, melainkan wajib dicatat sebagai *observed lab capacity ceiling* dan batas skala maket.
- **Open Decisions:** Tidak ada keputusan arsitektur baru; seluruh parameter rilis wajib dikunci di `final-release-manifest` pada akhir chapter ini.
- **Handover ke [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md):** Rilis final yang telah dibekukan (`final-release-manifest`), data biaya/kapasitas (`E20`), serta kesiapan untuk membuka segel *final holdout* `H-G4`.

## 9. Catatan Implementasi Tahap 2A: Hardening, Capacity, dan Resilience

### 9.1 Batas eksekusi

- **Run ID:** `c20-stage2a-20261120T090912Z`
- **Split:** `DEV` saja; partisi *Final Blind Holdout* tidak dibuka, dibaca, atau diparsing.
- **Biaya tunai:** `$0.00`; drill menggunakan backend sintetis lokal dan *in-process harness*.
- **Batas tahap:** Paket ini bukan `E20` final. Uji *publish/canary/rollback*, rekonsiliasi unit cost final `AT-015`, dan pembekuan `final-release-manifest` tetap `NOT_STARTED`.

### 9.2 Penutupan defect C19

| Defect | Disposisi Tahap 2A | Bukti regresi |
|---|---|---|
| `C19-DEF-001` | `RESOLVED`: viewport Rich menghitung ulang layout terhadap lebar terminal pada setiap refresh `Live` | `test_def001_viewport_reflows_against_current_console_width` |
| `C19-DEF-002` | `RESOLVED`: ringkasan evidence dan excerpt SOP disanitasi, dibatasi panjangnya, serta menampilkan versi SOP | `test_def002_bounded_sanitized_evidence_and_sop_version_render` |
| `C19-DEF-003` | `RESOLVED`: inisialisasi ulang memakai checkpoint + verifikasi tail; pembacaan penuh ditunda sampai history diminta; append diserialisasi | `test_def003_audit_tail_initialization_and_concurrent_chain_integrity` |
| `C19-DEF-004` | `RESOLVED`: revisi `v(N+1)` mewarisi `evidence`, `sop_citations`, dan `alert_received_at` | `test_def004_correct_revision_inherits_evidence_citations_and_alert_time` |
| `C19-DEF-005` | `CLOSED_WITH_DOCUMENTED_LIMITATION`: label solo-developer, bias familiaritas, dan status non-SME tetap wajib | `test_def005_manual_baseline_retains_solo_developer_bias_disclosure` |
| `C19-DEF-006` | `RESOLVED`: `kb_active_alias` menjadi kebijakan caller, `active_only` tetap alias legacy aman, dan query memuat ringkasan error tersanitasi | `test_def006_index_aliases_and_telemetry_enriched_query` |

### 9.3 Hasil kapasitas `OPS-01`

Sumber: [`capacity-series.json`](../../../evidence/c20-stage2a-20261120T090912Z/C20/capacity-series.json).

| Beban | Status | Hasil | Throughput | P50 / P95 | Peak RSS proses |
|---|---|---|---:|---:|---:|
| 100 duplicate alerts | `PASS` | 100 alert → 1 incident → 1 dossier; `hit_count=100` | 13,806.434 alert/s | 0.710 / 0.710 ms | 210.359 MiB |
| 5 unique concurrent | `PASS` | 5 accepted, 0 rejected, 5 dossier | 2,110.446 incident/s | 0.369 / 0.408 ms | 210.359 MiB |
| 20 unique concurrent | `PASS` | 20 accepted, 0 rejected, 20 dossier | 2,231.676 incident/s | 0.353 / 0.426 ms | 210.359 MiB |
| 50 unique concurrent | `PASS` | 50 accepted, 0 rejected, 50 dossier | 2,233.235 incident/s | 0.349 / 0.420 ms | 210.359 MiB |

Docker daemon tidak tersedia saat run, sehingga metrik kontainer diberi status `UNAVAILABLE`; angka CPU/RSS di atas secara eksplisit merupakan metrik proses harness dan tidak dilabeli ulang sebagai metrik kontainer. Seluruh level tetap berada di bawah plafon RAM lab 8 GiB.

### 9.4 Hasil resilience `OPS-02`, `AT-012`

Sumber: [`outage-and-kill-switch.json`](../../../evidence/c20-stage2a-20261120T090912Z/C20/outage-and-kill-switch.json).

- Enam dari enam drill `PASS`: LLM timeout, adapter telemetri, knowledge base, tracer sink, queue saturation, dan emergency kill switch.
- LLM timeout menghasilkan dossier `manual_fallback` dengan hipotesis `INCONCLUSIVE`.
- Outage telemetri menghasilkan `missing_sources` tanpa evidence imajiner; outage KB menghasilkan `NO_APPLICABLE_RUNBOOK`.
- Tracer sink fail-open tidak menghentikan investigasi; rantai audit lokal tetap valid.
- Queue saturation menghasilkan `REJECTED_BACKPRESSURE`; kill switch membatalkan incident aktif dan menolak intake baru dengan status `CANCELLED`.
- `safe_terminal_rate=100%`, `incidents_without_audit=0`, `auto_remediation_triggered=false`, dan `non_target_services_mutated=false`.

### 9.5 Verifikasi

- `python3 -m pytest -q tests/test_c20_capacity_resilience.py` → `8 passed`.
- Regresi terfokus C07/C11/C12/C13/C15/C16/C19/C20 → `102 passed`.
- `python3 scripts/run_c20_stage2a.py` → `PASS`; concurrency `5/20/50` seluruhnya `PASS`; resilience `6/6`.
- `python3 -m pytest -q tests/` → `469 passed, 6 skipped`; seluruh tes yang dieksekusi lulus.

