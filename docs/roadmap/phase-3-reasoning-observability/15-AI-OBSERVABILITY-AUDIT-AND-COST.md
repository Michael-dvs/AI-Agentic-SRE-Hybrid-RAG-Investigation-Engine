# C15 — AI Observability, Audit, and Cost

## 1. Chapter Information
- **Phase:** F3 — Reasoning & Observability
- **Status:** IMPLEMENTED
- **Documentation status:** APPROVED
- **Implementation status:** IMPLEMENTED
- **Evidence bundle:** `evidence/c15-20261116T085541Z/C15/` (Run ID: `c15-20261116T085541Z`)
- **Reviewer Decision & Baseline PoC Note:** Disetujui oleh Project Initiator sebagai baseline simulasi PoC: (1) Pemisahan tegar Sink 1 (Independent Security Audit Sink SHA-256 hash-chained, fail-closed) vs Sink 2 (Sanitized AI Observability Sink, lightweight OpenInference JSONL, fail-open) memenuhi ADR-S06 & BRD §12.2; (2) Pengendalian memori lab tetap di bawah 8 GiB RAM tanpa ketergantungan ClickHouse; (3) Multi-sink DLP scanner memverifikasi 0 kebocoran PII/rahasia/restricted/ground-truth dan 0 hidden CoT (<think>); (4) Akuntansi latensi (P95 <= 120s) dan shadow unit cost terukur otomatis untuk seluruh run (sukses maupun failed/timeout).
- **Dependencies:** [C08 — Secure Gateway and Foundation G1](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) (`G1 PASS`), [C11 — Durable Investigation Workflow](../phase-2-controlled-integration/11-DURABLE-INVESTIGATION-WORKFLOW.md), [C13 — Controlled LLM Investigator](13-CONTROLLED-LLM-INVESTIGATOR.md), [C14 — Evidence Validation and Uncertainty](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md), `G2 PASS` ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)), keputusan `ADR-S06` (pilihan sink AI observability & kebijakan *outage buffering*)
- **Next chapter:** [C16 — Human Review and Handover](16-HUMAN-REVIEW-AND-HANDOVER.md)
- **Related requirements:** `BR-014`, `FR-AGT-008`, `FR-OUT-006`, `NFR-003`, `NFR-005`, `NFR-006`, `NFR-007`, `NFR-008`, `NFR-012`, `NFR-013`, `NFR-017`, `NFR-018`, `KPI-07`, `KPI-14`, `BEN-03`, `DEP-06`, `RISK-08`
- **Related acceptance tests:** `SEC-03` (build & test owner *end-to-end* sanitasi ke seluruh sink LLM/Langfuse/trace; regresi di C18/C21), `SEC-01` (build owner pemindaian sink untuk ketiadaan dokumen *restricted*), `OPS-02` & `AT-012` (build & test owner persistensi *independent audit trail* saat LLM atau sink AI observability mati), `AT-015` (build owner perekaman *token, tool calls, latency, CPU/memory, shadow cost*; konsolidasi di C20/C21)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun lapisan *Sanitized AI Observability, Independent Security Audit Correlation, and Cost/Resource Telemetry* yang menghubungkan seluruh jejak investigasi (`incident_id`, transisi *workflow*, panggilan *tool*, skor/filter *retrieval*, hash model/prompt, pemakaian token, hasil validasi klaim, hingga keputusan reviewer) tanpa menjadikan platform AI tracing (seperti Langfuse atau ekuivalen ringan sesuai `ADR-S06`) sebagai satu-satunya rekaman audit keamanan (`AGENTS.md §6.3`, `BRD §12.2`).

