# Scope and Fidelity Baseline — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision Reference:** `TBD-07` (`APPROVED` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Approver Reference:** `project-initiator-michael`
- **Status:** `APPROVED FOR G0 BASELINE`

## 1. Tujuan Simulasi & Konsep Maket

Proyek ini membangun **miniatur fungsional ekosistem microservices (Hybrid Self-Built Simulation)** pada lingkungan lab terisolasi (`macOS` + `Docker Compose lokal`) untuk memvalidasi konsep **AI Agentic SRE & Hybrid RAG Investigation Engine**.

Hasil akhir yang dituju pada Gate G4 adalah paket bukti terukur untuk keputusan kelayakan konsep (`GO` / `CONDITIONAL GO` / `NO-GO` menuju studi kelayakan tahap berikutnya), **bukan** kesiapan deployment produksi bank.

## 2. In-Scope vs Out-of-Scope

### 2.1 In-Scope (Wajib Dipertahankan)
- Merancang dan menjalankan **5 layanan simulasi ringan yang saling bergantung** (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, dan `db-dummy`) di atas jaringan lab Docker Compose lokal.
- Menyediakan *normal/spike synthetic traffic generator* ber-seed dan *reversible fault injector* terpisah dari runtime agent, beserta katalog 14 skenario (`SC-01` s/d `SC-14`) yang memiliki *ground truth* terisolasi.
- Menghasilkan dan mengumpulkan *structured logs*, *RED metrics*, dan *distributed traces* yang berkorelasi (`OpenTelemetry-compatible`).
- Menyediakan *alert intake*, validasi envelope, deduplikasi berbasis fingerprint, dan korelasi dependensi layanan.
- Membangun *read-only telemetry tool adapters* dengan kontrak input/output tervalidasi dan batas kuota/time-window.
- Membangun *knowledge base* sintetis berlabel versi/status (`current`, `obsolete`, `restricted`, lintas layanan) dan pipeline *Hybrid RAG* (*lexical + dense + fusion + optional reranker + citations*) yang dapat dibandingkan terhadap *lexical-only* dan *dense-only*.
- Membangun *stateful deterministic investigation workflow* (`RECEIVED → CORRELATED → TRIAGED → EVIDENCE_COLLECTED → RETRIEVED → HYPOTHESES → VALIDATED → DRAFTED → HUMAN_REVIEW`) dengan integrasi LLM Hybrid terkendali dan *evidence validator*.
- Menghasilkan *Incident Investigation Dossier* (JSON & Markdown) beserta mekanisme review manusia (*approve/reject/edit*) dan evaluasi *offline/blind* pasca-investigasi.

### 2.2 Out-of-Scope (Dilarang Keras / Non-Goals)
- Koneksi ke sistem produksi PT Bank Negara Indonesia (Persero) Tbk, data nasabah, kredensial organisasi, IAM/CMDB/ITSM produksi, atau log transaksi nyata.
- Transaksi keuangan nyata, pemindahan dana, atau penggunaan PII asli.
- Kemampuan *write*, `restart`, `deploy`, `scale`, eksekusi shell/SQL/PromQL bebas, atau *auto-remediation* oleh agent investigator.
- Akses oleh agent, prompt, tool adapter, atau indeks RAG ke *ground truth registry* dan label *holdout* evaluator.
- Klaim kepatuhan regulasi, sertifikasi keamanan/pentest enterprise, HA/DR produksi, atau penggantian operasional L1/L2 nyata.
- Komponen berbayar yang melanggar kebijakan anggaran `Gratis / open-source saja ($0 cash outlay)`.

## 3. Topologi 5 Layanan Simulasi Terpilih (`TBD-07`)

Untuk memenuhi `FR-SIM-001` (minimal 3 layanan terhubung dengan ≥2 ketergantungan) sekaligus mendukung penuh seluruh 14 skenario `Must` dan `Should` (termasuk `SC-06` Auth mismatch dan `SC-07` Queue consumer lag) di dalam batas alokasi RAM Docker Lab maks 8 GB:

