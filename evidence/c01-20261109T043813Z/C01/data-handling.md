# Data Handling, Classification, and Trust Boundary Baseline — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision References:** `TBD-13`, `TBD-04` (`APPROVED` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Approver Reference:** `project-initiator-michael`

## 1. Prinsip Umum & Klasifikasi Data

1. **Klasifikasi Data Proyek (`TBD-13`):** Seluruh dataset aplikasi pada proyek ini berstatus **`SYNTHETIC_INTERNAL_LAB`** (100% data buatan/sintetis untuk kebutuhan pembuktian konsep).
2. **Larangan Mutlak (`RULE-001`, `NFR-012`, `NFR-017`):** Dilarang keras memasukkan, menyimpan, atau memproses data nasabah (PII asli), log transaksi produksi bank, topologi jaringan internal bank, atau kredensial/secret organisasi.
3. **Perlakuan terhadap Synthetic PII/Secret Fixtures (`SEC-03`):** Meskipun nilai PII atau token di dalam log uji bersifat sintetis (contoh: nomor kartu dummy, token JWT dummy, password dummy), pipeline wajib memperlakukannya sebagai **data sensitif uji** yang harus disanitasi oleh redactor deterministik sebelum masuk ke index embedding, prompt LLM, AI observability sink (Langfuse/setara), maupun paket ekspor. Jika proses sanitasi gagal, payload wajib **diblokir (`FAIL_CLOSED`)** disertai event audit; dilarang melakukan fallback ke payload mentah.

## 2. Evaluasi Penyimpanan Cloud-Synced Workspace (`Google Drive`)

- Direktori kerja proyek berada pada path lokal yang disinkronkan ke Google Drive pribadi milik pemilik proyek (`project-initiator-michael`).
- **Kebijakan Sink yang Disahkan (`TBD-13`):**
  - Dokumen kode sumber, konfigurasi non-rahasia, korpus SOP sintetis, serta paket evidence tersanitasi (`evidence/<run_id>/...`) **diizinkan** disimpan pada workspace ini karena 100% sintetis dan milik pribadi Project Owner.
  - **Larangan Kredensial di Cloud-Synced Folder:** Berkas `.env`, API key provider LLM, token autentikasi gateway, atau kredensial akun **dilarang keras** disimpan dalam bentuk plaintext di repository atau di dalam folder `evidence/`. Kredensial runtime nantinya wajib disuntikkan melalui variabel lingkungan sesi lokal atau lokasi di luar folder sinkronisasi/dilindungi `.gitignore`.

## 3. Matriks Kelompok Data, Pembaca, Sink, & Retensi (BRD §13)

| Data Group | Sumber | Pembaca & Sink yang Diizinkan (`Allowed Readers / Sinks`) | Jalur Terlarang (`Forbidden Paths`) | Aturan Retensi & Penghapusan (`TBD-13`) | Owner & Status Approval |
|---|---|---|---|---|---|
| **1. Scenario Registry & Ground Truth Labels** | Fault injector harness & evaluator setup | Hanya **Fault Harness** dan **Offline Evaluator** (join dilakukan hanya setelah status investigasi `CLOSED`) | **DILARANG KERAS** diakses oleh agent runtime, tool adapters, RAG ingestion/index, prompt LLM, AI tracing sink, atau paket demo publik (`RULE-002`, `AT-008`) | Disimpan selama PoC aktif + 30 hari pasca keputusan G4; versi per-run bersifat *append-only / immutable* | `project-initiator-michael` / `APPROVED` |
| **2. Evaluation Holdout Splits (`H-G3`, `H-G4`)** | Evaluator split registry | Hanya **Offline Evaluator** pada saat eksekusi gate terkait (`C18` untuk `H-G3`, `C21` untuk `H-G4`) | **DILARANG KERAS** dipakai untuk prompt tuning, indexing QA, few-shot examples, atau dilihat oleh agent (`FR-RAG-006`, `NFR-019`) | Dibekukan (*frozen*) sejak G1 hingga akhir PoC + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **3. Service Catalog & Topology** | Stack simulasi 5 layanan (`C03`/`C05`) | Service catalog store, dependency correlation (`C10`), tool `get_service_dependencies`, dan reviewer | Tidak boleh memuat hostname/IP infrastruktur produksi bank | Selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **4. Synthetic Telemetry (Logs, Metrics, Traces)** | 5 layanan simulasi & traffic generator | Backend telemetri lab, *read-only tool adapters* (`C09`) dengan sanitasi aktif, lalu ke konteks agent & dossier | Tidak boleh dikirim mentah (sebelum sanitasi) ke LLM eksternal atau AI observability sink (`SEC-03`); tidak boleh berisi instruksi pengendali sistem (`RULE-004`) | Data mentah container dapat di-reset antar-run; sampel evidence tersanitasi disimpan selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **5. Synthetic Runbooks / SOP Knowledge Base** | Dokumen Markdown/JSON sintetis yang ditulis di `C06` | Pipeline ingestion (setelah redaction), vector/lexical index (`C07`), retrieval dengan filter versi/ACL/service/env, konteks model, dan sitasi dossier | Dokumen `obsolete` dilarang dikutip sebagai SOP aktif (`RAG-01`); dokumen `restricted` lintas service dilarang terkirim ke konteks LLM/log (`SEC-01`); dilarang berisi jawaban GT | Versi dipelihara di git/manifest selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **6. Agent Trace & AI Observability** | Orchestrator workflow & gateway (`C11`, `C13`, `C15`) | Append-only local security/workflow audit log & sanitized AI observability sink | Dilarang menyimpan *hidden chain-of-thought* mentah, kredensial API, atau synthetic PII fixture yang belum disanitasi | Selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **7. Incident Investigation Dossier & Review Records** | Workflow output & human reviewer (`C12`, `C16`) | Human reviewer interface/report, handover export, dan offline evaluator | Tidak boleh memuat secret mentah atau membocorkan label skenario GT sebelum review ditutup | Immutable per revisi; disimpan selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |
| **8. Administrative Gate & Governance Records (`E01`–`E24`)** | Pelaksanaan chapter & review gate | Pemilik proyek & reviewer proyek | Dilarang di-index ke dalam RAG KB atau dimasukkan ke prompt LLM; dilarang memuat API key/secret | Selama PoC aktif + 30 hari pasca G4 | `project-initiator-michael` / `APPROVED` |

## 4. Tabletop Review terhadap Jalur Terlarang (Verifikasi Desain `C01-GOV-005`)

1. **Kasus Uji Negatif Desain 1 — *"Mount direktori Ground Truth ke container Agent agar diagnosis lebih akurat"*:**
   - **Keputusan Kebijakan:** **DITOLAK KERAS (`BLOCKED BY RULE-002 & KPI-10`)**.
   - **Penegakan untuk C02/C04:** Penyimpanan Ground Truth wajib berada pada path/volume dan identitas akses yang terpisah dari container orchestrator/agent dan tool adapters. Kebocoran 1 byte GT ke agent menyebabkan **Automatic NO-GO**.
2. **Kasus Uji Negatif Desain 2 — *"Kirim log sintetis yang mengandung fixture API key/PII dummy secara mentah ke Cloud LLM API karena hanya data buatan"*:**
   - **Keputusan Kebijakan:** **DITOLAK KERAS (`BLOCKED BY NFR-003, NFR-012, & SEC-03`)**.
   - **Penegakan untuk C02/C08/C09/C15:** Redactor/sanitizer wajib berjalan sebelum data keluar dari tool adapter/ingestion menuju LLM maupun AI tracing sink. Kegagalan sanitizer wajib menghentikan pengiriman payload.
