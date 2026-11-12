# C05 — Telemetry and Service Catalog

## 1. Chapter Information
- **Phase:** F1 — Foundation
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), [C03 — Lab Services and Synthetic Traffic](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md), [C04 — Fault Harness and Ground Truth Isolation](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md), penutupan `ADR-S02` (pilihan backend koleksi *logs/metrics/traces* & transport alert)
- **Next chapter:** [C06 — Synthetic Knowledge and Ingestion](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md)
- **Related requirements:** `BR-001`, `BR-003`, `BR-013`, `FR-SIM-001`, `FR-SIM-002`, `FR-OBS-001`, `FR-OBS-002`, `FR-OBS-003`, `FR-OBS-004` (sumber sinyal alert), `FR-OBS-006`, `FR-OBS-007`, `RULE-006`, `NFR-004`, `NFR-016`, `DEP-03`, `RISK-07`, `SC-01` s/d `SC-07`, `SC-09`, `UC-01`, `UC-02`, `UC-03`, `UC-07`
- **Related acceptance tests:** `AT-001` (build & test owner penyelesaian *stack + trace visibility*; diulang di C22), `AT-003` (build owner bagian korelasi sinyal *logs/metrics/traces* dan pemicu alert; penyelesaian `incident_id` terpusat di C10), `EV-02` & `AT-009` (build owner simulasi sumber trace hilang), `AT-016` (build owner observabilitas *dependency cascade*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun *pipeline* observabilitas yang mengumpulkan *structured logs*, metrik RED (*Rate, Errors, Duration*), dan *distributed traces* yang kompatibel dengan OpenTelemetry dari 5 layanan simulasi, menyusun *service catalog* beserta *observed dependency graph*, serta menyediakan sumber sinyal *alert* yang nyata. Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), seluruh bukti yang kelak dibaca oleh agent investigator harus berasal dari backend telemetri aktual di lab, bukan fixture teks yang dikarang model (`BR-003`).

Setelah chapter ini selesai, sinyal telemetri dari kondisi sehat (`SC-01`) maupun gangguan (`SC-02` s/d `SC-07`) dapat dikueri secara terikat waktu dan layanan, jejak satu permintaan terbukti melintasi $\ge 2$ ketergantungan layanan (`AT-001`), ketergantungan hulu-hilir tercatat beserta *timestamp* kesegarannya (`FR-OBS-006`), dan kehilangan backend *tracing* (`SC-09`) dapat disimulasikan secara *reversible* dengan menghasilkan penanda eksplisit tanpa rekayasa nilai nol palsu (`RULE-006`).

## 3. Scope & Boundaries
### In Scope
- Deployment dan konfigurasi kolektor OpenTelemetry serta backend ringan untuk *structured logs*, metrik RED, dan *distributed traces* di dalam batas memori Docker Compose 8 GiB RAM (`TBD-03`, `ADR-S02`).
- Validasi konsistensi atribut `timestamp` (ISO 8601 UTC internal), `service.name`, `environment`, `service.version`, `severity`, `event_type`, `trace_id`, dan `correlation_id` lintas ketiga sinyal (`FR-SIM-002`, `FR-OBS-001`–`003`).
- Pembentukan *Service Catalog* dan *observed dependency snapshot* yang memuat *edge* hulu-hilir, `observed_at`, `freshness`, serta `confidence` (`FR-OBS-006`).
- Pembuatan aturan pemicu *alert* (*threshold* atau *controlled trigger*) yang menghasilkan *alert envelope* sesuai skema [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) (`FR-OBS-004`).
- Mekanisme penonaktifan dan pemulihan sumber *distributed tracing* (`SC-09`) untuk menguji perilaku *missing telemetry source* (`FR-OBS-007`, `EV-02`).

