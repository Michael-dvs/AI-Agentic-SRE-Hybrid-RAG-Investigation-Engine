# Gate G1 Specification & Approval Record — Foundation Gate

- **Gate ID:** `G1 — Foundation Gate Approval`
- **Fase:** `F1 — Foundation`
- **Tanggal Evaluasi:** `2026-11-12T00:00:00Z`
- **Execution Run ID:** `c08-20261112T000000Z`
- **Status Akhir Gate:** **`PASSED`**
- **Otoritas Penilai:** Project Initiator / SRE Architecture Board / Security Reviewer
- **Dokumen Terkait:** [Master Implementation Roadmap](../roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md) §2.2 & §7, [C08 Specification](../roadmap/phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md), [G1 Evidence Package](../../evidence/c08-20261112T000000Z/C08/g1-record.md)

---

## 1. Definisi & Kriteria Kelulusan Formal Gate G1

Sesuai Master Implementation Roadmap §2.2 dan Proposal Lampiran A / BRD §17.1, Gate G1 bertujuan memvalidasi kelaikan fondasi teknis simulasi sebelum integrasi terkendali dimulai pada Fase 2. Gate G1 **dilarang diluluskan** hanya berdasarkan dokumen kontrak tertulis; seluruh invarian keamanan dan penolakan kueri ilegal wajib dibuktikan secara empiris di laboratorium.

### 5 Kriteria Kelulusan Wajib:

1. **Layanan Simulasi & Sinyal Telemetri Terverifikasi (`AT-001`, `E03`, `E05`):**
   - 5 microservices sintetis (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`) beroperasi stabil dengan generator trafik transaksi ber-seed.
   - Penangkapan telemetri lengkap: *RED metrics* Prometheus, *structured JSON logs* Loki, *distributed traces* Tempo, dan Service Catalog dependensi statis.
2. **Fault Injection Harness & Isolasi Ground Truth Terbukti (`AT-002`, `AT-008`, `E04`):**
   - 14 skenario gangguan (`SC-01` s/d `SC-14`) dapat disuntikkan dan dipulihkan secara bersih 100%.
   - Registry Ground Truth dan evaluator holdout queries terisolasi ketat di direktori `restricted/` dengan hash SHA-256 yang dibekukan, tanpa akses mount ke agent investigator.
3. **Korpus Pengetahuan Sintetis & Baseline Hybrid RAG Reproducible (`AT-006`, `AT-007`, `RAG-01`, `RAG-02`, `E06`, `E07`):**
   - 71 chunks pengetahuan terindeks lengkap (SOP, Runbook, Known Errors, Catatan Arsitektur).
   - Pencegahan SOP usang (`RAG-01`) dan penolakan kueri lintas batas layanan (`RAG-02`) teruji 100%.
   - Hybrid RRF ($k=60$) mengungguli BM25-only dan Dense-only baselines pada dataset `DEV`.
4. **Authenticated Read-Only Policy Gateway Aktif (`MCP-01`, `MCP-02`, `SEC-01`, `SEC-03`, `AT-005`, `E08`):**
   - Penolakan mutlak atas 100% permintaan fungsi mutasi (`restart`, `deploy`, `scale`, `exec`, `shell`, `SQL`) dengan kode `TOOL_NOT_ALLOWED`.
   - Penolakan tegas tanpa *silent clamping* atas jendela waktu melebihi batas kebijakan (`WINDOW_EXCEEDED`).
   - Modul redaksi deterministik (*pre-sink sanitizer*) dengan kebijakan `FAIL_CLOSED` tervalidasi menyamarkan rahasia sintetis (JWT, API key, credential, PAN) tanpa kebocoran raw data.
   - Log audit keamanan independen berformat `audit-event.v1.schema.json` mencatat seluruh keputusan dengan rantai hash SHA-256 valid.
5. **Penutupan Keputusan Wajib & Pembekuan Protokol Evaluasi (`RULE-012`, `AT-014`):**
   - Seluruh keputusan `TBD-05`, `TBD-06`, `TBD-08`, `TBD-10`, `TBD-11`, serta `ADR-S04` s/d `ADR-S08` ditutup dan disahkan resmi.
   - Ukuran sampel korpus evaluasi (`DEV`: 28 kueri, `H-G3`: 15 kueri, `H-G4`: 15 kueri) dan kunci hash dibekukan secara permanen.

---

## 2. Hasil Verifikasi Kriteria & Audit Bukti Empiris

| Kriteria G1 | Bukti Empiris di Laboratorium | Status |
|---|---|---|
| Kriteria 1 (Layanan & Telemetri) | 5 microservices sehat di Docker Compose; RED metrics, Loki logs, dan Tempo spans tervalidasi skema C02. | **PASS** |
| Kriteria 2 (Fault Harness & GT) | 14 skenario pulih 100%; isolasi path GT teruji via gateway blockade (`FORBIDDEN_SCOPE`). | **PASS** |
| Kriteria 3 (KB & RAG) | 71 chunks terbit; RRF $k=60$ dev benchmark lulus; 0 obsolete SOP lolos filter temporal. | **PASS** |
| Kriteria 4 (Secure Gateway) | 17/17 uji batas negatif lulus; redaksi fail-closed 100%; audit hash chaining SHA-256 valid. | **PASS** |
| Kriteria 5 (Keputusan & Evaluasi) | `TBD-05` disahkan ke Python Coordinator; hash `H-G3`/`H-G4` dibekukan; 0 blocker terbuka. | **PASS** |

---

## 3. Matriks Keputusan Arsitektur yang Disahkan pada Gate G1

| ID Keputusan | Hasil Evaluasi Empiris & Justifikasi | Status Akhir |
|---|---|---|
| **`TBD-05` / `ADR-TBD05`** | **Dify self-hosted didiskualifikasi** karena memakan >3.4 GiB RAM (melampaui plafon Docker lab 8 GiB pada Mac 16GB) dan gagal pada uji native hash-bound review (`SPK-C08-06`). **Opsi C (Deterministic Python State Machine Coordinator + SQLite)** disahkan resmi (jejak RAM ~38 MiB, 100% deterministik, 0 modifikasi skema JSON). | **CONFIRMED** |
| **`TBD-06` / `ADR-S08`** | Evaluator beroperasi terpisah secara offline post-dossier, membandingkan diagnosis dengan ground truth setelah dossier berstatus terminal (`CLOSED`). | **CONFIRMED** |
| **`TBD-08` / `ADR-S02`** | Transport alert menggunakan RabbitMQ topic exchange `telemetry.alerts` dengan deduplikasi alert ber-fingerprint sama selama 60 detik (`OPS-01`). | **CONFIRMED** |
| **`TBD-10` / `ADR-S02`** | OpenTelemetry Traces ke Tempo, Prometheus RED Metrics, Loki JSON structured logs. | **CONFIRMED** |
| **`TBD-11` / `ADR-S04`** | **Model Dense Multilingual & Fusion Strategy:** Model resmi `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, L2 normalized) + BM25 sparse + Reciprocal Rank Fusion ($k=60$). Disahkan untuk mendukung pemahaman semantik Bahasa Indonesia perbankan dan istilah teknis Inggris ($0.00 cost, RAM < 150 MiB). | **CONFIRMED** |
| **`ADR-S05`** | Semantic limits: Max window 3600s, max points 1000, max hits 500, max tool calls 30/incident. | **CONFIRMED** |
| **`ADR-S06`** | Pre-sink fail-closed redactor + SHA-256 hash-chained JSONL audit log. | **CONFIRMED** |
| **`ADR-S07`** | Optional APM & Ticket mock stubs read-only. | **CONFIRMED** |

---

## 4. Pembekuan Hash & Tata Kelola Evaluasi Formal

- **Frozen Holdout Queries (`H-G3` & `H-G4`):** `restricted/evaluator_queries/holdout_queries.json`  
  `SHA-256: 6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6`
- **Frozen Ground Truth Incident Records:** `restricted/gt_registry/ground_truth_records.jsonl`  
  `SHA-256: 149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95`

---

## 5. Pernyataan Kelulusan & Izin Melanjutkan

Seluruh kriteria kelulusan Foundation Gate telah terpenuhi 100% tanpa adanya *blocking failure* atau pelanggaran batasan keselamatan laboratorium.

> **STATUS GATE G1: `PASSED`**  
> **Izin Kerja:** Diberikan otorisasi penuh untuk memulai **Fase 2 — Controlled Integration** ([Chapter C09](../roadmap/phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md)).

