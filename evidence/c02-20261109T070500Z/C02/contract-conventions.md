# Canonical Contract Conventions, Time Semantics, Versioning, and Schema Registry — Chapter C02

- **Run ID:** `c02-20261109T070500Z`
- **Decision References:** `D-C02-01`, `D-C02-02`, `D-C02-03`, `D-C02-04`, `D-C02-05`, `D-C02-06` (`ACCEPTED` di [`ADR-DC02`](../../../docs/decisions/ADR-DC02-contract-conventions-and-qualification.md))
- **Timestamp (UTC):** `2026-11-09T07:15:00Z` (`2026-11-09T14:15:00+07:00` WIB)
- **Author / Approver (`owner_ref`):** `project-initiator-michael`
- **Check ID:** `C02-CON-004` (`PASS`)

---

## 1. Tujuan & Aturan Kompatibilitas Kontrak

Dokumen ini membekukan kamus kanonis untuk seluruh produsen dan konsumen data pada ekosistem **AI Agentic SRE & Hybrid RAG Investigation Engine**. Setiap antarmuka lintas komponen wajib mematuhi konvensi nama field, satuan, format waktu, dan versi di bawah ini agar tidak terjadi kegagalan korelasi diam-diam (*silent correlation drift*).

---

## 2. Konvensi Identitas, Penamaan Kanonis, & Harmonisasi Sumber (`D-C02-01`)

| Konsep | Nama Field Kanonis | Tipe & Format | Aturan Harmonisasi & Pemetaan Producer $\rightarrow$ Consumer |
|---|---|---|---|
| **Service Identity** | `service_id` (Katalog/API/Tools/Dossier) & `service.name` (Atribut OTel/Log/Chunk KB) | `string`, enum 5 layanan yang disahkan G0: `api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy` (ditambah `svc-a`, `svc-b`, `svc-c` khusus fixture uji kontrak `TEST-ONLY`) | `service_id` dan `service.name` memiliki pemetaan **1:1 identik** di dalam satu `environment`. Jika sebuah alert/log membawa nama layanan yang tidak ada di `Service Catalog`, status wajib menjadi `SERVICE_UNMAPPED` dan diarahkan ke *manual triage* (**dilarang** melakukan broad query lintas seluruh layanan). |
| **Environment** | `environment` | `string` (`lab` untuk eksekusi simulasi; `prod-sim` / `staging-sim` untuk uji isolasi negatif `RAG-02`/`SEC-01`) | Wajib hadir secara eksplisit pada setiap log, metrik, span, alert, kueri tool, chunk KB, dan dossier. Tidak ada nilai default implisit. |
| **Metric Input Name** | `metric_enum` | `string`, enum: `request_rate`, `error_rate`, `latency_p95` | Menyelesaikan perbedaan penamaan antara Proposal (`metric_enum`) dan BRD (`allowed_metric`): kawat protokol (*wire contract*) menggunakan **`metric_enum`**. Alias bebas tidak diizinkan agar LLM tidak dapat menyuntikkan ekspresi PromQL. |
| **Document Identity** | `document_id` & `document_version` | `string` (mis. `SOP-TX-001` dan `2.0`) | Digunakan secara seragam pada `knowledge-chunk.v1.schema.json`, `retrieval-result.v1.schema.json`, dan bagian `sop_citations` di `dossier.v1.schema.json` (menggantikan singkatan `doc_id` agar tidak terjadi ketidakcocokan nama field). |
| **Correlation & Trace IDs** | `incident_id`, `correlation_id`, `trace_id`, `span_id` | `trace_id`: 32 karakter hex huruf kecil non-zero (`^[0-9a-f]{32}$`, bukan semua `0`); `span_id`: 16 karakter hex (`^[0-9a-f]{16}$`); `incident_id` & `correlation_id`: string opak (`^[a-zA-Z0-9._:-]{4,128}$`) | `trace_id`, `span_id`, dan `correlation_id` **wajib dibangkitkan oleh aplikasi/OTel**, sedangkan `incident_id` **dibangkitkan oleh Alert Intake (`C10`)**. LLM **dilarang keras** mengarang ID observasi, dan ID **dilarang** memuat label skenario/holdout (seperti `db-timeout-holdout-01`). |
| **Closed Object Inputs** | `additionalProperties: false` | Properti JSON Schema | Seluruh objek request yang dapat dipengaruhi oleh output LLM menerapkan `additionalProperties: false` sehingga percobaan menyisipkan field hak akses (`allowed_groups`, `role`, `raw_query`) langsung ditolak pada validasi skema (`SCHEMA_INVALID`). |

