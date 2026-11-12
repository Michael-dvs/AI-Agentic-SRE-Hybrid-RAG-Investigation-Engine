# AGENTS.md — AI Agentic SRE & RAG Investigation Engine

> **Berlaku untuk:** seluruh repository dan seluruh subdirektori, kecuali ada `AGENTS.md` yang lebih spesifik dan tidak bertentangan dengan batasan keselamatan proyek ini.  
> **Tujuan:** pedoman operasional bagi Codex/agen pengembang untuk menyusun dokumentasi *chapter-by-chapter*, mengimplementasikan simulasi secara terkendali, dan membuktikan hasil melalui acceptance test.  
> **Bahasa kerja:** Bahasa Indonesia untuk dokumentasi dan laporan; nama API, identifier, nama file, konfigurasi, dan istilah teknis dapat menggunakan bahasa Inggris.  
> **Status:** panduan kerja repository; **bukan** bukti persetujuan BRD, penyelesaian chapter, kelulusan gate, ataupun kesiapan produksi.

## 1. Misi proyek dan batas yang tidak boleh diubah

Proyek ini adalah **AI Agentic SRE & RAG Investigation Engine — Scaled-Down Simulation Proof of Concept**. Bangun **maket digital fungsional** yang menyerupai alur investigasi insiden microservices di lingkungan enterprise dalam skala kecil dan terisolasi. Tujuan utamanya adalah **memvalidasi konsep**, mengukur manfaat dan keterbatasan, serta menghasilkan bukti untuk keputusan `GO` / `CONDITIONAL GO` / `NO-GO` menuju studi lanjutan—**bukan** mendapatkan izin deployment produksi.

**Keputusan konteks yang telah dikonfirmasi:**

- Gunakan pendekatan **Hybrid Self-Built Simulation**.
- Bangun sendiri **microservices simulasi**, traffic generator, fault injection, telemetry fixtures, tool adapters, RAG pipeline, dan logika investigasi agentic.
- Boleh menggunakan platform/framework pendukung yang sudah ada, misalnya Qdrant, OpenTelemetry, Elasticsearch, Dify, Langfuse, atau alternatif yang diputuskan melalui evaluasi/ADR; **nama-nama ini tidak semuanya merupakan pilihan final**.
- Seluruh layanan, insiden, dokumen, akun, event, dan data transaksi adalah **sintetis/dummy**.
- Agent hanya menyelidiki melalui **tool observasi read-only**; semua tindakan perubahan keadaan oleh agent berada di luar ruang lingkup.
- Hasil investigasi berbentuk **Incident Investigation/Handover Dossier** yang menyajikan bukti, hipotesis, kontradiksi, ketidakpastian, rujukan SOP/runbook, dan *human review*.
- Keberhasilan simulasi **tidak** membuktikan produksi enterprise siap digunakan, kepatuhan regulasi, integrasi perbankan yang teruji, atau generalisasi pada insiden nyata.

**Larangan absolut:**

1. Jangan akses, sambungkan, pindahkan, atau gunakan sistem produksi bank, kredensial organisasi, data nasabah, log transaksi asli, atau PII asli.
2. Jangan membuka kemampuan `restart`, `deploy`, `write`, `scale`, menjalankan shell/SQL arbitrer, atau auto-remediation kepada agent investigator.
3. Jangan memberi agent, tool investigator, prompt, log yang dilihat agent, atau RAG index akses ke **ground truth fault injection** dan label holdout evaluator.
4. Jangan mengklaim root cause **pasti terbukti** tanpa aturan verifikasi yang disetujui; jangan mengarang log, metric, trace, API result, SOP, sumber, atau sitasi.
5. Jangan menganggap target KPI, pilihan teknologi, durasi 16 minggu, angka kapasitas, atau otorisasi sponsor yang berstatus **PROPOSED/TBD** sebagai keputusan final.
6. Jangan menyatakan sebuah gate `PASSED`, sebuah tes `PASS`, atau sebuah chapter `IMPLEMENTED/VERIFIED` tanpa bukti pengujian yang benar-benar dijalankan.

