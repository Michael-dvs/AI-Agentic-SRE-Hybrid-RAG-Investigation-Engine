# C17 — Offline Evaluation and UAT Harness

## 1. Chapter Information
- **Phase:** F3 — Reasoning & Observability
- **Status:** APPROVED
- **Documentation status:** APPROVED
- **Implementation status:** VERIFIED
- **Evidence resmi:** [`E17`](../../../evidence/c17-20261119T032931Z-6ad5ea8e/C17/readiness-check.md); 0 open defects, segel holdout `VERIFIED` via baseline hash check Gate G1, dan kualifikasi scorer 100% lulus. Regresi penuh repositori: 421 passed, 6 skipped, 0 failed.
- **Dependencies:** [C04 — Fault Harness and Ground Truth Isolation](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md), [C07 — Hybrid Retrieval and Baselines](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md), [C08 — Secure Gateway and Foundation G1](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) (`G1 PASS` & protokol evaluasi dibekukan), [C14 — Evidence Validation and Uncertainty](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md), [C15 — AI Observability, Audit, and Cost](15-AI-OBSERVABILITY-AUDIT-AND-COST.md), [C16 — Human Review and Handover](16-HUMAN-REVIEW-AND-HANDOVER.md), `G2 PASS` ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md))
- **Next chapter:** [C18 — Red-Team, Holdout, and G3](18-RED-TEAM-HOLDOUT-AND-G3.md)
- **Related requirements:** `BR-008`, `BR-009`, `FR-SIM-005`, `FR-RAG-006`, `FR-AGT-008`, `FR-OUT-005`, `RULE-002`, `RULE-010`, `RULE-012`, `NFR-011`, `NFR-019`, `KPI-01` s/d `KPI-14`, `OBJ-06`, `RISK-01`, `RISK-02`, `RISK-09`
- **Related acceptance tests:** `AT-014` (build owner *offline evaluation harness* & *scorer verification*; eksekusi `H-G3` di C18 dan `H-G4` di C21), `AT-008` (build owner mekanisme *delayed GT join* hanya setelah investigasi `CLOSED`), serta eksekusi regresi pada split `DEV` untuk seluruh **12 ID Lampiran A** (`SEC-01`–`03`, `MCP-01`–`02`, `RAG-01`–`02`, `EV-01`–`02`, `OPS-01`–`02`, `HUM-01`) dan `AT-001`–`AT-016` (plus `AT-017` kondisional)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *Offline Evaluation and UAT Harness* yang mengeksekusi penghitungan metrik kualitas (`KPI-01` s/d `KPI-14`) serta buku besar pengujian penerimaan (*UAT ledger*) secara terisolasi tanpa pernah membuka akses *ground truth* kepada *runtime* agent (`RULE-002`, `BR-008`). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), penggabungan (*join*) antara hasil dossier dengan kunci jawaban di *Restricted Ground Truth Registry* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)) hanya boleh dilakukan oleh proses evaluator offline **setelah** status investigasi ditutup (`CLOSED`), dan hasil evaluasi tidak boleh diumpankan kembali ke memori, prompt, atau indeks RAG agent.

Setelah chapter ini selesai, sistem memiliki *evaluation runner* yang mencatat manifes reproduktifitas lengkap (`run_id`, *opaque* `incident_id`, `seed`, `code_commit`, versi *service/workflow/model/prompt/tool/KB*, `RULE-010`), *scorer* terverifikasi untuk seluruh `KPI-01` s/d `KPI-14` yang telah lulus uji akurasi penghitungan pada kasus positif/negatif yang diketahui di split `DEV`, serta buku besar regresi `DEV` (`dev-uat-ledger`) dan daftar temuan cacat (`defects`) sebagai prasyarat sebelum membuka *blind holdout* `H-G3` di [C18](18-RED-TEAM-HOLDOUT-AND-G3.md).

