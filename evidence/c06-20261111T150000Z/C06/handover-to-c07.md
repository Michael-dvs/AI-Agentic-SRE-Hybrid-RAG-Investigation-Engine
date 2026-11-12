# C06 Handover — To Chapter C07 (Hybrid Retrieval and Baselines)

- **Source Chapter:** `C06 — Synthetic Knowledge and Ingestion`
- **Target Chapter:** `C07 — Hybrid Retrieval and Baselines`
- **Evidence Package ID:** `E06` (`evidence/c06-20261111T150000Z/C06/`)
- **Execution Run ID:** `c06-20261111T150000Z`
- **Implementation Status:** `VERIFIED` (`31/31` automated tests `PASS` across C03, C04, C05, and C06)

---

## 1. Artefak yang Diserahterimakan ke C07

| Komponen / Artefak | Path Repositori | Keterangan & Peran untuk C07 |
|---|---|---|
| **Korpus Dokumen Sumber** | `knowledge_base/corpus/` (20 file Markdown) | Dokumen SOP, Runbook, Catatan Arsitektur, Known Errors, dan Post-Mortem sintetis mencakup 6 layanan. |
| **Pipeline Ingestion & Chunker** | `knowledge_base/ingestion/` | Modul validasi metadata, sanitizer pre-ingestion (`SEC-03`), structure-aware chunker, dan lifecycle manager. |
| **Manifest Indeks Rilis Awal** | `kb-idx-20261111-v1` | 71 chunk tervalidasi 100% terhadap `knowledge-chunk.v1.schema.json` (Draft 2020-12) dengan manifest hash `c9ee96dac3bb07b43a5230b1a881e63131250c8de77ca791ea002c8a810f5129`. |
| **Daftar Hash Chunk** | `evidence/c06-20261111T150000Z/C06/chunk-hashes.json` | 71 entri SHA-256 `content_hash` dan `chunk_id` deterministik untuk pelacakan provenance di C07. |
| **Dataset Kueri DEV (70%)** | `knowledge_base/eval_queries/dev_queries.json` | 28 pasang kueri evaluasi SRE berlabel untuk tuning parameter pencarian hybrid dan evaluasi Recall@5 di C07. |
| **Dataset Kueri HOLDOUT (30%)** | `restricted/evaluator_queries/holdout_queries.json` | 12 kueri evaluasi holdout (`H-G3`/`H-G4`) terkunci dan terisolasi dari proses ingestion maupun runtime model. |

---

## 2. Kontrak & Titik Uji Penting untuk Chapter C07

1. **Uji Pemisahan Keusangan (`RAG-01`, `SC-10`, `AT-007`):**
   - Korpus menyertakan pasangan `SOP-LEDGER-001` versi `1.0.0` (`status: "obsolete"`, `effective_to: "2026-06-01T00:00:00Z"`) dan versi `2.0.0` (`status: "approved"`, `effective_from: "2026-06-01T00:00:00Z"`).
   - Pada C07, pre-filter applicability wajib menolak versi `1.0.0` saat kueri dijalankan dengan `reference_time >= 2026-06-01T00:00:00Z`.
2. **Uji Pemisahan Multi-Layanan (`RAG-02`):**
   - Dokumen `SOP-GW-ERR-504` (`service_id: "api-gateway"`) dan `SOP-LEDGER-ERR-504` (`service_id: "ledger-service"`) memiliki kode error dan judul mirip, namun metadata `service_id` dan `service.name` tegas berbeda.
   - Pada C07, pre-filter `service_id` wajib mencegah dokumen timeout gateway terpilih pada insiden database ledger, dan sebaliknya.
3. **Uji Hak Akses & Klasifikasi Dokumen (`SEC-01`):**
   - Dokumen `SOP-SEC-KEY-ROTATION` memiliki `classification: "synthetic-restricted"` dan `allowed_groups: ["sre-core-l2", "security-admin"]`.
   - Pada C07/C08, pemanggil tanpa grup tersebut wajib menerima hasil tanpa dokumen ini.
4. **Reproducibility & Hash Integrity (`FR-RAG-002`, `AT-013`):**
   - Chunker deterministik menjamin eksekusi ulang pada korpus menghasilkan `content_hash` yang identik 100%, siap untuk pengindeksan vektor dense dan sparse di Qdrant.

