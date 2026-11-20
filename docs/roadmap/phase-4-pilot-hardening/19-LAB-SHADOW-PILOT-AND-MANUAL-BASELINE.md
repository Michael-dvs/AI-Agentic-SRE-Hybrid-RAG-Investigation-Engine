# C19 — Lab Shadow Pilot and Manual Baseline

## 1. Chapter Information
- **Phase:** F4 — Pilot & Hardening
- **Status:** APPROVED
- **Documentation status:** COMPLETE / APPROVED
- **Implementation status:** COMPLETE / IMPLEMENTED / VERIFIED (Tahap 1A prototype usability `VERIFIED`; Tahap 1B *Lab Shadow Pilot* & *Blinded Manual Baseline* `VERIFIED` pada paket bukti [`evidence/c19-20261120T083752Z/C19/`](../../../evidence/c19-20261120T083752Z/C19/readiness-check.md))
- **Dependencies:** [C16 — Human Review and Handover](../phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md), [C18 — Red-Team, Holdout, and G3](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md) (`G3 PASS`), protokol *pairing/timing/anti-carryover* (`ADR-S08`, `TBD-08`)
- **Next chapter:** [C20 — Capacity, Resilience, and Rollback](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md)
- **Related requirements:** `BR-005`, `FR-OUT-004`, `FR-OUT-006`, `RULE-008`, `RULE-011`, `NFR-018`, `NFR-020`, `KPI-06`, `KPI-08`, `BEN-01`, `BEN-02`, `BEN-04`, `DEP-05`, `RISK-03`, `RISK-09`, `UC-10`, `UC-11`
- **Related acceptance tests:** `HUM-01` & `AT-010` (verifikasi operasional pada *lab shadow pilot*), `AT-014` (build & test owner pengumpulan *matched manual baseline* untuk `KPI-08` dan penilaian rubrik reviewer untuk `KPI-06`; dikonsolidasikan di C21)

## 2. Objective & Expected Outcome
Chapter ini bertujuan menjalankan *Lab Shadow Pilot* di atas trafik dan gangguan simulasi terkontrol (bukan trafik produksi bank) serta mengukur *Matched Manual Investigation Baseline* guna mengevaluasi kegunaan praktis dossier bagi reviewer (`KPI-06`) dan efisiensi waktu investigasi relatif (`KPI-08`, `BEN-01`). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.2 dan `BRD §2.4`, angka historis 15–30 menit di dalam proposal lama tidak boleh diklaim sebagai hasil nyata PoC; efisiensi hanya boleh dihitung apabila tersedia pengukuran manual pada skenario dengan tingkat kesulitan sebanding (`RULE-011`).

Setelah chapter ini selesai, alur *shadow pilot* di lab telah diuji pada variasi insiden tanpa membocorkan split `H-G4`, rekaman waktu investigasi manual yang terkendali (*blinded manual baseline*) beserta protokol anti-*carryover* tersedia (atau keterbatasannya dideklarasikan secara jujur bila dilakukan oleh solo developer sesuai `TBD-02`/`TBD-08`), penilaian rubrik kualitas dossier (skala 1–5 atas *correctness, evidence sufficiency, actionability, clarity, uncertainty handling*, `BRD §15.4`) telah terkumpul, dan daftar temuan friksi operasional siap diperbaiki pada tahap *hardening* [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md).

## 3. Scope & Boundaries
### In Scope
- Pelaksanaan *shadow pilot* di lingkungan lab terisolasi di mana *workflow* AI berjalan secara paralel terhadap pemicu gangguan simulasi pada kasus pilot/`DEV` tanpa membuka segel `H-G4` (`NFR-001`, `NFR-019`).
- Pengukuran *Blinded Manual Baseline* (`BRD §6.1`, `RULE-011`) menggunakan dasbor/kueri telemetri dan dokumen SOP yang setara sebelum pelaku melihat output AI atau kunci *ground truth*; jika memakai pasangan kasus `H-G4` untuk perbandingan akhir, rekaman mentah waktu manual disegel di penyimpanan evaluator dan tidak digunakan untuk *tuning*.
- Pengumpulan penilaian reviewer atas dossier menggunakan rubrik 5 dimensi (`BRD §15.4`), pencatatan aksi `approve`/`reject`/`edit` (`KPI-06`, `HUM-01`, `AT-010`), serta pembedaan antara *system time-to-dossier* (`KPI-07`) dan waktu telaah manusia (*human review effort*).
- Identifikasi cacat kebergunaan (*usability defects*), friksi *startup/fallback*, dan observasi biaya/sumber daya awal sebagai masukan ke [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md).

