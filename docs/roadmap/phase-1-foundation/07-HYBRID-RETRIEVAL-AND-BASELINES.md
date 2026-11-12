# C07 — Hybrid Retrieval and Baselines

## 1. Chapter Information
- **Phase:** F1 — Foundation
- **Status:** APPROVED
- **Documentation status:** APPROVED
- **Implementation status:** VERIFIED (Paket Bukti E07; 10/10 pytest PASS; 28 DEV Benchmark 100% Hit@5; RSS 6.89 MiB)
- **Dependencies:** [C02 — Architecture, Contracts, and Evaluation Design](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md), [C06 — Synthetic Knowledge and Ingestion](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md), evaluasi `TBD-06` (arsitektur Hybrid RAG) dan `ADR-S04` (parameter RRF fusion, reranker, top-K)
- **Next chapter:** [C08 — Secure Gateway and Foundation G1](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)
- **Related requirements:** `BR-004`, `BR-011`, `FR-RAG-003`, `FR-RAG-004`, `FR-RAG-005`, `FR-RAG-007`, `FR-RAG-008`, `FR-RAG-009`, `RULE-004`, `RULE-005`, `NFR-004`, `NFR-008`, `NFR-016`, `KPI-05`, `KPI-11`, `OBJ-04`, `BEN-04`, `RISK-04`, `SC-10`, `UC-08`
- **Related acceptance tests:** `AT-006` (build & test owner baseline *lexical/dense/hybrid* pada split `DEV`; evaluasi *holdout* di C18/C21), `AT-007` (build & test owner tahap *retrieval*; verifikasi akhir dossier di C14/C18/C21), `RAG-01` (build & test owner pencegahan kutipan SOP *obsolete*), `RAG-02` (build & test owner isolasi *service/environment*), `SEC-01` (build & test owner sisi *retrieval* untuk pemblokiran dokumen *restricted* sebelum *reranker*/konteks)

## 2. Objective & Expected Outcome
Chapter ini bertujuan mengimplementasikan layanan *Hybrid Retrieval* yang menggabungkan pencarian leksikal (*BM25/sparse*) dan semantik (*dense vector*) melalui *Reciprocal Rank Fusion* (RRF) serta *reranker* opsional, dilengkapi penegakan filter otorisasi dan masa berlaku dokumen secara ketat di setiap jalur pencarian. Sesuai [Master Implementation Roadmap](../00-IMPLEMENTATION-MASTER-ROADMAP.md), performa *Hybrid RAG* wajib dibandingkan secara objektif terhadap baseline *lexical-only* dan *dense-only* pada himpunan kueri yang sama (`BR-011`, `FR-RAG-003`).

Setelah chapter ini selesai, sistem memiliki API *retrieval* yang mampu mengeksekusi mode `lexical`, `dense`, `hybrid`, dan `hybrid+reranker` (`FR-RAG-003`, `FR-RAG-007`), memblokir dokumen *unauthorized* (`SEC-01`), beda layanan/environment (`RAG-02`), atau *obsolete* (`RAG-01`, `SC-10`) **sebelum** masuk ke *reranker* maupun konteks model, mengembalikan sitasi lengkap yang dapat dibuka reviewer (`FR-RAG-005`), menyatakan ketiadaan referensi secara jujur (`no_match`, `FR-RAG-009`), serta menghasilkan laporan *benchmark* komparatif pada split `DEV` sebagai bukti pemilihan `TBD-06` dan `ADR-S04` menuju Gate G1.

## 3. Scope & Boundaries
### In Scope
- Implementasi tiga mode utama pencarian (`lexical-only`, `dense-only`, `hybrid` dengan RRF) serta opsi `reranker` *on/off* di atas korpus [C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md) (`FR-RAG-003`, `FR-RAG-007`).
- Penegakan filter wajib (`allowed_groups`, `classification`, `service.name`, `environment`, `status=active`, `effective_from <= query_time <= effective_to`) secara identik pada cabang leksikal, cabang *dense*, dan *cache* sebelum penggabungan RRF atau *reranking* (`FR-RAG-004`, `RULE-005`, `D-C02-04`).
- Pemformatan hasil *retrieval* berbatas kuota (*top-K*) yang menyertakan `document_id`, `document_version`, `section_path`, `source_uri` lokal, `content_hash`, dan skor relevansi (`FR-RAG-005`).
- Penanganan kondisi `no_match` / hasil kosong dan kegagalan backend pencarian (`source_unavailable`) tanpa mengarang judul SOP fiktif (`FR-RAG-009`, `NFR-016`).
- Eksekusi *benchmark* komparatif pada split `DEV` (mengukur *query-level hit-rate@5*, *classical recall@5*, *nDCG@5*, *MRR@10*, latensi P95, dan konsumsi memori) untuk menyiapkan rekomendasi `TBD-06` dan `ADR-S04`.

