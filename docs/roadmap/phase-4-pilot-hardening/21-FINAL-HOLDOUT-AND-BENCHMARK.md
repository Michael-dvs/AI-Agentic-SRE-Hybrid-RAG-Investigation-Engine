# C21 — Final Holdout and Benchmark

## 1. Chapter Information
- **Phase:** F4 — Pilot & Hardening (Menghasilkan bukti benchmark final menuju Gate `G4` di `C24`; **tidak** mengesahkan Gate `G4` secara langsung)
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C17 — Offline Evaluation and UAT Harness](../phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md), [C19 — Lab Shadow Pilot and Manual Baseline](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md), [C20 — Capacity, Resilience, and Rollback](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md), `G3 PASS` ([C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md) masih berlaku), `final-release-manifest` dan split `H-G4` dalam keadaan *frozen*
- **Next chapter:** `C22 — Reproducibility, Operations, and Demo` (`22-REPRODUCIBILITY-OPERATIONS-AND-DEMO.md` — didefinisikan pada [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), berstatus `NOT_STARTED`)
- **Related requirements:** `BR-003`, `BR-006`, `BR-008`, `BR-009`, `BR-011`, `FR-SIM-005`, `FR-SIM-006`, `FR-OBS-006`, `FR-RAG-003`–`007`, `FR-AGT-005`–`006`, `FR-AGT-008`, `FR-OUT-001`, `FR-OUT-003`–`004`, `FR-OUT-007` (Could), `RULE-002`, `RULE-007`, `RULE-010`–`012`, `NFR-004`–`005`, `NFR-007`–`008`, `NFR-013`, `NFR-019`, `KPI-01` s/d `KPI-14`, `OBJ-01`–`04`, `OBJ-07`, `BEN-01`–`04`, `RISK-01`, `RISK-09`, `RISK-14`, `SC-01` s/d `SC-14`
- **Related acceptance tests:** Test owner **Final Blind Holdout (`H-G4`)** untuk **`AT-014`** (`KPI-01` s/d `KPI-14`) dan **`AT-015`**, serta verifikasi rilis final untuk seluruh **12 test Proposal Lampiran A** (`SEC-01`–`03`, `MCP-01`–`02`, `RAG-01`–`02`, `EV-01`–`02`, `OPS-01`–`02`, `HUM-01`) dan suite kritis BRD (`AT-004` s/d `AT-012`, `AT-016`, serta `AT-017` kondisional; sementara `AT-013` dua *clean replay* final dijalankan di `C22` dan persetujuan Gate `G4` berada di `C24`)

## 2. Objective & Expected Outcome
Chapter ini bertujuan menjalankan evaluasi buta akhir (*Final Blind Holdout Benchmark*) di atas split `H-G4` yang belum pernah dibuka menggunakan rilis final yang telah dibekukan di [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md), serta mengonsolidasikan seluruh hasil pengukuran `KPI-01` s/d `KPI-14`, suite penerimaan Lampiran A dan BRD, perbandingan baseline manual ([C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md)), dan analisis kasus gagal secara transparan (`BR-008`, `BR-009`). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), C21 menghasilkan bukti benchmark final menuju Gate G4, **tetapi tidak menyetujui Gate G4 itu sendiri** (keputusan formal Gate G4 berada di `C24` setelah pembuktian dua *clean replay* `C22` dan analisis kesenjangan enterprise `C23`).

Setelah chapter ini selesai, tersedia laporan benchmark final (`kpi-report`) beserta skor mentah yang dapat direproduksi (`raw-scores`), hasil perbandingan mode *Hybrid RAG* vs *lexical-only* vs *dense-only* (dan ablasi *reranker* `FR-RAG-007`) pada kueri `H-G4`, hasil akurasi diagnosis *Top-3*, *evidence coverage*, *unsupported claim rate*, latensi, biaya unit, dan keselamatan pada skenario insiden `H-G4`, serta analisis kegagalan terperinci (`reviewed-failure-analysis`) tanpa penyesuaian ambang target pasca-uji (*no post-hoc threshold adjustment*, `RULE-012`).

