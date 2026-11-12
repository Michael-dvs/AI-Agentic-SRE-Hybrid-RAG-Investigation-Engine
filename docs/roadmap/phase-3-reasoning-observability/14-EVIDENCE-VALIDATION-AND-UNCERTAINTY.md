# C14 — Evidence Validation and Uncertainty

## 1. Chapter Information
- **Phase:** F3 — Reasoning & Observability
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C07 — Hybrid Retrieval and Baselines](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md), [C09 — Read-Only Telemetry Adapters](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md), [C13 — Controlled LLM Investigator](13-CONTROLLED-LLM-INVESTIGATOR.md), `G2 PASS` ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md))
- **Next chapter:** [C15 — AI Observability, Audit, and Cost](15-AI-OBSERVABILITY-AUDIT-AND-COST.md)
- **Related requirements:** `BR-003`, `BR-006`, `BR-013`, `FR-SIM-006`, `FR-OBS-006`, `FR-OBS-007`, `FR-RAG-004`, `FR-RAG-009`, `FR-AGT-005`, `FR-AGT-006`, `FR-AGT-007`, `FR-AGT-010`, `FR-OUT-003`, `RULE-005`, `RULE-006`, `RULE-007`, `NFR-004`, `NFR-016`, `KPI-03`, `KPI-04`, `KPI-11`, `OBJ-02`, `OBJ-03`, `RISK-03`, `RISK-04`, `SC-03` s/d `SC-10`, `SC-14`, `UC-02`, `UC-05` s/d `UC-08`
- **Related acceptance tests:** `EV-01` (build & test owner utama konflik metrik vs log; regresi di C18/C21), `EV-02` (build & test owner validasi akhir ketiadaan trace imajiner di dossier; regresi di C18/C21), `AT-009` (build & test owner utama bukti hilang/kontradiktif $\rightarrow$ `PARTIAL`/`INCONCLUSIVE`), `RAG-01` & `RAG-02` (build & test owner sisi *output dossier/SOP applicability*), `AT-007` (build & test owner sisi *applicability validation*), `AT-016` (build & test owner pembedaan *origin vs downstream impact* dan *uncertainty* pada *cascade*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *Deterministic Evidence & Applicability Validator* pada tahap `VALIDATED` yang memeriksa setiap klaim material dan kutipan SOP yang dihasilkan oleh [C13](13-CONTROLLED-LLM-INVESTIGATOR.md) terhadap *original bounded evidence* dari [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md) dan metadata dokumen dari [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) dan desain kontrak [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), validator tidak boleh hanya memercayai ringkasan model; validator wajib membaca langsung *evidence bundle* asli untuk mencegah halusinasi bukti, mendeteksi kontradiksi antarsinyal (`EV-01`), menangani korelasi waktu yang menyesatkan (`SC-14`), dan melarang promosi hipotesis menjadi `VERIFIED` (`RULE-007`).

Setelah chapter ini selesai, setiap klaim material di dalam dossier memiliki tautan `evidence_id` yang valid dan berada di dalam jendela waktu insiden atau secara eksplisit ditandai `UNSUPPORTED` dan diturunkan/dibuang (`FR-AGT-006`, `NFR-004`), konflik antara metrik dan log (`EV-01`) atau hilangnya sumber *trace* (`EV-02`, `SC-09`) secara otomatis menghasilkan label `PARTIAL` atau `INCONCLUSIVE` (`AT-009`), gangguan *cascade* (`SC-04`, `AT-016`) dan *concurrent faults* (`SC-08`) tidak disederhanakan secara palsu menjadi satu penyebab tunggal, serta rekomendasi SOP yang *obsolete* (`SC-10`, `RAG-01`) atau salah layanan/environment (`RAG-02`) dicegah masuk ke dossier akhir (`KPI-11` = 0).

## 3. Scope & Boundaries
### In Scope
- Pemeriksaan deterministik keterikatan klaim $\rightarrow$ `evidence_id` (`source_ref`), kesesuaian rentang waktu (`observed_at` berada di dalam `query_window` dan jendela insiden), serta status kualitas data (`complete`, `partial`, `truncated`, `unavailable`) (`FR-AGT-006`, `NFR-004`).
- Deteksi kontradiksi bukti (mis. metrik menunjukkan normal sementara log mengklaim error masif atau sebaliknya, `EV-01`), deteksi gejala di luar jendela waktu penyebab sebenarnya (`SC-14`), dan pembedaan *origin vs downstream symptom* pada *cascade* (`SC-03`–`SC-07`, `AT-016`) serta *concurrent independent faults* (`SC-08`).
- Aturan penetapan status investigasi ke `SUPPORTED`, `PARTIAL`, atau `INCONCLUSIVE` beserta daftar `supporting_evidence`, `contradicting_evidence`, dan `unknowns`, serta blokade keras terhadap penggunaan label `VERIFIED` (`RULE-007`).
- Pemeriksaan ulang (*post-retrieval output check*) atas setiap sitasi SOP terhadap `service.name`, `environment`, `status=active`, dan masa berlaku (`effective_from`/`effective_to`) sebelum dirangkum ke dalam dossier (`RULE-005`, `RAG-01`, `RAG-02`, `AT-007`).

### Out of Scope
- Mengizinkan LLM mengesampingkan keputusan penolakan dari validator deterministik.
- Mengakses *ground truth registry* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)) untuk memvalidasi apakah hipotesis model benar (`RULE-002`; validator hanya memeriksa konsistensi terhadap bukti telemetri/SOP yang tersedia bagi runtime).

