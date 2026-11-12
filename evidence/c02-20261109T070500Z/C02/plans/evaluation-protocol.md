# C02 Step 09 — Protokol Evaluasi Offline, Isolasi Split Holdout, dan Aturan Scoring KPI

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/plans/evaluation-protocol.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 09 & §7.7–7.8)  
> **Status:** `SPECIFIED` (Kontrak evaluasi & aturan anti-leakage dibekukan; ukuran sampel final & beberapa aturan denominator tetap keputusan G1 sesuai `ADR-S08` & `TBD-08`/`TBD-10`)

---

## 1. Pemisahan Public Runtime Manifest vs Restricted Evaluation Manifest (`RULE-03`, `AT-008`)

Untuk mencegah kebocoran ground-truth (GT) ke investigator agent, semua eksekusi eksperimen dan benchmark dipisahkan menjadi dua proyeksi manifest yang berbeda:

| Aspek | `runtime-manifest.v1.schema.json` (Public / Runtime) | `evaluation-manifest.v1.schema.json` (Restricted / `TB-05`) |
|---|---|---|
| **Pembaca yang Diizinkan** | `principal_investigator`, `principal_tool_gateway`, `principal_reviewer`, `principal_evaluator` | **Hanya** `principal_evaluator` dan `principal_fault_harness` |
| **Lokasi Penyimpanan** | Runtime workspace (`artifacts/runs/<run_id>/runtime-manifest.json`) | Restricted workspace (`restricted/gt-registry/<run_id>/evaluation-manifest.json`) — **tidak di-mount** ke container investigator/MCP/Qdrant |
| **Identifier Run & Insiden** | `run_id` (`run-...`) dan `incident_id` (`inc-...`) bersifat **opaque** (tanpa nama fault/split). | Memetakan `run_id` + `incident_id` ke `scenario_id` (`SC-01`..`SC-14`), `split_id` (`dev`, `H-G3`, `H-G4`), dan `fault_injection_seed`. |
| **Informasi yang Dilarang Keras** | Dilarang memuat `scenario_id`, `fault_type`, `expected_root_cause`, `split_assignment`, `inject_command`, atau path direktori evaluator. | Dilarang dibaca sebelum dossier insiden mencapai state `CLOSED` dan memiliki `dossier_hash` final. |

> **Catatan Penting C02:** Sesuai C02 Step 09 Action 2, dokumen ini dan direktori `E02` hanya mendefinisikan **desain skema** dan protokol evaluasi. Label penugasan split aktual (`H-G3` / `H-G4`) dan jawaban insiden nyata **tidak disimpan di `E02`** agar tidak masuk ke konteks agen.

---

## 2. Desain Tiga Split Dataset & Anti-Overlap (`ADR-S08`, `D-C02-05`)

1. **`dev` (Development & Tuning Split):**
   - Boleh digunakan pada Chapter C04–C17 untuk debugging fault injection, kalibrasi threshold alert, tuning chunking/fusion RAG (`ADR-S04`), dan penyempurnaan prompt/validator.
2. **`H-G3` (Locked Pre-Pilot Holdout Split):**
   - Dibekukan sebelum eksekusi Gate G3. Digunakan untuk memverifikasi kesiapan reasoning, validasi bukti, dan guardrail sebelum memasuki Fase 4.
   - Tidak boleh digunakan untuk memperbarui contoh few-shot atau korpus KB.
3. **`H-G4` (Locked Final Concept Approval Holdout Split):**
   - Dibekukan dengan manifest SHA-256 (`freeze_hash`) sebelum eksekusi benchmark C19/G4.
   - Menggunakan *random seed*, parameter waktu onset, dan kombinasi layanan/variasi gejala yang tidak pernah terlihat pada `dev` maupun `H-G3`.
   - Tidak boleh dipakai ulang apabila pernah dibuka untuk debugging kegagalan model.
4. **Kandidat Ukuran Sampel (`PROPOSED` — Dikunci di G1 via `ADR-S08`):**
   - Proposal menyarankan kandidat **100–200 kueri retrieval** dan **30–50 incident replay**. Angka pasti yang proporsional terhadap batas RAM 16 GB Apple Silicon (8 GiB Docker Lab) dan kuota LLM `$0.00` akan dikunci pada Gate G1 setelah baseline waktu eksekusi C04–C08 terukur.

---

## 3. Aturan Delayed Ground-Truth Join (Post-Closure Gate)

Evaluator offline (`CMP-GOV-04`) wajib menjalankan pemeriksaan gerbang berikut secara berurutan sebelum menghitung skor (`evaluation-result.v1.schema.json`):
1. **Verifikasi State Terminal:** Periksa `workflow-event` terakhir untuk `incident_id` target. State wajib `CLOSED` dengan `terminal_outcome` salah satu dari `CLOSED_APPROVED`, `CLOSED_REJECTED`, atau `CLOSED_MANUAL_FALLBACK` (atau terminal failure yang tercatat eksplisit di run ledger). Jika state masih `DRAFTED` atau `HUMAN_REVIEW`, percobaan join **ditolak** dengan kode `PREMATURE_EVALUATION_BLOCKED` dan dicatat di security audit (`C02-CON-010`).
2. **Verifikasi Integritas Hash Dossier:** Hitung ulang SHA-256 atas file dossier JSON yang ditutup dan pastikan cocok dengan `closed_dossier_hash` pada `evaluation-manifest` serta `target_dossier_hash` pada `review-event`.
3. **Verifikasi Ketiadaan Kebocoran (Leakage Scan):** Periksa bahwa `dossier.json`, log tool calls, dan prompt trace tidak mengandung token rahasia evaluator (`gt_oracle_token` / nama file holdout). Jika ditemukan kebocoran, run ditandai `INVALIDATED_LEAKAGE` dan dikeluarkan dari klaim keberhasilan.
4. **Immutability Hasil Evaluasi:** Apabila sebuah insiden dibuka kembali (reopened) untuk eksperimen revisi, sistem wajib membuat `evaluation_id` baru dan mempertahankan record evaluasi lama di dalam run ledger.