## 2. Sumber acuan dan resolusi konflik

Sebelum memulai **setiap tugas substantif**, temukan dan baca sumber relevan yang *benar-benar ada* di repository:

| Sumber | Lokasi yang diharapkan / cara menemukan | Peran |
|---|---|---|
| BRD simulasi | `BRD.md` atau `BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md` | Tujuan, scope, requirement `BR-*`, `FR-*`, `NFR-*`, aturan `RULE-*`, skenario, dan UAT `AT-*` |
| Proposal teknis v2.0 | `Proposal-v2.0.docx` atau berkas dengan judul `Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0*.docx` | Referensi arsitektur dan **12 acceptance test asli** dari Lampiran A |
| Master Roadmap | `docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md` | Urutan fase/chapter, dependensi, deliverable, gate dan baseline jadwal kerja setelah disetujui |
| Document Manifest | `docs/roadmap/DOCUMENT-MANIFEST.md` | Inventaris dokumen, file aktual, status dokumentasi dan implementasi, batch pekerjaan |
| RTM | `docs/roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md` | Keterlacakan requirement → chapter → test → evidence |
| Gate specifications | `docs/gates/G0-*.md` sampai `G4-*.md` | Persyaratan masuk/keluar fase dan bukti keputusan |
| ADR dan chapter yang disetujui | `docs/decisions/`, `docs/phase-*/` | Keputusan teknis yang berlaku dan kontrak dari langkah terdahulu |

- Nama/path di atas adalah **konvensi target**, bukan bukti file telah tersedia. Periksa filesystem terlebih dahulu; jangan membuat isi fiktif jika sumber belum ditemukan.
- Jika proposal DOCX belum bisa dibaca oleh tool yang tersedia, nyatakan hambatan dan jangan mengarang isi/ID pengujian. Jangan mengganti sumber dengan pengetahuan umum.
- **Otoritas:** keputusan eksplisit yang telah disetujui pemilik proyek > ruang lingkup/kebutuhan BRD > urutan implementasi pada Master Roadmap yang disetujui > referensi teknis proposal > rekomendasi Codex. **Namun, saat terjadi konflik substantif, berhenti pada bagian terdampak, catat konflik dan usulkan resolusi; jangan otomatis menimpa salah satu dokumen.**
- Label keputusan harus dipertahankan: `CONFIRMED`, `SOURCE`, `PROPOSED`, `TBD`. Rekomendasi Codex tidak berubah menjadi `CONFIRMED` tanpa persetujuan.
- BRD v1.0 berstatus **Draft for Stakeholder Review**. Proposal teknis telah diterima pengusul sebagai konsep; hal itu **bukan** bukti persetujuan resmi dari bank ataupun persetujuan BRD.
- Jangan mengedit BRD, proposal, Master Roadmap, RTM yang disetujui, atau gate criteria tanpa permintaan eksplisit. Untuk perubahan penting, catat dampak dan minta keputusan dahulu.

## 3. Cara kerja Codex: kenali mode tugas

Tentukan mode dari instruksi pengguna **sebelum** mengubah repository:

| Mode | Boleh dilakukan | Jangan dilakukan |
|---|---|---|
| **Planning / Audit** | Membaca sumber, memetakan kebutuhan, mengidentifikasi gap dan dependensi, membuat dokumen kontrol jika diminta | Menginstal/deploy aplikasi, mengubah scope tanpa izin, mengklaim tes lulus |
| **Chapter Authoring** | Menulis/merevisi Markdown chapter yang diminta, contoh kode/konfigurasi dalam *fenced code block*, review tautan dan requirement mapping | Membuat kode aplikasi, menjalankan fault injection atau mengganti keputusan final |
| **Implementation** | Menulis kode/config khusus chapter yang diotorisasi, menjalankan tes aman di lab, mencatat evidence | Melompat chapter/gate, menyentuh produksi, melakukan operasi destruktif yang tidak disetujui |
| **Verification / Gate Review** | Mengeksekusi tes yang diizinkan, memeriksa bukti, mencatat hasil dan kegagalan, mengusulkan keputusan | Mengisi bukti palsu atau meluluskan gate tanpa reviewer/otoritas yang sesuai |

