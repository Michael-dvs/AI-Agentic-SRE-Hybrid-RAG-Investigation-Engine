# C02 Step 07 — Desain Siklus Hidup Knowledge Base & Kontrak Retrieval (Hybrid RAG)

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/knowledge-lifecycle.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 07 & §7.5)  
> **Status:** `SPECIFIED` (Kontrak kandidat yang dibekukan melalui `D-C02-01`..`06`; parameter runtime/fusion/reranker tetap `ADR-S04` & `TBD-06`)

---

## 1. Tujuan & Invarian Keamanan Knowledge Layer (`TB-03`)

Knowledge Layer menyediakan rujukan prosedur operasional standar (SOP), runbook, catatan arsitektur, dan known-error articles sintetis untuk membantu investigasi insiden. Kontrak pada dokumen ini memastikan:
1. **Satu Kontrak Lintas Mode Retrieval (`FR-KB-002`, `FR-KB-003`):** Kontrak request, chunk metadata, dan hasil sitasi berlaku identik pada mode `lexical_only`, `dense_only`, `hybrid_rrf`, maupun `hybrid_rerank`.
2. **Pre-Retrieval Entitlement & Applicability Filtering (`RULE-05`, `FR-SEC-004`, `SEC-01`, `RAG-01`, `RAG-02`):** Pemfilteran hak akses (`allowed_groups`, `classification`), kesesuaian layanan/lingkungan (`service_id`, `environment`), status publikasi (`status == "approved"`), dan rentang waktu berlaku (`effective_from <= reference_time < effective_to`) dieksekusi di server **sebelum** kandidat masuk ke fusion, reranker, atau konteks LLM.
3. **Ketiadaan Fabrikasi pada No-Match:** Ketika tidak ada dokumen yang memenuhi filter atau skor minimum, adapter wajib mengembalikan `status: "no_match"` dan `gap_reason: "NO_APPLICABLE_RUNBOOK"`, bukan mengarang prosedur atau menurunkan filter diam-diam ke dokumen `obsolete`/`restricted`.
4. **Prose Dokumen adalah Data Tidak Dipercaya (`RULE-06`, `SEC-02`):** Seluruh teks chunk dibungkus dalam delimiter `<untrusted_sop_chunk>` saat diteruskan ke LLM; instruksi di dalam teks SOP tidak pernah dieksekusi sebagai perintah tool atau perubahan kebijakan.

---

## 2. Kontrak Metadata Dokumen & Chunk (`knowledge-chunk.v1.schema.json`)

Setiap chunk yang diindeks ke Qdrant (`TB-03`) wajib memenuhi skema `urn:sre-sim:contract:knowledge-chunk:1` yang mempertahankan seluruh 16 field wajib BRD `FR-KB-001` ditambah field tata kelola proposal:

| Field | Tipe | Semantik & Aturan Validasi |
|---|---|---|
| `schema_version` | `string` (`"1.0"`) | Versi skema kontrak chunk. |
| `chunk_id` | `string` | Identifier deterministik berbasis `(document_id, document_version, section_path, chunk_index)`. Perubahan isi menghasilkan `document_version` dan `content_hash` baru; tidak menimpa sitasi lama. |
| `document_id` | `string` | Identifier kanonik dokumen (mis. `SOP-TX-DB-001`). Dipetakan ke `doc_id` pada sitasi dossier sesuai `D-C02-01`. |
| `document_version` | `string` | Versi semantik/revisi dokumen sumber (mis. `"2.1.0"`). Berbeda dari `index_version` koleksi Qdrant. |
| `index_version` | `string` | Versi snapshot indeks/koleksi tempat chunk dipublikasikan (mis. `"idx-v1-20261109"`). |
| `title` | `string` | Judul dokumen sintetis. |
| `source_uri` | `string` (`^kb://...`) | URI logis yang di-resolve melalui `SRC-KB-CORPUS` di `source-registry.csv`. **Bukan** URL HTTP bebas atau path traversal filesystem (`../`). |
| `section_path` | `string` | Hirarki bagian dokumen (mis. `"3.2 > Connection Pool Exhaustion > Verification"`). |
| `service_id` | `string` | Kunci kanonik katalog layanan (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`). |
| `service.name` | `string` | Nama OTel layanan yang berkorespondensi 1-ke-1 dengan `service_id`. |
| `environment` | `string` | Lingkungan target (`lab`, `sim-staging`, `sim-prod-like`). |
| `application` | `string` | Nama aplikasi logis (`sre-simulation-poc`). |
| `component` | `string` | Kategori komponen (`gateway`, `identity`, `core-transaction`, `notification`, `persistence`). |
| `status` | `enum` | `approved`, `draft`, `obsolete`, `withdrawn`. Hanya `approved` yang memenuhi syarat sitasi aktif. |
| `effective_from` | `date-time` (`Z`) | Waktu mulai berlakunya versi dokumen dalam UTC. |
| `effective_to` | `date-time` (`Z`) / `null` | Waktu berakhirnya masa berlaku dokumen dalam UTC. Nilai `null` secara eksplisit berarti *open-ended validity* (masih berlaku sampai digantikan), **bukan** data hilang (`D-C02-04`). |
| `content_hash` | `string` (SHA-256 hex) | Hash SHA-256 64 karakter dari `content` yang telah dinormalisasi dan disanitasi. |
| `classification` | `enum` | `synthetic-internal`, `synthetic-restricted`, `synthetic-confidential`. |
| `allowed_groups` | `array<string>` | Daftar grup otorisasi yang berhak membaca chunk ini (minimal 1 grup). |
| `owner_ref` | `string` | Referensi pemilik dokumen sintetis. |
| `language` | `enum` | `id`, `en`, `id-en`. |
| `content` | `string` | Isi teks chunk yang telah melewati DLP/redaction gate. |
| `updated_at` | `date-time` (`Z`) | Timestamp pembaruan metadata/indeks terakhir dalam UTC. |

---

## 3. Predikat Applicability & Authorization (`D-C02-04`)

Retrieval adapter menerapkan predikat wajib berikut pada **semua** cabang pencarian (dense vector, sparse BM25/SPLADE, dan pre-rerank):

```text
IS_AUTHORIZED_AND_APPLICABLE(chunk, req, server_ctx) :=
  chunk.service_id == req.service_id
  AND chunk.environment == req.environment
  AND chunk.status == "approved"
  AND chunk.effective_from <= req.reference_time
  AND (chunk.effective_to IS NULL OR req.reference_time < chunk.effective_to)
  AND (chunk.allowed_groups INTERSECT server_ctx.caller_groups) IS NOT EMPTY
  AND chunk.classification IN server_ctx.allowed_classifications
```

- **Server-Derived Authorization Context:** `caller_groups` dan `allowed_classifications` **tidak ada** di dalam model-visible `retrieval-request.v1.schema.json`. Keduanya disuntikkan oleh MCP/Retrieval Gateway berdasarkan identitas terautentikasi `principal_investigator` dan scope insiden aktif.
- **Isolasi Cabang Pencarian:** Di Qdrant, payload filter di atas dikirim sebagai `Filter(must=[...])` ke dalam masing-masing `Prefetch` (baik dense maupun sparse) sebelum tahap `FusionQuery(fusion=Fusion.RRF)`. Dengan demikian, dokumen yang tidak sah (`SEC-01`), milik service/environment lain (`RAG-02`), atau sudah `obsolete`/melewati `effective_to` (`RAG-01`) tidak pernah masuk ke kandidat fusion maupun reranker.

---

## 4. Kontrak Request & Result (`retrieval-request.v1` & `retrieval-result.v1`)

### 4.1 `retrieval-request.v1.schema.json`
Input yang dikendalikan oleh coordinator/model dibatasi secara ketat (`additionalProperties: false`):
- `service_id`, `environment`: target layanan dan lingkungan insiden.
- `query_text`: string kueri terbatas (`minLength: 3`, `maxLength: 512`).
- `reference_time`: timestamp UTC (`Z`) acuan insiden untuk mengevaluasi `[effective_from, effective_to)`.
- `retrieval_mode`: enum `lexical_only`, `dense_only`, `hybrid_rrf`, `hybrid_rerank`.
- `top_k`: jumlah maksimum sitasi akhir (`minimum: 1`, batas atas kebijakan dievaluasi oleh gateway, kandidat C06/C07).
- `max_context_tokens`: anggaran token maksimum untuk seluruh chunk yang dikembalikan.
- `index_version_policy`: `"latest_approved"` atau pin versi indeks eksplisit untuk replay deterministik.

### 4.2 `retrieval-result.v1.schema.json`
Output terstruktur ke coordinator dan evidence validator:
- `status`: `ok`, `no_match`, `unavailable`, `rejected`.
- `retrieval_mode_executed`: mode yang benar-benar dijalankan.
- `index_version`: versi indeks aktual yang melayani kueri.
- `observed_at`: waktu eksekusi kueri UTC (`Z`).
- `applied_filters`: ringkasan filter otorisasi dan applicability yang diterapkan oleh server (`service_id`, `environment`, `reference_time`, `status_required`, `caller_scope_ref`).
- `citations`: daftar terurut item sitasi terotorisasi, masing-masing memuat `chunk_id`, `document_id`, `document_version`, `title`, `section_path`, `source_uri`, `service_id`, `environment`, `status`, `effective_from`, `effective_to`, `content_hash`, `score`, `score_type` (`bm25_sparse`, `cosine_dense`, `rrf_fusion`, `cross_encoder_rerank`), `source_branch` (`sparse`, `dense`, `hybrid`, `reranked`), `sanitized_excerpt`, dan `applicability_verified: true`.
- `truncated`: boolean apakah hasil dipotong oleh `max_context_tokens` atau `top_k`.
- `gap_reason`: `null` bila `status == "ok"`, atau kode alasan eksplisit (`NO_APPLICABLE_RUNBOOK`, `RETRIEVAL_UNAVAILABLE`, `FORBIDDEN_SCOPE`, `SCHEMA_INVALID`).

> **Larangan Pencampuran Skor Mentah:** Adapter dilarang menjumlahkan skor kosinus dense dan skor BM25 sparse secara langsung. Penggabungan antar-cabang wajib menggunakan metode fusion yang didefinisikan pada `ADR-S04` (mis. Reciprocal Rank Fusion / RRF atau reranker cross-encoder pada kandidat yang sudah lolos filter).

---

## 5. Siklus Hidup Ingesti, Update, Supersede, Rollback, dan Cache

1. **Staging & Validasi (`C06`):**
   - Dokumen sumber sintetis di `kb/corpus/` diperiksa terhadap larangan kebocoran: tidak boleh memuat dokumen administratif `E01`/`E02`, ground-truth registry, atau kueri holdout (`H-G3`/`H-G4`).
   - Setiap dokumen divalidasi kelengkapan metadatanya, dinormalisasi (UTF-8, line endings), dan melewati DLP/redaction gate sebelum pemotongan chunk.
2. **Chunking & Dual Encoding (`C06`–`C07`):**
   - Pemotongan berbasis struktur heading Markdown (`section_path`) agar langkah verifikasi dan langkah eskalasi tidak terpotong secara sembarangan.
   - Setiap chunk menghasilkan representasi dense vector dan sparse vector sesuai pilihan `ADR-S04` (`TBD-06`).
3. **Version-Fenced Publish & Superseding (`RAG-01`):**
   - Saat versi baru dokumen diterbitkan (mis. `SOP-TX-DB-001` versi `2.0.0` menggantikan `1.0.0` pada `2026-11-01T00:00:00Z`):
     - Dokumen `1.0.0` diperbarui menjadi `status: "obsolete"` dan `effective_to: "2026-11-01T00:00:00Z"`.
     - Dokumen `2.0.0` dimasukkan dengan `status: "approved"` dan `effective_from: "2026-11-01T00:00:00Z"`, `effective_to: null`.
   - Pembaruan dilakukan secara atomik melalui alias koleksi Qdrant (`kb_active_alias -> kb_chunks_idx_vN`) sehingga pembaca tidak pernah melihat indeks setengah terbarui (campuran chunk versi lama dan baru sebagai sama-sama `approved`).
4. **Tombstone, Hard Delete & Rollback:**
   - Penarikan darurat dokumen (`status: "withdrawn"`) atau penghapusan chunk wajib memperbarui payload Qdrant dan menginvalidasi cache retrieval secara sinkron.
   - Rollback indeks dilakukan dengan mengembalikan pointer `kb_active_alias` ke snapshot `index_version` sebelumnya yang telah tervalidasi.
5. **Aturan Kunci Cache (Cache Key Invariant):**
   - Apabila caching diaktifkan, kunci cache **wajib** menyertakan tuple lengkap:
     `(index_version, policy_version, caller_scope_ref, service_id, environment, time_bucket(reference_time), retrieval_mode, normalized_query_hash)`.
   - Perubahan `index_version`, pencabutan dokumen, atau perubahan `allowed_groups` otomatis membatalkan entri cache lama sehingga dokumen `obsolete`/`restricted` tidak pernah bocor lewat cache hit.

