# C16 — Human Review and Handover

## 1. Chapter Information
- **Phase:** F3 — Reasoning & Observability
- **Status:** APPROVED
- **Documentation status:** APPROVED
- **Implementation status:** VERIFIED (C16 Scope: AuthorizedReviewManager, Version-Bound Approval, Append-Only Revision vN+1, HandoverExporter with Ground Truth Isolation, DummyTicketManager AT-017, Review Console CLI TBD-11; 9/9 C16 pytest PASS, 397/397 full suite PASS)
- **Dependencies:** [C12 — Baseline Dossier and End-to-End G2](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md) (`G2 PASS`), [C14 — Evidence Validation and Uncertainty](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md), [C15 — AI Observability, Audit, and Cost](15-AI-OBSERVABILITY-AUDIT-AND-COST.md), keputusan `TBD-11` (antarmuka review manusia) dan `ADR-S07` (disposisi *optional dummy ticket*)
- **Next chapter:** [C17 — Offline Evaluation and UAT Harness](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)
- **Related requirements:** `BR-005`, `BR-012`, `BR-014`, `BR-015` (Could), `FR-RAG-005`, `FR-AGT-010`, `FR-OUT-001`, `FR-OUT-004`, `FR-OUT-005`, `FR-OUT-006`, `FR-OUT-007` (Could), `RULE-007`, `RULE-008`, `NFR-005`, `NFR-011`, `NFR-018`, `NFR-020`, `KPI-06`, `BEN-03`, `UC-10`
- **Related acceptance tests:** `HUM-01` (build & test owner lengkap: rekomendasi kritis wajib melewati L1 review, *version-bound approval*, tanpa aksi otomatis; regresi di C18/C19/C21), `AT-010` (build & test owner lengkap: keterbacaan dossier, *approve/reject/edit*, dan pencatatan audit), `AT-017` (*conditional build & test owner*: jika diaktifkan melalui `ADR-S07`, buat *dummy ticket* hanya setelah revisi disetujui; jika tidak dipilih, rekam disposisi `NOT_RUN / N/A` berpersetujuan)

## 2. Objective & Expected Outcome
Chapter ini bertujuan menyempurnakan permukaan *Human Review and Incident Handover* di atas fondasi review dasar [C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md) sehingga reviewer L1/L2 dapat memeriksa setiap klaim, bukti telemetri, sitasi SOP, konflik sinyal, dan ketidakpastian tanpa perlu memahami detail internal *framework* AI (`NFR-020`), melakukan persetujuan, penolakan, atau koreksi secara terotorisasi dan *append-only* (`BR-012`, `FR-OUT-004`), serta mengekspor paket handover demo yang terpisah dari laporan evaluasi internal (`FR-OUT-005`).

Setelah chapter ini selesai, permukaan review (Web UI ringan atau antarmuka laporan/CLI terotorisasi sesuai `TBD-11`) menampilkan status *workflow*, latensi, error, serta tautan bukti dan SOP lokal yang dapat dibuka (`FR-OUT-006`, `FR-RAG-005`), rekomendasi kritis wajib mendapatkan *sign-off* reviewer L1 dan tidak pernah memicu remediasi otomatis (`HUM-01`, `RULE-008`), koreksi reviewer menghasilkan revisi baru tanpa menimpa bukti asli atau *ground truth* (`NFR-011`), serta fitur opsional *dummy ticketing* (`BR-015`, `FR-OUT-007`, `AT-017`) telah diimplementasikan setelah persetujuan manusia atau dicatat disposisi pengecualiannya secara eksplisit.

## 3. Scope & Boundaries
### In Scope
- Penyediaan permukaan review manusia sesuai pilihan `TBD-11` yang menyajikan progres *workflow*, metrik latensi/error dari [C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md), isi dossier tervalidasi dari [C14](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md), serta tautan bukti telemetri (`evidence_id`) dan sitasi dokumen SOP (`source_uri` lokal) yang dapat dibuka langsung oleh reviewer (`FR-OUT-006`, `NFR-020`).
- Penegakan otorisasi reviewer, validasi kecocokan nomor revisi (`VERSION_CONFLICT` jika mencoba menyetujui revisi usang), penyimpanan keputusan `APPROVED` / `REJECTED` / `CORRECTED` beserta catatan koreksi secara *append-only*, dan transisi status insiden ke `CLOSED` (`FR-OUT-004`, `HUM-01`, `UC-10`).
- Pembuatan mekanisme ekspor *handover package* dan bukti demo tersanitasi yang terpisah secara fisik dan akses dari laporan evaluasi *ground truth* (`FR-OUT-005`).
- Implementasi kondisional *dummy ticket creation* (`FR-OUT-007`, `AT-017`) ke penyimpanan tiket lokal dummy **hanya** dari revisi dossier yang telah berstatus `APPROVED` (apabila diaktifkan pada `ADR-S07`).

