# E14 — Kesiapan dan Bukti Empiris Chapter 14 (C14): Evidence Validation and Uncertainty

- **Run ID:** `c14-20261116T075346Z`; lab simulasi sintetis lokal; reviewer: `project-initiator-michael`.
- **Status implementasi:** `IMPLEMENTED`; `VERIFIED` untuk cakupan C14 simulasi PoC (Semantic Claim Validation, Out-of-Window Filtering SC-14, Contradiction Detection EV-01, Missing Trace Abstention EV-02/SC-09, Post-Retrieval SOP Applicability Filter RAG-01/02, Cascade Origin Heuristic AT-016, Multi-Fault Separation SC-08, Strict Rule Guard RULE-005/RULE-007; seluruh 17/17 unit/integration test C14 PASS, 374/374 full test suite PASS).
- **Reviewer Decision & Baseline PoC Note:**
  1. **Kontrak Dossier v1 (ADR-DC02):** Kontrak JSON dossier v1 tetap 100% patuh pada skema beku tanpa field tambahan. Ringkasan validasi klaim C14 disajikan sebagai *sidecar* terpisah dan dirender visual pada laporan Markdown.
  2. **Batas Status Hipotesis:** Karena model belum menggunakan formal Natural Language Inference (NLI) penuh untuk kalimat naratif bebas, status hipotesis AI dibatasi maksimal `PARTIAL` demi prinsip kejujuran bukti (*intellectual honesty*).
  3. **Heuristik Cascade Origin:** Penentuan layanan asal kegagalan berantai (*origin service*) pada simulasi PoC menggunakan heuristik pemilahan layanan hulu non-gateway. Untuk skala enterprise/komersial di lingkungan APS-BNI, arsitektur disiapkan untuk digantikan oleh penelusuran graf rentang span OpenTelemetry terawal.

---

## 1. Hasil Pengujian Aktual

Seluruh pengujian unit dan integrasi C14 dijalankan melalui pytest dengan hasil **17 passed, 0 failed, 0 errors** (dan seluruh suite repositori mencapai **374 passed, 6 skipped** tanpa regresi pada C01–C13).

| Requirement / Acceptance Test ID | Status | Hasil Aktual & Lokasi Bukti Empiris |
|---|---|---|
| `EV-01` & `AT-009` (Signal Contradiction) | `PASS` | Konflik antara log server error masif vs metrik error_rate 0% terdeteksi deterministik. Status investigasi diturunkan menjadi `PARTIAL` dengan bukti kontradiksi dicatat transparan. Bukti: [contradiction-cases.json](contradiction-cases.json). |
| `EV-02` & `AT-009` (Missing Trace Abstention) | `PASS` | Ketika backend tracing berstatus `SOURCE_UNAVAILABLE` (skenario `SC-09`), sistem secara jujur mencatat ketidakpastian di `unknowns`, menurunkan status ke `INCONCLUSIVE` (confidence $\le 0.40$), dan menghasilkan 0 span imajiner. Bukti: [missing-source-dossiers.json](missing-source-dossiers.json). |
| `RAG-01`, `RAG-02`, & `AT-007` (SOP Applicability) | `PASS` | Sitasi runbook kedaluwarsa (`effective_to` di masa lalu, skenario `SC-10`) atau salah layanan/environment langsung digugurkan dari dossier aktif (`KPI-11` = 0). Bukti: [sop-applicability-results.json](sop-applicability-results.json). |
| `AT-016`, `SC-04`, `SC-08` (Cascade & Multi-Fault) | `PASS` | Kegagalan berantai memisahkan layanan hulu vs hilir. Gangguan independen ganda tidak digabungkan secara keliru. Bukti: [claim-validation.json](claim-validation.json). |
| `SC-14` & `NFR-004` (Time Window & Grounding) | `PASS` | Bukti di luar jendela waktu insiden ditolak dengan kode `OUT_OF_WINDOW`. Nilai klaim yang tidak cocok dengan telemetri ditandai `VALUE_MISMATCH`. Bukti: [claim-validation.json](claim-validation.json). |
| `RULE-005` & `RULE-007` (Security & Strict Anti-Verified) | `PASS` | Penggunaan status atau kata kunci `VERIFIED` diblokir keras secara deterministik dan diturunkan ke `PARTIAL`/`INCONCLUSIVE`. Bukti: [claim-validation.json](claim-validation.json). |

---

## 2. Inventaris Paket Bukti E14

Direktori `evidence/c14-20261116T075346Z/C14/` memuat seluruh artefak wajib:
1. `claim-validation.json` & `.jsonl`: Detail klaim terverifikasi, reason code, dan delta nilai.
2. `contradiction-cases.json` & `.jsonl`: Bukti deteksi konflik metrik vs log (`EV-01`) dan penanganan multi-fault (`SC-08`).
3. `missing-source-dossiers.json` & `.jsonl`: Bukti penanganan pemadaman tracing (`EV-02`, `SC-09`) dan abstensi jujur.
4. `sop-applicability-results.json` & `.jsonl`: Bukti penyaringan SOP aktif vs kedaluwarsa (`RAG-01`, `RAG-02`, `AT-007`).
5. `pytest-verified-output.txt`: Rekaman log eksekusi pytest suite C14 (17 passed).
6. `readiness-check.md`: Berkas kesiapan ini.

---

## 3. Handover ke Chapter 15

Dengan diterimanya batasan baseline PoC di atas, seluruh artefak C14 siap dikonsumsi oleh:
- **Chapter 15 (C15 — AI Observability, Audit, and Cost):** Untuk menghubungkan jejak trace span validasi klaim, reason codes, metrik latensi, dan token accounting ke sink observabilitas AI.
