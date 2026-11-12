# C10 — Alert Intake and Dependency Correlation

## 1. Chapter Information
- **Phase:** F2 — Controlled Integration
- **Status:** IMPLEMENTED / REVIEW_REQUIRED
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** IMPLEMENTED — kedua defect diperbaiki dan 63 tes lulus; `VERIFIED` menunggu exit criteria resource dan review. Lihat [E10](../../../evidence/c10-final-20261112T063556Z/C10/readiness-check.md).
- **Dependencies:** [C05 — Telemetry and Service Catalog](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md), [C08 — Secure Gateway and Foundation G1](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) (`G1 PASS`), [C09 — Read-Only Telemetry Adapters](09-READ-ONLY-TELEMETRY-ADAPTERS.md), parameter `ADR-S05` (dedup TTL, correlation window, queue bounds)
- **Next chapter:** [C11 — Durable Investigation Workflow](11-DURABLE-INVESTIGATION-WORKFLOW.md)
- **Related requirements:** `BR-013`, `FR-SIM-006`, `FR-OBS-001`, `FR-OBS-004`, `FR-OBS-005`, `FR-OBS-006`, `NFR-005`, `NFR-006`, `NFR-010` (fondasi *bounded burst*), `RISK-07`, `SC-04`, `SC-08`, `SC-12`, `UC-02`, `UC-06`
- **Related acceptance tests:** `AT-003` (build & test owner penyelesaian korelasi sinyal + `incident_id`; diulang di C12/C22), `OPS-01` (build & test owner sisi *intake* untuk 100 *duplicate alerts*; diuji *end-to-end* di C12/C20/C21), `AT-016` (build & test owner tahap korelasi *dependency cascade*; dilengkapi validasi klaim di C14/C18/C21)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun layanan *Alert Intake, Deduplication, and Dependency Correlation* yang menerima sinyal *alert* dari [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md), memvalidasi dan menormalisasi waktu serta identitas layanan, melakukan deduplikasi berbasis *fingerprint* dan jendela waktu agar tidak terjadi ledakan *workflow* saat *alert storm* (`SC-12`, `OPS-01`), serta menyusun graf dampak ketergantungan (*dependency impact graph*) tanpa menyatukan dua gangguan independen secara keliru (`SC-08`).

Setelah chapter ini selesai, setiap *alert* yang valid menghasilkan atau memperbarui `incident_id` secara idempoten (`FR-OBS-004`–`005`), semburan 100 *duplicate alerts* berhasil dideduplikasi dengan penggunaan antrean dan sumber daya yang terikat (`OPS-01`), layanan yang tidak terdaftar atau ambigu diarahkan ke *manual triage* alih-alih membuka kueri lintas layanan tanpa batas, serta relasi *origin vs downstream symptom* pada kasus *cascade* (`SC-04`, `AT-016`) dan *concurrent faults* (`SC-08`) terpetakan secara akurat.

## 3. Scope & Boundaries
### In Scope
- Implementasi endpoint *alert intake* terautentikasi/bertanda tangan sesuai `ADR-S02`/`ADR-S03` yang memvalidasi skema *alert envelope*, menormalisasi zona waktu ke UTC ISO 8601, dan mencocokkan `service.name` terhadap *Service Catalog* ([C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md)) (`FR-OBS-004`).
- Implementasi algoritma *deduplication fingerprint*, *idempotency key*, *Time-to-Live* (TTL), antrean terbatas (*bounded queue/backpressure*), serta pencatatan audit *merge/split* insiden (`FR-OBS-005`, `OPS-01`).
- Implementasi korelasi topologi yang menggabungkan *Service Catalog*, *trace lineage*, *freshness* *edge*, dan perubahan teramati menjadi *dependency impact graph* per insiden (`FR-OBS-006`, `BR-013`, `AT-016`).
- Penanganan khusus untuk *concurrent independent incidents* (`SC-08`) agar dua gangguan pada layanan yang tidak berhubungan tidak dipaksa bergabung menjadi satu penyebab tunggal.