## 4. Prerequisites
- Gate G2 ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)) berstatus `PASS`.
- Output kandidat hipotesis berstruktur dari [C13](13-CONTROLLED-LLM-INVESTIGATOR.md) (`E13`), *evidence envelope* asli dari [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md) (`E09`), dan metadata sitasi *Hybrid RAG* dari [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md) (`E07`) tersedia.
- Kontrak aturan validasi klaim, *reason codes*, dan matriks penurunan status (`SUPPORTED` / `PARTIAL` / `INCONCLUSIVE`) dari [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) (`D-C02-03`, `D-C02-04`) tersedia.

## 5. Implementation Roadmap
1. **Implementasi Pemeriksa Provenansi Klaim dan Jendela Waktu (`FR-AGT-006`, `NFR-004`)**
   - *Apa yang harus dilakukan:* Bangun validator yang memeriksa setiap klaim material pada output [C13](13-CONTROLLED-LLM-INVESTIGATOR.md) terhadap peta `evidence_id` asli dari [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md): pastikan ID bukti benar-benar ada, nilai metrik/log tidak direkayasa, dan `observed_at` berada di dalam jendela waktu insiden (menangani `SC-14` *misleading correlation* di luar jendela penyebab). Tandai klaim tanpa rujukan valid sebagai `UNSUPPORTED`.
   - *Mengapa diperlukan:* Menekan tingkat klaim tanpa bukti (`KPI-04` $\le 2\%$, `0` untuk klaim keamanan kritis) dan menjamin `KPI-03` (*evidence coverage*).
   - *Expected output:* Modul `claim-validation` beserta kode alasan (*reason codes*: `MISSING_EVIDENCE_REF`, `OUT_OF_WINDOW`, `VALUE_MISMATCH`).
   - *Cara memverifikasi:* Umpankan kandidat hipotesis yang merujuk pada `evidence_id` fiktif dan bukti di luar jendela waktu (`SC-14`); pastikan klaim tersebut ditolak/diturunkan secara deterministik.
2. **Implementasi Deteksi Kontradiksi, Missing Source, dan Multi-Fault (`EV-01`, `EV-02`, `AT-009`, `SC-08`)**
   - *Apa yang harus dilakukan:* Evaluasi konsistensi lintas sinyal (*metrics vs logs vs traces*). Jika terdapat konflik sinyal (`EV-01`) atau sumber utama seperti *distributed tracing* berstatus `SOURCE_UNAVAILABLE` (`EV-02`, `SC-09`), turunkan status hipotesis/investigasi menjadi `PARTIAL` atau `INCONCLUSIVE` dan wajibkan pencantuman *contradicting evidence* serta *unknowns*. Pada kasus *cascade* (`SC-04`, `AT-016`) dan dua fault independen (`SC-08`), pastikan hipotesis memisahkan penyebab hulu vs dampak hilir atau mempertahankan dua hipotesis terpisah.
   - *Mengapa diperlukan:* Mencegah diagnosis yang terlalu percaya diri (*overconfident wrong root cause*, `RISK-03`, `BR-006`).
   - *Expected output:* Mesin aturan penurunan kepercayaan (*confidence downgrade*) dan daftar `contradiction-cases`.
   - *Cara memverifikasi:* Uji dengan fixture metrik vs log yang saling bertentangan (`EV-01`) dan trace yang dimatikan (`SC-09`, `EV-02`); pastikan hasil akhir berstatus `PARTIAL`/`INCONCLUSIVE` dan tidak ada satu pun *trace span* imajiner.
3. **Implementasi Validasi Ulang Applicability SOP dan Pencegahan Status `VERIFIED` (`RULE-005`, `RULE-007`)**
   - *Apa yang harus dilakukan:* Periksa setiap sitasi SOP yang diajukan model terhadap metadata asli dokumen [C07](../phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md) (`service.name`, `environment`, `status=active`, `effective_from`/`effective_to`, `allowed_groups`). Tolak rekomendasi yang mengutip SOP *obsolete* (`SC-10`, `RAG-01`), beda layanan (`RAG-02`), atau ketika hasil retrieval adalah `no_applicable_runbook` (`FR-RAG-009`). Blokir setiap kemunculan status `VERIFIED` pada output.
   - *Mengapa diperlukan:* Menjamin lapisan pertahanan kedua (*defense-in-depth*) setelah filter *retrieval* agar `KPI-11` tetap `0`.
   - *Expected output:* Modul `sop-applicability-results` dan *schema guard* pelarang label `VERIFIED`.
   - *Cara memverifikasi:* Suntikkan sitasi dokumen `obsolete` dan label `VERIFIED` ke input validator; pastikan sitasi digugurkan dan label `VERIFIED` ditolak.
