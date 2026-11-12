# Review Findings, Content Audit, and Negative Tabletop Verification — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Review Timestamp (UTC):** `2026-11-09T05:00:00Z` (`2026-11-09T12:00:00+07:00` WIB)
- **Reviewer Reference (`reviewer_ref`):** `project-initiator-michael` (Self-Review Disclosed sesuai `ownership.md`)

## 1. Pemeriksaan Konsistensi Lintas-Artefak (`C01-GOV-010`)

Dilakukan pemeriksaan silang (*cross-document consistency audit*) terhadap seluruh artefak di dalam `evidence/c01-20261109T043813Z/C01/`:

1. **Integritas Sumber (`source-hashes.sha256` & `source-register.md`):**
   - Keempat berkas sumber (`BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md`, `Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx`, `docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md`, `docs/roadmap/01-SCOPE-DECISIONS-AND-G0.md`) terverifikasi `OK` melalui `shasum -a 256 -c`.
2. **Konsistensi Scope $\leftrightarrow$ Resource $\leftrightarrow$ Model $\leftrightarrow$ Budget (`scope-baseline.md`, `lab-readiness.md`, `model-and-license-review.md`, `budget-and-schedule.md`):**
   - Topologi 5 layanan simulasi ringan (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) mendukung penuh 14 skenario (`SC-01` s/d `SC-14`) dan 88 requirement ID.
   - Kapasitas host terukur (`macOS arm64`, `8 CPU`, `16 GiB RAM`, `~39.5 GiB Free Disk`) dipisahkan secara tegas dari alokasi proyek yang disetujui (**maks 4–6 CPU, 8 GiB RAM, 15 GiB Disk**).
   - Pilihan rute model **Hybrid** (Free-Tier Cloud API untuk inference utama + Embedding lokal ringan `FastEmbed` & LLM lokal ringan `Ollama <=3B` untuk fallback) selaras dengan plafon memori 8 GiB RAM sekaligus mematuhi kebijakan anggaran **`$0.00 USD` (Gratis / Open-Source & Free-Tier saja)**.
3. **Pemeriksaan Data Minimization & Kerahasiaan (`data-handling.md` & Seluruh Artefak E01):**
   - Tidak ditemukan API key, token autentikasi, password, berkas `.env`, nomor seri perangkat keras pribadi, atau data produksi bank di dalam seluruh berkas `evidence/c01-20261109T043813Z/C01/`.
   - Implikasi penyimpanan pada folder sinkronisasi Google Drive pribadi telah dievaluasi dan dibatasi secara eksplisit pada data sintetis (`SYNTHETIC_INTERNAL_LAB`) tanpa secret.

## 2. Prosedur Uji Negatif Tabletop (`Section 8.3 Negative Review Procedure`)

Sesuai `01-SCOPE-DECISIONS-AND-G0.md` §8.3, empat usulan pelanggaran diuji terhadap baseline G0 tanpa mengubah dokumen baseline yang telah disahkan:

| ID Uji Tabletop | Usulan Perubahan yang Diuji | Keputusan Reviewer (`project-initiator-michael`) | Rule / Gate / KPI yang Dilanggar | Disposisi |
|---|---|---|---|---|
| **NEG-C01-01** | *"Investigator dapat membaca tabel Ground Truth (GT) agar akurasi diagnosis lebih tinggi"* | **DITOLAK (`REJECTED`)** | Melanggar `RULE-002`, `BR-008`, `FR-SIM-005`, `KPI-10`, dan `AT-008`. Membocorkan GT ke runtime agent memicu **Automatic NO-GO** | Tetap wajib terisolasi di luar mount/network/tool agent; hanya boleh di-join oleh evaluator offline setelah investigasi `CLOSED` |
| **NEG-C01-02** | *"Synthetic secret/PII fixture boleh dikirim mentah ke Cloud LLM API karena hanya data buatan"* | **DITOLAK (`REJECTED`)** | Melanggar `NFR-003`, `NFR-012`, `SEC-03`, dan kebijakan `data-handling.md` §1 & §4. Kegagalan sanitasi fixture sensitif memicu **Automatic NO-GO** | Redactor deterministik wajib menyamarkan seluruh fixture PII/secret sebelum embedding, LLM call, maupun AI observability sink (`FAIL_CLOSED`) |
| **NEG-C01-03** | *"Target Recall@5 atau Top-3 Accuracy diganti/diturunkan setelah melihat hasil evaluasi holdout"* | **DITOLAK (`REJECTED`)** | Melanggar `RULE-012`, `NFR-019`, BRD §21.1, dan aturan `no_posthoc_change_rule` pada `measurement-plan.md` | Perubahan target atau prompt pasca-evaluasi membatalkan status blind holdout dan wajib memulai siklus eksperimen baru dengan holdout independen baru |
| **NEG-C01-04** | *"Gate G0 diberi status PASS ketika persetujuan anggaran atau rute provider model masih berstatus PENDING"* | **DITOLAK (`REJECTED`)** | Melanggar kriteria `C01-GOV-006`, `C01-GOV-007`, `C01-GOV-009`, dan `C01-GOV-011` pada `01-SCOPE-DECISIONS-AND-G0.md` | Gate G0 hanya boleh `PASS` setelah rute model (`TBD-04`) dan plafon anggaran (`TBD-09`) ditutup dengan keputusan `APPROVED` yang nyata |

## 3. Daftar Defect (Defect Register C01)

- **Critical Defects:** `0` (Tidak ada).
- **Major / Minor Defects:** `0` (Tidak ada).
- **Catatan Keterbatasan yang Diungkapkan (*Disclosed Limitations*):**
  - `LIM-C01-01`: Pelaksanaan proyek dilakukan oleh solo developer (`project-initiator-michael`), sehingga review dokumen dan evaluasi manusia bersifat *self-reviewed* kecuali reviewer independen (`TBD-08`) ditambahkan pada Gate G1. Keterbatasan ini telah dicatat secara eksplisit pada `ownership.md` dan `measurement-plan.md`.