Setelah chapter ini selesai, seluruh jejak eksekusi AI dapat diinspeksi melalui *dashboard*/ekspor terstruktur (`BR-014`, `NFR-018`), pemindaian DLP/sanitizer membuktikan 0 kebocoran *synthetic PII/secret fixture* maupun dokumen *restricted* ke sink mana pun (`SEC-03`, `SEC-01`), metrik latensi (`KPI-07`, `NFR-007`, `NFR-008`) serta pemakaian token/komputasi dan *shadow unit cost* per insiden (`AT-015`, `KPI-14`) terekam otomatis, dan mematikan sink AI observability atau mengalami kegagalan sanitizer terbukti tidak menghapus jejak *independent security audit* (`OPS-02`, `AT-012`).

## 3. Scope & Boundaries
### In Scope
- Integrasi *sanitized AI tracing* (Langfuse *self-hosted* atau alternatif ringan *open-source* yang dipilih pada `ADR-S06` di dalam plafon 8 GiB RAM) yang menautkan `incident_id`, `correlation_id`, versi *workflow/model/prompt/KB*, durasi per *state*, panggilan *tool* (dengan argumen ter-hash/tersanitasi), dan hasil validasi (`NFR-005`, `NFR-018`).
- Pemisahan tegas antara *AI observability trace* (untuk kualitas/debugging) dan *independent append-only security audit log* (untuk kepatuhan kontrol akses, penolakan *tool*, dan keputusan review) (`BRD §12.2`).
- Penegakan redaksi `SEC-03` (`FAIL_CLOSED`) sebelum data dikirim ke sink AI observability dan larangan perekaman *hidden chain-of-thought* atau kunci jawaban *ground truth* (`NFR-003`, `NFR-012`).
- Pengukuran otomatis durasi *intake-to-dossier* (`KPI-07`), latensi *retrieval* (`NFR-008`), jumlah token input/output, panggilan *embedding/tool*, pemakaian CPU/RAM kontainer, serta estimasi *shadow cost* per insiden (termasuk insiden yang gagal/timeout) (`NFR-013`, `AT-015`, `KPI-14`).

### Out of Scope
- Mengirim jejak telemetri ke layanan cloud berbayar atau eksternal tanpa persetujuan (`TBD-09`, `TBD-13`).
- Menggunakan *raw unsanitized payload* sebagai *fallback* ketika modul redaksi gagal (`Proposal §9.1`).
- Mengizinkan sink AI observability membaca *Restricted Ground Truth Registry* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)).

## 4. Prerequisites
- Gate G2 ([C12](../phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)) berstatus `PASS`.
- Komponen *Secure Gateway* ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)), *Durable Workflow* ([C11](../phase-2-controlled-integration/11-DURABLE-INVESTIGATION-WORKFLOW.md)), *Controlled LLM Investigator* ([C13](13-CONTROLLED-LLM-INVESTIGATOR.md)), dan *Evidence Validator* ([C14](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)) telah beroperasi.
- Keputusan `ADR-S06` mengenai pemilihan sink AI observability yang muat di dalam anggaran memori 8 GiB RAM dan kebijakan *outage buffering/drop* telah disahkan pada Gate G1.

## 5. Implementation Roadmap
1. **Korelasi End-to-End AI Trace dan Independent Security Audit (`NFR-005`, `NFR-018`)**
   - *Apa yang harus dilakukan:* Pasang eksportir *trace* tersanitasi sesuai `ADR-S06` yang mencatat *span* untuk setiap tahap `FR-AGT-001`, hash argumen *tool*, ID/skor dokumen *retrieval*, `model_id`/`prompt_hash`, serta hasil validasi [C14](14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md), sambil menjaga *independent append-only security audit log* tetap ditulis langsung oleh gateway/workflow ke penyimpanan audit lokal.
   - *Mengapa diperlukan:* Memungkinkan penelusuran penuh dari `incident_id` ke setiap keputusan AI dan *tool* tanpa bergantung tunggal pada ketersediaan sink AI observability.
   - *Expected output:* Modul *AI trace exporter* dan tabel/berkas `audit-correlation`.
   - *Cara memverifikasi:* Jalankan satu insiden sampai selesai dan buktikan `incident_id` dapat digunakan untuk menggabungkan (*join*) rekaman di *security audit log* dengan *trace* di sink AI observability.
