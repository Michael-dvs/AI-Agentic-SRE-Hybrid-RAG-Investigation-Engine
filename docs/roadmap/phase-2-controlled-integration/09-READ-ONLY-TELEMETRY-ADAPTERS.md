# C09 — Read-Only Telemetry Adapters

## 1. Chapter Information
- **Phase:** F2 — Controlled Integration
- **Status:** IMPLEMENTED / VERIFIED
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** IMPLEMENTED (Paket bukti diverifikasi di `evidence/c09-20261112T041500Z/C09/`; 20/20 test cases PASS)
- **Dependencies:** [C05 — Telemetry and Service Catalog](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md), [C08 — Secure Gateway and Foundation G1](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) (`G1 PASS`), keputusan kuota/batas waktu `ADR-S05` dan disposisi opsional `ADR-S07`
- **Next chapter:** [C10 — Alert Intake and Dependency Correlation](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)
- **Related requirements:** `BR-003`, `BR-004`, `BR-007`, `BR-016`, `FR-OBS-002`, `FR-OBS-003`, `FR-OBS-007`, `FR-AGT-002`, `FR-AGT-003`, `FR-AGT-004`, `FR-AGT-007`, `RULE-002`, `RULE-003`, `RULE-006`, `NFR-003`, `NFR-006`, `NFR-016`, `KPI-09`, `OBJ-05`, `DEP-03`, `RISK-12`, `SC-09`
- **Related acceptance tests:** `AT-005` (build & test owner utama; regresi di C18/C21), `MCP-01` & `MCP-02` (build & test owner integrasi adapter ke backend nyata), `EV-02` & `AT-009` (build & test owner sisi *data/source unavailable*), `SEC-03` (build owner sanitasi output tool sebelum konteks model), `AT-008` (test owner pemeriksaan seluruh jalur adapter tidak mengakses *ground truth*), `AT-012` (build owner penanganan *tool backend outage*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *read-only telemetry tool adapters* yang menghubungkan *Authenticated Policy Gateway* ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) ke backend *metrics*, *logs*, *distributed traces*, dan *service catalog* nyata di lab ([C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md)). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), seluruh bukti telemetri yang dikumpulkan investigator wajib berasal dari kueri terparameterisasi yang terikat kontrak—tanpa kueri bebas (seperti PromQL/SQL/shell arbitrer) dan tanpa hak perubahan *state* (`RULE-003`, `BR-007`).

