# ADR-S04: Arsitektur Hybrid RAG Qdrant-Native (Dense + Sparse), Chunking, Fusion, dan Evaluasi Reranker (`TBD-06`)

- **ID Keputusan:** `ADR-S04` (Mencakup `TBD-06`)
- **Status:** `ACCEPTED & CONFIRMED IN G1` (Model dense embedding multibahasa resmi disahkan pada Gate G1)
- **Tanggal:** `2026-11-09` (Diperbarui pada `2026-11-12`)
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C06`, `C07`, `C08`, `C14`, `C18`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/knowledge-lifecycle.md`, `evidence/c02-20261109T070500Z/C02/contracts/knowledge-chunk.v1.schema.json`, `evidence/c02-20261109T070500Z/C02/contracts/retrieval-request.v1.schema.json`, `evidence/c02-20261109T070500Z/C02/contracts/retrieval-result.v1.schema.json`, `evidence/c07-20261111T160000Z/C07/retrieval-adr.md`, `evidence/c08-20261112T000000Z/C08/g1-record.md`

---

## 1. Konteks & Permasalahan

BRD (`FR-RAG-003`..`005`) dan Proposal mensyaratkan perbandingan empat mode retrieval (`lexical_only`, `dense_only`, `hybrid_rrf`, dan opsional `hybrid_rerank`) dengan pre-filtering hak akses dan masa berlaku dokumen (`SEC-01`, `RAG-01`, `RAG-02`), namun seluruh stack harus berjalan di dalam batas **8 GiB Docker Lab** pada Mac 16 GB Apple Silicon dengan biaya **`$0.00`**.

Selain itu, korpus pengetahuan perbankan pada Chapter C06 disusun menggunakan Bahasa Indonesia teknis operasional perbankan (contoh: "Prosedur Mitigasi Antrean Sambungan Basis Data", "Langkah Eskalasi Lonjakan Latensi"). Model embedding dense berbahasa Inggris monolitik berisiko menimbulkan kesenjangan semantik (*semantic mismatch*) pada kueri triage insiden di Fase 2 dan 3.

---

## 2. Opsi yang Dipertimbangkan

1. **Opsi 1 (Arah Terpilih): Qdrant-Native Named Vectors (Dense Vector + Sparse BM25/SPLADE Vector dalam satu engine Qdrant) dengan model embedding multibahasa lokal (`paraphrase-multilingual-MiniLM-L12-v2`).**
2. **Opsi 2: Qdrant (Dense) + Elasticsearch Cluster Terpisah (BM25 Lexical).** Ditolak sebagai pilihan utama karena kontainer JVM Elasticsearch menambah beban RAM >2 GiB dan menimbulkan risiko ketidakcocokan versi/filter antara dua engine saat update/supersede dokumen.

---

## 3. Keputusan Desain yang Disahkan pada Gate G1

1. **Kontrak Terpadu yang Dibekukan (`ACCEPTED`):**
   - Skema `knowledge-chunk.v1`, `retrieval-request.v1`, dan `retrieval-result.v1` berlaku seragam untuk `lexical_only`, `dense_only`, `hybrid_rrf`, dan `hybrid_rerank`.
   - Predikat otorisasi dan applicability (`service_id`, `environment`, `status == "approved"`, `effective_from <= reference_time < effective_to`, `allowed_groups`) wajib dieksekusi pada **setiap** cabang `Prefetch` di Qdrant sebelum tahap fusion maupun reranker (`D-C02-04`).
   - Publikasi indeks baru menggunakan pertukaran alias atomik (`kb_active_alias`) dan kunci cache wajib menyertakan `index_version` serta `caller_scope_ref`.
2. **Model Dense Embedding Resmi (`CONFIRMED`):**
   - **`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** (384 dimensi, unit L2 normalized).
   - **Justifikasi Pemilihan:**
     - Mendukung pemahaman semantik silang antara Bahasa Indonesia operasional dan istilah teknis SRE Inggris.
     - Bobot model sangat ringan (~118 MB), efisien dieksekusi di CPU Apple Silicon.
     - Nol biaya lisensi/API pihak ketiga ($0.00), bebas ketergantungan koneksi cloud eksternal.
     - Konsumsi memori sangat rendah (< 150 MiB RAM), menyisakan headroom luas pada anggaran 8 GiB lab.
     - Teruji mencapai 100% Hit-Rate@5 pada 28 kueri evaluasi `DEV` di Chapter C07.
3. **Representasi Sparse & Strategi Fusion (`CONFIRMED`):**
   - **Representasi Sparse (`TBD-06`):** Standard BM25 lexical token index dengan ekspansi istilah teknis multibahasa.
   - **Strategi Chunking & Fusion:** Pemotongan berbasis heading Markdown (`section_path`, target 256–512 token, overlap 32–64 token) dan Reciprocal Rank Fusion (`RRF` dengan $k=60$).
4. **Opsional Cross-Encoder Reranker:**
   - Dinyatakan opsional/disabled by default karena mode `hybrid_rrf` sudah mencapai 100% Hit-Rate@5 pada benchmark `DEV` tanpa latensi tambahan reranker.

---

## 4. Konsekuensi

- **Positif:** Menghemat >1.8 GiB RAM dibanding dual-engine Qdrant+Elasticsearch, menjamin pemahaman semantik akurat atas dokumen SOP perbankan berbahasa Indonesia, 0 biaya operasional, dan integritas evaluasi offline tetap terlindungi.
- **Tindak Lanjut:** Seluruh adapter kueri telemetri dan orkestrator investigasi Fase 2 (`C09`, `C11`) wajib memanfaatkan `RetrievalService` berbasis model multilingual 384-d ini melalui Secure Gateway C08.

