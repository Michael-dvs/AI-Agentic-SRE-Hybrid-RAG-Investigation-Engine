# G0 Record — Project Initiation, Scope, and Readiness Gate

- **Run ID:** `c01-20261109T043813Z`
- **Input Baseline:** `source-hashes.sha256` + `source-register.md`
- **Gate Status:** **`PASS`**
- **Decision Date / Time (UTC):** `2026-11-09T05:01:00Z` (`2026-11-09T12:01:00+07:00` WIB)
- **Approver Reference (`owner_ref`):** `project-initiator-michael` (Michael — Project Initiator, Owner, & Lead Solo Developer)
- **Scope and Ownership Baseline:** `scope-baseline.md` + `requirements.csv` (88 IDs) + `scenario-scope.csv` (14 Scenarios) + `ownership.md`
- **Lab, Data, and Model Baseline:** `lab-readiness.md` + `data-handling.md` + `model-and-license-review.md`
- **Budget and Evaluation Protocol:** `budget-and-schedule.md` + `measurement-plan.md`
- **Decision and Conflict Reconciliation:** `decision-log.md` + `conflict-log.md`
- **Validation Results:** `validation-results.csv` (`C01-GOV-001` s/d `C01-GOV-011` seluruhnya `PASS`) + `review-findings.md`
- **Critical Blockers:** `None` (Seluruh 8 keputusan wajib G0: `TBD-01`, `TBD-02`, `TBD-03`, `TBD-04`, `TBD-07`, `TBD-09`, `TBD-12`, `TBD-13` telah ditutup dengan status `APPROVED`)

## 1. Ringkasan Keputusan Gate G0 yang Disahkan

1. **Lingkup & Topologi Simulasi (`TBD-07`):** Disahkan pembangunan maket mandiri **5 layanan ringan yang saling terhubung** (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) di atas Docker Compose lokal untuk mendukung penuh seluruh 88 requirement (`Must` & `Should`) serta 14 skenario (`SC-01` s/d `SC-14`).
2. **Ownership & Tata Kelola (`TBD-01`, `TBD-02`):** Proyek dikerjakan secara mandiri oleh `project-initiator-michael` dengan deklarasi transparan atas rangkap peran dan bias *self-review*. Tidak ada klaim persetujuan resmi dari unit organisasi PT Bank Negara Indonesia (Persero) Tbk.
3. **Kapasitas Lab Lokal (`TBD-03`):** Dari kapasitas host `macOS arm64` terukur (`8 CPU`, `16 GiB RAM`, `~39.5 GiB Free Disk`), disahkan **Approved Allocation untuk Docker Lab: maksimum 4–6 CPU, 8 GiB RAM (`8589934592` bytes), dan 15 GiB Disk**.
4. **Rute Model Hybrid & Lisensi (`TBD-04`, `TBD-12`):** Disahkan rute **Hybrid gratis (`$0`)** menggunakan Free-Tier Cloud API untuk inference utama (hanya untuk data sintetis yang telah lulus redactor `SEC-03`) dikombinasikan dengan embedding lokal ringan (`FastEmbed`/`sentence-transformers`) dan LLM lokal ringan (`Ollama <=3B`) untuk fallback/outage mode, dengan seluruh perangkat lunak pendukung berlisensi open-source/community free.
5. **Anggaran & Jadwal (`TBD-09`):** Plafon biaya tunai dikunci pada **`$0.00 USD` (`Rp 0` — Gratis / Open-Source & Free-Tier saja)** dengan pencatatan *shadow unit cost* dan jadwal berbasis kelulusan Gate (`G0`–`G4`).
6. **Penanganan Data & Isolasi Ground Truth (`TBD-13`):** Klasifikasi data adalah `SYNTHETIC_INTERNAL_LAB`, retensi selama PoC aktif + 30 hari pasca G4, penyimpanan di workspace Google Drive pribadi diizinkan khusus untuk kode & evidence tersanitasi (**dilarang menyimpan secret/`.env`**), dan Ground Truth serta split holdout (`H-G3`/`H-G4`) wajib terisolasi penuh dari runtime agent.

## 2. Daftar Keputusan yang Ditangguhkan secara Terkontrol ke C02 / Gate G1 (`Deferred G1 Decisions`)

Sesuai Master Roadmap §3, keputusan berikut memiliki pemilik dan tenggat yang jelas pada `C02` atau `C08` (`G1`) serta tidak memblokir Gate G0:

| ID Keputusan | Pemilik (`owner_ref`) | Tenggat Kapitel / Gate | Dampak & Pekerjaan di C02 / C08 |
|---|---|---|---|
| **TBD-05** | `project-initiator-michael` | Desain spike di `C02`; pengesahan di `C08 (G1)` | Pemilihan engine orkestrasi stateful (Custom Python / LangGraph / Dify) yang muat dalam plafon 8 GiB RAM |
| **TBD-06** | `project-initiator-michael` | Sebelum `C07`; pengesahan di `C08 (G1)` | Pemilihan arsitektur Hybrid RAG (Qdrant native dense+sparse vs Qdrant + Elasticsearch BM25) berdasarkan bukti memori & kualitas |
| **TBD-08** | `project-initiator-michael` | `C08 (G1)` | Konfirmasi ketersediaan reviewer SME eksternal atau penetapan final status `SELF_EVALUATED_DEVELOPER_LABELS` |
| **TBD-10** | `project-initiator-michael` | `C08 (G1)` | Pembekuan ukuran sampel eksak korpus retrieval/replay, stratifikasi `Dev`/`H-G3`/`H-G4`, dan denominator detail |
| **TBD-11** | `project-initiator-michael` | `C08 (G1)` | Pemilihan antarmuka review manusia (Web UI ringan vs Markdown/CLI terotorisasi) |
| **ADR-S01 s/d ADR-S03** | `project-initiator-michael` | **`C02`** (sebelum implementasi `C03`/`C05`/`C08`) | Penetapan bahasa/framework layanan, backend OTel telemetry, dan transport/identitas gateway keamanan |
| **ADR-S04 s/d ADR-S08** | `project-initiator-michael` | `C06`–`C08 (G1)` | Parameter chunking/RRF/reranker, kuota/timeout/circuit-breaker, AI observability sink, disposisi dummy ticket (`AT-017`), dan aturan skor multi-fault |

## 3. Rasional Keputusan & Otorisasi Langkah Berikutnya

- **Decision Rationale:** Seluruh prasyarat tata kelola, inventarisasi sumber, pemetaan 88 kebutuhan dan 14 skenario, profil kapasitas lab lokal, batas keamanan data sintetis, rute model hybrid `$0`, dan protokol evaluasi awal telah lengkap, konsisten, dan terverifikasi lulus pada `C01-GOV-001` s/d `C01-GOV-011`.
- **C02 Authorized to Start:** **`YES`** (Diizinkan memulai Chapter C02 — *Architecture, Contracts, and Evaluation Design*).
- **Batas Otorisasi:** Kelulusan Gate G0 ini hanya mengizinkan pengerjaan desain kontrak dan arsitektur pada Chapter C02; **bukan** klaim bahwa aplikasi telah dibangun atau acceptance test runtime (`AT-001`–`AT-017` / Lampiran A) telah dijalankan.
- **Supersedes:** `none` (Baseline G0 pertama).