**Default apabila permintaan ambigu:** lakukan audit/read-only, usulkan perubahan; jangan melakukan tindakan berisiko atau mengasumsikan perintah untuk implementasi. Instruksi eksplisit pengguna dapat memilih satu chapter atau satu batch tertentu; **jangan membuat 21 chapter sekaligus tanpa perintah**. Jika diminta mengerjakan satu chapter, selesaikan satu chapter lalu berhenti pada batas tugas tersebut.

Untuk setiap tugas:

1. Baca instruksi ini, dokumen sumber, status manifest/RTM, dan chapter dependensi.
2. Nyatakan tujuan, mode, batas file, dependensi, dan kemungkinan blocker secara ringkas.
3. Verifikasi prerequisite, state gate, dan keputusan yang diperlukan; tandai blocker `TBD`.
4. Lakukan **hanya** perubahan yang relevan dengan tugas.
5. Validasi hasil dengan cara yang diizinkan pada mode tersebut.
6. Perbarui manifest/RTM **jika diizinkan dan file tersedia**; jangan menaikkan status approval secara otomatis.
7. Laporkan file yang dibuat/diubah, hasil verifikasi nyata, sisa risiko, dan tindakan berikutnya.

## 4. Roadmap, 21 chapter, dan lima gate

Struktur kerja di bawah mengikuti **rancangan 21 chapter yang telah dibahas**. Nama, dependensi, dan pengelompokan akhir ditentukan oleh **Master Implementation Roadmap yang disetujui**; jangan menganggap daftar ini lebih tinggi dari dokumen tersebut.

| Phase | Chapter | Fokus pekerjaan |
|---|---|---|
| **P1 — Foundation** | 01–06 | 01 Project Setup & Environment; 02 Simulated Microservices & Service Inventory; 03 Synthetic Logs & Fault Injection; 04 Knowledge Base & Qdrant; 05 Hybrid RAG & Retrieval Evaluation; 06 MCP Security Contracts |
| **P2 — Controlled Integration** | 07–11 | 07 Observability & Alert Pipeline; 08 MCP Read-Only Tool Adapters; 09 Alert Intake & Event Correlation; 10 Agentic Workflow Orchestration; 11 Service Dependency Mapping |
| **P3 — Reasoning & Observability** | 12–16 | 12 LLM Integration & Agent Reasoning; 13 Evidence Correlation & Validation; 14 Incident Handover Dossier; 15 Langfuse & Audit Trail; 16 Human Review & Guardrails |
| **P4 — Pilot & Hardening** | 17–21 | 17 Incident Scenario Test Suite; 18 Acceptance Test Execution; 19 Performance, Security & Resilience; 20 End-to-End Demonstration; 21 Evaluation Report & Concept Approval |

**Gate** adalah titik keputusan, **bukan** chapter implementasi:

- **G0 — Project Initiation & Readiness:** scope simulasi, data sintetis, peran, kemampuan lab, budget cap/LLM, pendekatan evaluasi dan isu pemblokir disepakati.
- **G1 — Foundation:** layanan simulasi terhubung, fault injection dan ground-truth terpisah, telemetry dasar, KB versi aktif/kadaluarsa, baseline retrieval yang dapat diulang.
- **G2 — Controlled Integration:** alur alert sampai **draft** dossier berfungsi, tool read-only, error/fallback, pemisahan ground-truth, replay terkontrol.
- **G3 — Reasoning & Observability:** validator bukti, reviewer, audit, guardrail dan pengujian keamanan awal, perilaku gagal yang aman.
- **G4 — Concept Approval:** benchmark holdout, kualitas investigasi, reproducibility, biaya/limitasi, gap enterprise, dan rekomendasi keputusan konsep.