2. **Penegakan Redaksi Multi-Sink (`SEC-03`) dan Pemindaian Kebocoran (`SEC-01`, `AT-008`)**
   - *Apa yang harus dilakukan:* Pastikan seluruh *payload* menuju sink AI observability, log aplikasi, dan penyimpanan bukti melewati *sanitizer* `SEC-03` dengan mode `FAIL_CLOSED`. Bangun skrip pemindai (*DLP/sink scanner*) yang memeriksa seluruh rekaman *trace* dan log terhadap pola *synthetic PII/secret fixtures*, dokumen `restricted` lintas layanan (`SEC-01`), dan label *ground truth* (`AT-008`).
   - *Mengapa diperlukan:* Membuktikan secara *end-to-end* bahwa tidak ada data terlarang yang bocor ke log atau sistem observabilitas AI (`NFR-003`, `NFR-012`).
   - *Expected output:* Konfigurasi *pre-sink redaction guard* dan laporan `dlp-sink-scan`.
   - *Cara memverifikasi:* Jalankan insiden yang melibatkan log berisi *synthetic secret/PII* dan percobaan akses dokumen *restricted*; jalankan pemindai sink dan pastikan ditemukan 0 kebocoran mentah.
3. **Instrumentasi Metrik Latensi, Pemakaian Token/Resource, dan Shadow Cost (`AT-015`, `KPI-07`, `KPI-14`)**
   - *Apa yang harus dilakukan:* Rekam *timestamp* presisi untuk `alert_received_at`, durasi tiap *state*, durasi *retrieval* (`NFR-008`), dan `dossier_ready_at` (`KPI-07`), serta hitung jumlah token input/output, panggilan *tool/embedding*, puncak CPU/RAM, dan *shadow unit cost* (menggunakan tabel tarif referensi yang transparan meskipun biaya aktual `$0.00` pada *Free-Tier*/lokal), baik untuk eksekusi sukses maupun yang gagal/timeout.
   - *Mengapa diperlukan:* Menyediakan data objektif untuk evaluasi efisiensi operasional dan biaya (`NFR-013`, `AT-015`) tanpa menyembunyikan biaya dari *failed runs*.
   - *Expected output:* Modul kolektor `usage-cost-metrics` dan ringkasan dashboard/ekspor kualitas AI (`BR-014`).
   - *Cara memverifikasi:* Periksa bahwa setiap eksekusi insiden menghasilkan baris metrik lengkap yang memuat durasi *end-to-end*, rincian token, dan pemakaian memori.
4. **Pengujian Outage Sink AI Observability dan Kegagalan Sanitizer (`OPS-02`, `AT-012`)**
   - *Apa yang harus dilakukan:* Matikan layanan sink AI observability (Langfuse/ekuivalen) dan simulasikan error internal pada modul *sanitizer* di tengah jalannya investigasi, lalu amati perilaku *buffer/drop/block* sesuai kebijakan `ADR-S06`.
   - *Mengapa diperlukan:* Membuktikan bahwa matinya sink AI observability tidak menghentikan pembuatan dossier maupun menghilangkan *independent security audit*, sedangkan kegagalan *sanitizer* wajib memblokir pengiriman *payload* mentah (`FAIL_CLOSED`).
   - *Expected output:* Rekaman uji ketahanan `sink-outage-proof`.
   - *Cara memverifikasi:* Pastikan saat sink AI dimatikan, investigasi tetap selesai dan *security audit log* tetap lengkap; pastikan saat *sanitizer* dipaksa gagal, 0 *payload* mentah terkirim ke model atau sink.