### Out of Scope
- Orkestrasi *state machine* investigasi (`RECEIVED` s/d `HUMAN_REVIEW`) yang mengonsumsi antrean insiden (dibangun di [C11](11-DURABLE-INVESTIGATION-WORKFLOW.md)).
- Penalaran LLM atau penyusunan dokumen dossier akhir (dibangun di [C12](12-BASELINE-DOSSIER-AND-END-TO-END-G2.md)–[C14](../phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)).
- Pembacaan label `scenario_id` dari *fault harness* untuk menentukan pengelompokan insiden (`RULE-002`).

## 4. Prerequisites
- Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) berstatus `PASS`.
- Sumber *alert*, *Service Catalog*, dan *observed dependency snapshots* dari [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md) (`E05`) serta adapter `get_service_dependencies` dari [C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md) (`E09`) telah berfungsi.
- Parameter `ADR-S05` (*dedup TTL*, *correlation window*, batas panjang antrean, dan batas sumber daya *burst*) telah ditetapkan pada Gate G1.

## 5. Implementation Roadmap
1. **Implementasi Validasi Alert Intake dan Normalisasi Konteks Insiden (`FR-OBS-004`)**
   - *Apa yang harus dilakukan:* Bangun layanan *intake* yang memverifikasi autentikasi pengirim *alert*, memvalidasi skema *payload* terhadap kontrak [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), menormalisasi *timestamp* ke UTC, dan memverifikasi keberadaan `service.name` serta `environment` di *Service Catalog*; arahkan *alert* dengan layanan tidak dikenal/ambigu ke status `MANUAL_TRIAGE_REQUIRED`.
   - *Mengapa diperlukan:* Mencegah *alert* cacat atau layanan tidak terpetakan memicu kueri melebar (*broad unscoped query*) yang melanggar prinsip *least privilege* (`Proposal §9`).
   - *Expected output:* Layanan *intake* dengan pembuatan `incident_id` (opaque UUID/ID) dan pencatatan status awal.
   - *Cara memverifikasi:* Kirim *alert* valid, *alert* dengan skema rusak, dan *alert* dengan nama layanan asing; pastikan hanya *alert* valid yang menghasilkan konteks insiden aktif sementara sisanya ditolak atau ditandai untuk triase manual.
2. **Implementasi Deduplikasi Fingerprint, Idempotency, dan Bounded Queue (`FR-OBS-005`, `OPS-01`)**
   - *Apa yang harus dilakukan:* Hitung *fingerprint* deterministik per *alert* (berdasarkan layanan, lingkungan, kelas gejala/alert rule, dan jendela waktu `ADR-S05`), simpan di registri deduplikasi dengan TTL terkonfigurasi, terapkan *bounded queue* dengan *backpressure*, dan catat setiap penggabungan (*merge*) atau pemisahan (*split*) ke dalam log audit.
   - *Mengapa diperlukan:* Menjamin semburan *alert* berulang tidak melahirkan *worker* investigasi tanpa batas yang menguras kuota API atau memori lab (`RISK-07`, `RISK-08`).
   - *Expected output:* Registri deduplikasi, antrean insiden terbatas, dan `merge-split-log`.
   - *Cara memverifikasi:* Kirim ulang *alert* dengan *idempotency key* atau *fingerprint* yang sama dalam jendela TTL; pastikan hanya 1 `incident_id` aktif yang dibuat dan *hit count* bertambah secara tercatat.