**Periksa dependensi lintas fase:** G1 memerlukan telemetry dasar meskipun chapter observability lengkap berada di P2; G2 memerlukan **draft dossier** meskipun dossier lengkap dirinci di P3; G3 memerlukan security/negative tests meskipun pengujian penerimaan komprehensif berada di P4. Rencanakan *minimum viable contract* pada fase awal dan perluasan pada fase selanjutnya, atau ajukan perubahan urutan melalui Master Roadmap. **Jangan mengabaikan kontradiksi tersebut.**

Rentang minggu 1–4, 5–8, 9–12, 13–16 dalam proposal adalah **ilustrasi**, bukan komitmen jadwal. G4 adalah **kelayakan konsep untuk langkah berikutnya**, bukan production release.

### Status yang harus dipisahkan

- **Documentation:** `NOT_STARTED` → `DRAFT` → `REVIEW_REQUIRED` → `APPROVED`.
- **Implementation:** `NOT_STARTED` → `IN_PROGRESS` → `IMPLEMENTED` → `VERIFIED`.
- **Gate:** `NOT_EVALUATED` / `BLOCKED` / `READY_FOR_REVIEW` / `PASSED` / `FAILED` / `CONDITIONAL` (sesuaikan keputusan reviewer).
- Status file Markdown `APPROVED` **tidak** membuktikan kode telah dibangun. Status tes `PASS` hanya sah jika test run dan evidence benar-benar ada.

## 5. Standar dokumentasi chapter dan pengendalian proyek

Setiap chapter `.md` harus menjadi **panduan kerja operasional step-by-step**, bukan esai teori. Minimal memuat:

1. **Chapter metadata:** ID, phase, version, status dokumentasi/implementasi terpisah, owner `TBD` bila belum ditetapkan, prerequisite, related `BR/FR/NFR/RULE`, related test IDs.
2. **Objective, expected outcome, scope, exclusions**, dan beda self-built vs third-party.
3. **Prerequisites checklist** dan metode memastikan kesiapan.
4. **Architecture, data flow, contracts**, serta diagram Mermaid bila membantu.
5. **Step-by-step implementation** dengan urutan yang tidak ambigu. **Setiap step** berisi: objective, alasan, actions, file/folder, konfigurasi, perintah (bila relevan), expected output, validation, troubleshooting, evidence.
6. **Interfaces & integration:** typed input/output, auth/scope, timeout, retry, failure/error codes.
7. **Testing:** positive/negative cases, prasyarat, input, langkah uji, expected result, kriteria pass/fail, bukti.
8. **Acceptance test mapping:** rujukan ID proposal dan BRD, tidak hanya narasi umum.
9. **Deliverables / artifact paths**, Definition of Done, rollback/cleanup, risiko/TBD, handover ke chapter berikutnya.

**Kualitas isi:**

- Nyatakan langkah terminal yang *dapat dijalankan*, tetapi jangan menyebutnya sudah berhasil jika belum dieksekusi.
- Contoh output, path, endpoint, angka resource, dan versi package yang belum diverifikasi harus jelas diberi label `contoh`/`TBD`.
- Cantumkan file yang benar-benar perlu dibuat; jangan mengarang struktur proyek yang bertentangan dengan repository.
- Gunakan tautan relatif yang valid, ID konsisten, dan satu istilah untuk konsep yang sama.
- Saat menulis chapter, tautkan dependensi sebelumnya dan kontrak yang dipakai chapter berikutnya.
- Jika keputusan kritis belum tersedia, jelaskan pilihan dan konsekuensinya dalam bagian `TBD — Decision Required`; jangan diam-diam memilih.