---

## 3. Semantik Waktu, Jendela Kueri, & Satuan Metrik (`D-C02-02`)

1. **Format Timestamp Kanonis (`RFC 3339 UTC Z`):**
   - Seluruh field waktu di dalam JSON wajib menggunakan format **ISO 8601 / RFC 3339 dalam zona waktu UTC dengan akhiran huruf `Z`** (pola regex: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$`).
   - Timestamp tanpa zona waktu (mis. `2026-11-09T09:00:00`) atau tanggal kalender tidak valid (mis. bulan `13`) **ditolak** pada validasi skema (`FORMAT_CHECKER` + `pattern`).
   - Adapter intake boleh menormalisasi timestamp ber-offset valid (mis. `+07:00`) ke UTC `Z` hanya setelah tanda tangan sumber diverifikasi, dengan menyimpan offset sumber pada log intake jika relevan.
2. **Pemisahan Empat Jenis Timestamp:**
   - `timestamp` / `event_time` / `sample_at`: Waktu terjadinya peristiwa atau pengukuran pada layanan simulasi.
   - `alert_received_at`: Waktu saat `Alert Intake` menerima dan memvalidasi sinyal alert (titik mulai perhitungan `KPI-07` *Time-to-Investigation*).
   - `observed_at`: Waktu saat `MCP Policy Gateway` atau `Retrieval Service` membungkus hasil kueri ke dalam envelope (`tool-result` / `retrieval-result`).
   - `dossier_ready_at` & `reviewed_at`: Waktu saat revisi dossier selesai dirakit (titik akhir `KPI-07`) dan waktu saat reviewer manusia mengambil keputusan.
3. **Semantik Jendela Kueri (`Half-Open Interval [start, end)`):**
   - Seluruh rentang waktu kueri (`start`, `end` atau `window_start`, `window_end`) didefinisikan sebagai interval setengah terbuka **`[start, end)`** ($\text{start} \le t < \text{end}$).
   - Aturan validasi semantik wajib di Gateway: `start < end` (jika `start >= end`, tolak dengan `INVALID_TIME_RANGE`) dan `(end - start) <= policy.max_window_seconds` (jika melampaui batas, **tolak tegas dengan `WINDOW_EXCEEDED`** sesuai `MCP-02`; dilarang melakukan *silent clamping*).
4. **Satuan Kanonis RED Metrics:**
   - `request_rate`: **`requests/s`** (permintaan per detik, float $\ge 0.0$).
   - `error_rate`: **`ratio`** (proporsi error terhadap total request pada jendela agregasi, float dalam rentang `[0.0 .. 1.0]`; mis. `0.25` berarti 25% error — dilarang mencampuradukkan rasio `0.25` dengan `25%` atau jumlah error mentah).
   - `latency_p95`: **`ms`** (persentil ke-95 durasi respons dalam milidetik, float $\ge 0.0$; nilai detik dari histogram Prometheus wajib dikonversi ke `ms` oleh adapter dengan menyertakan `"unit": "ms"`).
   - **Agregasi Lintas-Layanan:** Persentil (`latency_p95`) **dilarang** dijumlahkan atau dirata-rata secara aritmatika sederhana lintas layanan.

---

## 4. Semantik Data Hilang (`Missing ≠ Zero`) & Provenance (`D-C02-03`)

1. **Perbedaan `ok` (Empty), `partial`, `unavailable`, dan `rejected`:**
   - `status = "ok"` dengan `records = []`: Sumber telemetri sehat dan berhasil dikueri, tetapi memang tidak ada baris log error pada jendela tersebut (*available-empty*).
   - `status = "partial"` (`truncated = true` atau `data_quality = "partial"`): Sebagian data berhasil diambil tetapi terpotong oleh batas `max_hits`/`max_points` atau hanya sebagian sub-sumber yang merespons.
   - `status = "unavailable"` (`data_quality = "unavailable"`, `error_code = "SOURCE_UNAVAILABLE"` atau `"BACKEND_TIMEOUT"`, `records = []`, `source_ref = null`): Backend penyimpanan (mis. Tempo pada `SC-09` / `EV-02`) mati atau tidak terjangkau. **Nilai metrik tidak boleh diisi `0` dan span trace tidak boleh dikarang.**
   - `status = "rejected"`: Permintaan ditolak oleh Policy Gateway sebelum menyentuh backend (`FORBIDDEN_SCOPE`, `WINDOW_EXCEEDED`, `LIMIT_EXCEEDED`, `SCHEMA_INVALID`, `TOOL_NOT_ALLOWED`).
2. **Provenance Wajib:**
   - Setiap item bukti di dalam dossier wajib dapat ditelusuri ke `evidence_id` yang memuat `source_ref` (referensi kueri terdaftar, bukan URL bebas), `observed_at`, `query_window`, `data_quality`, dan `sanitized: true`.

---

## 5. Tata Kelola Versi Terpisah & Kebijakan Breaking Change (`D-C02-01`, `D-C02-06`)

Sistem memelihara **8 pengidentifikasi versi yang berbeda** dan tidak boleh saling dipertukarkan:
1. `schema_version`: Versi skema kontrak JSON (saat ini `"1.0"` untuk seluruh `*.v1.schema.json`).
2. `workflow_version`: Versi definisi state machine / graf orkestrasi.
3. `policy_version`: Versi aturan kuota, batas window, dan allowlist gateway.
4. `model_version` & `prompt_version`: Identitas model LLM (`provider:model_tag`) dan template prompt yang digunakan.
5. `document_version`: Versi dokumen SOP/runbook individual (mis. `"1.0"` obsolete vs `"2.0"` approved).
6. `index_version`: Versi snapshot/alias indeks koleksi Qdrant yang memagari konsistensi pembacaan (*version fence*).
7. `dossier_version` & `dossier_hash`: Nomor revisi sekuensial (`1`, `2`, ...) dan checksum SHA-256 atas kanonis JSON dossier yang menjadi target pengesahan reviewer manusia (`HUM-01`).
8. `rubric_version` & `split_version`: Versi protokol penilaian dan pembekuan split evaluasi (`DEV`/`H-G3`/`H-G4`).

**Kebijakan Perubahan Skema (*Breaking-Change Policy*):**
- Konsumen wajib memeriksa `schema_version` saat startup/penerimaan pesan dan menolak versi mayor yang tidak dikenal dengan `UNSUPPORTED_SCHEMA` (**dilarang** melakukan *silent fallback* ke skema lama).
- Setiap perubahan pada field wajib, tipe data, atau nilai enum di `contracts/*.schema.json` mengharuskan pembaruan `schema-manifest.csv`, eksekusi ulang runner kualifikasi `C02 §8.2`, dan pembangkitan ulang `contracts-final.sha256`.

---

## 6. Penelusuran End-to-End Satu Insiden Lintas Kontrak (`C02-CON-004 Traceability Proof`)

Tabel berikut membuktikan bahwa satu insiden dapat ditelusuri dari produsen hingga evaluator tanpa ambiguitas penamaan atau ID buatan model:

| Tahap Alur | Kontrak Skema | Field Kunci yang Diteruskan | Produsen $\rightarrow$ Konsumen | Jaminan Invariant |
|---|---|---|---|---|
| **1. Request & Log/Span** | `telemetry-log.v1.schema.json`, `telemetry-metric.v1.schema.json` | `service.name="transaction-service"`, `service_id="transaction-service"`, `environment="lab"`, `trace_id="4bf92f3577b34da6a3ce929d0e0e4736"`, `correlation_id="corr-tx-9001"`, `timestamp="2026-11-09T09:01:12Z"` | `transaction-service` $\rightarrow$ `Loki` / `Prometheus` / `Tempo` | ID dibuat oleh aplikasi; tidak mengandung `scenario_id` |
| **2. Alert Intake** | `alert-event.v1.schema.json` | `alert_id="alt-20261109-001"`, `service_id="transaction-service"`, `environment="lab"`, `event_time="2026-11-09T09:01:15Z"`, `window_start="2026-11-09T09:00:00Z"`, `window_end="2026-11-09T09:05:00Z"`, `trace_id="4bf92f3577b34da6a3ce929d0e0e4736"` | `Alert Source` $\rightarrow$ `Alert Intake` | Diverifikasi terhadap `service-catalog.v1.schema.json`; menghasilkan `incident_id="inc-20261109-0001"` |
| **3. Bounded Tool Call** | `metrics-request.v1.schema.json` $\rightarrow$ `tool-result.v1.schema.json` | `service_id="transaction-service"`, `environment="lab"`, `metric_enum="error_rate"`, `start="2026-11-09T09:00:00Z"`, `end="2026-11-09T09:05:00Z"` $\rightarrow$ `source_ref="prom:qry:8812"`, `observed_at="2026-11-09T09:05:03Z"`, `sanitized=true` | `Coordinator` $\rightarrow$ `MCP Policy Gateway` $\rightarrow$ `Coordinator` | Scope diikat oleh server; hasil memiliki `source_ref` & satuan `ratio` |
| **4. Authorized Retrieval** | `retrieval-request.v1.schema.json` $\rightarrow$ `retrieval-result.v1.schema.json` | `service_id="transaction-service"`, `environment="lab"`, `incident_reference_time="2026-11-09T09:01:15Z"`, `index_version="idx-v1-20261109"` $\rightarrow$ `document_id="SOP-TX-001"`, `document_version="2.0"`, `source_uri="kb://sop/transaction-service/SOP-TX-001-v2.md#retry-policy"` | `Coordinator` $\rightarrow$ `Retrieval Service` $\rightarrow$ `Coordinator` | Hanya dokumen `approved` & efektif pada waktu insiden yang dikembalikan |
| **5. Dossier & Human Review** | `dossier.v1.schema.json` $\rightarrow$ `review-event.v1.schema.json` | `incident_id="inc-20261109-0001"`, `dossier_version=1`, `dossier_hash="sha256:..."`, `supporting_evidence_ids=["ev-001"]`, `status="SUPPORTED"` $\rightarrow$ `target_dossier_version=1`, `target_dossier_hash="sha256:..."`, `decision="approve"` | `Validator/Dossier Gen` $\rightarrow$ `Human Reviewer` $\rightarrow$ `Audit Store` | Review mengikat revisi & hash eksak; transisi ke `CLOSED` |
| **6. Offline Evaluation** | `evaluation-manifest.v1.schema.json` $\rightarrow$ `evaluation-result.v1.schema.json` | `incident_id="inc-20261109-0001"`, `incident_terminal_status="CLOSED"`, `closed_dossier_hash="sha256:..."` di-join dengan `scenario_id="SC-02"` di `RESTRICTED_EVAL_ROOT` | `Closed Dossier` + `Restricted GT` $\rightarrow$ `Offline Evaluator` | Join hanya diizinkan karena `incident_terminal_status == "CLOSED"` |

