# C07 Handover — To Chapter C08 (Secure Gateway and Foundation G1)

- **Source Chapter:** `C07 — Hybrid Retrieval and Baselines`
- **Target Chapter:** `C08 — Secure Gateway and Foundation G1`
- **Evidence Package ID:** `E07` (`evidence/c07-20261111T160000Z/C07/`)
- **Execution Run ID:** `c07-20261111T160000Z`
- **Implementation Status:** `VERIFIED` (`10/10` tests `PASS` on C07, `41/41` tests `PASS` repository-wide)

---

## 1. Artefak yang Diserahterimakan ke Chapter C08

| Komponen / Artefak | Path Repositori | Keterangan & Peran untuk C08 / Gate G1 |
|---|---|---|
| **Paket Modul Retrieval** | `knowledge_base/retrieval/` | Modul `RetrievalEngine`, `RetrievalService`, `StrictPreFilter`, `embeddings.py` (model resmi `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 384-d), dan `models.py` yang siap diproteksi Secure Gateway. |
| **Metrik Baseline DEV** | `evidence/c07-20261111T160000Z/C07/baseline-metrics.json` | Bukti empiris perbandingan 4 mode pada 28 kueri DEV: Hit@5 100%, MRR@10 0.9732, P95 1.29 ms, RAM 6.89 MB. |
| **Hasil Uji Filter Negatif** | `evidence/c07-20261111T160000Z/C07/filter-negative-tests.json` | Bukti lulus uji negatif `RAG-01`/`SC-10` (obsolete prevention), `RAG-02` (cross-service isolation), `SEC-01` (restricted access), `FR-RAG-009` (no_match), dan `NFR-016` (outage). |
| **Audit Sitasi & Provenance** | `evidence/c07-20261111T160000Z/C07/citation-checks.json` | 100% hash SHA-256 sitasi cocok dengan `chunk-hashes.json`, URI format `kb://` valid, `status: "approved"`. |
| **Catatan Eksekusi Benchmark** | `evidence/c07-20261111T160000Z/C07/retrieval-runs.jsonl` | Rekaman 112 baris eksekusi kueri lengkap (28 kueri $\times$ 4 mode) untuk auditabilitas Gate G1. |
| **Rekomendasi ADR Retrieval** | `evidence/c07-20261111T160000Z/C07/retrieval-adr.md` | Rekomendasi final penyelesaian `TBD-06` (Unified Hybrid Vector+Sparse) dan `ADR-S04` (RRF $k=60$, Reranker optional/disabled by default). |
| **Log Hasil Uji Otomatis** | `evidence/c07-20261111T160000Z/C07/test-results.txt` | Catatan eksekusi nyata test runner `pytest tests/test_c07_hybrid_retrieval.py` (10/10 PASS). |

---

## 2. Instruksi Integrasi untuk Chapter C08 (Secure Gateway & Gate G1)

1. **Pembungkusan Tool Adapter Read-Only:**
   - Di C08, `RetrievalService` akan dibungkus sebagai adapter tool investigator read-only (misalnya `retrieve_runbooks` atau `search_knowledge_base`).
   - Secure Gateway wajib menyuntikkan `caller_scope_ref` dan `caller_groups` dari claims token JWT pemanggil secara server-side sebelum memanggil `service.execute_retrieval()`.
2. **Penegakan Gate G1 (Foundation Phase Gate):**
   - Bukti dari paket `E07` ini menyediakan data empiris lengkap untuk memenuhi kriteria Gate G1 poin RAG & Knowledge Base:
     - Baseline komparatif lexical vs dense vs hybrid terbukti (`BR-011`, `AT-006`).
     - Filter versi usang dan hak akses terbukti efektif (`RAG-01`, `RAG-02`, `SEC-01`, `AT-007`).
     - Nol kebocoran dataset evaluasi holdout (`restricted/evaluator_queries/holdout_queries.json` tidak pernah disentuh).
     - Biaya $0.00 dan penggunaan memori < 10 MB mendukung plafon 8 GiB lab.

