# Gate G2 Specification & Approval Record — Controlled Integration Gate

- **Gate ID:** `G2 — Controlled Integration Gate Approval`
- **Fase:** `F2 — Controlled Integration`
- **Tanggal Evaluasi:** `2026-11-12T08:30:00Z`
- **Execution Run ID:** `c12-20261112T083000Z`
- **Status Akhir Gate:** **`PASSED`**
- **Otoritas Penilai:** Project Initiator / SRE Architecture Board / Security Reviewer
- **Dokumen Terkait:** [Master Implementation Roadmap](../roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.3 & §7, [C12 Specification](../roadmap/phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md), [G2 Evidence Package](../../evidence/c12-20261112T083000Z/C12/g2-record.md)

---

## 1. Definisi & Kriteria Kelulusan Formal Gate G2

Sesuai Master Implementation Roadmap §2.3 dan Proposal Lampiran A / BRD §17.2, Gate G2 bertujuan memvalidasi kelaikan integrasi terkendali end-to-end seluruh modul fondasi dan integrasi Fase 2 (C09 Read-Only Adapters, C10 Alert Intake & Dependency Correlation, C11 Durable Investigation Workflow, dan C12 Baseline Dossier & Replay Suite) sebelum memasuki Fase 3 (Reasoning & Observability). Gate G2 **dilarang diluluskan** tanpa bukti empiris eksekusi replay laboratorium, validasi skema kanonikal, penegakan batasan zero-mutation, isolasi ground-truth mutlak, dan penegakan tata kelola human-in-the-loop tanpa remediasi otomatis.

### 5 Kriteria Kelulusan Wajib:

1. **End-to-End Investigation Replay & Baseline Dossier Generation (`AT-004`, `AT-010`, `AT-013`, `BR-005`, `FR-OUT-001`, `FR-OUT-002`, `E12`):**
   - Integrasi penuh pipeline investigasi: Alert Intake -> Deduplication -> Dependency Correlation -> Triage -> Evidence Collection -> Retrieval -> Hypotheses -> Validation -> Drafted -> Human Review.
   - 5 skenario deterministik (`SC-01`, `SC-02`, `SC-03`, `SC-09`, `SC-12`) tereksekusi tanpa error tak tertangani, menghasilkan *Incident Investigation Dossier* standar enterprise (JSON & Markdown) yang 100% valid terhadap skema kanonikal `dossier.v1.schema.json` dan struktur 9-bagian Appendix A BRD v1.0.
   - Hash integritas kanonikal `dossier_hash` (SHA-256) terhitung dan tervalidasi pada seluruh dossier.
2. **Zero Mutation Enforced (`KPI-09 = 0`, `MCP-01`, `RULE-001`):**
   - Seluruh pemanggilan tool observasi dibatasi pada tool *read-only* melalui Authenticated Policy Gateway (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`).
   - Penolakan mutlak 100% terhadap aksi mutasi (`restart`, `deploy`, `scale`, `exec`, `shell`, `SQL`) dengan kode error `TOOL_NOT_ALLOWED`.
   - Tidak ada modifikasi status layanan eksternal atau database produksi simulasi oleh agent investigator.
3. **Zero Ground Truth Exposure Enforced (`KPI-10 = 0`, `RULE-002`, `AT-008`):**
   - Direktori `restricted/` dan registry ground truth tidak disentuh, diimpor, atau dibocorkan ke dalam prompt, log, telemetri, atau dossier investigasi.
   - Investigator menyimpulkan hipotesis dan bukti murni dari sinyal observabilitas empiris (Loki, Prometheus, Tempo, Knowledge Base).
4. **Degraded Path, Honest Uncertainty & Manual Fallback (`RULE-006`, `EV-01`, `EV-02`, `AT-009`, `AT-012`, `SC-09`):**
   - Saat backend telemetri mengalami kegagalan (misalnya Tempo trace outage pada `SC-09`), sistem secara jujur mencatat sumber hilang pada `missing_sources` dengan kode `SOURCE_UNAVAILABLE` dan menetapkan status `support_status: "INCONCLUSIVE"` tanpa mengarang trace palsu.
   - Saat kuota atau batas waktu terlampaui (`DEADLINE_EXCEEDED` / `BUDGET_EXHAUSTED`), generator *Manual Fallback* (`fallback.py`) menghasilkan dossier darurat (`investigation_mode: "manual_fallback"`, `review_summary.status: "MANUAL_TRIAGE"`) lengkap dengan checklist triage manual bagi operator L1/L2.
5. **Minimum Authorized Human Review & Zero Auto-Remediation (`HUM-01`, `FR-OUT-004`, `FR-OUT-005`):**
   - Antarmuka review manusia mendukung 4 keputusan formal: `approve`, `reject`, `edit`, `escalate_manual` oleh role terotorisasi (`L1_OPERATOR`, `L2_SRE_REVIEWER`, `PROJECT_OWNER_LAB`).
   - Setiap keputusan review dicatat di tabel append-only SQLite `review_records` dan diekspor ke `review-records.jsonl` sesuai `review-event.v1.schema.json`.
   - Verifikasi integritas hash dan proteksi konflik versi (`StaleDossierVersionError`).
   - Persetujuan reviewer **tidak pernah** memicu aksi remediasi otomatis (`auto_action_triggered: false`).

---

## 2. Hasil Verifikasi Kriteria & Audit Bukti Empiris

| Kriteria G2 | Bukti Empiris di Laboratorium (`evidence/c12-20261112T083000Z/C12/`) | Status |
|---|---|---|
| **Kriteria 1 (End-to-End Replay & Dossier)** | 5 skenario (`SC-01`, `SC-02`, `SC-03`, `SC-09`, `SC-12`) tereksekusi mulus; seluruh JSON lulus validasi Draft 2020-12 `dossier.v1.schema.json`; 5 Markdown dossiers memuat 9 seksi BRD Appendix A lengkap; hash SHA-256 valid. | **PASS** |
| **Kriteria 2 (Zero Mutation Enforced)** | 0 instruksi mutasi dipanggil (`KPI-09 = 0`); 4 read-only tools lolos gateway C08/C09; percobaan write/restart ditolak dengan `TOOL_NOT_ALLOWED`. | **PASS** |
| **Kriteria 3 (Zero GT Exposure)** | 0 akses direktori `restricted/` (`KPI-10 = 0`); isolasi namespace terbukti; tidak ada label `scenario_id` ground truth pada dossier. | **PASS** |
| **Kriteria 4 (Degraded Path & Fallback)** | `SC-09` mencatat 2 missing sources tanpa trace palsu (`EV-02`); `ManualFallbackGenerator` terbukti saat deadline/budget terlampaui (`AT-012`), menghasilkan checklist L1/L2 manual. | **PASS** |
| **Kriteria 5 (Human Review & No Auto-Remediation)** | Review `SC-02` dan `SC-03` disetujui L2 SRE Reviewer; audit record valid terhadap `review-event.v1.schema.json`; seluruh event review mencatat `auto_action_triggered: false` (`HUM-01`). | **PASS** |

---

## 3. Matriks Hasil Replay Skenario Fase 2 (E12)

| Skenario ID | Nama Skenario | Incident ID | Status Akhir | Support Status | Dossier Hash (SHA-256) | Catatan Khusus |
|---|---|---|---|---|---|---|
| **SC-01** | Normal Baseline Traffic | `inc-sc01-nominal-001` | `HUMAN_REVIEW` | `SUPPORTED` | `226978129bd9...` | Zero false positive; metrik nominal; SLA 100%. |
| **SC-02** | HTTP 5xx Error Burst | `inc-sc02-5xx-burst-001` | `CLOSED` | `PARTIAL` | `e89a29cadf99...` | Disetujui oleh `sre_lead_hendra` (L2 SRE Reviewer); rekomendasi manual rollback. |
| **SC-03** | DB Pool Exhaustion | `inc-sc03-db-exhaustion-001` | `CLOSED` | `INCONCLUSIVE` | `3169a96eee90...` | Disetujui oleh `sre_lead_hendra`; identifikasi bottleneck pool pada `ledger-service`. |
| **SC-09** | Tempo Trace Outage | `inc-sc09-trace-outage-001` | `HUMAN_REVIEW` | `INCONCLUSIVE` | `7b5748c78ca9...` | 2 sumber `unavailable` (`TempoClient`); 0 trace palsu dikarang (`EV-02`). |
| **SC-12** | 100 Duplicate Alerts | `inc-20261112-a8e0a0da` | `HUMAN_REVIEW` | `PARTIAL` | `4b65cfb84ad8...` | 100 alert disaring menjadi 1 insiden tunggal (`OPS-01`); resource stabil. |

---

## 4. Evaluasi Ketahanan & Penanganan Fallback

- **Fallback Dossier Generation (`fallback.py`):**
  - Diuji secara empiris melalui `tests/test_c12_baseline_dossier_g2.py::test_manual_fallback_on_deadline_exceeded_at012`.
  - Saat `DEADLINE_EXCEEDED` terjadi, investigasi tidak mengalami *unhandled panic*; sistem langsung menghasilkan berkas fallback `fallback-report.json` dan `fallback-report.md`.
  - Berkas fallback mempertahankan daftar bukti parsial yang telah dikumpulkan sebelum batas waktu terlampaui dan menyematkan checklist triage manual darurat.
- **Human Review Integrity (`review.py`):**
  - Append-only audit record di SQLite dan JSONL (`review-records.jsonl`).
  - Penolakan mutlak terhadap manipulasi versi stale (`StaleDossierVersionError`) dan role tidak berwenang (`UnauthorizedReviewerError`).
  - Penegakan invariansi `auto_action_triggered: false` menjamin keputusan manusia tidak menimbulkan efek samping eksekusi sepihak pada infrastruktur lab.

---

## 5. Pernyataan Kelulusan & Izin Melanjutkan

Seluruh 5 kriteria kelulusan Controlled Integration Gate telah terpenuhi 100% secara empiris di laboratorium tanpa adanya deviasi, tanpa pembocoran ground truth, dan tanpa aksi mutasi pada lingkungan lab.

> **STATUS GATE G2: `PASSED`**  
> **Izin Kerja:** Diberikan otorisasi penuh untuk memulai **Fase 3 — Reasoning & Observability** ([Chapter C13 — Controlled LLM Investigator](../roadmap/phase-3-reasoning-and-observability/13-CONTROLLED-LLM-INVESTIGATOR.md)).