### Out of Scope
- Penggunaan kueri `H-G3` atau `H-G4` untuk *tuning* bobot RRF, *chunking*, atau pemilihan arsitektur (`FR-RAG-006`, `NFR-019`).
- Klaim bahwa target kandidat `KPI-05` ($\ge 90\%$) atau `NFR-008` (P95 $\le 2\text{ s}$) telah lulus final sebelum diuji pada *locked holdout* di [C18](../phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md) dan [C21](../phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md).
- Validasi kesesuaian rekomendasi SOP terhadap bukti telemetri di dalam dossier akhir (diselesaikan di [C14](../phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md)).

## 4. Prerequisites
- Korpus sintetis berversi, indeks *staging/published*, dan split kueri `DEV` dari [C06](06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md) telah tersedia (`E06`).
- Kontrak skema kueri/respons *retrieval*, aturan *version-fencing*, dan protokol metrik dari [C02](02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) tersedia.
- Kandidat mesin pencari (`TBD-06`: Qdrant+BM25 engine vs Qdrant-native dense+sparse) siap diuji di dalam plafon alokasi Docker Compose 8 GiB RAM (`TBD-03`).

## 5. Implementation Roadmap
1. **Implementasi Mode Pencarian Lexical, Dense, dan Pre-Filter Otorisasi/Versi (`FR-RAG-003`, `FR-RAG-004`)**
   - *Apa yang harus dilakukan:* Bangun *query runner* untuk mode `lexical-only` dan `dense-only` yang menerapkan filter *server-side* atas `allowed_groups`, `service.name`, `environment`, `status`, dan rentang tanggal efektif (`effective_from`/`effective_to`) sebelum mengambil kandidat.
   - *Mengapa diperlukan:* Memastikan paritas filter di semua cabang pencarian sehingga dokumen terlarang (`SEC-01`), lintas layanan (`RAG-02`), atau kadaluarsa (`RAG-01`) tidak pernah bocor melalui salah satu indeks.
   - *Expected output:* Modul *retrieval* dengan paritas filter di cabang leksikal dan *dense*.
   - *Cara memverifikasi:* Jalankan kueri negatif untuk SOP *restricted* milik layanan lain dan SOP *obsolete* yang memiliki kemiripan kata kunci tinggi; pastikan 0 dokumen terlarang/usang muncul di kandidat kedua cabang.
2. **Implementasi Reciprocal Rank Fusion (RRF), Deduplikasi Versi, dan Reranker Opsional (`FR-RAG-007`)**
   - *Apa yang harus dilakukan:* Gabungkan kandidat *top-N* leksikal dan *top-N* *dense* (uji titik awal kandidat 30/30 $\rightarrow$ RRF $\rightarrow$ *top-5* sesuai `ADR-S04`), lakukan deduplikasi yang mempertahankan identitas `document_id + document_version + section_path`, dan tambahkan tahap *reranker* yang dapat diaktifkan/dinonaktifkan melalui konfigurasi.
   - *Mengapa diperlukan:* Meningkatkan presisi urutan sitasi sekaligus memungkinkan evaluasi ablasi *reranker on/off* sesuai kebutuhan `FR-RAG-007`.
   - *Expected output:* Pipeline *fusion* dan *reranking* terkonfigurasi yang hanya memproses kandidat yang telah lulus filter otorisasi.
   - *Cara memverifikasi:* Periksa jejak eksekusi kueri hibrida untuk memastikan *reranker* hanya menerima input yang berstatus `authorized` dan `active`.
3. **Penyusunan Envelope Sitasi Lengkap dan Penanganan No-Match / Outage (`FR-RAG-005`, `FR-RAG-009`)**
   - *Apa yang harus dilakukan:* Format setiap hasil dengan `chunk_id`, `document_id`, `document_version`, `section_path`, `source_uri` lokal, dan `content_hash`. Jika tidak ada dokumen yang melewati ambang/filter, kembalikan status `no_applicable_runbook`; jika indeks mati, kembalikan `source_unavailable`.
   - *Mengapa diperlukan:* Mendukung keterlacakan sitasi oleh reviewer manusia dan mencegah halusinasi referensi SOP saat tidak ada dokumen yang cocok (`RULE-006`).
   - *Expected output:* Kontrak respons *retrieval* lengkap dengan resolver URI lokal dan penanda *gap* eksplisit.
   - *Cara memverifikasi:* Uji kueri untuk topik di luar cakupan korpus dan uji saat indeks dimatikan sementara; pastikan respons memuat penanda eksplisit tanpa referensi fiktif.
