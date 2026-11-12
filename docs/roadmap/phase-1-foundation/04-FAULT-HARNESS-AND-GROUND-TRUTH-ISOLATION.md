# C04 — Fault Harness and Ground Truth Isolation

## 1. Chapter Information
- **Phase:** F1 — Foundation
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), [C03 — Lab Services and Synthetic Traffic](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md)
- **Next chapter:** [C05 — Telemetry and Service Catalog](05-TELEMETRY-AND-SERVICE-CATALOG.md)
- **Related requirements:** `BR-002`, `BR-008`, `BR-010`, `FR-SIM-004`, `FR-SIM-005`, `FR-SIM-006`, `FR-SIM-007`, `RULE-001`, `RULE-002`, `RULE-009`, `RULE-010`, `NFR-001`, `NFR-002`, `NFR-011`, `DEP-04`, `RISK-02`, `RISK-14`, `SC-02` s/d `SC-14`
- **Related acceptance tests:** `AT-002` (build & test owner tahap fondasi; diulang pada *clean replay* di C22), `AT-008` (build & test owner tahap isolasi identitas/storage; diuji *end-to-end* di C12, C18, C21), `AT-013` (build owner bagian stabilitas *ground truth*), `AT-016` (build owner bagian injeksi *cascade fault*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *fault injection harness* yang sepenuhnya dapat dibalik (*reversible*) serta registri *ground truth* yang terisolasi secara fisik dan logis dari *runtime* agent investigator. Mengacu pada [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md) dan kontrak batas kepercayaan (*trust boundary*) di [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), hanya identitas operator/harness yang berhak memicu atau mereset gangguan, sedangkan agent investigator tidak pernah memiliki akses baca maupun panggil ke kontrol *fault* atau label *ground truth* (`RULE-002`).

Setelah chapter ini selesai, operator dapat mengaktifkan, menghentikan, dan mereset skenario gangguan pada layanan simulasi [C03](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md), membekukan rekaman *ground truth* (`scenario_id`, `fault_type`, `target_service`, `seed`, `onset_at`, `ended_at`, `expected_symptoms`) secara *append-only* pada penyimpanan khusus evaluator (`FR-SIM-005`, `NFR-011`), serta membuktikan bahwa layanan kembali 100% sehat pasca-reset (`FR-SIM-007`).

## 3. Scope & Boundaries
### In Scope
- Pemisahan jaringan, kredensial identitas, dan *volume mount* antara *Fault Harness + Restricted Ground Truth Registry* dengan *Agent Runtime* (`RULE-002`, `AT-008`).
- Implementasi kontrol *start/stop/reset fault* yang *reversible* untuk gangguan tingkat layanan/jaringan (`SC-02` HTTP 5xx, `SC-03` DB latency, `SC-04` dependency unavailable, `SC-05` pool exhaustion, `SC-06` auth mismatch, `SC-07` queue consumer lag, `SC-08` dua fault konkuren).
- Penyusunan katalog dan resep (*recipes*) standar untuk seluruh 14 skenario (`SC-01` s/d `SC-14`), di mana aktivasi operasional `SC-09` (trace hilang), `SC-10` (SOP usang), `SC-11` (log adversarial), `SC-12` (100 duplicate alerts), `SC-13` (LLM outage), dan `SC-14` (korelasi menyesatkan) disinkronkan dengan chapter pemilik komponennya.
- Pembekuan *ground truth record* secara *append-only* sebelum investigasi dimulai dan penyediaan *opaque run/incident reference* agar nama skenario tidak bocor ke telemetri aplikasi.

### Out of Scope
- Pemberian akses *fault control* atau *reset* kepada *tool registry* yang dipanggil oleh LLM/investigator (`FR-AGT-003`, `MCP-01`).
- Evaluasi otomatis pencocokan hipotesis dossier terhadap *ground truth* (dibangun di [C17](../phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md)).
- Pengujian *fault injection* di luar kontainer lab lokal (`RULE-009`).

## 4. Prerequisites
- Layanan simulasi 5 komponen dan generator trafik dari [C03](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md) telah berjalan dan tervalidasi (`E03`).
- Skema `scenario-oracle`, *restricted evaluation manifest*, dan matriks batas akses identitas dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.
- Lokasi penyimpanan terisolasi untuk *Restricted Ground Truth Registry* (di luar direktori/mount yang dapat diakses kontainer agent/tools/RAG) telah ditetapkan sesuai kebijakan `TBD-13`.

## 5. Implementation Roadmap
1. **Isolasi Penyimpanan dan Identitas Ground Truth Registry (`RULE-002`, `FR-SIM-005`)**
   - *Apa yang harus dilakukan:* Siapkan direktori/penyimpanan *append-only* khusus evaluator dengan izin sistem berkas/kontainer terpisah dan kredensial khusus `fault-harness` yang tidak di-mount ke jaringan atau kontainer runtime investigator.
   - *Mengapa diperlukan:* Kegagalan isolasi *ground truth* adalah kondisi `Automatic NO-GO` (`BRD §15.5`, `RISK-02`).
   - *Expected output:* Modul penulis *append-only ground truth registry* dan konfigurasi isolasi kontainer/volume.
   - *Cara memverifikasi:* Jalankan uji akses negatif dari identitas/kontainer *agent runtime* menuju path/endpoint *ground truth* dan pastikan ditolak (`Permission Denied` / `Connection Refused`).
2. **Implementasi Kontrol Injeksi Gangguan Layanan yang Reversible (`FR-SIM-004`, `FR-SIM-006`)**
   - *Apa yang harus dilakukan:* Bangun pengendali `start_fault`, `stop_fault`, dan `reset_all` untuk mengaktifkan gangguan pada 5 layanan (`SC-02` s/d `SC-08`) tanpa menyertakan label `scenario_id` atau nama fault di dalam respons HTTP publik maupun log aplikasi.
   - *Mengapa diperlukan:* Memastikan gejala gangguan hanya terlihat melalui sinyal observabilitas alami (latensi, kode error, antrean), bukan karena bocornya nama skenario di log.
   - *Expected output:* Layanan/CLI *fault harness* terautentikasi beserta *hooks* gangguan yang dikendalikan dari luar jalur investigator.
   - *Cara memverifikasi:* Aktifkan masing-masing fault (`SC-02` s/d `SC-08`), amati perubahan perilaku layanan, dan pastikan log aplikasi tidak memuat string `SC-02` atau label jawaban *ground truth*.
3. **Katalogisasi Lengkap Skenario `SC-01` s/d `SC-14` dan Resep Lintas Komponen**
   - *Apa yang harus dilakukan:* Dokumentasikan dan kodifikasikan manifes 14 skenario mencakup prasyarat, perintah *setup/inject/reset*, `seed`, durasi, gejala yang diharapkan, tingkat kesulitan, rubrik evaluator, dan *repeat count*. Untuk `SC-09` s/d `SC-14`, siapkan resep injeksi yang akan dihubungkan ke komponen telemetri ([C05](05-TELEMETRY-AND-SERVICE-CATALOG.md)), KB ([C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md)), intake ([C10](../phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)), dan LLM/validator ([C13](../phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)–[C14](../phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)).
   - *Mengapa diperlukan:* Menjamin seluruh skenario `Must` dan `Should` dari `BRD §14` memiliki spesifikasi eksekusi yang konsisten tanpa ada yang dihilangkan diam-diam.
   - *Expected output:* Katalog skenario terstruktur (`scenario-manifest`) dan registri oracle terisolasi.
   - *Cara memverifikasi:* Audit kelengkapan 14 ID skenario terhadap tabel `BRD §14` dan skema [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md).
4. **Implementasi Mekanisme Clean Reset dan Pemeriksaan Residual Fault (`FR-SIM-007`)**
   - *Apa yang harus dilakukan:* Buat prosedur `reset` deterministik yang menghentikan seluruh fault aktif, menguras antrean/koneksi macet pada layanan dummy, dan memverifikasi kembalinya metrik dasar ke kondisi sehat.
   - *Mengapa diperlukan:* Mencegah kontaminasi gejala (*carryover*) dari satu skenario ke skenario pengujian berikutnya.
   - *Expected output:* Skrip/fungsi `reset` otomatis dengan pemeriksaan pasca-reset.
   - *Cara memverifikasi:* Setelah menginjeksi *cascade fault* (`SC-04`) dan *concurrent fault* (`SC-08`), jalankan `reset` dan buktikan rantai permintaan kembali sehat dalam batas waktu yang ditentukan.
5. **Pengujian Verifikasi `AT-002` dan Boundary `AT-008`**
   - *Apa yang harus dilakukan:* Jalankan siklus *inject $\rightarrow$ verify symptom $\rightarrow$ freeze GT record $\rightarrow$ runtime negative access check $\rightarrow$ reset $\rightarrow$ verify clean state* dan rekam bukti tersanitasi ke `E04`.
   - *Mengapa diperlukan:* Membuktikan kesiapan `AT-002` dan isolasi awal `AT-008` sebelum sinyal dikoleksi oleh pipeline observabilitas di [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md).
   - *Expected output:* Paket bukti `E04` (`scenario-manifest`, `reset-proof`, `gt-access-denials`).
   - *Cara memverifikasi:* Periksa bahwa seluruh upaya baca GT oleh identitas runtime gagal dan bukti `E04` yang dipublikasikan tidak membocorkan kunci jawaban holdout.

## 6. Expected Deliverables
- *Reversible fault injection harness* yang hanya dapat dipanggil oleh identitas operator/harness.
- Katalog 14 skenario (`SC-01` s/d `SC-14`) dengan resep *setup*, *inject*, dan *reset*.
- *Isolated append-only Ground Truth Registry* pada penyimpanan khusus evaluator.
- Paket bukti tersanitasi `E04` pada `evidence/<run_id>/C04/`: `scenario-manifest`, `reset-proof`, dan `gt-access-denials`.

## 7. Validation & Exit Criteria
- `AT-002` (tahap fondasi): Injeksi dan *reset* gangguan untuk `SC-02` s/d `SC-08` berfungsi konsisten, layanan kembali ke kondisi bersih tanpa *residual fault* (`FR-SIM-007`), dan waktu mulai/berakhir tercatat di registri terpisah.
- `AT-008` (tahap *storage/identity boundary*): Identitas runtime investigator terbukti ditolak saat mencoba mengakses penyimpanan, jaringan, atau endpoint *ground truth* dan *fault harness* (`KPI-10` = 0 kebocoran).
- Tidak ada label `scenario_id` atau deskripsi *root cause* yang bocor ke *header* HTTP, pesan error aplikasi, atau log standar layanan simulasi.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Kebocoran tidak sengaja label fault melalui nama variabel lingkungan atau pesan *exception* aplikasi (`RISK-02`); mitigasi dengan *opaque fault flags* dan pemindaian string log sebelum lanjut ke [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md).
- **Open Decisions:** Parameter numerik durasi dan jumlah pengulangan (*repeat count*) final untuk benchmark formal menunggu pembekuan protokol pada Gate G1 ([C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) / `TBD-10`).
- **Handover ke [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md):** Layanan yang dapat diinjeksi gangguan secara *reversible* (`SC-02` s/d `SC-08`), resep simulasi kehilangan trace (`SC-09`), serta paket bukti `E04`.

