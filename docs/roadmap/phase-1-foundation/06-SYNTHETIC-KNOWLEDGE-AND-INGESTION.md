# C06 — Synthetic Knowledge and Ingestion

## 1. Chapter Information
- **Phase:** F1 — Foundation
- **Status:** DRAFT
- **Documentation status:** COMPLETE / REVIEW_REQUIRED
- **Implementation status:** NOT_STARTED
- **Dependencies:** [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), [C04 — Fault Harness and Ground Truth Isolation](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md), [C05 — Telemetry and Service Catalog](05-TELEMETRY-AND-SERVICE-CATALOG.md), persetujuan model *embedding* (`TBD-04`) dan parameter awal chunking (`ADR-S04`)
- **Next chapter:** [C07 — Hybrid Retrieval and Baselines](07-HYBRID-RETRIEVAL-AND-BASELINES.md)
- **Related requirements:** `BR-004`, `BR-008`, `FR-RAG-001`, `FR-RAG-002`, `FR-RAG-004`, `FR-RAG-006`, `FR-RAG-008`, `RULE-001`, `RULE-002`, `RULE-005`, `NFR-011`, `NFR-012`, `NFR-014`, `NFR-019`, `DEP-04`, `RISK-02`, `RISK-04`, `SC-10`
- **Related acceptance tests:** `AT-006` (build owner korpus & indeks), `AT-007` (build owner metadata versi/status SOP), `AT-008` (build owner pengecualian *ground truth* dari indeks KB), `RAG-01` (build owner *version lifecycle* current vs obsolete), `RAG-02` (build owner pemisahan metadata `service.name`/`environment`), `SEC-01` (build owner metadata `classification` & `allowed_groups`), `SEC-03` (build owner sanitasi *pre-embedding/pre-indexing*)

## 2. Objective & Expected Outcome
Chapter ini bertujuan membangun korpus pengetahuan sintetis (*Synthetic Knowledge Base*) yang selaras dengan *Service Catalog* [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md) beserta *pipeline ingestion* berversi yang mencakup validasi skema, redaksi data sensitif (`SEC-03`), *structure-aware chunking*, *embedding*, pengindeksan, dan manajemen siklus hidup (*publish/update/obsolete/delete/rollback*). Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), korpus hanya memuat dokumen sintetis dan sama sekali tidak boleh mengindeks registri *ground truth* maupun kunci jawaban skenario `holdout` (`RULE-002`, `FR-RAG-006`).

Setelah chapter ini selesai, seluruh dokumen SOP, *runbook*, *known errors*, catatan arsitektur, dan *post-mortem* simulasi memiliki metadata wajib yang tervalidasi (`FR-RAG-001`–`002`), dokumen versi lama (*obsolete*, `SC-10`) dan dokumen *restricted* lintas layanan telah terindeks dengan atribut kontrol akses yang tepat untuk pengujian `RAG-01`, `RAG-02`, dan `SEC-01`, serta kueri evaluasi *retrieval* telah dipisahkan secara ketat antara `DEV` dan `HOLDOUT` (`H-G3`/`H-G4`).

## 3. Scope & Boundaries
### In Scope
- Penulisan korpus dokumen sintetis (SOP, *runbook*, *known error*, *architecture notes*, *simulated post-mortem*) untuk 5 layanan simulasi, mencakup variasi status `active`/`current` vs `obsolete` (`SC-10`), perbedaan `environment`, serta variasi `classification` dan `allowed_groups` (`FR-RAG-001`).
- Implementasi *pipeline ingestion*: validasi format/metadata $\rightarrow$ kanonikalisasi & redaksi *synthetic PII/secret fixtures* (`SEC-03`) $\rightarrow$ *structure-aware chunking* $\rightarrow$ *embedding* lokal (`TBD-04`) $\rightarrow$ pengindeksan ke *staging* $\rightarrow$ verifikasi kualitas $\rightarrow$ *atomic/alias publish* (`FR-RAG-002`, `FR-RAG-008`).
- Implementasi operasi pembaruan versi, penandaan *obsolete*, *tombstone/delete* lintas indeks/cache, serta *rollback* versi indeks (`FR-RAG-008`).
- Penyusunan korpus kueri evaluasi *retrieval* berlabel (target kandidat 100–200 kueri sesuai `BRD §15.3` / `TBD-10`) dengan pemisahan ketat `DEV` (untuk *tuning* di [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md)) dan `H-G3`/`H-G4` (disimpan di penyimpanan terisolasi evaluator, `FR-RAG-006`).

