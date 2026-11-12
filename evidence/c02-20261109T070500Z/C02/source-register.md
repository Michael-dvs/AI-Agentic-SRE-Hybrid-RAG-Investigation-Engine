# Source and Decision Register — Chapter C02 (Architecture, Contracts, and Evaluation Design)

- **Run ID:** `c02-20261109T070500Z`
- **Snapshot Timestamp (UTC):** `2026-11-09T07:05:00Z` (`2026-11-09T14:05:00+07:00` WIB)
- **Upstream Handover Reference:** `evidence/c01-20261109T043813Z/C01/handover-to-c02.md` (`Gate G0 = PASS`)
- **Hash Manifest Pointer:** `source-hashes.sha256` (SHA-256 via `/usr/bin/shasum -a 256`)
- **Authority Reference (`owner_ref`):** `project-initiator-michael`

---

## 1. Urutan Otoritas Sumber (`Source Precedence`)

Sesuai `AGENTS.md` §2 dan `docs/roadmap/phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md` §1.1:
1. **Keputusan eksplisit pemilik proyek (`project-initiator-michael`)**, termasuk baseline Gate `G0` (`E01`) dan tabel *Confirmed Project Decisions* pada penugasan C02.
2. **BRD Simulasi PoC v1.0** (`BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md`).
3. **Master Implementation Roadmap v0.1** (`docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md`).
4. **Proposal Teknis Revisi 2.0** (`Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx`), termasuk 12 *acceptance tests* asli pada Lampiran A.
5. **Playbook Chapter C01 & C02** (`01-SCOPE-DECISIONS-AND-G0.md` dan `02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md`).

---

## 2. Inventaris Berkas Sumber & Rekonsiliasi Checksum SHA-256

| Kode | Path Aktual di Repository | Versi | Status Sumber | SHA-256 Checksum (`source-hashes.sha256`) | Catatan Rekonsiliasi terhadap `E01` |
|---|---|---|---|---|---|
| `AG` | `AGENTS.md` | `1.0` | Pedoman Operasional Repository (`APPROVED`) | `e1f6726f3cd507fa3294856aff038821fda5ead1d6580aa17469dfed587f6320` | Mengikat seluruh batas keselamatan simulasi dan larangan *write/GT leak* |
| `B` | `BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md` | `1.0` | Baseline Kebutuhan Simulasi (`CONFIRMED` scope lab) | `eafc44b7f7cb24aed9cb5dcc4f061590ab3e0cc22a7327e373f3316829d6c59f` | **Identik 100%** dengan hash pada `E01/source-hashes.sha256` |
| `P` | `Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx` | `2.0` | Referensi Konsep & 12 Test Lampiran A (`SOURCE`) | `844d435837ec39c30f4da272af64cb66d0c37d4ab4fb1c06813918bcb26b93f0` | **Identik 100%** dengan hash pada `E01/source-hashes.sha256` |
| `M` | `docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md` | `0.1` | Master Roadmap (`APPROVED` struktur 24 chapter) | `95366b781e809424e8be37c064e474d2e58206a743c17eaf48554544e1fd72fc` | **Identik 100%** dengan hash pada `E01/source-hashes.sha256` |
| `C01` | `docs/roadmap/phase-1-foundation/01-SCOPE-DECISIONS-AND-G0.md` | `0.1` | Playbook C01 (`APPROVED` & dieksekusi di `E01`) | `dd8b94c7ef18db36df36f214959b317770e327a2c55492e7cea68c19e2b3d5b4` | Saat `E01` dijalankan, berkas berada di `docs/roadmap/01-SCOPE-DECISIONS-AND-G0.md` (`85e4a0f2...`). Setelah penataan direktori per fase (`phase-1-foundation/`), 3 tautan relatif disesuaikan dengan `../` tanpa perubahan substansi sedikit pun (terbukti rekonstruksi hash = `85e4a0f2...`) |
| `C02` | `docs/roadmap/phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md` | `0.1` | Playbook Eksekusi C02 (`APPROVED FOR EXECUTION`) | `58100302661569e3a37dfc90ad0f848fd4bee93afe963033eafe4c8266e56d94` | Playbook otoritatif untuk seluruh Step 01 s/d Step 12 pada paket `E02` ini |
| `C03` | `docs/roadmap/phase-1-foundation/03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md` | `0.1` | Target Handover Berikutnya (`DOCUMENTED`) | `2b17ee6921b741b19aafe0944089c7f90ed527823812d210f5d511565d261e2d` | Menjadi konsumen langsung dari kontrak layanan dan `ADR-S01` yang dibekukan di `C02` |