## 3. Scope & Boundaries
### In Scope
- Implementasi *Offline Evaluation Runner* dengan identitas kredensial khusus `offline-evaluator` yang memetakan *opaque* `incident_id`/`run_id` ke `scenario_id` dan label *ground truth* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)) **hanya** sesudah investigasi berstatus terminal `CLOSED` (`RULE-002`, `D-C02-05`).
- Implementasi kalkulator metrik terbeku (`KPI-01` s/d `KPI-14`) sesuai definisi dan denominator yang telah disahkan pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md): `TBD-10`, `ADR-S08`), termasuk penanganan kasus *multi-fault* (`SC-08`), kasus sehat (`SC-01`), dossier dengan 0 klaim material, serta eksekusi yang gagal/*timeout* tanpa mempercantik denominator.
- Verifikasi kebenaran kalkulator (*scorer verification*) menggunakan kasus uji sintetis berlabel di split `DEV` (termasuk diagnosis salah, klaim tanpa bukti, sitasi *obsolete*, dan *fallback*).
- Eksekusi regresi penuh pada split `DEV` untuk seluruh 12 pengujian Lampiran A Proposal dan `AT-001` s/d `AT-016` (serta `AT-017` sesuai disposisi) dengan pencatatan ke dalam `dev-uat-ledger` dan `defect-register`.

### Out of Scope
- Membuka atau menjalankan kueri/skenario dari split *holdout* `H-G3` (dijalankan di [C18](18-RED-TEAM-HOLDOUT-AND-G3.md)) maupun `H-G4` (dijalankan di [C21](../phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md)) selama pengembangan dan *debugging* *harness* di C17 (`FR-RAG-006`, `NFR-019`).
- Klaim bahwa pengujian regresi pada split `DEV` merupakan bukti kelulusan final `AT-013` (dua *clean replay* final di C22) atau `AT-014` (*locked holdout benchmark* di C18/C21).

## 4. Prerequisites
- Gate G2 ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)) berstatus `PASS`, dan protokol evaluasi/denominator KPI telah dibekukan pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- *Restricted Ground Truth Registry* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)), layanan *Hybrid Retrieval* ([C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md)), *Evidence Validator* ([C14](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)), kolektor metrik/audit ([C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md)), dan *Human Review* ([C16](16-HUMAN-REVIEW-AND-HANDOVER.md)) telah beroperasi penuh.
- Skema `evaluation-manifest`, `evaluation-result`, dan format rekaman UAT (`Master Roadmap §7.3`) tersedia dari [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md).

## 5. Implementation Roadmap
1. **Implementasi Reproducible Run Registry dan Delayed Ground-Truth Join (`RULE-002`, `RULE-010`)**
   - *Apa yang harus dilakukan:* Bangun *runner* evaluasi terisolasi yang merekam manifes eksekusi lengkap (`run_id`, `incident_id`, `seed`, `code_commit`, versi *service/config/workflow/model/prompt/tool/KB*, *timestamp*) dan memberlakukan penjaga kode (*guard*) yang menolak pembacaan/penggabungan *ground truth* apabila status insiden belum `CLOSED`. Pastikan hasil *join* disimpan khusus di direktori evaluator dan tidak pernah ditulis ke ruang kerja *agent runtime*.
   - *Mengapa diperlukan:* Mencegah kebocoran kunci jawaban selama investigasi berlangsung (`AT-008`, `KPI-10`).
   - *Expected output:* Modul *Offline Evaluation Runner* dan `evaluation-manifest-schema`.
   - *Cara memverifikasi:* Coba panggil fungsi *GT join* terhadap insiden yang masih berstatus `HYPOTHESES` atau `HUMAN_REVIEW`; pastikan panggilan ditolak dengan error pelanggaran protokol.
2. **Implementasi Scorer `KPI-01` s/d `KPI-14` Tanpa Manipulasi Denominator (`BRD §15.2`, `ADR-S08`)**
   - *Apa yang harus dilakukan:* Kodifikasikan fungsi penghitung untuk semua 14 KPI: tingkat penyelesaian (`KPI-01`), akurasi *Top-3 root cause* termasuk aturan *multi-fault* `SC-08` (`KPI-02`), *evidence coverage* (`KPI-03`), *unsupported material claim rate* (`KPI-04`), *retrieval Hit-Rate@5* dan *Classical Recall@5* (`KPI-05`), penerimaan reviewer tanpa *substantial rework* (`KPI-06`), latensi P95 `intake-to-dossier` (`KPI-07`), efisiensi relatif terhadap baseline manual jika tersedia (`KPI-08`), serta enam metrik keselamatan/operasional (`KPI-09` s/d `KPI-14`).
   - *Mengapa diperlukan:* Menjamin seluruh angka benchmark dihitung dengan rumus deterministik yang sama dan tidak mengecualikan kasus gagal/*timeout* secara diam-diam (`RISK-09`).
   - *Expected output:* Pustaka *scorer* terbeku dan dokumen `metric-definitions`.
   - *Cara memverifikasi:* Periksa bahwa *failed/timed-out runs* tetap masuk sebagai kegagalan pada `KPI-01` dan biayanya tetap dihitung pada `KPI-14`.
3. **Verifikasi Akurasi Scorer dengan Fixture Positif dan Negatif (`Scorer Qualification`)**
   - *Apa yang harus dilakukan:* Uji kalkulator *scorer* menggunakan kumpulan dossier sintetis yang hasilnya sudah diketahui secara pasti: (a) diagnosis *Top-1* dan *Top-3* benar, (b) diagnosis salah total, (c) dossier dengan klaim tanpa bukti (`KPI-04` > 2%), (d) dossier yang mengutip SOP *obsolete* (`KPI-11` gagal), dan (e) dossier *fallback* akibat *outage* (`KPI-12`).
   - *Mengapa diperlukan:* Membuktikan *scorer* tidak menghasilkan nilai *hardcoded* atau *false pass* sebelum digunakan menilai Gate G3 dan G4.
   - *Expected output:* Laporan verifikasi kalkulator `scorer-checks`.
   - *Cara memverifikasi:* Pastikan skor yang dikeluarkan oleh program cocok 100% dengan perhitungan manual pada kelima fixture uji.
4. **Eksekusi Regresi UAT Lengkap pada Split `DEV` (`Master Roadmap §7.3`)**
   - *Apa yang harus dilakukan:* Jalankan seluruh 12 skenario pengujian Lampiran A Proposal (`SEC-01`–`03`, `MCP-01`–`02`, `RAG-01`–`02`, `EV-01`–`02`, `OPS-01`–`02`, `HUM-01`) dan `AT-001` s/d `AT-016` (plus disposisi `AT-017`) menggunakan skenario dan kueri dari split `DEV`, lalu rekam setiap baris hasil (`test_run_id`, `test_id`, `requirement_ids`, `preconditions`, `commands`, `expected`, `actual`, `status`, `evidence_link`, `defect_id`, `reviewer`, `disposition`) ke `dev-uat-ledger`.
   - *Mengapa diperlukan:* Menemukan dan memperbaiki cacat integrasi pada split `DEV` sebelum membuka segel *blind holdout* `H-G3` di [C18](18-RED-TEAM-HOLDOUT-AND-G3.md).
   - *Expected output:* Buku besar `dev-uat-ledger` yang terisi lengkap dari eksekusi nyata pada split `DEV`.
   - *Cara memverifikasi:* Pastikan seluruh baris pada `dev-uat-ledger` memiliki tautan bukti yang valid dan 0 hasil yang difabrikasi.

5. **Pencatatan Defect, Verifikasi Keutuhan Segel Holdout, dan Pengemasan Bukti `E17`**
   - *Apa yang harus dilakukan:* Dokumentasikan seluruh temuan kegagalan dari split `DEV` beserta tindak lanjut perbaikannya ke dalam `defects`, verifikasi bahwa hash serta log akses split `H-G3` dan `H-G4` belum tersentuh, lalu kemas seluruh artefak ke dalam paket `E17`.
   - *Mengapa diperlukan:* Menjamin integritas pemisahan dataset (`NFR-019`) dan kesiapan masuk ke evaluasi **Gate G3** ([C18](18-RED-TEAM-HOLDOUT-AND-G3.md)).
   - *Expected output:* Paket bukti `E17` (`evaluation-manifest-schema`, `metric-definitions`, `dev-uat-ledger`, `scorer-checks`, `defects`).
   - *Cara memverifikasi:* Pastikan log akses membuktikan split `H-G3` serta `H-G4` memiliki 0 pembacaan selama C17 dan kandidat rilis siap dibekukan.

## 6. Expected Deliverables
- *Offline Evaluation and UAT Harness* yang berjalan dengan identitas terpisah dan menegakkan *post-closure Ground Truth join*.
- Modul kalkulator metrik terbeku untuk `KPI-01` s/d `KPI-14` beserta bukti kualifikasi `scorer-checks`.
- Buku besar hasil regresi UAT pada split `DEV` (`dev-uat-ledger`) dan registri cacat (`defects`).
- Paket bukti tersanitasi `E17` pada `evidence/<run_id>/C17/`: `evaluation-manifest-schema`, `metric-definitions`, `dev-uat-ledger`, `scorer-checks`, dan `defects` (sementara tabel *join* label *ground truth* disimpan di area terbatas evaluator).

## 7. Validation & Exit Criteria
- `AT-008` & `RULE-002` (sisi evaluator): Penggabungan *ground truth* terbukti hanya dapat dieksekusi setelah insiden berstatus `CLOSED`, dan tidak ada artefak hasil *join* yang dapat diakses oleh *agent runtime*.
- `AT-014` (kesiapan *harness*): Kalkulator `KPI-01` s/d `KPI-14` terbukti akurat melalui `scorer-checks` dan dapat dihitung ulang secara deterministik dari rekaman observasi mentah.
- Seluruh 12 ID pengujian Lampiran A Proposal dan `AT-001` s/d `AT-016` telah memiliki prosedur otomatis/terstruktur yang dieksekusi pada split `DEV` dengan hasil dan *defect* tercatat jujur.
- Hash dan log akses membuktikan bahwa dataset *holdout* `H-G3` dan `H-G4` masih tersegel utuh (0 pembacaan selama C17).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Memperbaiki prompt atau aturan setelah melihat kegagalan tanpa memisahkan mana skenario `DEV` dan mana skenario `holdout` (`RISK-01`); mitigasi dengan membatasi seluruh iterasi C17 hanya pada split `DEV`.
- **Open Decisions:** Apabila reviewer SME eksternal (`TBD-08`) belum tersedia, seluruh penilaian rubrik manusia di dalam *harness* wajib diberi atribut `label_source: SELF_EVALUATED_DEVELOPER_LABELS` secara transparan.
- **Handover ke [C18](18-RED-TEAM-HOLDOUT-AND-G3.md):** Kandidat rilis Fase 3 yang telah dibekukan pasca-perbaikan cacat `DEV`, *evaluation harness* yang telah terverifikasi (`E17`), serta kesiapan pembukaan *blind holdout* `H-G3` untuk penilaian **Gate G3**.