### Out of Scope
- Integrasi ke sistem ITSM produksi nyata (seperti ServiceNow/Jira korporat) atau pemicuan tindakan operasional otomatis (`BR-016`, `RULE-008`).
- Mengizinkan fitur *edit* reviewer mengubah rekaman mentah telemetri, isi indeks KB aktif secara langsung, atau *ground truth registry* (`NFR-011`).

## 4. Prerequisites
- Gate G2 ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)) berstatus `PASS`.
- Output dossier tervalidasi dari [C14](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md) (`E14`) dan jejak metrik/audit dari [C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md) (`E15`) telah tersedia.
- Keputusan Gate G1 untuk `TBD-11` (pilihan antarmuka review) dan `ADR-S07` (disposisi *optional dummy ticket*) telah ditetapkan.

## 5. Implementation Roadmap
1. **Pembangunan Permukaan Review yang Mudah Dibaca dan Navigasi Bukti (`FR-OUT-006`, `NFR-020`)**
   - *Apa yang harus dilakukan:* Bangun antarmuka review sesuai `TBD-11` yang merender ringkasan eksekutif, *timeline* sinyal, tabel bukti, hipotesis berperingkat beserta bukti pendukung/penyangkal (`FR-AGT-010`), sitasi SOP (`FR-RAG-005`), *unknowns*, rekomendasi langkah pemeriksaan manual, serta indikator progres, latensi, dan error dari [C15](15-AI-OBSERVABILITY-AUDIT-AND-COST.md).
   - *Mengapa diperlukan:* Memastikan reviewer L1/L2 dapat memverifikasi setiap klaim ke sumber aslinya dalam hitungan detik tanpa perlu membaca log internal *framework* AI.
   - *Expected output:* Permukaan review fungsional dan rekaman `review-walkthrough`.
   - *Cara memverifikasi:* Buka sebuah dossier hasil investigasi dan klik/buka seluruh tautan `evidence_id` serta `source_uri` SOP lokal; pastikan semuanya terbuka dengan benar.
2. **Penegakan Kontrol Review L1, Version-Bound Approval, dan Append-Only Revisions (`FR-OUT-004`, `HUM-01`, `UC-10`)**
   - *Apa yang harus dilakukan:* Terapkan aturan bahwa setiap dossier—khususnya yang memuat rekomendasi langkah kritis—tertahan pada status `HUMAN_REVIEW` hingga reviewer berwenang memberikan keputusan. Saat reviewer melakukan koreksi/edit, buat nomor revisi baru secara *append-only* dengan tetap menyimpan revisi awal dan bukti asli; tolak permintaan `approve` yang mengacu pada nomor revisi lama (`VERSION_CONFLICT`).
   - *Mengapa diperlukan:* Membuktikan `HUM-01`, `AT-010`, dan `RULE-008` bahwa manusia memegang kendali penuh dan tidak ada tindakan otomatis yang dieksekusi sebelum maupun sesudah *sign-off*.
   - *Expected output:* Modul *versioned review controller* dan bukti `approval-rejection-revisions`.
   - *Cara memverifikasi:* Uji skenario: (a) identitas tanpa hak mencoba menyetujui dossier (ditolak), (b) reviewer menolak dossier (`REJECTED`), (c) reviewer mengedit hipotesis lalu menyetujui revisi baru (`CORRECTED` $\rightarrow$ `APPROVED`), dan (d) percobaan menyetujui revisi lama (ditolak dengan `VERSION_CONFLICT`).
3. **Pemisahan Ekspor Paket Handover Demo dari Laporan Evaluasi (`FR-OUT-005`)**
   - *Apa yang harus dilakukan:* Buat fungsi ekspor yang menghasilkan paket handover insiden (dossier JSON/Markdown final, riwayat review, dan *evidence bundle* tersanitasi) di direktori terpisah dari penyimpanan laporan evaluator offline ([C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)).
   - *Mengapa diperlukan:* Mencegah paket handover atau materi demo menyertakan kunci jawaban *ground truth* atau metrik internal `holdout` (`RULE-002`).
   - *Expected output:* Modul eksportir dan artefak `handover-export`.
   - *Cara memverifikasi:* Periksa isi paket `handover-export` dan pastikan tidak ada atribut `scenario_id`, `ground_truth`, atau data `H-G3`/`H-G4`.
