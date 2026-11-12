# C02 Step 08 — Kontrak State Machine Workflow, Dossier, Human Review, dan Security Audit

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/workflow-contract.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 08 & §7.6)  
> **Status:** `SPECIFIED` (Kontrak kandidat yang dibekukan melalui `D-C02-01`..`06`; batas angka retry/timeout runtime tetap `ADR-S05`)

---

## 1. Tujuan & Pemisahan Tanggung Jawab Control Plane

Kontrak ini mengikat siklus hidup investigasi insiden dari penerimaan alert hingga penutupan dossier dan handoff ke evaluator offline:
1. **Deterministik Control Plane (`FR-ORCH-001`):** Transisi state, kuota tool, batas waktu (deadline), idempotency key, dan fallback dikendalikan oleh kode koordinator (`CMP-INV-03`), **bukan** oleh keputusan bebas model LLM.
2. **Validasi Bukti & Ketidakpastian Eksplisit (`RULE-04`, `EV-01`, `EV-02`):** Setiap klaim/hipotesis harus merujuk pada `evidence_id` yang nyata di bagian `evidence[]` dalam rentang waktu yang valid. Status dukungan menggunakan enum kanonik `SUPPORTED`, `PARTIAL`, atau `INCONCLUSIVE`. Nilai `VERIFIED` dilarang tanpa mekanisme persetujuan SME independen (`D-C02-03`).
3. **Human Review Terikat Versi & Hash (`FR-GOV-001`, `HUM-01`):** Keputusan reviewer manusia (`approve`, `reject`, `edit`) wajib mengikat pasangan `(dossier_version, dossier_hash)` yang spesifik. Persetujuan terhadap revisi lama otomatis ditolak dengan `VERSION_CONFLICT` jika isi dossier berubah.
4. **Pemisahan AI Observability vs Security Audit (`NFR-SEC-004`, `ADR-S06`):** Audit keamanan disimpan secara append-only di sink independen (`CMP-GOV-02`) dengan rantai hash (`prev_event_hash -> event_hash`), terpisah dari trace kualitas AI (Langfuse / local trace store) dan tidak pernah menyimpan *hidden chain-of-thought*.

---

## 2. Tabel Transisi State & Penanganan Kegagalan (`workflow-event.v1.schema.json`)

Urutan happy-path wajib mengikuti baseline `AGENTS.md` §6.3 dan BRD `FR-ORCH-001`:
`RECEIVED → CORRELATED → TRIAGED → EVIDENCE_COLLECTED → RETRIEVED → HYPOTHESES → VALIDATED → DRAFTED → HUMAN_REVIEW → CLOSED → LEARNED`