## 3. Scope & Boundaries
### In Scope
- Pemeriksaan *preflight* atas kecocokan hash `final-release-manifest` ([C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md)), keutuhan segel split `H-G4` ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)), dan isolasi *ground truth* (`RULE-002`, `RULE-010`, `NFR-019`).
- Eksekusi *Final Retrieval Benchmark* (`AT-006`, `KPI-05`, `NFR-008`) untuk membandingkan `lexical-only`, `dense-only`, `hybrid`, dan `hybrid+reranker` pada himpunan kueri `H-G4`.
- Eksekusi *Final Blind Incident Replay* (`AT-014`) di atas skenario `H-G4` yang mencakup kasus sehat (`SC-01`), gangguan tunggal (`SC-02`, `SC-03`, `SC-05`, `SC-06`, `SC-07`), *cascade* (`SC-04`, `AT-016`), *concurrent independent faults* (`SC-08`), kehilangan *trace* (`SC-09`, `EV-02`), jebakan SOP usang (`SC-10`, `RAG-01`), injeksi log adversarial (`SC-11`, `SEC-02`), *duplicate burst* (`SC-12`, `OPS-01`), *LLM outage* (`SC-13`, `OPS-02`), dan korelasi menyesatkan (`SC-14`, `EV-01`), ditambah verifikasi regresi 12 test Lampiran A pada rilis final.
- Penghitungan akhir `KPI-01` s/d `KPI-14` menggunakan *scorer* terbeku [C17](../phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md), termasuk perbandingan terhadap baseline manual [C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) (`KPI-08`) bila valid dan analisis mendalam atas seluruh kasus gagal.

### Out of Scope
- Melakukan perubahan kode, prompt, bobot retrieval, atau konfigurasi setelah segel `H-G4` dibuka lalu mengklaim hasil revisi tersebut sebagai hasil *blind benchmark* pada `H-G4` yang sama (`BRD §21.1`).
- Mengubah definisi denominator KPI atau menurunkan ambang kelulusan setelah melihat skor akhir (`RULE-012`).
- Mengeksekusi dua *clean environment replay* `AT-013` atau panduan demo operasional (dikerjakan di `C22`) dan menandatangani keputusan kelayakan Gate G4 (dikerjakan di `C24`).

## 4. Prerequisites
- Gate G3 ([C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md)) masih berstatus `PASS` dan valid terhadap rilis yang dibekukan.
- *Offline Evaluation Harness* ([C17](../phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md), `E17`), rekaman baseline manual dan rubrik reviewer ([C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md), `E19`), serta `final-release-manifest` dan basis biaya ([C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md), `E20`) telah tersedia lengkap.
- Segel kriptografis (SHA-256) dan log akses membuktikan bahwa dataset `H-G4` belum pernah dibuka atau digunakan selama Fase 1 s/d `C20`.

## 5. Implementation Roadmap
1. **Verifikasi Preflight Release Freeze dan Segel Split `H-G4` (`RULE-010`, `NFR-019`)**
   - *Apa yang harus dilakukan:* Periksa kesesuaian SHA-256 seluruh artefak kode, konfigurasi, model/prompt, dan indeks KB terhadap `final-release-manifest` dari [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md), serta verifikasi bahwa hash split `H-G4` cocok dengan baseline Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) dan memiliki 0 akses baca sebelumnya.
   - *Mengapa diperlukan:* Membuktikan secara matematis bahwa benchmark akhir dijalankan di atas rilis yang terbeku dan dataset `H-G4` yang murni *blind*.
   - *Expected output:* Berkas `holdout-g4-manifest`.
   - *Cara memverifikasi:* Hentikan eksekusi jika terdapat perbedaan satu *byte* pun pada hash rilis atau jika ditemukan riwayat akses ke `H-G4` sebelum C21.