4. **Pengujian Terintegrasi Skenario `SC-03` s/d `SC-10`, `SC-14`, dan Konflik `EV-01`**
   - *Apa yang harus dilakukan:* Jalankan validator di atas hasil investigasi skenario `SC-03` (DB latency), `SC-04` (dependency unavailable / cascade), `SC-05` (pool exhaustion), `SC-07` (queue lag), `SC-08` (concurrent faults), `SC-09` (missing trace), `SC-10` (obsolete SOP trap), dan `SC-14` (misleading correlation), serta kasus uji `EV-01`.
   - *Mengapa diperlukan:* Membuktikan secara fungsional bahwa aturan validasi klaim dan ketidakpastian bekerja konsisten pada seluruh ragam kegagalan tunggal, berantai, maupun kontradiktif.
   - *Expected output:* Rekaman hasil validasi skenario terintegrasi dan log penurunan status (`SUPPORTED` / `PARTIAL` / `INCONCLUSIVE`).
   - *Cara memverifikasi:* Periksa bahwa kasus negatif (`EV-01`, `EV-02`, `SC-09`, `SC-10`, `SC-14`) menghasilkan status serta *reason code* yang tepat tanpa klaim palsu.

5. **Perakitan Paket Bukti `E14` dan Verifikasi Kesiapan Handover**
   - *Apa yang harus dilakukan:* Konsolidasikan seluruh artefak hasil validasi ke dalam paket bukti tersanitasi `E14` (`claim-validation`, `contradiction-cases`, `missing-source-dossiers`, `sop-applicability-results`) dan pastikan antarmuka output siap dikonsumsi oleh [C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md), [C16](16-HUMAN-REVIEW-AND-HANDOVER.md), serta [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md).
   - *Mengapa diperlukan:* Menjamin keterlacakan bukti untuk `EV-01`, `EV-02`, `AT-007`, `AT-009`, dan `AT-016` sebelum evaluasi Gate G3.
   - *Expected output:* Paket bukti lengkap `E14` pada `evidence/<run_id>/C14/`.
   - *Cara memverifikasi:* Periksa bahwa 100% klaim yang lolos ke draf dossier memiliki `evidence_id` sah dan seluruh 4 berkas bukti `E14` tervalidasi skemanya.

## 6. Expected Deliverables
- Modul *Deterministic Evidence & Applicability Validator* yang terintegrasi pada tahap `VALIDATED`.
- Aturan pemetaan status `SUPPORTED`, `PARTIAL`, dan `INCONCLUSIVE` beserta pencatatan *supporting/contradicting evidence* dan *unknowns*.
- Penjaga *post-retrieval SOP applicability* (`RAG-01`, `RAG-02`, `FR-RAG-009`) dan pemblokir label `VERIFIED` (`RULE-007`).
- Paket bukti tersanitasi `E14` pada `evidence/<run_id>/C14/`: `claim-validation`, `contradiction-cases`, `missing-source-dossiers`, dan `sop-applicability-results`.

## 7. Validation & Exit Criteria
- `EV-01` & `AT-009`: Ketika metrik dan log saling bertentangan, validator menurunkan status menjadi `PARTIAL` atau `INCONCLUSIVE` dan menampilkan kedua bukti yang berkonflik secara transparan.
- `EV-02` & `AT-009`: Ketika sumber *tracing* hilang (`SC-09`), dossier memuat penanda *missing source* di bagian *unknowns* tanpa satu pun referensi *trace* imajiner (`RULE-006`).
- `RAG-01`, `RAG-02`, & `AT-007`: Dossier hanya mencantumkan SOP yang berstatus `active`, efektif pada waktu insiden, dan sesuai dengan `service.name` serta `environment` insiden (`KPI-11` = 0).
- `AT-016`, `SC-08`, & `SC-14`: Dossier membedakan penyebab hulu dari dampak hilir pada *cascade*, tidak memaksakan satu penyebab pada dua gangguan independen (`SC-08`), dan menurunkan hipotesis yang hanya didukung korelasi di luar jendela waktu (`SC-14`).
- Tidak ada hipotesis yang diberi label `VERIFIED` (`RULE-007`).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Validator yang terlalu kaku menolak klaim valid hanya karena perbedaan format pembulatan angka metrik; mitigasi dengan memvalidasi keberadaan `evidence_id`, arah tren/ambang, dan jendela waktu sesuai konvensi `D-C02-02`.
- **Open Decisions:** Aturan skor untuk kasus *multi-fault* (`SC-08`) pada evaluator mengikuti ketetapan `ADR-S08` dari Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- **Handover ke [C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md), [C16](16-HUMAN-REVIEW-AND-HANDOVER.md), dan [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md):** Dossier tervalidasi beserta metrik tingkat klaim (`supported_claims`, `unsupported_claims`, `contradictions`, `unknowns`) dan paket bukti `E14`.