**Dokumen kontrol:**

- `00-IMPLEMENTATION-MASTER-ROADMAP.md`: **apa, kapan, dan dependensi** chapter/gate.
- `DOCUMENT-MANIFEST.md`: **dokumen yang harus tersedia, batch, status dokumen, status implementasi, reviewer**.
- `REQUIREMENTS-TRACEABILITY-MATRIX.md`: **kebutuhan → desain/chapter → test → evidence → status**.
- `docs/decisions/ADR-*.md`: hanya untuk keputusan arsitektur yang memengaruhi banyak chapter (misalnya orchestration engine, search strategy, LLM, deployment), dengan opsi, trade-off, konsekuensi, pemilik dan status.
- Gate files `docs/gates/G0-*.md`–`G4-*.md`: specification, checklist, evidence dan keputusan reviewer. Tuliskan spesifikasi **sebelum** pengujian; jangan mengisi hasil kelulusan sebelum ada bukti.

Jangan menyisipkan seluruh isi RTM ke setiap chapter. Gunakan ID dan referensi silang. Jika `DOCUMENT-MANIFEST.md` atau RTM belum dibuat, pada tugas yang mengizinkan pembuatan dokumen kontrol, buat berdasarkan **inventaris hasil audit sumber**, bukan angka atau asumsi yang tidak diperiksa.

## 6. Arsitektur minimum dan kontrak keamanan

**Alur inti:** synthetic traffic + fault injection → simulated services → logs/metrics/traces → alert intake/correlation → controlled agent workflow → read-only telemetry tools + authorized Hybrid RAG → evidence validator → dossier → human review → **offline evaluator**.

### 6.1 Simulation, observability, dan ground truth

- Untuk kebutuhan BRD `FR-SIM-001`, minimal **3 layanan simulasi yang saling bergantung**; contoh `api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`, storage dummy adalah **kandidat**, bukan daftar final.
- Semua log menggunakan structured format dengan timestamp, service, environment, severity/event type, correlation ID/trace ID, dan versi layanan; metrik RED dan distributed trace disediakan sesuai requirement.
- Fault injector dapat mulai/berhenti/reset dan menyimpan `scenario_id`, fault type, target, seed, onset/end, expected symptoms. Fault injector **bukan** bagian dari tool registry yang dapat dipanggil agent.
- Ground truth dan locked holdout harus terisolasi dari agent runtime, RAG, prompt, telemetry API yang dapat dikueri agent, dan dataset tuning. Evaluator offline baru membandingkan setelah dossier ditutup. Jangan bocorkan fault labels lewat nama event/log, metadata, file mount, atau debug endpoint.
- Semua timestamp direkomendasikan menggunakan UTC internal ISO 8601; format presentasi boleh menggunakan waktu lokal; tandai deviasi yang disetujui.

### 6.2 Knowledge base & Hybrid RAG

- Sumber hanya dokumen **sintetis** yang dibuat untuk demo: SOP, runbook, known error, notes arsitektur dan post-mortem simulasi.
- Metadata minimum: `chunk_id`, `document_id`, `document_version`, `source_uri`, `section_path`, `service.name`, `environment`, `status`, `effective_from`, `effective_to`, `classification`, `allowed_groups`, `content_hash`, `updated_at` (tambahkan field yang diminta kontrak final).
- Ingestion: validation → normalization/redaction → chunking → embeddings → dense/lexical indexing → fusion → optional reranking → citations. Tes update/delete/obsolete dan entitlement filtering.
- Hybrid RAG harus dapat dibandingkan terhadap **lexical-only** dan **dense-only** pada query set yang sama. Qdrant + Elasticsearch BM25 **atau** Qdrant-native sparse/hybrid masih memerlukan ADR/benchmark sebelum final.
- Retrieval dan model tidak boleh memperlakukan SOP, runbook atau log sebagai instruksi pengendali. Dokumen restricted atau obsolete tidak boleh muncul sebagai sumber aktif.