### Out of Scope
- Menghubungkan *shadow pilot* ke sistem pemantauan produksi, *alert* nyata bank, atau tim *on-call* operasional nyata (`BRD §4.2`).
- Mengklaim penghematan waktu $\ge 40\%$ (`KPI-08`) atau validasi SME independen apabila protokol perbandingan manual tidak adil atau hanya dilakukan tanpa pemisahan *carryover* (`BRD §2.4`, `TBD-08`).
- Menggunakan skenario `H-G4` untuk iterasi perbaikan prompt/kode selama *shadow pilot* (`NFR-019`).

## 4. Prerequisites
- Gate G3 ([C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md)) berstatus `PASS`.
- Permukaan *Human Review* ([C16](../phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md)) dan dashboard/ekspor AI observability ([C15](../phase-3-reasoning-observability/15-AI-OBSERVABILITY-AUDIT-AND-COST.md)) berjalan stabil.
- Protokol *matched manual baseline*, aturan *anti-carryover*, dan deklarasi peran reviewer (`TBD-08`, `ADR-S08`) telah disahkan pada Gate G1.

## 5. Implementation Roadmap
1. **Penyiapan Protokol Anti-Carryover dan Eksekusi Blinded Manual Baseline (`RULE-011`, `BRD §6.1`)**
   - *Apa yang harus dilakukan:* Siapkan lembar kerja dan pencatat waktu (*timer*) untuk alur investigasi manual (`AS-IS`: terima *alert* $\rightarrow$ eksplorasi metrik/log/trace $\rightarrow$ cari SOP $\rightarrow$ tulis hipotesis & bukti). Pastikan sesi manual dijalankan **sebelum** pelaku melihat dossier AI atau label *ground truth* untuk skenario yang dipasangkan; segel hasil mentah di evaluator jika menyangkut pasangan evaluasi final.
   - *Mengapa diperlukan:* Mencegah efek ingatan (*carryover bias*) yang membuat perbandingan waktu manual vs AI menjadi tidak sah (`RISK-09`).
   - *Expected output:* Dokumen dan rekaman `manual-timing-protocol-and-records`.
   - *Cara memverifikasi:* Periksa *timestamp* log bahwa sesi manual selesai dan dikunci sebelum dossier AI untuk insiden pasangan tersebut dibuka oleh penguji.
2. **Pelaksanaan Sesi Lab Shadow Pilot pada Skenario Pilot/Dev (`BRD §17`)**
   - *Apa yang harus dilakukan:* Jalankan *shadow workflow* secara berkesinambungan di atas trafik dan injeksi gangguan lab (mencakup kasus normal, gangguan layanan tunggal, *cascade*, SOP usang, dan *degraded mode* dari himpunan non-`H-G4`), lalu amati perilaku *intake*, progres *workflow*, dan kesiapan dossier di permukaan review [C16](../phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md).
   - *Mengapa diperlukan:* Menguji keandalan operasional dan pengalaman pengguna secara realistis di lab sebelum pembekuan rilis final.
   - *Expected output:* Rekaman eksekusi `pilot-run-log`.
   - *Cara memverifikasi:* Pastikan seluruh insiden *pilot* tercatat dari *alert* hingga `HUMAN_REVIEW` / `CLOSED` tanpa intervensi kode tersembunyi.
3. **Penilaian Rubrik Reviewer dan Verifikasi Kontrol `HUM-01` / `AT-010`**
   - *Apa yang harus dilakukan:* Lakukan review atas setiap dossier hasil *shadow pilot* menggunakan rubrik 5 dimensi (*correctness, evidence sufficiency, actionability, clarity, uncertainty handling*), rekam keputusan `APPROVED` (tanpa atau dengan *minor/substantial rework*) atau `REJECTED`, serta catat durasi telaah manusia. Cantumkan deklarasi eksplisit `SELF_EVALUATED_DEVELOPER_LABELS` apabila tidak ada SME eksternal (`TBD-08`).
   - *Mengapa diperlukan:* Menyediakan bukti terstruktur bagi `KPI-06`, `BEN-02`, dan `NFR-020` tanpa memalsukan independensi reviewer.
   - *Expected output:* Kumpulan skor dan catatan koreksi pada `review-rubric`.
   - *Cara memverifikasi:* Pastikan setiap dossier memiliki skor rubrik lengkap, atribut sumber reviewer yang jujur, dan 0 aksi otomatis pasca-persetujuan (`HUM-01`).