| Service ID | Peran Simulasi | Ketergantungan Upstream/Downstream | Skenario Utama yang Didukung |
|---|---|---|---|
| `api-gateway` | Entrypoint HTTP, routing request, agregasi respons, propagasi trace context | Menerima traffic dari generator; memanggil `auth-service` dan `transaction-service` | `SC-01`, `SC-02`, `SC-03`, `SC-04`, `SC-06`, `SC-08`, `SC-12` |
| `auth-service` | Verifikasi token sintetis & konfigurasi otorisasi dummy | Dipanggil oleh `api-gateway` | `SC-01`, `SC-06` (401/403 config mismatch vs 5xx), `SC-08` |
| `transaction-service` | Orkestrasi transaksi dummy tanpa dana, penulisan ke storage dummy, publikasi event ke antrean lokal | Dipanggil oleh `api-gateway`; memanggil `db-dummy` dan mengirim event ke `notification-service` | `SC-01`, `SC-02` (HTTP 5xx), `SC-03` (DB latency cascade), `SC-04` (dependency down), `SC-05` (pool exhaustion), `SC-11` (adversarial log) |
| `notification-service` | Konsumsi event asinkron dari in-memory/lightweight queue | Mengonsumsi event dari `transaction-service` | `SC-01`, `SC-07` (queue consumer lag / backlog), `SC-08`, `SC-14` |
| `db-dummy` | Layanan penyimpanan/database lokal ringan dengan hook simulasi latensi, koneksi, dan ketersediaan | Dipanggil oleh `transaction-service` | `SC-01`, `SC-03` (artificial latency), `SC-04` (unavailable), `SC-05` (connection pool limit) |

## 4. Matriks Fidelitas Simulasi (Model Fidelity Matrix)

| Dimensi | Yang Dibuktikan pada Maket Lab | Penyederhanaan yang Dipilih | Yang Tidak Dibuktikan (Enterprise Gap) | Status Approval |
|---|---|---|---|---|
| **Layanan & Topologi** | 5 layanan saling bergantung (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) & propagasi kegagalan | Container ringan lokal di Docker Compose (total alokasi ≤8 GB RAM) | Skala ribuan microservices & seluruh portofolio aplikasi bank | `APPROVED` (`project-initiator-michael`) |
| **Traffic & Faults** | Request normal/spike ber-seed & 14 skenario fault (`SC-01`–`SC-14`) yang reversible dengan GT terisolasi | Pola musiman disederhanakan; fault dikendalikan harness lokal | Pola trafik nasabah riil & kegagalan perangkat keras datacenter | `APPROVED` (`project-initiator-michael`) |
| **Telemetry** | Structured logs, RED metrics, dan distributed traces berkorelasi (`OpenTelemetry`) | Volume & retensi terbatas sesuai disk budget 15 GB | Skala ingesti log terabyte harian & retensi audit multi-tahun | `APPROVED` (`project-initiator-michael`) |
| **Knowledge Base & RAG** | SOP/runbook sintetis berlabel versi (`current`/`obsolete`), klasifikasi (`restricted`), & filter layanan/environment | Korpus dokumen sintetis terkurasi untuk domain 5 layanan lab | Siklus hidup persetujuan SOP bank resmi & ribuan dokumen heterogen | `APPROVED` (`project-initiator-michael`) |
| **Keamanan & Kontrol Tool** | Gateway terautentikasi, skema read-only, sanitasi PII/secret sintetis, isolasi GT, penolakan prompt injection | Identitas & kredensial terpisah tingkat lab lokal | Integrasi IAM/SSO korporat, DLP enterprise, & uji penetrasi resmi | `APPROVED` (`project-initiator-michael`) |
| **Human Review & Evaluasi** | Alur approve/reject/edit dossier oleh reviewer, evaluasi blind H-G3 & H-G4 | Peran reviewer & evaluator dijalankan oleh `project-initiator-michael` (deklarasi eksplisit *self-review*) | Validasi operasional independen oleh tim L1/L2 SOC/NOC produksi | `APPROVED` (`project-initiator-michael`) |

## 5. Rekapitulasi Cakupan Kebutuhan (88 Requirement IDs)

- **Business Requirements (`BR-001` s/d `BR-016`):** 16 ID (`10 Must` = `INCLUDED`, `4 Should` = `INCLUDED`, `1 Could` (`BR-015`) = `CONDITIONAL`, `1 Won't` (`BR-016`) = `EXCLUDED_BY_SOURCE`).
- **Functional Requirements (`FR-SIM`, `FR-OBS`, `FR-RAG`, `FR-AGT`, `FR-OUT`):** 40 ID (`30 Must` = `INCLUDED`, `9 Should` = `INCLUDED`, `1 Could` (`FR-OUT-007`) = `CONDITIONAL`).
- **Business Rules (`RULE-001` s/d `RULE-012`):** 12 ID (`12 Rule` = `INCLUDED`).
- **Non-Functional Requirements (`NFR-001` s/d `NFR-020`):** 20 ID (`10 Must` = `INCLUDED`, `10 Should` = `INCLUDED`).
- **Total:** **88 ID terpetakan utuh** di dalam `requirements.csv` tanpa ada `Must` atau `Should` yang dihapus.