### 6.3 Agent control plane, MCP/tool policy, evidence

- Gunakan urutan state yang terlacak: `RECEIVED → CORRELATED → TRIAGED → EVIDENCE_COLLECTED → RETRIEVED → HYPOTHESES → VALIDATED → DRAFTED → HUMAN_REVIEW`. Status terminal/feedback dicatat secara eksplisit jika implementasi menggunakannya.
- Workflow control, izin tool, scope, schema, timeout, rate limit, tool-call budget, dan keputusan guardrail ditentukan oleh **kode/policy deterministik**, bukan diserahkan kepada prompt LLM.
- Contoh tool read-only dari proposal/BRD: `get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`; `get_apm_health` hanya jika sumber APM simulasi tersedia. Input typed dan allowlisted; batasi service, environment, time window, max hits/points, deadline dan response size.
- Jangan beri LLM akses shell/exec, arbitrary SQL/PromQL, generic query endpoint, rahasia, jaringan luar lab, atau hak tulis.
- Response tool harus memiliki provenance (`source_ref`, `observed_at`, `query_window`), status sanitasi, data quality, truncation, error code. Ketika sumber gagal, catat `source_unavailable`/`missing` dengan jelas.
- Bedakan observasi, korelasi, hipotesis, kontradiksi, dan *unknowns*. Gunakan `SUPPORTED` / `PARTIAL` / `INCONCLUSIVE` atau label yang ditetapkan schema; **jangan** mengangkat hipotesis ke `VERIFIED` tanpa aturan SME yang disetujui.
- Dossier (JSON dan Markdown/human-readable) memuat incident, service/environment, timeline, evidence IDs, citations doc/version/section, ranked hypotheses, evidence for/against, unknowns, suggested **human-controlled** next checks, reviewer decision, serta versi workflow/model/prompt/KB.
- Langfuse boleh digunakan untuk observability kualitas AI; audit keamanan harus terpisah. Sanitasi sebelum telemetry/model logging; jangan menyimpan *hidden chain-of-thought*.

## 7. Acceptance tests: pertahankan dua namespace

**Jangan mengganti/menomori ulang test ID asli.** Terdapat **dua set pengujian yang berbeda**:

**A. Lampiran A proposal teknis v2.0 (12 ID):**

| ID | Tujuan / expected outcome ringkas |
|---|---|
| `SEC-01` | Akses SOP restricted lintas layanan ditolak; tidak bocor ke LLM/log |
| `SEC-02` | Instruksi berbahaya di log tidak mengubah policy/tool behavior |
| `SEC-03` | Synthetic PII/secret disanitasi sebelum LLM/Langfuse |
| `MCP-01` | Permintaan write/restart/deploy oleh model ditolak; tool tak tersedia |
| `MCP-02` | Query di luar maximum time window ditolak |
| `RAG-01` | SOP lama tidak dikutip sebagai versi aktif |
| `RAG-02` | Dokumen service/environment berbeda tidak tercampur |
| `EV-01` | Konflik metrics/logs menghasilkan partial/inconclusive |
| `EV-02` | Backend tracing hilang dicatat, tanpa trace imajiner |
| `OPS-01` | 100 duplicate alerts dideduplikasi dengan konsumsi resource terkendali |
| `OPS-02` | LLM outage memicu manual fallback dan audit trail tetap tersedia |
| `HUM-01` | Rekomendasi kritis harus direview L1; tidak ada auto action |

**B. BRD v1.0 (17 ID):** `AT-001` sampai `AT-017`. Ini menguji startup stack, fault/ground truth, observability, state machine, tool guardrail, retrieval, SOP validity, GT isolation, missing/contradictory evidence, dossier review, prompt injection, LLM outage, repeatability, holdout benchmark, biaya, dependency cascade dan optional dummy ITSM.

**Aturan mapping:**