4. **Analisis Friksi Operasional dan Pencatatan Defect Pilot (`pilot-defects`)**
   - *Apa yang harus dilakukan:* Rangkum seluruh cacat kebergunaan (*usability*), hambatan navigasi bukti/SOP, anomali performa kontainer, serta batasan metodologi baseline manual ke dalam `pilot-defects`.
   - *Mengapa diperlukan:* Memberikan daftar perbaikan terfokus untuk diselesaikan dan dibekukan pada [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md) sebelum *final benchmark* [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md).
   - *Expected output:* Berkas registri `pilot-defects` dengan prioritas perbaikan menuju [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md).
   - *Cara memverifikasi:* Pastikan setiap temuan memiliki tingkat keparahan dan rencana tindak lanjut yang jelas.

5. **Pengemasan Paket Bukti `E19` dan Pemeriksaan Keutuhan Segel `H-G4`**
   - *Apa yang harus dilakukan:* Kumpulkan seluruh artefak (`pilot-run-log`, `manual-timing-protocol-and-records`, `review-rubric`, `pilot-defects`) ke dalam paket bukti `E19` dan verifikasi ulang bahwa segel split `H-G4` tidak pernah dibuka selama aktivitas *shadow pilot*.
   - *Mengapa diperlukan:* Menjaga validitas *Final Blind Holdout* `H-G4` (`NFR-019`) sebelum pembekuan rilis di [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md).
   - *Expected output:* Paket bukti lengkap `E19` pada `evidence/<run_id>/C19/`.
   - *Cara memverifikasi:* Pastikan keempat berkas `E19` tersedia lengkap dan hash/log akses `H-G4` tetap bersih (0 akses).

## 6. Expected Deliverables
- Rekaman eksekusi *Lab Shadow Pilot* (`pilot-run-log`) pada lingkungan simulasi.
- Protokol dan rekaman waktu *Blinded Manual Baseline* (`manual-timing-protocol-and-records`) beserta deklarasi batas validitas/bias (`RULE-011`, `TBD-08`).
- Hasil penilaian rubrik reviewer 5 dimensi dan tingkat *rework* (`review-rubric`) untuk `KPI-06`.
- Daftar temuan dan cacat pilot (`pilot-defects`) serta paket bukti tersanitasi `E19` pada `evidence/<run_id>/C19/`.

## 7. Validation & Exit Criteria
- `HUM-01`, `AT-010`, & `NFR-020`: Permukaan review terbukti dapat digunakan untuk memeriksa bukti, mengedit/menolak/menyetujui dossier, dan menahan rekomendasi kritis tanpa memicu remediasi otomatis.
- `AT-014` (input `KPI-06` & `KPI-08`): Rubrik penilaian reviewer dan rekaman waktu baseline manual tersedia sesuai protokol `ADR-S08`; jika terdapat keterbatasan karena pengerjaan solo (`TBD-02`), keterbatasan tersebut dinyatakan secara eksplisit agar [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md) tidak membuat klaim efisiensi yang menyesatkan.
- Seluruh aktivitas *shadow pilot* terbukti tidak membaca atau membocorkan skenario *final holdout* `H-G4`.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Bias *self-review* dan *carryover* karena pengembang tunggal (`project-initiator-michael`) memahami desain skenario (`TBD-02`); mitigasi dengan memisahkan waktu pengukuran manual sebelum melihat output AI, mematuhi rubrik objektif berbasis bukti, dan mencantumkan *caveat* `SELF_EVALUATED` di seluruh laporan.
- **Open Decisions:** Apakah `KPI-08` dilaporkan sebagai perbandingan berpasangan terukur atau diberi penanda *caveat/not-evaluable* untuk klaim efisiensi organisasi ditentukan berdasarkan validitas rekaman `manual-timing-protocol-and-records` sesuai aturan [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) §8.5.
- **Handover ke [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md) dan [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md):** Daftar perbaikan kebergunaan/operasional (`pilot-defects`) untuk dituntaskan di [C20](20-CAPACITY-RESILIENCE-AND-ROLLBACK.md), serta rekaman baseline manual dan rubrik reviewer (`E19`) untuk dikonsolidasikan di [C21](21-FINAL-HOLDOUT-AND-BENCHMARK.md).