3. **Pembangunan Korelasi Ketergantungan dan Dependency Impact Graph (`FR-OBS-006`, `AT-016`)**
   - *Apa yang harus dilakukan:* Untuk setiap insiden aktif, kueri *Service Catalog* dan `get_service_dependencies` ([C09](09-READ-ONLY-TELEMETRY-ADAPTERS.md)) guna menyusun sub-graf hulu-hilir yang menandai layanan pemicu *alert*, kandidat *upstream/downstream dependencies*, *freshness* *edge*, serta penanda ketidakpastian jika *edge* sudah *stale*.
   - *Mengapa diperlukan:* Membantu membedakan titik asal gangguan (*origin*) dari gejala ikutan di hilir/hulu pada skenario *cascade* (`SC-04`) tanpa mengklaim kausalitas mutlak.
   - *Expected output:* Struktur data `dependency-impact` yang tertaut pada setiap `incident_id`.
   - *Cara memverifikasi:* Picu gangguan pada `db-dummy` (`SC-03`/`SC-04`) yang memunculkan *alert* di `transaction-service` dan `api-gateway`; pastikan graf menautkan ketiganya dengan arah ketergantungan yang benar.
4. **Penanganan Multi-Alert Independen / Concurrent Faults (`SC-08`, `UC-06`)**
   - *Apa yang harus dilakukan:* Terapkan aturan pemisahan korelasi sehingga dua *alert* yang terjadi bersamaan pada jalur layanan yang tidak memiliki keterkaitan *trace lineage* atau *dependency edge* aktif tetap dipertahankan sebagai insiden/cabang terpisah, bukan digabung paksa.
   - *Mengapa diperlukan:* Memenuhi syarat `SC-08` dan `UC-06` agar sistem tidak memaksakan satu *root cause* tunggal ketika terjadi dua gangguan independen.
   - *Expected output:* Aturan *correlation split* dan bukti pemisahan pada skenario *concurrent faults*.
   - *Cara memverifikasi:* Injeksi dua gangguan independen secara bersamaan (`SC-08`) dan verifikasi bahwa *intake* tidak melebur keduanya menjadi satu penyebab palsu.
5. **Pengujian Burst 100 Duplicate Alerts (`SC-12`, `OPS-01`) dan Penyelesaian `AT-003`**
   - *Apa yang harus dilakukan:* Jalankan pengujian injeksi 100 *duplicate alerts* dalam satu semburan cepat (`SC-12`) serta skenario *cascade* (`SC-04`) dan *concurrent* (`SC-08`), sambil merekam jumlah insiden yang terbentuk, panjang antrean, jumlah panggilan *tool*, serta penggunaan CPU/RAM ke `E10`.
   - *Mengapa diperlukan:* Membuktikan penyelesaian `AT-003` dan kelulusan sisi *intake* untuk `OPS-01` serta `AT-016`.
   - *Expected output:* Paket bukti `E10` (`intake-validation`, `incident-fingerprints`, `merge-split-log`, `burst-resource-series`, `dependency-impact`).
   - *Cara memverifikasi:* Pastikan dari 100 *duplicate alerts*, hanya 1 insiden investigasi yang dijadwalkan, konsumsi CPU/RAM tetap di bawah plafon `ADR-S05`, dan log/metric/trace terhubung ke `incident_id` tersebut (`AT-003`).

## 6. Expected Deliverables
- Layanan *Alert Intake* terautentikasi dengan validasi skema, normalisasi waktu UTC, dan penanganan *unmapped/ambiguous service*.
- Mesin deduplikasi berbasis *fingerprint* dan TTL beserta antrean terbatas (*bounded queue*) dan log audit *merge/split*.
- Modul *Dependency Correlation* yang menghasilkan *dependency impact graph* per insiden.
- Paket bukti tersanitasi `E10` pada `evidence/<run_id>/C10/`: `intake-validation`, `incident-fingerprints`, `merge-split-log`, `burst-resource-series`, dan `dependency-impact`.