4. **Pengujian Negatif Invalidation Cache, Siklus Hidup, dan Cross-Service Scope (`RAG-01`, `RAG-02`, `SEC-01`)**
   - *Apa yang harus dilakukan:* Uji skenario pembaruan/penghapusan dokumen pada indeks dan *query cache* (jika cache diaktifkan), kueri kode error yang sama pada dua layanan berbeda (`RAG-02`), serta upaya *bypass* grup akses (`SEC-01`).
   - *Mengapa diperlukan:* Membuktikan *version-fence* dan *entitlement key* bekerja di seluruh jalur termasuk *cache* (`D-C02-04`).
   - *Expected output:* Rekaman hasil uji negatif `filter-negative-tests` dan `citation-checks`.
   - *Cara memverifikasi:* Pastikan setelah dokumen diubah menjadi `obsolete` atau dihapus, kueri berulang tidak pernah mengembalikan versi lama dari *cache*.
5. **Eksekusi Benchmark Komparatif pada Split `DEV` dan Penyusunan Bukti ADR (`AT-006`, `TBD-06`)**
   - *Apa yang harus dilakukan:* Jalankan himpunan kueri `DEV` pada keempat konfigurasi (`lexical-only`, `dense-only`, `hybrid`, `hybrid+reranker`), catat *hit-rate@5*, *classical recall@5*, *nDCG@5*, *MRR@10*, latensi P50/P95 (`NFR-008`), serta jejak memori kontainer untuk menyusun draf keputusan `TBD-06` dan `ADR-S04`.
   - *Mengapa diperlukan:* Menyediakan bukti terukur bagi Gate G1 ([C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md)) tanpa menyentuh split `H-G3`/`H-G4`.
   - *Expected output:* Paket bukti `E07` (`retrieval-runs`, `filter-negative-tests`, `citation-checks`, `baseline-metrics`, `retrieval-adr`).
   - *Cara memverifikasi:* Pastikan seluruh mode diuji pada kueri `DEV` yang identik, semua sitasi dapat dibuka secara lokal, dan log evaluasi membuktikan 0 akses ke `H-G3`/`H-G4`.

## 6. Expected Deliverables
- Layanan/API *Hybrid Retrieval* yang mendukung mode `lexical-only`, `dense-only`, `hybrid`, dan `hybrid+reranker`.
- Enforcement filter otorisasi (`allowed_groups`), layanan (`service.name`), lingkungan (`environment`), dan masa berlaku (`status`/`effective dates`) beserta penanganan `no_match` dan `source_unavailable`.
- Laporan perbandingan baseline *retrieval* pada split `DEV` dan dokumen rekomendasi `retrieval-adr` (`TBD-06`, `ADR-S04`).
- Paket bukti tersanitasi `E07` pada `evidence/<run_id>/C07/`: `retrieval-runs`, `filter-negative-tests`, `citation-checks`, `baseline-metrics`, dan `retrieval-adr`.

## 7. Validation & Exit Criteria
- `AT-006` (tahap baseline `DEV`): Mode *lexical-only*, *dense-only*, *hybrid*, dan *hybrid+reranker* dapat dieksekusi secara deterministik pada kueri `DEV` dengan metrik relevansi, latensi, dan sitasi lengkap tercatat.
- `AT-007` & `RAG-01` (tahap *retrieval*): Saat SOP versi lama memiliki skor kemiripan leksikal/vektor lebih tinggi (`SC-10`), filter memastikan hanya SOP `current` yang berlaku yang dikembalikan sebagai konteks aktif (`KPI-11` = 0 kutipan *obsolete* aktif).
- `RAG-02` & `SEC-01` (tahap *retrieval*): Kueri untuk layanan A tidak pernah mengembalikan dokumen milik layanan B atau dokumen `restricted` di luar `allowed_groups` pemanggil, baik pada hasil akhir maupun input *reranker*.
- `FR-RAG-009`: Kueri tanpa dokumen yang cocok mengembalikan penanda `no_applicable_runbook` secara eksplisit tanpa sitasi rekaan.

## 8. Risks, Open Decisions & Handover
- **Risiko:** Menjalankan Qdrant sekaligus Elasticsearch di Docker Compose lokal berpotensi mendekati batas 8 GiB RAM (`RISK-07`); hasil profil memori pada Step 5 wajib menjadi dasar keputusan `TBD-06`.
- **Open Decisions:** Pengesahan final `TBD-06` (Qdrant+BM25 vs Qdrant-native hybrid) dan `ADR-S04` (parameter *chunking/fusion/reranker/top-K*) dibawa ke review Gate G1 pada [C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md).
- **Handover ke [C08](08-SECURE-GATEWAY-AND-FOUNDATION-G1.md):** Endpoint *retrieval* yang siap diproteksi *Secure Gateway*, hasil uji negatif ACL/versi, laporan *benchmark* `DEV` (`E07`), serta draf ADR *retrieval* untuk disahkan pada Gate G1.