### Out of Scope
- Adapter *tool* MCP read-only untuk agent (dibangun di [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).
- Layanan *alert intake*, *deduplication*, dan pembuatan `incident_id` terpusat (dibangun di [C10](../phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md); jangan mengklaim `AT-003` telah lulus penuh pada C05).
- Dashboard AI observability / Langfuse (dibangun di [C15](../phase-3-reasoning-observability/15-AI-OBSERVABILITY-AUDIT-AND-COST.md)).

## 4. Prerequisites
- Layanan simulasi [C03](03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md) dan *fault harness* [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md) telah berjalan stabil.
- Skema envelope telemetri, *service catalog*, *dependency edge*, dan *alert payload* dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) telah didefinisikan.
- Keputusan `ADR-S02` mengenai pemilihan backend *logs*, *metrics*, dan *traces* yang muat dalam anggaran 8 GiB RAM telah disahkan; jika belum, berstatus `TBD — Decision Required`.

## 5. Implementation Roadmap
1. **Deployment Kolektor dan Backend Logs, RED Metrics, serta Traces (`FR-OBS-001`–`003`)**
   - *Apa yang harus dilakukan:* Tambahkan kolektor dan backend telemetri terpilih (`ADR-S02`) ke manifes Docker Compose dengan batas memori eksplisit, lalu arahkan *output* log, metrik RED, dan OTel trace dari 5 layanan simulasi ke kolektor tersebut.
   - *Mengapa diperlukan:* Menyediakan sumber observasi terpusat yang dapat dikueri secara deterministik tanpa melampaui kapasitas host lab (`RISK-07`).
   - *Expected output:* Layanan kolektor dan backend telemetri aktif dengan retensi lokal terukur.
   - *Cara memverifikasi:* Jalankan trafik sehat (`SC-01`) dan pastikan log, metrik RED (*request rate*, *error rate*, *latency*), serta *span trace* dari kelima layanan masuk ke backend.
2. **Verifikasi Korelasi Lintas Sinyal dan Normalisasi Waktu (`BRD §13.3`)**
   - *Apa yang harus dilakukan:* Terapkan pemeriksaan kualitas data otomatis untuk memastikan seluruh sinyal memakai format waktu ISO 8601 UTC (`D-C02-02`), memiliki `trace_id`/`correlation_id` yang dibuat aplikasi, serta membedakan kondisi *data missing* dari angka `0`.
   - *Mengapa diperlukan:* Mencegah kegagalan korelasi temporal saat validator bukti memeriksa klaim di Fase 3 (`DEP-03`).
   - *Expected output:* Skrip pemeriksa kualitas skema telemetri dan sampel rekaman terkorelasi.
   - *Cara memverifikasi:* Kueri satu `trace_id` dari transaksi gagal (`SC-02`) dan buktikan *log error*, kenaikan metrik 5xx, dan *trace span* mengacu pada layanan serta jendela waktu yang sama.
3. **Pembangunan Service Catalog dan Observed Dependency Snapshot (`FR-OBS-006`)**
   - *Apa yang harus dilakukan:* Buat registri *service catalog* (`service_id`, `owner_label`, `environment`, `version`, `dependencies`) yang diperbarui dengan *observed dependency edges* dari *trace/telemetry*, lengkap dengan atribut `source`, `observed_at`, dan penanda *stale edge*.
   - *Mengapa diperlukan:* Menjadi acuan otorisasi *service scope* pada KB ([C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md)) dan gateway ([C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)), serta mendukung pelacakan dampak hulu-hilir (`BR-013`, `AT-016`).
   - *Expected output:* Berkas/endpoint *catalog snapshot* dan graf ketergantungan teramati.
   - *Cara memverifikasi:* Injeksi latensi DB (`SC-03`) atau kegagalan layanan (`SC-04`) dan periksa bahwa graf membedakan *origin dependency* (`db-dummy`) dari layanan terdampak di hulu (`transaction-service`, `api-gateway`).