5. **Ekspor Ringkasan Observabilitas AI dan Pengemasan Bukti `E15` (`BR-014`)**
   - *Apa yang harus dilakukan:* Hasilkan ekspor terstruktur jejak AI yang telah disanitasi (`sanitized-trace-export`), laporan korelasi audit (`audit-correlation`), hasil pemindaian DLP (`dlp-sink-scan`), dan ringkasan metrik biaya/latensi (`usage-cost-metrics`) ke dalam paket `E15`.
   - *Mengapa diperlukan:* Menyediakan visibilitas kualitas dan biaya bagi reviewer ([C16](16-HUMAN-REVIEW-AND-HANDOVER.md)) serta data terukur bagi *Offline Evaluation Harness* ([C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)).
   - *Expected output:* Paket bukti lengkap `E15` pada `evidence/<run_id>/C15/`.
   - *Cara memverifikasi:* Pastikan kelima artefak `E15` tersedia, bebas dari *hidden chain-of-thought* (`NFR-012`), dan lulus pemindaian `dlp-sink-scan` dengan 0 pelanggaran.

## 6. Expected Deliverables
- Integrasi *sanitized AI observability tracing* (`ADR-S06`) yang terpisah dari *independent append-only security audit log*.
- Pemindai otomatis kebocoran DLP/fixture (`dlp-sink-scan`) untuk memverifikasi `SEC-01`, `SEC-03`, dan `AT-008` di seluruh sink.
- Kolektor metrik latensi (`KPI-07`, `NFR-008`), konsumsi sumber daya/token, dan *shadow cost* (`AT-015`, `KPI-14`) beserta tampilan/ekspor ringkasan (`BR-014`).
- Paket bukti tersanitasi `E15` pada `evidence/<run_id>/C15/`: `sanitized-trace-export`, `audit-correlation`, `dlp-sink-scan`, `usage-cost-metrics`, dan `sink-outage-proof`.

## 7. Validation & Exit Criteria
- `SEC-03` & `SEC-01` (*end-to-end sink check*): Pemindaian seluruh rekaman di sink AI observability, prompt log, dan dossier menunjukkan 0 *synthetic PII/secret fixture* mentah, 0 dokumen `restricted` lintas layanan, dan 0 *hidden chain-of-thought*.
- `OPS-02` & `AT-012` (persistensi audit): Saat LLM atau sink AI observability dimatikan, *independent security audit trail* tetap mencatat seluruh kejadian dengan lengkap dan dapat diinspeksi.
- `AT-015`, `NFR-013`, & `NFR-018`: Durasi per *state*, latensi `intake-to-dossier`, latensi *retrieval*, jumlah token/panggilan, pemakaian CPU/RAM, dan estimasi *shadow cost* tercatat untuk setiap insiden (termasuk yang gagal).
- Kegagalan pada modul *sanitizer* terbukti bekerja secara `FAIL_CLOSED` (memblokir pengiriman data mentah ke model maupun sink).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Menjalankan tumpukan Langfuse penuh (beserta dependensi database tambahannya) dapat mengonsumsi RAM yang signifikan pada batas 8 GiB (`RISK-07`); mitigasi dengan mematuhi pilihan arsitektur ringan yang telah disahkan pada `ADR-S06`.
- **Open Decisions:** Kebijakan retensi rekaman trace (`TBD-13`: selama PoC + 30 hari pasca G4) dan pilihan sink (`ADR-S06`) mengikuti keputusan Gate G0/G1; tarif referensi untuk perhitungan *shadow unit cost* (`AT-015`) didokumentasikan secara eksplisit sebagai asumsi simulasi karena anggaran aktual adalah `$0.00`.
- **Handover ke [C16](16-HUMAN-REVIEW-AND-HANDOVER.md) dan [C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md):** Tautan observabilitas AI dan metrik latensi/error untuk ditampilkan pada permukaan review manusia ([C16](16-HUMAN-REVIEW-AND-HANDOVER.md)), serta ekspor `usage-cost-metrics` dan `sanitized-trace-export` (`E15`) untuk dihubungkan ke *Offline Evaluation Harness* ([C17](17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)).