4. **Implementasi atau Pencatatan Disposisi Dummy Ticket (`FR-OUT-007`, `AT-017`)**
   - *Apa yang harus dilakukan:* Jika `ADR-S07` mengaktifkan fitur opsional *dummy ticketing*, bangun pembuat tiket lokal dummy yang hanya dapat dipicu setelah revisi dossier berstatus `APPROVED` dan menautkan `ticket_id` ke `incident_id` + `revision_number`. Jika `ADR-S07` mengecualikan fitur ini, rekam disposisi resmi `NOT_RUN / N/A (Approved Optional Exclusion)` tanpa menandainya sebagai `PASS`.
   - *Mengapa diperlukan:* Menjaga integritas pelaporan `AT-017` sesuai aturan `AGENTS.md §7` dan [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md).
   - *Expected output:* Artefak `ticket-test-or-disposition`.
   - *Cara memverifikasi:* Jika diaktifkan, coba buat tiket dari dossier berstatus `DRAFTED` atau `REJECTED` (wajib ditolak) lalu buat dari dossier `APPROVED` (berhasil membuat tiket dummy lokal).

5. **Validasi End-to-End Alur Review Manusia dan Perakitan Bukti `E16` (`HUM-01`, `AT-010`)**
   - *Apa yang harus dilakukan:* Jalankan skenario *walkthrough* lengkap dari penerimaan dossier tervalidasi hingga penutupan insiden (`CLOSED`), lalu kumpulkan seluruh artefak (`review-walkthrough`, `approval-rejection-revisions`, `handover-export`, `ticket-test-or-disposition`) ke dalam paket `E16`.
   - *Mengapa diperlukan:* Membuktikan kesiapan penuh `HUM-01` dan `AT-010` sebelum pengujian regresi di [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md) dan Gate G3 di [C18](18-RED-TEAM-HOLDOUT-AND-G3.md).
   - *Expected output:* Paket bukti lengkap `E16` pada `evidence/<run_id>/C16/`.
   - *Cara memverifikasi:* Pastikan seluruh 4 artefak `E16` tersedia, tercatat di *security audit log*, dan 0 aksi otomatis terjadi.

## 6. Expected Deliverables
- Permukaan *Human Review* yang menampilkan progres, latensi/error, serta tautan bukti dan sitasi SOP yang dapat dibuka (`FR-OUT-006`, `NFR-020`).
- Pengendali keputusan review (`approve`, `reject`, `edit/correction`) yang terikat versi revisi dan tersimpan secara *append-only* (`FR-OUT-004`, `HUM-01`).
- Eksportir *handover package* yang terpisah dari laporan evaluasi (`FR-OUT-005`) beserta implementasi/disposisi `AT-017`.
- Paket bukti tersanitasi `E16` pada `evidence/<run_id>/C16/`: `review-walkthrough`, `approval-rejection-revisions`, `handover-export`, dan `ticket-test-or-disposition`.

## 7. Validation & Exit Criteria
- `HUM-01` & `AT-010`: Dossier valid secara skema dan mudah dibaca manusia; rekomendasi kritis wajib melewati persetujuan reviewer L1; aksi `approve`, `reject`, dan `edit` tercatat secara *append-only* dengan identitas reviewer dan *timestamp*; 0 aksi remediasi otomatis terjadi.
- Percobaan review oleh identitas tidak berwenang atau persetujuan terhadap revisi dossier yang telah usang (`VERSION_CONFLICT`) ditolak secara deterministik dan tercatat di *security audit log*.
- `FR-OUT-005`: Paket ekspor handover terbukti terpisah dari laporan evaluasi dan bebas dari data *ground truth*.
- `AT-017`: Terverifikasi hanya membuat tiket dummy lokal sesudah *human approval* (jika dipilih pada `ADR-S07`), atau tercatat eksplisit sebagai `NOT_RUN / N/A` yang disetujui.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Karena proyek dikerjakan mandiri (`TBD-02`), pelaksana merangkap sebagai reviewer simulasi sehingga berpotensi menimbulkan bias penerimaan (`KPI-06`); mitigasi dengan menerapkan daftar periksa rubrik yang objektif dan mendeklarasikan status `SELF_EVALUATED` sesuai keputusan `TBD-08`.
- **Open Decisions:** Pilihan antarmuka review (`TBD-11`) dan disposisi *dummy ticket* (`ADR-S07`) mengikuti ketetapan yang telah disahkan pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- **Handover ke [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md) dan [C19](../phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md):** Dossier yang telah mencapai status terminal `CLOSED` pasca-review manusia, rekaman revisi/keputusan reviewer untuk penghitungan `KPI-06`, serta paket bukti `E16`.
