# ADR-DC02: Konvensi Kontrak Kanonik, Semantik Waktu/Error/Versi, dan Kualifikasi JSON Schema Draft 2020-12 (`D-C02-01` s.d. `D-C02-06`)

- **ID Keputusan:** `ADR-DC02` (Mencakup `D-C02-01`, `D-C02-02`, `D-C02-03`, `D-C02-04`, `D-C02-05`, `D-C02-06`)
- **Status:** `ACCEPTED` (Dibekukan untuk Baseline Kontrak `v1`)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** Seluruh Chapter `C02`–`C21`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/contract-conventions.md`, `evidence/c02-20261109T070500Z/C02/schema-manifest.csv`, `evidence/c02-20261109T070500Z/C02/validation-runner.log`

---

## 1. Konteks & Permasalahan

Dokumen sumber (Proposal v2.0 vs BRD v1.0) memiliki beberapa perbedaan nama atribut (mis. `metric_enum` vs `allowed_metric`, `document_id` vs `doc_id`, serta contoh label status `VERIFIED`). Agar produsen dan konsumen di C03–C21 tidak mengalami *contract drift*, konvensi penamaan, waktu, satuan, kode error, dan dialek validator harus dibekukan sebelum implementasi dimulai.

---

## 2. Enam Keputusan Kontrak Kanonik yang Disahkan

1. **`D-C02-01` (Penamaan Kanonik & Strategi Versi):**
   - Setiap skema memiliki `$id` unik `urn:sre-sim:contract:<logical-name>:1` dan `additionalProperties: false` pada seluruh input yang terlihat oleh model.
   - Nama kanonik metrik adalah `metric_enum` (`request_rate`, `error_rate`, `latency_p95`).
   - Metadata KB mempertahankan `document_id` dan `document_version`, dengan pemetaan eksplisit 1-ke-1 ke `doc_id` dan `version` pada `dossier.v1.sop_citations[]`.
2. **`D-C02-02` (Waktu, Jendela Kueri, dan Satuan):**
   - Seluruh timestamp kontrak wajib menggunakan RFC 3339 UTC dengan sufiks `Z` (`pattern: "Z$"`).
   - Jendela kueri menggunakan interval setengah terbuka `[start, end)` dengan validasi semantik `start < end`.
   - Satuan kanonik RED: `requests/s`, `ratio` (`[0.0, 1.0]`), dan `ms`. Data yang hilang/tidak tersedia dilarang direpresentasikan sebagai angka `0`.
3. **`D-C02-03` (Kode Error, Status Hipotesis, dan Integritas Revisi Review):**
   - Menggunakan 19 kode alasan/error kanonik (`UNAUTHENTICATED`, `FORBIDDEN_SCOPE`, `TOOL_NOT_ALLOWED`, `SCHEMA_INVALID`, `WINDOW_EXCEEDED`, `LIMIT_EXCEEDED`, `INVALID_TIME_RANGE`, `BUDGET_EXHAUSTED`, `DEADLINE_EXCEEDED`, `CANCELLED`, `SOURCE_UNAVAILABLE`, `BACKEND_TIMEOUT`, `REDACTION_FAILED`, `NO_APPLICABLE_RUNBOOK`, `RETRIEVAL_UNAVAILABLE`, `VERSION_CONFLICT`, `UNSUPPORTED_SCHEMA`, `SERVICE_UNMAPPED`, `PREMATURE_EVALUATION_BLOCKED`).
   - Status dukungan hipotesis dibatasi pada `SUPPORTED`, `PARTIAL`, dan `INCONCLUSIVE` (nilai `VERIFIED` dilarang tanpa persetujuan SME).
   - `review-event.v1` wajib mengikat `target_dossier_version` dan `target_dossier_hash`.
4. **`D-C02-04` (Applicability Knowledge Base & Version Fencing):**
   - Hanya dokumen dengan `status == "approved"` dan `effective_from <= reference_time < effective_to` (`effective_to: null` = open-ended validity) untuk `service_id` dan `environment` yang cocok yang boleh dikembalikan oleh cabang pencarian dense, sparse, maupun reranker.
   - `source_uri` wajib berpola `^kb://[A-Za-z0-9._/-]+$`.
5. **`D-C02-05` (Pemisahan Manifest Evaluasi & Aturan Denominator):**
   - `runtime-manifest.v1` dilarang memuat label skenario atau nama split holdout; `evaluation-manifest.v1` mewajibkan `required_terminal_state: "CLOSED"`.
6. **`D-C02-06` (Dialek Skema & Kualifikasi Offline):**
   - Menggunakan **JSON Schema Draft 2020-12** (`https://json-schema.org/draft/2020-12/schema`) yang divalidasi secara offline menggunakan Python `jsonschema.Draft202012Validator` (`FORMAT_CHECKER` aktif) dan `referencing.Registry` dengan pelarangan pengambilan `$ref` eksternal.