---

## 4. Definisi Numerator, Denominator, dan Penanganan Kegagalan KPI

Seluruh target numerik di bawah berstatus `PROPOSED` dari Proposal v2.0 / BRD v1.0 dan baru menjadi ambang kelulusan formal setelah disahkan di Gate G1 (`TBD-08`, `TBD-10`, `ADR-S08`):

| KPI ID | Nama Metrik | Kandidat Target (`PROPOSED`) | Definisi Numerator & Denominator | Aturan Edge Case, Kegagalan, & Keputusan G1 |
|---|---|---|---|---|
| `KPI-01` | Retrieval Recall@5 / Hit-Rate@5 | `>= 90%` (Proposal) | **Classical Recall@5:** `\|Relevant_Chunks_Retrieved_in_Top5\| / \|All_GroundTruth_Relevant_Chunks\|`. **Hit-Rate@5:** proporsi kueri yang memperoleh `>= 1` chunk relevan di Top-5. | **Wajib dilaporkan keduanya secara terpisah** (`D-C02-05`); dilarang menukar istilah Hit-Rate@5 menjadi Recall@5 setelah eksperimen selesai. Kueri negatif yang memang tidak punya SOP (`NO_APPLICABLE_RUNBOOK`) dievaluasi pada akurasi abstention terpisah. |
| `KPI-02` | Top-3 Root Cause Diagnosis Accuracy | `>= 85%` (Proposal) | **Numerator:** Jumlah run insiden fault di mana akar masalah ground-truth tercakup dalam maksimal 3 hipotesis teratas berstatus `SUPPORTED` atau `PARTIAL`. **Denominator:** Seluruh run insiden fault yang dijadwalkan pada split uji (termasuk run yang gagal/timeout). | - **Kasus Multi-Fault (`SC-08`):** Laporkan *All-Causes-in-Top-3* (ketat, default) dan *Primary-Cause-in-Top-3* secara terpisah.<br>- **Kasus Healthy (`SC-01`):** Dihitung pada metrik *False Positive Incident Rate* terpisah, bukan dimasukkan ke numerator `KPI-02` untuk mendongkrak skor.<br>- **Status `INCONCLUSIVE`:** Benar secara keselamatan pada bukti hilang (`SC-09`), namun dihitung pada *Safety Abstention Accuracy*, bukan diklaim sebagai diagnosis root-cause terbukti. |
| `KPI-03` | Evidence Coverage | `>= 95%` (Proposal) | **Numerator:** Jumlah klaim/pernyataan observasi material di dalam dossier yang memiliki tautan `evidence_id` valid dan sesuai jendela waktu. **Denominator:** Total klaim observasi material di dalam dossier. | Dossier kosong atau gagal dengan `0` klaim material **tidak** otomatis mendapat skor `100%`; kasus tersebut ditandai `ZERO_CLAIMS_FALLBACK` dan dilaporkan proporsinya secara eksplisit. |
| `KPI-04` | Unsupported Material Claim Rate | `<= 2%` (Proposal) | **Numerator:** Jumlah klaim material atau sitasi SOP di dalam dossier yang tidak didukung oleh `evidence[]` / `sop_citations[]` atau bertentangan dengan bukti tanpa penanda kontradiksi. **Denominator:** Total klaim material di dalam dossier. | Setiap halusinasi span trace ketika Tempo mati (`EV-02`/`SC-09`) atau sitasi SOP `obsolete` sebagai aktif (`RAG-01`/`SC-10`) otomatis menambah numerator dan memicu kegagalan guardrail terkait. |
| `KPI-05` | P95 Intake-to-Dossier Latency (TTI) | `<= 120 detik` (Proposal) | Persentil ke-95 dari selisih waktu `(dossier_ready_at - alert_received_at)` dalam detik. | Diukur terpisah dari waktu tunggu reviewer manusia (`reviewed_at - dossier_ready_at`). Klaim penurunan median TTI `>= 40%` hanya boleh dilaporkan jika baseline investigasi manual terukur pada skenario yang sama. |
| `KPI-06` | Human Reviewer Acceptance Rate & Rubric | `>= 85%` (Proposal) | Proporsi dossier pada split uji yang memperoleh keputusan reviewer `approve` (atau `edit` minor tanpa kesalahan akar masalah/keselamatan) + skor rubrik skala 1–5 pada 5 dimensi: *Correctness, Evidence Sufficiency, Actionability, Clarity, Uncertainty Handling*. | Karena proyek dijalankan secara individual (`CONFIRMED`), evaluasi reviewer oleh pemilik proyek harus diberi label **Self-Review / Lab Owner Assessment**, bukan klaim validasi SME bank independen (`TBD-10`). |
| `KPI-07` | Cost & Resource Ceiling Compliance | `$0.00` biaya berbayar; RAM Docker `<= 8 GiB` | Total pengeluaran API berbayar (`$0.00`), jumlah pemanggilan remote LLM vs fallback lokal/manual, dan puncak RSS kontainer. | Run yang gagal/retry tetap dihitung dalam konsumsi kuota token dan waktu eksekusi; dilarang menghapus failed runs dari laporan biaya/kuota. |