## 9. Usability RFC & Non-Final Design Notes (PROPOSED / UNDER_REVIEW)
- **Status:** `PROPOSED / NOT_FINAL` (Memerlukan review dan persetujuan formal Project Authority).
- **Rujukan Dokumen Detil:** [`RFC-UNIFIED-TUI-AND-TELEGRAM-DISPATCHER.md`](RFC-UNIFIED-TUI-AND-TELEGRAM-DISPATCHER.md).
- **Inti Usulan:**
  1. **Unified SRE Command Center (TUI Dashboard):** Mengganti pemanggilan CLI per-file yang terfragmentasi dengan antarmuka TUI terpadu berbasis library `rich` (layout panel ganda dengan sidebar navigasi: *Active Incidents, Archive Dossiers, Service Health, AI Config, Telegram Dispatcher*).
  2. **Emergency Telegram Dispatcher:** Menambahkan modul notifikasi instan yang menembakkan ringkasan insiden darurat, dugaan AI, dan sitasi SOP ke grup Telegram SRE on-call secara otomatis saat alarm berbunyi.
- **Rencana Uji Coba:** Diuji coba pada tahap pelaksanaan *Lab Shadow Pilot* (C19) sebagai opsi antarmuka penelaahan manusia untuk meminimalkan friksi operasional tanpa melanggar batasan keselamatan (`RULE-008`, `HUM-01`).

## 10. Rekaman Implementasi Tahap 1A — Prototype Usability

- **Batas implementasi:** hanya `RFC-F4-USABILITY-01` Tahap 1A. Tidak ada *Lab Shadow Pilot*, *Blinded Manual Baseline*, rubrik 5 dimensi, registri `pilot-defects`, paket `E19`, atau akses partisi `H-G4`.
- **Unified SRE Command Center:** `scripts/sre_dashboard.py` dan `orchestrator/usability_console.py` menyediakan navigasi *Active Incidents*, *Archive Dossiers*, *Service Health*, *AI Model Config*, dan *Telegram Alerts*. Aksi `APPROVE`, `REJECT`, `CORRECT`, dan `ESCALATE` memakai `AuthorizedReviewManager`; persetujuan mengekspor paket melalui `HandoverExporter`.
- **Emergency Telegram Dispatcher:** `orchestrator/telegram_dispatcher.py` hanya mengirim notifikasi keluar untuk dossier `PENDING_REVIEW`. Kredensial kosong menghasilkan `DRY_RUN`; kegagalan jaringan menghasilkan `FALLBACK` tanpa menggagalkan alur investigasi. Tidak ada listener masuk atau jalur eksekusi perintah.
- **Kontrol keselamatan:** semua review event mempertahankan `auto_action_triggered=false`; output UI dan Telegram dibentuk dari field yang diizinkan tanpa membaca registri *ground truth*; aksi reviewer ditulis ke audit JSONL append-only dengan timestamp UTC dan rantai SHA-256 yang dilanjutkan saat proses dibuka ulang.
- **Verifikasi aktual:** `python3 -m pytest -q tests/test_c19_usability_console.py` menghasilkan `7 passed`; `python3 -m pytest -q` menghasilkan `457 passed, 6 skipped`; smoke entrypoint menerima `Q`, merender *Active Incidents*, dan keluar dengan status `0`.
- **Status tata kelola RFC:** implementasi prototype dan hasil unit test tidak mengubah status RFC dari `PROPOSED / UNDER_REVIEW` serta tidak membuktikan exit criteria C19 Tahap 1B.

## 11. Rekaman Implementasi Tahap 1B — Lab Shadow Pilot & Manual Baseline

- **Run ID & Paket Bukti `E19`:** `c19-20261120T083752Z` pada [`evidence/c19-20261120T083752Z/C19/`](../../../evidence/c19-20261120T083752Z/C19/readiness-check.md).
- **Modul Implementasi & Skrip:**
  - [`evaluator/manual_baseline.py`](../../../evaluator/manual_baseline.py) dan [`scripts/manual_baseline_collector.py`](../../../scripts/manual_baseline_collector.py) (protokol *anti-carryover*, penguncian `lock_sha256`, kalkulasi `KPI-08`, dan deklarasi `SELF_EVALUATED_DEVELOPER_LABELS`).
  - [`evaluator/pilot_rubric.py`](../../../evaluator/pilot_rubric.py) (rubrik 5 dimensi skala 1–5 `KPI-06` dan registri cacat `pilot-defects`).
  - [`scripts/run_shadow_pilot.py`](../../../scripts/run_shadow_pilot.py) (orkestrator 7 skenario *DEV* melalui `DeterministicInvestigator`, `SREDashboard`, `ReviewActionController`, `HandoverExporter`, dan `TelegramDispatcher`).
  - [`tests/test_c19_shadow_pilot.py`](../../../tests/test_c19_shadow_pilot.py) (pengujian terotomasi protokol *anti-carryover*, rubrik, integrasi `scorer.py`, pilot *end-to-end*, dan segel `H-G4`).