| State Saat Ini | Transisi Valid Berikutnya | Producer yang Diizinkan | Output yang Dipersistenkan | Cabang Kegagalan / Cancel (`terminal_outcome`) |
|---|---|---|---|---|
| `RECEIVED` | `CORRELATED`, `REJECTED` | `CMP-INV-01` (Alert Intake) | Bukti autentikasi webhook, event tervalidasi, `incident_id` awal | Signature gagal / skema rusak → `REJECTED` (`UNAUTHENTICATED` / `SCHEMA_INVALID`) |
| `CORRELATED` | `TRIAGED`, `MANUAL_TRIAGE_REQUIRED` | `CMP-INV-02` (Correlation Engine) | Fingerprint dedup, pengelompokan alert ke `incident_id`, resolusi `service_id` | Layanan tidak terpetakan di katalog → `MANUAL_TRIAGE_REQUIRED` (`SERVICE_UNMAPPED`) |
| `TRIAGED` | `EVIDENCE_COLLECTED`, `CANCELLED`, `FAILED_SAFE` | `CMP-INV-03` (Coordinator) | Rencana pemanggilan tool read-only sesuai budget & scope | Kill-switch operator → `CANCELLED`; kehabisan kuota awal → `FAILED_SAFE` |
| `EVIDENCE_COLLECTED` | `RETRIEVED`, `CANCELLED` | `CMP-INV-03` + `CMP-INV-04` (MCP Gateway) | Kumpulan `tool-result.v1` ber-provenance + penanda `SOURCE_UNAVAILABLE` bila backend gagal | Semua sumber telemetri mati → tetap lanjut ke `RETRIEVED` dengan penanda bukti kosong (`EV-02`), tidak mengarang data |
| `RETRIEVED` | `HYPOTHESES`, `VALIDATED` (mode deterministik G2 / fallback LLM) | `CMP-INV-03` + `CMP-KNOW-05` (Retrieval Adapter) | `retrieval-result.v1` berisi sitasi SOP `approved` atau `NO_APPLICABLE_RUNBOOK` | Jika semua jalur LLM gagal (`OPS-02`), lewati sintesis bebas LLM dan buat ringkasan bukti deterministik (`MANUAL_FALLBACK_ACTIVE`) menuju `VALIDATED` |
| `HYPOTHESES` | `VALIDATED`, `CANCELLED` | `CMP-INV-03` + `CMP-INV-06` (LLM Router) | Kandidat hipotesis terstruktur yang tertaut ke `evidence_id` & `chunk_id` | Output model melanggar skema / timeout → fallback ke ringkasan deterministik (`LLM_FALLBACK_DETERMINISTIC`) |
| `VALIDATED` | `DRAFTED` | `CMP-INV-07` (Evidence Validator) | Hasil pemeriksaan temporal, kontradiksi (`EV-01`), penghapusan/penurunan klaim tanpa bukti ke `PARTIAL`/`INCONCLUSIVE` | Klaim tanpa `evidence_id` valid diturunkan statusnya atau ditolak; tidak pernah dinaikkan menjadi `SUPPORTED` |
| `DRAFTED` | `HUMAN_REVIEW` | `CMP-INV-08` (Dossier Generator) | Artifact `dossier.v1` JSON + Markdown rendering dengan `dossier_version` dan `dossier_hash` (SHA-256) | Jika gagal menulis audit record → `FAILED_SAFE` (fail-closed) |
| `HUMAN_REVIEW` | `CLOSED`, `DRAFTED` (revisi) | `CMP-GOV-01` (Human Review Interface) | `review-event.v1` berisi keputusan `approve` / `reject` / `edit` atas `(dossier_version, dossier_hash)` | Revisi stale (`dossier_hash` tidak cocok) → ditolak dengan `VERSION_CONFLICT`; tidak ada auto-remediation (`HUM-01`) |
| `CLOSED` | `LEARNED` (opsional, pasca-evaluasi) | `CMP-INV-03` / `CMP-GOV-04` | Snapshot dossier final yang immutable (`terminal_outcome: "CLOSED_APPROVED"` / `"CLOSED_REJECTED"` / `"CLOSED_MANUAL_FALLBACK"`) | Hanya setelah `CLOSED` tercapai, evaluator offline (`CMP-GOV-04`) diizinkan melakukan join ke ground-truth (`RULE-03`) |

---

## 3. Aturan Validasi Bukti, Klaim, dan Ketidakpastian (`CMP-INV-07`)

Sebelum dossier bertransisi dari `VALIDATED` ke `DRAFTED`, Evidence Validator menjalankan pemeriksaan deterministik:
1. **Referential Integrity:** Setiap ID di dalam `supporting_evidence_ids[]` dan `contradicting_evidence_ids[]` wajib eksis di `dossier.evidence[].evidence_id`. Referensi ke ID fiktif menyebabkan klaim ditolak (`SCHEMA_INVALID` / `UNSUPPORTED_CLAIM_REMOVED`).
2. **Temporal Alignment:** Timestamp observasi bukti (`observed_at` / `sample_at`) wajib berada di dalam atau beririsan secara sah dengan jendela insiden `[window_start, window_end)` sesuai kebijakan korelasi. Bukti di luar jendela waktu (`SC-14`) tidak boleh mendukung hipotesis `SUPPORTED`.
3. **Penanganan Bukti Kontradiktif & Hilang (`EV-01`, `EV-02`):**
   - Jika `contradicting_evidence_ids` tidak kosong (mis. metrik RED normal tetapi log melaporkan error parsial), `support_status` maksimal adalah `PARTIAL` atau `INCONCLUSIVE`.
   - Jika backend telemetri mengembalikan `status: "unavailable"` (mis. Tempo mati pada `EV-02`), `missing_sources[]` wajib mencatat sumber tersebut dan `unknowns[]` wajib menjelaskan dampaknya; validator menolak setiap span/trace yang tidak berasal dari `tool-result` berstatus `ok`/`partial`.
4. **Pemeriksaan Ulang Applicability SOP (`RAG-01`, `RAG-02`):** Setiap item pada `sop_citations[]` diperiksa kembali agar memiliki `service_id == dossier.service_id`, `environment == dossier.environment`, `status == "approved"`, dan `effective_from <= alert_received_at < effective_to`. Teks SOP tidak boleh dijadikan bukti observasi runtime saat ini.

---

## 4. Kontrak Dossier Tunggal (`dossier.v1.schema.json`)