4. **Konfigurasi Sumber Alert dan Envelope Generator (`FR-OBS-004`)**
   - *Apa yang harus dilakukan:* Konfigurasikan aturan deteksi ambang metrik/log atau pemicu terkontrol yang menghasilkan *alert payload* bertanda waktu sesuai kontrak [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) ketika gangguan diinjeksi.
   - *Mengapa diperlukan:* Menyediakan pemicu insiden yang realistis dari sinyal telemetri untuk diumpankan ke layanan *Alert Intake* pada [C10](../phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md).
   - *Expected output:* Konfigurasi *alert rules* dan contoh *alert fixtures* nyata dari eksekusi skenario lab.
   - *Cara memverifikasi:* Picu `SC-02` dan `SC-03`, lalu pastikan *alert envelope* terbentuk dengan `service.name`, `severity`, dan jendela waktu yang akurat; pastikan `SC-01` (sehat) tidak menghasilkan alert kritis.
5. **Pengujian Skenario Missing Trace Source (`SC-09`) dan Pengumpulan Bukti `E05`**
   - *Apa yang harus dilakukan:* Jalankan pengujian berurutan untuk `SC-01` (sehat), `SC-02` (5xx), `SC-03` (latensi), `SC-04` (cascade), serta `SC-09` (matikan sementara backend trace secara *reversible*), lalu ekspor hasil kueri ke `E05`.
   - *Mengapa diperlukan:* Menyelesaikan pembuktian `AT-001` dan menyediakan bukti dasar `EV-02`/`AT-009` bahwa hilangnya sumber trace terdeteksi sebagai `source_unavailable`, bukan nol error.
   - *Expected output:* Paket bukti `E05` (`logs-sample`, `metrics-window`, `trace-summary`, `catalog-snapshot`, `missing-source-record`).
   - *Cara memverifikasi:* Pastikan saat backend trace dimatikan (`SC-09`), kueri mengembalikan status *unavailable* eksplisit dan setelah diaktifkan kembali, koleksi trace pulih normal.

## 6. Expected Deliverables
- Konfigurasi kolektor OpenTelemetry dan backend *logs*, *metrics*, serta *traces* yang berjalan di Docker Compose lokal.
- *Service catalog* dan *observed dependency snapshot* untuk 5 layanan simulasi.
- Aturan pembangkit *alert* beserta sampel *alert envelope* nyata dari skenario gangguan.
- Paket bukti tersanitasi `E05` pada `evidence/<run_id>/C05/`: `logs-sample`, `metrics-window`, `trace-summary`, `catalog-snapshot`, dan `missing-source-record`.

## 7. Validation & Exit Criteria
- `AT-001` (selesai pada tingkat komponen fondasi; diulang di C22): Tumpukan layanan bersih menyala, rantai permintaan melewati $\ge 2$ ketergantungan, serta topologi layanan dan *distributed traces* terlihat utuh di backend.
- `AT-003` (bagian sinyal; penyelesaian `incident_id` di [C10](../phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md)): Gangguan dari *fault harness* menghasilkan *structured log*, kenaikan metrik RED, *trace span*, dan sinyal *alert* yang saling berkorelasi.
- `EV-02` / `SC-09` (bagian sumber data): Penonaktifan backend trace tercatat sebagai `source_unavailable` tanpa menghasilkan span/metrik palsu.
- Total penggunaan memori kontainer layanan + backend observabilitas tetap berada di dalam anggaran 8 GiB RAM (`TBD-03`).

## 8. Risks, Open Decisions & Handover
- **Risiko:** Backend observabilitas mengonsumsi RAM berlebih atau *disk I/O* tinggi saat menerima *burst* log (`RISK-07`); mitigasi dengan membatasi retensi lokal dan memilih komponen ringan sesuai `ADR-S02`.
- **Open Decisions:** `ADR-S02` (pilihan spesifik backend *logs/metrics/traces* dan mekanisme *alert transport*) wajib dikunci sebelum implementasi C05 dimulai.
- **Handover ke [C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md), [C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md), [C09](../phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md), dan [C10](../phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md):** *Service catalog* resmi (untuk validasi metadata KB dan ACL gateway), *endpoint* kueri backend telemetri (untuk adapter read-only C09), sumber *alert* (untuk intake C10), serta paket bukti `E05`.