- **Ringkasan Eksekusi Lab Shadow Pilot (`DEV`):**
  - 7/7 insiden (`inc-pilot-dev-sc01-001` s/d `inc-pilot-dev-sc09-007`) selesai melalui siklus 9-state menuju `CLOSED` (mencakup kontrol sehat, *single fault*, kaskade lintas layanan, filter SOP `approved` vs `obsolete`, koreksi TUI `CORRECT` `v1 -> v2 -> APPROVE`, dan mode terdegradasi `get_trace_summary` outage -> `INCONCLUSIVE` `EV-02`).
  - Seluruh 7 insiden memicu notifikasi pasif Telegram `DRY_RUN`, menghasilkan `auto_action_triggered_count == 0` (`HUM-01`, `RULE-008`), `handover_gt_leak_count == 0` (`AT-008`), dan rantai hash audit SHA-256 valid (`15` event).
- **Ringkasan Blinded Manual Baseline (`KPI-08` — [`manual-timing-protocol-and-records.md`](../../../evidence/c19-20261120T083752Z/C19/manual-timing-protocol-and-records.md)):**
  - `7` pasangan terukur pada split `dev` (`all_records_locked_before_ai_view = True`).
  - Median manual AS-IS: `340.000 s`; median *System TTI* (`KPI-07`): `0.032 s`; median *Human Review Effort*: `40.000 s`; median total AI-assisted: `40.032 s`; pengurangan waktu relatif (`KPI-08`): `88.23%` (`0.8823`).
  - **Deklarasi Batas Validitas (`TBD-02`, `TBD-08`, `ADR-S08`):** Seluruh rekaman dilabeli `assessment_kind: "self_review_lab_owner"` / `SELF_EVALUATED_DEVELOPER_LABELS` dan tidak diklaim sebagai validasi SME perbankan independen.
- **Ringkasan Rubrik 5 Dimensi (`KPI-06` — [`review-rubric.md`](../../../evidence/c19-20261120T083752Z/C19/review-rubric.md)):**
  - `KPI-06` (*accepted without substantial rework*): `6/7` (`85.71%`; `6` `APPROVED`, `1` `APPROVED_WITH_MINOR_EDIT` dengan rework pada `inc-pilot-dev-sc07-006`, `0` `REJECTED`).
  - Rata-rata dimensi (skala 1–5): Correctness `4.43`, Evidence Sufficiency `4.43`, Actionability `4.14`, Clarity `4.57`, Uncertainty Handling `4.29` (rata-rata keseluruhan `4.37 / 5.00`).
- **Daftar Cacat Pilot Handover ke C20 ([`pilot-defects.md`](../../../evidence/c19-20261120T083752Z/C19/pilot-defects.md)):**
  - `C19-DEF-001` (`USABILITY`, `P2-HIGH`): Reflow layout terminal TUI tertunda saat resize mendadak.
  - `C19-DEF-002` (`USABILITY`, `P2-HIGH`): Pratinjau excerpt bukti telemetri dan teks SOP belum tersedia langsung di panel detail TUI.
  - `C19-DEF-003` (`PERFORMANCE`, `P3-MEDIUM`): Pembacaan ulang penuh audit JSONL sinkron pada `ReviewActionController`.
  - `C19-DEF-004` (`RAG_NAVIGATION`, `P2-HIGH`): Revisi `CORRECT` `v(N)->v(N+1)` di `review.py`/`dossier.py` belum mewariskan field `evidence`/`sop_citations` terserialisasi.
  - `C19-DEF-005` (`BASELINE_BIAS`, `P3-MEDIUM`): Keterbatasan label pengembang tunggal lab (`TBD-02`/`TBD-08`).
  - `C19-DEF-006` (`RAG_NAVIGATION`, `P2-HIGH`): Ketidakselarasan `index_version_policy='active_only'` di `investigator.py` vs `'kb_active_alias'` di `prefilter.py`.
- **Verifikasi Segel `H-G4` ([`holdout-h4-seal-verification.json`](../../../evidence/c19-20261120T083752Z/C19/holdout-h4-seal-verification.json)):**
  - Status `VERIFIED_SEALED`: SHA-256 `holdout_queries.json` dan `ground_truth_records.jsonl` cocok 100% dengan baseline Gate G1; `runner_h_g4_guard_blocked == true`; `0` baris `H-G4` dibaca atau diparsing selama C19.
- **Verifikasi Regresi Penuh ([`pytest-verified-output.txt`](../../../evidence/c19-20261120T083752Z/C19/pytest-verified-output.txt)):**
  - `python3 -m pytest -q` menghasilkan `461 passed, 6 skipped` (exit code `0`).