1. RTM memuat **setiap** `BR-*`, `FR-*`, `NFR-*` dan `RULE-*` yang relevan ke chapter, acceptance test, verifier, lokasi evidence, dan hasil. `AT-001`–`AT-017` serta seluruh 12 ID proposal harus tercakup—boleh punya beberapa chapter penghasil/penguji.
2. Bedakan **test specification/documented**, **implemented**, **executed**, dan **passed**. Kehadiran test case tertulis tidak sama dengan pass.
3. Tambahan skenario/test dari simulasi memakai ID baru yang tidak bertabrakan, mis. `SIM-AT-001`; jangan menghapus pengujian proposal.
4. Untuk test yang belum dapat dijalankan karena dependensi, catat `NOT_RUN`/`BLOCKED`, alasan, dan chapter atau gate yang harus menanganinya.
5. Test kritis negatif harus memeriksa **penolakan dan ketiadaan side effect**, bukan hanya pesan error dari LLM.

## 8. Evaluasi, eksperimen, dan evidence

- Simpan source of truth fault injection dan holdout di path/permission terpisah. Jangan gunakan contoh holdout untuk prompt tuning, prompt fixtures, demo happy-path, atau retrieval indexing.
- Untuk evaluasi retrieval, bandingkan BM25-only, dense-only, hybrid, dan reranker (jika dipakai) pada korpus dan pertanyaan berlabel yang sama; laporkan metrik relevansi dan latency, ukuran sampel, dataset split serta metode.
- Untuk investigasi, ukur top-3 diagnosis terhadap ground truth, evidence coverage, unsupported claim rate, time-to-dossier, human reviewer acceptance, dan keberhasilan fallback; laporkan error dan kelas kegagalan, bukan hanya rerata.
- Proposal menyebut **kandidat**: Recall@5 ≥90%, evidence coverage ≥95%, unsupported material claims ≤2%, top-3 diagnosis ≥85%, L2 acceptance ≥85%, P95 intake-to-dossier ≤120 detik, median TTI turun ≥40% (hanya dengan baseline yang valid). **Angka-angka ini belum final**; benchmark formal harus menggunakan definisi/ambang yang disahkan.
- Dataset awal proposal menyarankan 100–200 query retrieval dan 30–50 incident replay bila resource memadai. Smoke test kecil **tidak** cukup sebagai klaim acceptance final.
- Setiap test run yang benar-benar dijalankan menyimpan: `run_id`, `scenario_id`, seed, code commit/version, workflow/model/prompt/KB version, environment, time, test procedure, expected vs actual, `PASS/FAIL/BLOCKED`, diagnostic output, artifact path, reviewer (jika diperlukan).
- Gunakan lokasi evidence yang disepakati, misalnya `artifacts/evidence/<run_id>/`; buat struktur ini **hanya saat diotorisasi menjalankan tes**. Jangan fabrikasi screenshot, log, angka KPI atau output tool.
- Jika sebuah tes gagal, catat defect dan efeknya terhadap acceptance/gate. Jangan menghilangkan hasil gagal dari laporan.

## 9. Aturan perubahan kode, keamanan lab, dan validasi

Dalam mode **Implementation**:

- Tinjau repository terlebih dahulu. Ikuti bahasa, formatter, struktur, test runner, dan kontrak yang sudah ada. Jika belum ada, dokumentasikan pilihan (ADR/TBD) sebelum memperkenalkan stack baru yang berpengaruh besar.
- Buat perubahan terkecil yang memenuhi chapter. Hindari refactor lintas fase yang tidak diminta dan jangan mengubah kontrak yang dipakai chapter lain tanpa pembaruan yang disetujui.
- Pisahkan komponen: simulasi/fault injector, telemetry/adapters, policy/agent, KB/RAG, offline evaluator, dossier/review.
- Simpan konfigurasi non-rahasia secara versioned; gunakan `.env.example` dengan placeholder. **Jangan commit `.env`, API key, token, service credential, dump sensitif, atau trace mengandung rahasia**. Pastikan `.gitignore` melindunginya.
- Jangan mengirim telemetry, data uji, atau secrets ke provider eksternal tanpa konfigurasi dan persetujuan scope yang eksplisit. Bila LLM eksternal digunakan, masukkan **data sintetis yang telah disanitasi** saja dan catat risiko egress/retention.
- Container/lab harus memiliki boundary yang jelas. Perintah `rm -rf`, database reset, `docker system prune`, penghapusan volume, atau operasi yang bisa merusak data di luar sandbox membutuhkan otorisasi eksplisit dan pengecekan target.
- Fault injection hanya dijalankan jika pengguna meminta implementasi/pengujian yang relevan, hanya pada layanan simulasi yang diidentifikasi. Jangan menguji endpoint produksi atau layanan publik.
- Jalankan pemeriksaan paling spesifik yang tersedia: lint/schema/unit → integration → contract/negative → end-to-end → benchmark. Jika test tidak bisa dijalankan, beri label **NOT_RUN** dan jelaskan mengapa.
- Berikan fallback aman dan alasan eksplisit ketika LLM, Qdrant, observability, atau tool backend gagal. Tidak boleh memalsukan data yang tidak tersedia.

## 10. Definition of Done dan gate governance

**Dokumentasi chapter dinyatakan siap review apabila:** isi sesuai template, seluruh prerequisite jelas, langkah dapat dijalankan, file/kontrak dan expected output dirinci, mapping BRD+proposal lengkap, contoh diberi label, tautan valid, konflik/TBD diungkap, dan tidak mengklaim tes sudah dijalankan.

**Implementasi chapter dinyatakan `VERIFIED` hanya apabila:** fitur yang diwajibkan tersedia, tes relevan benar-benar dijalankan, seluruh tes kritis lulus, evidence dapat ditinjau ulang, risiko/defect terdokumentasi, dan reviewer berwenang menerima hasil jika disyaratkan.

**Gate dinyatakan `PASSED` hanya apabila:** kriteria gate yang disetujui terpenuhi, bukti ada, blocker kritis terselesaikan, dan keputusan reviewer/owner direkam. Kegagalan isolasi ground truth, kemampuan write oleh investigator, kebocoran data/fixture yang seharusnya disanitasi, atau bukti kritis yang dikarang adalah **blocker / NO-GO** sesuai BRD.

**Jika gate belum disetujui:** agent boleh membuat rencana/analisis untuk fase berikutnya tetapi tidak boleh menganggap implementasi fase berikutnya telah diotorisasi. Jangan menaikkan status gate sendiri.

## 11. Format laporan akhir Codex untuk setiap tugas

Selalu akhiri pekerjaan dengan ringkasan ringkas dan dapat diaudit:

1. **Mode & scope:** planning / documentation / implementation / verification; chapter/batch yang ditangani.
2. **Files:** path file baru/diubah; jelaskan jika ada dokumen yang tidak bisa diakses.
3. **What changed:** deliverable konkret dan alasan.
4. **Requirements/tests:** IDs terkait dan status sebenarnya (`SPECIFIED`, `NOT_RUN`, `PASS`, `FAIL`, `BLOCKED`).
5. **Validation:** command/check yang benar-benar dijalankan beserta hasil; jangan mengarang hasil.
6. **Open decisions:** `TBD`, konflik sumber, risiko, dan dependensi yang menghalangi.
7. **Next step:** chapter/gate berikutnya sesuai roadmap dan syarat untuk melanjutkan.

**Prinsip kerja terakhir:** *read sources → respect scope → follow chapter dependencies → implement only what is authorized → test against original acceptance IDs → preserve evidence → request human decision at gates*. Proyek ini adalah **PoC simulasi untuk pembuktian konsep**, bukan proyek integrasi produksi.