Dossier JSON adalah *single source of truth* terstruktur. Rendering Markdown manusia dihasilkan secara deterministik dari objek JSON yang sama tanpa menambah klaim baru:
- **Identitas & Versi:** `schema_version` (`"1.0"`), `incident_id`, `dossier_version` (integer monotonik mulai dari `1`), `dossier_hash` (SHA-256 hex atas payload kanonik dossier).
- **Konteks Insiden:** `severity`, `service_id`, `environment`, `alert_received_at`, `window_start`, `window_end`, `dossier_ready_at`, `investigation_mode` (`"agentic_llm"`, `"deterministic_baseline"`, `"manual_fallback"`).
- **Bukti & Observasi (`evidence[]`):** Daftar item bukti dari tool dengan `evidence_id`, `tool_name`, `source_ref`, `query_window`, `observed_at`, `data_quality`, `truncated`, `summary`, dan `sanitized: true`.
- **Sumber Hilang (`missing_sources[]`):** Daftar eksplisit backend/sumber yang `unavailable` beserta `error_code` (`SOURCE_UNAVAILABLE`, `BACKEND_TIMEOUT`, `NO_APPLICABLE_RUNBOOK`).
- **Hipotesis Terperingkat (`hypotheses[]`):** `hypothesis_id`, `rank`, `statement`, `support_status` (`SUPPORTED`, `PARTIAL`, `INCONCLUSIVE`), `supporting_evidence_ids`, `contradicting_evidence_ids`, `reason_summary`, dan `unknowns`. Aturan JSON Schema (`allOf`/`if`/`then`) memaksa `supporting_evidence_ids` memiliki minimal 1 elemen jika `support_status == "SUPPORTED"`.
- **Sitasi SOP (`sop_citations[]`):** Menggunakan field `doc_id` dan `version` yang dipetakan secara eksplisit dari `document_id` dan `document_version` (`D-C02-01`), ditambah `chunk_id`, `section_path`, `source_uri`, dan `applicability_verified: true`.
- **Rekomendasi Langkah Berikutnya yang Dikendalikan Manusia (`recommended_checks[]`):** Hanya tindakan verifikasi/eskalasi manual yang membutuhkan persetujuan operator (`requires_human_approval: true`, `auto_execution_allowed: false`).
- **Status Review (`review_summary`):** Status saat ini (`PENDING_REVIEW`, `APPROVED`, `REJECTED`, `EDITED`, `MANUAL_TRIAGE`) dan referensi ke `review_event_id` terakhir.
- **Metadata Reprodusibilitas (`reproducibility`):** `workflow_version`, `policy_version`, `model_version`, `prompt_version`, `tool_schema_version`, `kb_index_version`, dan `correlation_ids[]`. Tidak memuat label ground-truth atau nama split holdout.

---

## 5. Idempotensi, Retry, Cancel, Fallback, dan Audit (`review-event.v1` & `audit-event.v1`)

1. **Idempotensi Transisi & Pembuatan Dossier:**
   - Setiap operasi workflow membawa `idempotency_key = SHA256(incident_id + ":" + state + ":" + step_attempt_scope)`.
   - Retry akibat kegagalan transien tidak pernah menggandakan dossier final atau membuat dua `dossier_version` paralel untuk revisi yang sama.
2. **Stale Review Protection (`C02-CON-009`):**
   - `review-event.v1.schema.json` mewajibkan `target_dossier_version` dan `target_dossier_hash`.
   - Apabila coordinator menerima `review-event` dengan `target_dossier_hash` yang berbeda dari hash revisi aktif saat ini, event ditolak dengan kode `VERSION_CONFLICT` dan dicatat di audit log.
3. **LLM Outage & Manual Fallback (`OPS-02`, `SC-13`):**
   - Ketika baik remote free-tier LLM maupun local fallback LLM melewati batas waktu atau gagal (`BACKEND_TIMEOUT` / `SOURCE_UNAVAILABLE`), coordinator mengaktifkan `investigation_mode: "manual_fallback"`, menyusun dossier deterministik berisi timeline alert, bukti telemetri yang berhasil dikumpulkan, dan sitasi SOP yang cocok, lalu menyerahkannya ke `HUMAN_REVIEW` tanpa kehilangan jejak audit.
4. **Immutable Security Audit (`audit-event.v1.schema.json`):**
   - Mencatat setiap autentikasi intake, pemanggilan/penolakan tool, redaction gate, perubahan state workflow, fallback LLM, keputusan reviewer, dan akses evaluator.
   - Setiap record menyimpan `prev_event_hash` dan `event_hash` (SHA-256) untuk mendeteksi modifikasi pasca-kejadian.