## 7. Validation & Exit Criteria
- `AT-003` (selesai pada tingkat integrasi; diulang di C12/C22): Gangguan dari *fault harness* menggerakkan *logs*, *metrics*, *traces*, dan *alert* yang menghasilkan `incident_id` terkorelasi secara utuh.
- `OPS-01` (sisi *intake*; diuji *end-to-end* di C12/C20/C21): Semburan 100 *duplicate alerts* (`SC-12`) berhasil dideduplikasi menjadi 1 insiden aktif dengan panjang antrean dan konsumsi memori/CPU tetap berada di dalam batas yang disahkan.
- `AT-016` & `SC-08` (tahap korelasi): Skenario *cascade* (`SC-04`) menghasilkan bukti ketergantungan hulu-hilir beserta penanda *freshness/uncertainty*, sedangkan dua gangguan independen (`SC-08`) tidak digabung secara keliru.
- *Alert* untuk layanan yang tidak dikenal di *Service Catalog* ditolak/diarahkan ke triase manual tanpa membuka cakupan kueri ke seluruh layanan.

### Hasil aktual run C10
- `AT-003`: `PASS` pada lingkup replay C10: log, span, metrik dan incident ditautkan berdasarkan service serta waktu/trace dalam [bukti](../../../evidence/c10-verify-20261112T053639Z/C10/cross-signal-links.json); metrik agregat tidak memiliki trace ID, dan referensi alert belum didereferensi.
- `AT-016`: `PASS` pada lingkup korelasi C10 dalam [pemeriksaan graf](../../../evidence/c10-verify-20261112T053639Z/C10/cascade-graph-check.json); freshness stale dan ketidakpastian tetap eksplisit. `OPS-01`: `PARTIAL` karena plafon resource disahkan dan uji end-to-end belum tersedia.
- **C10-VERIFY-001/002:** `RESOLVED` pada pengujian yang dijalankan. [Atomicity](../../../evidence/c10-final-20261112T063556Z/C10/failure-atomicity.json) menolak admission saat korelasi gagal; [SC-08](../../../evidence/c10-final-20261112T063556Z/C10/sc08-live-replay.json) menggunakan dua container terisolasi dan menghasilkan dua incident terpisah dari alert aktual. `VERIFIED` masih menunggu batas resource dan review.
- Runtime: `AlertIntakeService` memerlukan token sintetis, snapshot catalog, deduplicator dan correlator yang disuntikkan; `POST /alerts` memakai HMAC, schema C02 dan triase manual. Admission dikorelasikan di bawah lock sebelum commit; callback tidak boleh masuk kembali ke deduplicator. TTL dedup 60 detik dikonfirmasi G1; correlation window 60 detik dipilih pengguna untuk lab, belum dibekukan dalam ADR-S05. Kapasitas antrean maksimum 500; registri bersifat in-memory.
- Korelasi lintas layanan memerlukan jalur terarah dan trace ID yang sama atau edge teramati yang fresh; topologi deklaratif tanpa timestamp ditandai stale. Hasil merupakan kandidat `INCONCLUSIVE`, bukan bukti sebab. Logger audit atau sink terkonfigurasi harus dipertahankan operator.
- Runner fault bawaan mereset seluruh layanan dalam `finally`; replay alternatif memakai fault ID unik dan membersihkan hanya fault tersebut. Bukti integrasi dan penilaian resource lengkap masih diperlukan.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Jendela waktu korelasi (*correlation window*) yang terlalu lebar dapat menggabungkan dua insiden terpisah, sedangkan jendela yang terlalu sempit gagal menangkap efek *cascade* lambat; mitigasi dengan mengkalibrasi nilai `ADR-S05` pada skenario `DEV` (`SC-04` vs `SC-08`).
- **Open Decisions:** G1 mengonfirmasi dedup 60 detik; correlation window 60 detik adalah pilihan lab pengguna yang belum dibekukan dalam ADR-S05. Plafon resource burst C10 dan reviewer yang berwenang masih `TBD`.
- **Handover ke [C11](11-DURABLE-INVESTIGATION-WORKFLOW.md):** implementasi siap ditinjau; handover terverifikasi menunggu exit criteria resource dan review evidence.