### Out of Scope
- Dokumen SOP internal bank yang asli atau data nasabah/produksi (`RULE-001`).
- Mesin kueri *Hybrid RAG* (*lexical + dense + RRF + reranker*) dan *benchmark* kualitas *retrieval* (dibangun di [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md)).
- Memasukkan `scenario_id`, waktu injeksi eksak *fault*, atau label *holdout* ke dalam dokumen KB (`RULE-002`, `AT-008`).

## 4. Prerequisites
- Kontrak metadata *chunk* KB (`chunk_id`, `document_id`, `document_version`, `title`, `source_uri`, `section_path`, `service.name`, `environment`, `status`, `effective_from`, `effective_to`, `classification`, `allowed_groups`, `content_hash`, `updated_at`) dan aturan siklus hidup dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.
- Katalog skenario [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md) dan *Service Catalog* 5 layanan dari [C05](05-TELEMETRY-AND-SERVICE-CATALOG.md) tersedia sebagai acuan penulisan SOP.
- Rute model *embedding* lokal gratis (`FastEmbed` / `sentence-transformers` sesuai `TBD-04`) dan kandidat *search engine* (`TBD-06`) siap dikonfigurasi di dalam batas memori 8 GiB RAM (`TBD-03`); versi model spesifik dikunci sebelum *ingestion* dijalankan.