Setelah chapter ini selesai, keempat *tool* wajib (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`; ditambah `get_apm_health` hanya jika diaktifkan oleh `ADR-S07`) beroperasi penuh di belakang gateway, mengembalikan *standard response envelope* berprovenansi (`source_ref`, `observed_at`, `query_window`, `data_quality`, `truncated`, `sanitized`, `error_code`), serta menangani kegagalan atau ketiadaan backend (`SC-09`, `EV-02`) secara eksplisit tanpa mengarang data.

## 3. Scope & Boundaries
### In Scope
- Implementasi adapter *read-only* untuk `get_service_metrics`, `search_error_logs`, `get_trace_summary`, dan `get_service_dependencies` (serta disposisi `get_apm_health` sesuai `ADR-S07`) menggunakan kredensial backend khusus *read-only* (`FR-AGT-002`).
- Penegakan kueri terparameterisasi berbasis *enum* metrik dan *allowlist* atribut; pelarangan penuh atas ekspresi kueri mentah dari pemanggil (`MCP-01`, `AT-005`).
- Penegakan batas `query_window`, `max_points`, `max_hits`, `max_depth`, *per-call deadline*, dan kuota panggilan per insiden sesuai `ADR-S05` (`FR-AGT-004`, `MCP-02`).
- Pembungkusan hasil ke dalam *response envelope* standar [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) yang telah melewati redaktor `SEC-03`, lengkap dengan penanda `truncated`, `data_quality`, dan `source_unavailable` saat backend mati (`FR-OBS-007`, `EV-02`).
- Remediasi dispatcher: respons metrik kosong diteruskan sebagai daftar kosong tanpa membuat titik metrik sintetis; `metric_name` diprioritaskan oleh adapter dengan fallback `metric_enum`.

### Out of Scope
- Fungsi *write*, *restart*, *deploy*, *scale*, atau modifikasi konfigurasi layanan dalam bentuk apa pun (`FR-AGT-003`, `BR-016`).
- Akses baca dari adapter mana pun menuju registri *ground truth* atau pengendali *fault harness* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md), `RULE-002`).
- Logika orkestrasi urutan pemanggilan *tool* (dibangun di [C11](11-DURABLE-INVESTIGATION-WORKFLOW.md)).

## 4. Prerequisites
- Gate G1 pada [C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) berstatus `PASS`.
- Backend *logs*, *RED metrics*, *distributed traces*, dan *service catalog* dari [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md) (`E05`) berjalan stabil.
- Kontrak JSON Schema *input/output* keempat *tool* dari [C02](../phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) serta keputusan kuota/batas waktu `ADR-S05` dan `ADR-S07` telah disahkan.

## 5. Implementation Roadmap
1. **Implementasi Adapter Kueri Terparameterisasi ke Backend Lab (`FR-AGT-002`, `FR-OBS-002`–`003`)**
   - *Apa yang harus dilakukan:* Bangun adapter `get_service_metrics`, `search_error_logs`, `get_trace_summary`, dan `get_service_dependencies` yang menerjemahkan input bertipe (seperti `service_id`, `allowed_metric` enum, `start`/`end`, `error_code`, `trace_id`, `max_depth`) menjadi kueri *read-only* ke backend [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md); jika `get_apm_health` tidak dipilih pada `ADR-S07`, kembalikan status `unsupported_source` yang jujur tanpa memalsukan data.
   - *Mengapa diperlukan:* Mencegah *query injection* dan menjamin pemisahan kontrak logis dari implementasi vendor backend (`RISK-12`).
   - *Expected output:* Kode keempat adapter *read-only* yang terhubung ke backend telemetri lab.
   - *Cara memverifikasi:* Jalankan kueri positif pada data trafik/gangguan lab (`SC-01` s/d `SC-04`) dan pastikan hasil cocok dengan observasi backend [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md).
2. **Integrasi Enforcement Gateway, Kuota, dan Penolakan Batas (`FR-AGT-004`, `MCP-02`)**
   - *Apa yang harus dilakukan:* Daftarkan adapter di belakang *Authenticated Policy Gateway* [C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) sehingga otorisasi `service_id`/`environment`, batas maksimum `query_window`, `max_points`, `max_hits`, `max_depth`, *deadline*, serta *rate/call budget* (`ADR-S05`) diperiksa sebelum adapter memanggil backend.
   - *Mengapa diperlukan:* Memastikan model tidak dapat memperluas cakupan akses atau memicu *denial-of-service* terhadap backend observabilitas melalui argumen *tool* (`MCP-02`, `AT-005`).
   - *Expected output:* Konfigurasi *policy binding* antara gateway dan seluruh adapter.
   - *Cara memverifikasi:* Kirim permintaan dengan rentang waktu melebihi batas maksimum dan jumlah titik berlebih; pastikan gateway menolak permintaan dengan `WINDOW_EXCEEDED` / `LIMIT_EXCEEDED` dan backend mencatat 0 kueri masuk.
3. **Standardisasi Response Envelope, Provenance, dan Sanitasi Output (`SEC-03`, `FR-OBS-007`)**
   - *Apa yang harus dilakukan:* Bungkus setiap respons adapter dengan metadata `tool_name`, `source_ref`, `observed_at`, `query_window`, `data_quality` (`complete`/`partial`/`unavailable`), `truncated`, `sanitized`, dan `error_code`, serta lewatkan seluruh *records* (terutama pesan log dan atribut span) ke *sanitizer* `SEC-03` sebelum dikembalikan.
   - *Mengapa diperlukan:* Memberikan jejak provenansi bagi validator bukti ([C14](../phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)) dan mencegah kebocoran *synthetic PII/secrets* dari log aplikasi ke prompt model (`NFR-003`).
   - *Expected output:* Formatter *response envelope* berprovenansi dan terintegrasi redaktor `SEC-03`.
   - *Cara memverifikasi:* Injeksi log yang memuat *synthetic secret/PII* dan jumlah baris melebihi `max_hits`; pastikan output bertanda `sanitized: true`, `truncated: true`, dan 0 *secret* mentah tampil di respons.
4. **Penanganan Outage Backend dan Missing Telemetry Source (`EV-02`, `AT-012`)**
   - *Apa yang harus dilakukan:* Implementasikan *timeout*, *circuit breaker*, dan pemetaan error eksplisit ketika backend *logs*, *metrics*, atau *traces* lambat atau mati (`SC-09`), sehingga adapter mengembalikan `data_quality: "unavailable"` dan `error_code: "SOURCE_UNAVAILABLE"` tanpa merangkai angka nol atau *trace* imajiner.
   - *Mengapa diperlukan:* Menjamin kegagalan aman (*safe failure*, `NFR-006`, `NFR-016`) dan memenuhi kontrak `EV-02`.
   - *Expected output:* Penanganan *graceful error* pada seluruh adapter beserta pencatatan *audit event*.
   - *Cara memverifikasi:* Matikan backend *tracing* (`SC-09`) lalu panggil `get_trace_summary`; pastikan respons mengembalikan `SOURCE_UNAVAILABLE` secara deterministik dalam batas *timeout*.
5. **Verifikasi Positif, Negatif, dan Isolasi Ground Truth (`AT-005`, `AT-008`, `MCP-01`)**
   - *Apa yang harus dilakukan:* Jalankan suite pengujian langsung terhadap adapter untuk kueri positif, percobaan aksi *write/restart/deploy* (`MCP-01`), pelanggaran batas jendela waktu (`MCP-02`), pelanggaran scope layanan, percobaan kueri ke *ground truth* (`AT-008`), serta simulasi *backend outage*, lalu simpan bukti ke `E09`.
   - *Mengapa diperlukan:* Menyelesaikan pembuktian `AT-005` dan memverifikasi kesiapan *tool layer* sebelum dihubungkan ke *workflow* di [C11](11-DURABLE-INVESTIGATION-WORKFLOW.md).
   - *Expected output:* Paket bukti `E09` (`tool-request-response-sanitized`, `authorization-denials`, `limit-and-timeout-results`, `source-outage-audit`).
   - *Cara memverifikasi:* Audit log backend dan *security audit* gateway untuk memastikan 0 perubahan *state* (`KPI-09` = 0) dan 0 akses ke *ground truth* (`KPI-10` = 0).

## 6. Expected Deliverables
- Implementasi 4 adapter telemetri *read-only* (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`; plus disposisi `get_apm_health`) yang terhubung ke backend lab [C05](../phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md).
- Integrasi penuh validasi skema, batas kuota/waktu (`ADR-S05`), kredensial *read-only* terpisah, dan sanitasi output `SEC-03`.
- Penanganan eksplisit `SOURCE_UNAVAILABLE` dan *timeout* tanpa fabrikasi data (`EV-02`).
- Paket bukti tersanitasi `E09` pada `evidence/<run_id>/C09/`: `tool-request-response-sanitized`, `authorization-denials`, `limit-and-timeout-results`, dan `source-outage-audit`.