*Catatan Dokumen Kontrol:* `docs/roadmap/DOCUMENT-MANIFEST.md` (hash awal pra-pembaruan C02: `d7b9af6cc27b5be92853f7d06863ecfb05af3deddfa50afe425a9b67e31255c4`) dan `docs/roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md` (hash awal pra-pembaruan C02: `1429e063138cd6de4dd1366721d66377403b9351b9d4ec30ec5cfeee9243fb5f`) diperbarui pada akhir eksekusi C02 untuk mencatat artefak `E02` dan `ADR-S01`–`S08`.

---

## 3. Keputusan Terkonfirmasi Pemilik Proyek (`Confirmed Project Owner Decisions`)

Keputusan berikut telah dikonfirmasi secara eksplisit oleh pemilik proyek (`project-initiator-michael`) untuk memandu arsitektur dan kontrak C02:

| Decision Area | Nilai Terpilih (`Selected Value`) | Status Otorisasi | Implikasi Langsung pada Kontrak & ADR C02 |
|---|---|---|---|
| **Development OS & CPU** | `macOS` pada `Apple Silicon (arm64)` | `CONFIRMED` | Seluruh image Docker Compose wajib mendukung multi-arch / `linux/arm64` native tanpa emulasi Rosetta x86_64 yang boros memori |
| **System RAM & Lab Allocation** | `16 GB` unified memory host; **maks `8 GiB` (`8589934592` bytes) untuk Docker Lab** (`TBD-03`) | `CONFIRMED` | Memerlukan arsitektur *resource-conscious*, *memory limits* ketat per kontainer, dan desain *Docker Compose profiles* agar layanan inti tidak terganggu komponen opsional berat |
| **Deployment Runtime** | `Docker Compose` pada Mac lokal | `CONFIRMED` | Ditetapkan dalam `ADR-S01` dan `plans/operations-contract.md` |
| **Service Language & Framework** | `Python 3.12` + `FastAPI` | `CONFIRMED` | Ditetapkan dalam `ADR-S01` (`ACCEPTED`) dan `service-api-design.md` untuk kelima layanan simulasi (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) |
| **Observability Stack** | `Prometheus` (metrics) + `Loki` (logs) + `Tempo` (traces) + `Grafana` (visualisasi) dengan instrumentasi `OpenTelemetry` | `SELECTED; capacity validation pending` | Ditetapkan dalam `ADR-S02` (`ACCEPTED` untuk arsitektur & kontrak query; validasi retensi/memori aktual diverifikasi di `C05`/`C08`). Grafana hanya untuk visualisasi, **bukan** *system of record* |
| **Workflow Orchestration** | `Dify-first` | `CANDIDATE; requires capability evaluation` | Dijadikan kandidat utama pada rencana spike `C08` (`plans/c08-orchestrator-spike.md` & `ADR-TBD05`), diuji terhadap 10 syarat wajib dan plafon RAM 8 GiB dibanding alternatif coordinator ringan (`LangGraph` / *Custom Python State Machine*) |
| **Hybrid RAG Architecture** | `Qdrant-native dense + sparse` | `SELECTED APPROACH; implementation details pending` | Mengeliminasi kebutuhan klaster Elasticsearch terpisah (menghemat ~2–4 GiB JVM heap pada Mac 16 GB). Detail model dense/sparse (BM25/SPLADE), chunking, RRF fusion, dan reranker dievaluasi pada `DEV` split di `C06`–`C07` (`ADR-S04`, `TBD-06`) dengan tetap mempertahankan pembanding *dense-only* dan *sparse-only* |
| **LLM Strategy** | **Free remote model primary $\rightarrow$ Local model fallback (`Ollama <=3B`) $\rightarrow$ Controlled manual/deterministic fallback** | `CONFIRMED POLICY; providers/models TBD` | Kontrak abstraksi router model provider-independen ditetapkan di `C02` (`ADR-S06`, `workflow-contract.md`). Tidak ada pemanggilan model eksternal atau unduhan model lokal pada eksekusi `C02` |
| **Budget & Licensing** | `$0.00` (Zero paid software/API usage; open-source permissive / community free preference) | `CONFIRMED` | Mengikat seluruh pemilihan komponen pada `ADR-S01` s/d `ADR-S08` (`TBD-09`, `TBD-12`) |
| **Execution & Approval Authority** | Individual execution oleh `project-initiator-michael` (User / Project Initiator) | `CONFIRMED` | Otoritas sah untuk PoC lab mandiri; tidak mengklaim validasi SME independen atau otorisasi produksi bank (`TBD-01`, `TBD-02`, `TBD-08`) |