## 5. Implementation Roadmap
1. **Penyusunan Korpus Dokumen Sintetis Multi-Versi dan Multi-Layanan (`FR-RAG-001`)**
   - *Apa yang harus dilakukan:* Tulis dokumen SOP/runbook, *known errors*, catatan arsitektur, dan *post-mortem* sintetis untuk kelima layanan (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`), termasuk pasangan dokumen dengan kode error identik lintas layanan (`RAG-02`), dokumen `restricted` khusus grup tertentu (`SEC-01`), dan versi SOP usang vs aktif (`SC-10`, `RAG-01`).
   - *Mengapa diperlukan:* Menyediakan materi uji yang representatif bagi fitur pencarian hibrida serta pengujian negatif otorisasi dan keusangan dokumen.
   - *Expected output:* Repositori dokumen sumber Markdown/JSON sintetis beserta `corpus-manifest` berversi.
   - *Cara memverifikasi:* Periksa bahwa setiap layanan di *Service Catalog* memiliki dokumen terkait, dan pastikan pemindaian teks membuktikan tidak ada referensi ke `scenario_id` atau kunci jawaban *ground truth* (`AT-008`).
2. **Validasi Metadata, Kanonikalisasi, dan Redaksi Pre-Ingestion (`SEC-03`, `RULE-005`)**
   - *Apa yang harus dilakukan:* Bangun tahap validasi *pre-ingestion* yang menolak dokumen tanpa metadata wajib (`document_id`, `document_version`, `service.name`, `environment`, `status`, `effective_from`, `effective_to`, `classification`, `allowed_groups`) serta menjalankan *sanitizer* untuk menyamarkan *synthetic PII/secret fixtures* sebelum teks di-*chunk* atau di-*embed*.
   - *Mengapa diperlukan:* Mencegah kebocoran *secret/PII fixture* ke vektor/indeks (`SEC-03`, `NFR-012`) dan menjamin filter *applicability* memiliki atribut yang lengkap.
   - *Expected output:* Modul validator/redaktor *ingestion* dan laporan `ingestion-redaction-report`.
   - *Cara memverifikasi:* Umpankan dokumen uji yang berisi *synthetic secret/PII* dan metadata tidak lengkap; pastikan dokumen cacat ditolak dan *secret* tersamarkan 100% sebelum masuk ke tahap *chunking*.
3. **Implementasi Structure-Aware Chunking dan Provenance Hashing (`FR-RAG-002`)**
   - *Apa yang harus dilakukan:* Potong dokumen berdasarkan struktur bagian/langkah SOP dan tabel (uji rentang kandidat 350–700 token dengan *overlap* 50–100 token sesuai `ADR-S04`), lalu bangkitkan `chunk_id` deterministik, `section_path`, `source_uri` lokal, dan `content_hash` (SHA-256).
   - *Mengapa diperlukan:* Mempertahankan keutuhan prosedur operasional saat dikutip di dalam dossier (`FR-RAG-005`) dan menjamin reproduktifitas indeks (`BRD §13.2`).
   - *Expected output:* Artefak *chunks* terstruktur beserta daftar `chunk-hashes`.
   - *Cara memverifikasi:* Jalankan proses *chunking* dua kali pada korpus yang sama dan pastikan `chunk_id` serta `content_hash` yang dihasilkan identik 100%.
4. **Pengindeksan Berversi, Lifecycle Update/Delete/Tombstone, dan Rollback (`FR-RAG-008`)**
   - *Apa yang harus dilakukan:* Bangun alur *staging index $\rightarrow$ quality check $\rightarrow$ publish version/alias*, serta dukung pembaruan versi dokumen (mengubah versi lama menjadi `obsolete`), penghapusan/*tombstone* yang membersihkan entri di seluruh indeks/cache, dan *rollback* ke versi indeks sebelumnya.
   - *Mengapa diperlukan:* Menjamin dokumen yang telah dicabut atau diganti tidak tertinggal sebagai dokumen `current` di indeks maupun cache (`RAG-01`, `AT-007`).
   - *Expected output:* Skrip manajemen siklus hidup indeks dan rekaman uji `publish-delete-rollback-record`.
   - *Cara memverifikasi:* Publikasikan versi baru sebuah SOP, verifikasi versi lama otomatis berstatus non-aktif/`obsolete`, uji penghapusan dokumen, lalu uji *rollback* dan cek konsistensi hash manifes.
5. **Pembuatan dan Isolasi Dataset Kueri Evaluasi Retrieval (`FR-RAG-006`)**
   - *Apa yang harus dilakukan:* Susun himpunan kueri evaluasi *retrieval* beserta label relevansi dokumen/bagian dan bagi ke dalam split `DEV` (untuk eksperimen [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md)) serta split terkunci `H-G3` dan `H-G4` pada penyimpanan terisolasi evaluator.
   - *Mengapa diperlukan:* Mencegah *data leakage* dan *overfitting* parameter pencarian terhadap kueri evaluasi final (`NFR-019`, `RISK-01`).
   - *Expected output:* Manifes split kueri di penyimpanan evaluator terisolasi dan bukti pengecualian *holdout* dari QA indeks.
   - *Cara memverifikasi:* Pastikan skrip *ingestion* dan *tuning* di runtime tidak memiliki akses baca ke berkas kueri `H-G3`/`H-G4`.

## 6. Expected Deliverables
- Korpus dokumen sintetis berversi (SOP, *runbook*, *known errors*, *architecture notes*, *post-mortem*) yang mencakup kasus `current`, `obsolete` (`SC-10`), `restricted` (`SEC-01`), dan multi-layanan (`RAG-02`).
- *Pipeline ingestion* deterministik dengan fitur validasi skema, redaksi `SEC-03`, *chunking*, *embedding*, serta siklus hidup *publish/update/delete/rollback*.
- Dataset kueri evaluasi *retrieval* yang dipisahkan antara `DEV` dan `HOLDOUT` (`H-G3`/`H-G4` terisolasi).
- Paket bukti tersanitasi `E06` pada `evidence/<run_id>/C06/`: `corpus-manifest`, `ingestion-redaction-report`, `chunk-hashes`, dan `publish-delete-rollback-record`.

## 7. Validation & Exit Criteria
- Seluruh dokumen yang terindeks memiliki metadata wajib lengkap (`FR-RAG-001`, `FR-RAG-002`) dan `content_hash` yang dapat direproduksi ulang dari sumber.
- Pemeriksaan `SEC-03` tahap *ingestion* membuktikan 0 *synthetic PII/secret fixture* lolos tanpa redaksi ke dalam *chunk* atau vektor *embedding*.
- Siklus hidup `FR-RAG-008` (pembaruan versi SOP, *obsolete transition* `SC-10`, penghapusan/*tombstone*, dan *rollback*) terbukti konsisten tanpa menyisakan dokumen lama berstatus `current`.
- Pemeriksaan `AT-008` tahap KB membuktikan tidak ada dokumen/chunk yang memuat label *ground truth* atau daftar kueri `H-G3`/`H-G4`.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Dokumen sintetis terlalu generik atau sebaliknya secara tidak sengaja memuat petunjuk jawaban skenario *holdout* (`RISK-02`, `RISK-04`); mitigasi dengan audit silang terhadap `scenario-manifest` [C04](04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md).
- **Open Decisions:** Pemilihan final arsitektur indeks (`TBD-06`: Qdrant+BM25 vs Qdrant-native hybrid), parameter final *chunking/top-K* (`ADR-S04`), dan ukuran sampel eksak korpus evaluasi (`TBD-10`) dievaluasi di [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md) dan dikunci pada Gate G1 ([C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)).
- **Handover ke [C07](07-HYBRID-RETRIEVAL-AND-BASELINES.md):** Indeks KB berversi yang telah terisi korpus sintetis tersanitasi, manifes hash *chunk*, serta split kueri `DEV` untuk *benchmark* mode *retrieval*.