## 7. Validation & Exit Criteria
- `AT-005`, `MCP-01`, & `MCP-02`: Seluruh permintaan *tool* yang dilarang (*write/restart/deploy/shell/SQL*), melanggar scope layanan/environment, atau melampaui batas `query_window`/`max_points`/`max_hits` ditolak sebelum eksekusi backend dan tidak mengubah *state* layanan (`KPI-09` = 0).
- `EV-02` & `AT-012` (sisi adapter data): Saat backend *tracing* atau telemetri dimatikan (`SC-09`), adapter mengembalikan envelope `SOURCE_UNAVAILABLE` secara jujur beserta rekaman audit tanpa mengarang *span* atau metrik nol.
- `SEC-03` (tahap *pre-model*): Seluruh *synthetic PII/secret fixtures* di dalam log/span tersamarkan sebelum keluar dari adapter.
- `AT-008` (jalur *tool*): Tidak ada satu pun adapter atau argumen kueri yang dapat membaca *ground truth registry* ([C04](../phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md)).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Kueri log atau trace pada jendela waktu yang padat menghasilkan *payload* terlalu besar bagi konteks model; mitigasi dengan menegakkan batas keras `max_hits`/`max_points` dan menyertakan flag `truncated: true`.
- **Open Decisions:** Disposisi opsional `get_apm_health` (`ADR-S07`) dan angka batas kuota/timeout (`ADR-S05`) mengikuti keputusan yang telah dikunci pada Gate G1 ([C08](../phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- **Handover ke [C10](10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md) dan [C11](11-DURABLE-INVESTIGATION-WORKFLOW.md):** Endpoint *tool* observasi *read-only* yang siap dipanggil oleh *workflow orchestrator*, kontrak *error/unavailable envelope* untuk validator bukti ([C14](../phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)), serta paket bukti `E09`.

