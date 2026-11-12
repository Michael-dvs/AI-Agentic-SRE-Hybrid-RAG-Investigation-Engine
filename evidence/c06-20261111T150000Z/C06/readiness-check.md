# C06 Readiness Check — Synthetic Knowledge and Ingestion

- **Chapter:** `C06 — Synthetic Knowledge and Ingestion`
- **Phase:** `F1 — Foundation`
- **Execution Run ID:** `c06-20261111T150000Z`
- **Evidence Location:** `evidence/c06-20261111T150000Z/C06/`
- **Evaluation Date:** `2026-11-11T15:00:00Z`
- **Verification Result:** `ALL PREREQUISITES SATISFIED (PASS)`

---

## 1. Prerequisite Verification Matrix

| Prerequisite ID | Requirement Source | Required State | Actual State | Status |
|---|---|---|---|---|
| `PRQ-C06-01` | `C01 / G0` | Gate G0 disetujui (`PASS`) dengan plafon anggaran $0 dan batas lab lokal | Terverifikasi di `evidence/c01-20261109T043813Z/C01/g0-record.md` | `PASS` |
| `PRQ-C06-02` | `C02` | Kontrak skema `knowledge-chunk.v1.schema.json` (Draft 2020-12) terkualifikasi offline | Terverifikasi di `evidence/c02-20261109T070500Z/C02/contracts/knowledge-chunk.v1.schema.json` | `PASS` |
| `PRQ-C06-03` | `C04` | Katalog skenario dan registri Ground Truth terisolasi di `restricted/gt_registry/` | Terverifikasi di `evidence/c04-20261110T102500Z/C04/readiness-check.md` | `PASS` |
| `PRQ-C06-04` | `C05` | Service Catalog 6 layanan (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`, `db-dummy`) dan alert pipeline operasional | Terverifikasi di `evidence/c05-20261111T113000Z/C05/handover-to-c06-c08-c09-c10.md` | `PASS` |
| `PRQ-C06-05` | `ADR-S04` | Arah Qdrant-native hybrid (dense+sparse), strategi structure-aware chunking (350–700 token), dan pemisahan kueri evaluasi | Terverifikasi di `docs/decisions/ADR-S04-rag-chunking-fusion-and-reranker.md` | `PASS` |

---

## 2. Invariant & Boundary Audit (`AGENTS.md`)

1. **100% Data Sintetis (`RULE-001`):**
   - Seluruh dokumen SOP, runbook, catatan arsitektur, known error, dan post-mortem merupakan dokumen sintetis buatan lab. Tidak ada satupun data nasabah, kredensial asli, atau dokumen rahasia bank riil.
2. **Isolasi Ground Truth (`RULE-002`, `AT-008`, `FR-RAG-006`):**
   - Pemindaian regex membuktikan tidak ada teks string `SC-01`..`SC-14`, frasa `fault_harness`, atau petunjuk skenario buatan di dalam korpus Markdown maupun chunk JSON.
   - Dataset kueri evaluasi `HOLDOUT` (`H-G3` / `H-G4`) diisolasi di `restricted/evaluator_queries/holdout_queries.json` dan tidak dimasukkan ke dalam manifest indeks knowledge base runtime.
3. **Redaksi Pre-Ingestion (`SEC-03`):**
   - Sanitizer pre-ingestion memindai synthetic secret fixtures (dummy JWT, database URI passwords, Bearer tokens, synthetic API keys, payment card PAN) dan menyamarkannya menjadi token netral `[REDACTED_*]` sebelum tahap chunking.
4. **Batas Ruang Lingkup C06:**
   - Mesin pencari vektor Qdrant, komputasi embedding, dan pengujian Recall@5 berada di Chapter C07. Chapter C06 fokus pada penulisan korpus, validasi metadata, redaksi, chunking, manajemen siklus hidup, dan penyusunan dataset kueri `DEV` vs `HOLDOUT`.