2. **Eksekusi Final Retrieval Benchmark dan Blind Incident Replay pada `H-G4` (`AT-006`, `AT-014`)**
   - *Apa yang harus dilakukan:* Jalankan benchmark keempat mode *retrieval* (`lexical-only`, `dense-only`, `hybrid`, `hybrid+reranker`) pada kueri `H-G4`, kemudian jalankan *blind incident replay* untuk seluruh skenario insiden di `H-G4` (termasuk variasi multi-seed sesuai protokol G1) hingga dossier ditutup dan dievaluasi oleh *Offline Evaluation Harness* ([C17](../phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)), serta jalankan verifikasi akhir 12 test Lampiran A Proposal.
   - *Mengapa diperlukan:* Menghasilkan bukti empiris utama untuk menilai pencapaian objektif bisnis `OBJ-01` s/d `OBJ-05` dan `BEN-01` s/d `BEN-04`.
   - *Expected output:* Rekaman lengkap `raw-scores` serta seluruh dossier yang berhasil maupun gagal/timeout.
   - *Cara memverifikasi:* Pastikan 100% jadwal eksekusi `H-G4` tercatat di dalam `raw-scores` tanpa ada eksekusi gagal yang dihapus, dan pemeriksaan `AT-008` membuktikan 0 akses *ground truth* oleh agent selama *run*.
3. **Kalkulasi Konsolidasi `KPI-01` s/d `KPI-14` dan Perbandingan Baseline Manual (`AT-014`, `AT-015`)**
   - *Apa yang harus dilakukan:* Hitung nilai akhir seluruh `KPI-01` s/d `KPI-14` beserta interval kepercayaan/dispersi antar-seed dan rincian per layanan/skenario/tingkat kesulitan. Gabungkan dengan data waktu manual dari [C19](19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) untuk `KPI-08` (atau cantumkan status `NOT_EVALUABLE / CAVEAT` beserta alasannya jika baseline manual memiliki keterbatasan *self-review*) dan data biaya dari [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md) untuk `KPI-14`/`AT-015`.
   - *Mengapa diperlukan:* Menyajikan papan skor yang transparan dan mematuhi aturan bahwa keselamatan kritis (`KPI-09`, `KPI-10`, `KPI-11`) dinilai secara terpisah dari rata-rata akurasi (`BRD §15.5`).
   - *Expected output:* Laporan komprehensif `kpi-report` dan `baseline-comparison-or-limitation`.
   - *Cara memverifikasi:* Hitung ulang sampel metrik dari `raw-scores` untuk memastikan konsistensi 100% dengan tabel di `kpi-report`.
4. **Analisis Kegagalan Terperinci dan Klasifikasi Batas Generalisasi (`BR-009`, `BRD §21.1`)**
   - *Apa yang harus dilakukan:* Tinjau setiap kasus di `H-G4` yang menghasilkan diagnosis kurang tepat, klaim `UNSUPPORTED`, status `INCONCLUSIVE`, atau latensi tinggi, lalu klasifikasikan akar masalahnya di dalam `reviewed-failure-analysis`.
   - *Mengapa diperlukan:* Memberikan dasar teknis yang jujur bagi kajian kesenjangan enterprise di `C23` dan keputusan pemilik proyek pada Gate G4 (`GO` / `CONDITIONAL GO` / `NO-GO`).
   - *Expected output:* Dokumen `reviewed-failure-analysis`.
   - *Cara memverifikasi:* Pastikan setiap kegagalan atau anomali di `raw-scores` dibahas secara eksplisit tanpa disembunyikan.

5. **Pengemasan Bukti Benchmark `E21` dan Penjagaan Lock Rilis Menuju `C22`–`C24`**
   - *Apa yang harus dilakukan:* Kumpulkan seluruh artefak (`holdout-g4-manifest`, `raw-scores`, `kpi-report`, `baseline-comparison-or-limitation`, `reviewed-failure-analysis`) ke dalam paket `E21`, dan pastikan kode/konfigurasi rilis tetap terkunci tanpa perubahan pasca-uji untuk digunakan pada dua *clean replay* di `C22`.
   - *Mengapa diperlukan:* Mematuhi aturan `RULE-012` (*no post-hoc tuning/threshold adjustment*) dan menjaga konsistensi versi antara benchmark `C21` dan uji reproduktifitas `C22`.
   - *Expected output:* Paket bukti lengkap `E21` pada `evidence/<run_id>/C21/`.
   - *Cara memverifikasi:* Pastikan kelima berkas `E21` lengkap dan hash `final-release-manifest` sesudah eksekusi `H-G4` identik 100% dengan hash sebelum eksekusi.

## 6. Expected Deliverables
- Manifes verifikasi *preflight* rilis final dan keutuhan segel `H-G4` (`holdout-g4-manifest`).
- Kumpulan skor mentah yang dapat direproduksi (`raw-scores`) untuk benchmark *retrieval*, *incident diagnosis*, *evidence faithfulness*, *latency*, *cost*, dan *safety* pada `H-G4`.
- Laporan konsolidasi `KPI-01` s/d `KPI-14` (`kpi-report`) beserta evaluasi perbandingan manual atau deklarasi keterbatasannya (`baseline-comparison-or-limitation`).
- Laporan analisis kasus gagal dan batas generalisasi (`reviewed-failure-analysis`).
- Paket bukti tersanitasi `E21` pada `evidence/<run_id>/C21/`: `holdout-g4-manifest`, `raw-scores`, `kpi-report`, `baseline-comparison-or-limitation`, dan `reviewed-failure-analysis`.

## 7. Validation & Exit Criteria
- `AT-014` & `AT-015` (final benchmark): Seluruh `KPI-01` s/d `KPI-14` telah dihitung pada split *locked holdout* `H-G4` menggunakan protokol dan denominator yang dibekukan di Gate G1, lengkap dengan nilai terukur, dispersi, rincian biaya unit, atau alasan `NOT_EVALUABLE` yang transparan.
- Seluruh 12 pengujian Lampiran A Proposal (`SEC-01`–`03`, `MCP-01`–`02`, `RAG-01`–`02`, `EV-01`–`02`, `OPS-01`–`02`, `HUM-01`) dan pengujian kritis BRD (`AT-004` s/d `AT-012`, `AT-016`, serta `AT-017` kondisional) terverifikasi pada rilis final, dengan 0 pelanggaran pada metrik keselamatan wajib (`KPI-09` = 0, `KPI-10` = 0, `KPI-11` = 0).
- Tidak ada modifikasi kode, prompt, atau penurunan ambang KPI setelah `H-G4` dijalankan (`BRD §21.1`, `RULE-012`).
- **Batas Gate G4:** Penyelesaian C21 menyediakan bukti kuantitatif utama untuk Gate G4, **tetapi belum meluluskan Gate G4**; kelulusan Gate G4 wajib menunggu penyelesaian dua *clean environment replay* (`AT-013`) dan SOP demo di `C22`, tinjauan risiko & kesenjangan enterprise di `C23`, serta penandatanganan keputusan di `C24`.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Menyamakan hasil benchmark pada dataset sintetis skala kecil dengan jaminan akurasi pada insiden produksi perbankan nyata (`RISK-11`, `RISK-14`); mitigasi dengan mendokumentasikan seluruh kasus gagal dan batas representativeness di `reviewed-failure-analysis` sebagai input langsung bagi `C23`.
- **Open Decisions:** Apabila setelah C21 ditemukan cacat kritis yang memaksa perubahan kode/prompt/model, klaim hasil benchmark `H-G4` untuk versi baru tersebut batal demi aturan `BRD §21.1` dan mengharuskan siklus evaluasi baru dengan split *holdout* independen (`TBD — Decision Required` oleh pemilik proyek jika terjadi regresi kritis).
- **Handover ke `C22 — Reproducibility, Operations, and Demo` ([Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md)):** Rilis benchmark yang tetap terkunci (`final-release-manifest`), paket skor dan analisis kegagalan `E21`, serta kesiapan untuk pembuktian dua *clean environment replay* (`AT-013`) di `C22`, kajian kesenjangan enterprise di `C23`, dan keputusan akhir **Gate G4** di `C24`.
