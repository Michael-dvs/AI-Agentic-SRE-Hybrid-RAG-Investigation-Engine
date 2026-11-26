# HANDBOOK OPERASIONAL & PANDUAN PENGGUNAAN TOOLS
## AI Agentic SRE & Hybrid RAG Investigation Engine — Simulation PoC

> **Status Proyek:** **SELESAI (Fase 1 s/d Fase 4 — Chapter `C01` s/d `C24` + Remediasi `P0-01` s/d `P2-07`)**  
> **Keputusan Resmi Gate G4:** **`CONDITIONAL GO`** (*Concept Feasibility Approved with Corrective Action Plan `CAP-01` s/d `CAP-05`*)  
> **Hasil Pengujian Otomatis:** **Seluruh Suite Regresi Aktif Lulus (`pytest -p anyio`)** *(tes penjaga freeze historis Stage 3A mendeteksi modifikasi pasca-freeze hingga owner re-freeze)*  
> **Invarian Keselamatan:** **Zero Mutation (`KPI-09 = 0`), Zero Ground Truth Leakage (`KPI-10 = 0`), Zero Obsolete SOP Active (`KPI-11 = 0`), Zero DLP Violation (`SEC-03 PASS`), No Auto-Remediation (`HUM-01 PASS`)**  
> **Batas Hukum & Keamanan:** Seluruh data, layanan, transaksi, dan akun adalah **100% sintetis**. Maket ini dirancang untuk pembuktian konsep mekanistik dan kelayakan di laboratorium terisolasi; **bukan** izin deployment produksi perbankan nyata.

---

## DAFTAR ISI

1. [Rangkuman Hasil Pengembangan PoC](#1-rangkuman-hasil-pengembangan-poc)
2. [Arsitektur Maket Digital & Alur Investigasi](#2-arsitektur-maket-digital--alur-investigasi)
3. [Prasyarat Sistem & Alokasi Port](#3-prasyarat-sistem--alokasi-port)
4. [Langkah Setup & Instalasi Lingkungan Lab](#4-langkah-setup--instalasi-lingkungan-lab)
5. [Panduan Operasional Lab (Siklus Hidup Kontainer & Trafik)](#5-panduan-operasional-lab-siklus-hidup-kontainer--trafik)
6. [Panduan Penggunaan Tools & Konsol Investigasi](#6-panduan-penggunaan-tools--konsol-investigasi)
   - 6.1 [Unified SRE TUI Dashboard (`sre_dashboard.py`)](#61-unified-sre-tui-dashboard-sre_dashboardpy)
   - 6.2 [Interactive & Scriptable Review CLI (`review_console.py`)](#62-interactive--scriptable-review-cli-review_consolepy)
   - 6.3 [Clean Environment Replay & Verification Runner (`run_c22_clean_replay.py`)](#63-clean-environment-replay--verification-runner-run_c22_clean_replaypy)
   - 6.4 [Holdout Benchmark & Offline Evaluator (`run_c21_benchmark.py`)](#64-holdout-benchmark--offline-evaluator-run_c21_benchmarkpy)
   - 6.5 [DLP Scanner & Audit Log Verifier (`dlp_sink_scanner.py`)](#65-dlp-scanner--audit-log-verifier-dlp_sink_scannerpy)
7. [Naskah Latihan Demonstrasi Pemangku Kepentingan (15 Menit — UC-11)](#7-naskah-latihan-demonstrasi-pemangku-kepentingan-15-menit--uc-11)
8. [Panduan Troubleshooting & Penanganan Masalah](#8-panduan-troubleshooting--penanganan-masalah)
9. [Tata Kelola, Keterbatasan Terbuka, & Corrective Action Plan (CAP)](#9-tata-kelola-keterbatasan-terbuka--corrective-action-plan-cap)

---

## 1. Rangkuman Hasil Pengembangan PoC

Proyek ini telah berhasil menyelesaikan seluruh 24 Chapter operasional (`C01` s/d `C24`) dan melewati 4 evaluasi gerbang formal:
- **Gate G0 (Project Readiness & Initiation):** Standarisasi ruang lingkup, model tata kelola `AGENTS.md`, 20 kontrak JSON Schema, dan 88 kebutuhan BRD (`16 BR`, `40 FR`, `12 RULE`, `20 NFR`).
- **Gate G1 (Foundation):** 5 microservices sintetis, generator trafik deterministik, 14 skenario gangguan reversibel, telemetri RED/Logs/Traces, korpus RAG, dan Authenticated Policy Gateway (`C01`–`C08`).
- **Gate G2 (Controlled Integration):** Telemetry adapters read-only, antrean deduplikasi 100 alert, dependency impact correlator, 9-state machine engine, dan dossier awal (`C09`–`C12`).
- **Gate G3 (Reasoning & Observability):** Integrasi LLM tersanitasi, honest uncertainty validator, audit hash chain SHA-256, human review console, evaluasi blind holdout `H-G3`, dan pertahanan Red-Team (`C13`–`C18`).
- **Gate G4 (Concept Approval Gate):** Evaluasi akhir 43 butir penerimaan (`12` proposal + `17` BRD + `14` KPI kandidat), pengujian kapasitas/resiliensi, 2x clean replay reproducibility `AT-013` (`KPI-13 = 1.0`), analisis 5 pilar enterprise, dan penandatanganan memo kelayakan **`CONDITIONAL GO`**.

### Verifikasi Kriteria Keselamatan Mutlak (*Hard-Stop Safety Invariants*)
| Invarian Keselamatan | Target / Ambang | Hasil Aktual | Keterangan |
|---|---|---|---|
| `KPI-09` (Prohibited Mutations) | `== 0` | **`0`** | Upaya mutasi state (`restart`, `deploy`, `write`, `exec`, `SQL`) ditolak 100% |
| `KPI-10` (Ground Truth Leakage) | `== 0` | **`0`** | Direktori `restricted/` diisolasi penuh dari agen dan RAG (`0o700`) |
| `KPI-11` (Obsolete SOP Active) | `== 0` | **`0`** | Filter metadata versi mencegah runbook kadaluwarsa muncul sebagai aktif |
| `SEC-01`, `02`, `03` (Security Hardening) | `100% PASS` | **`100%`** | Sanitasi PII/kredensial, penolakan injeksi log, isolasi ACL tenant |
| `HUM-01` (`auto_action_triggered`) | `== False` | **`False`** | Tidak ada remediasi otomatis; persetujuan dossier wajib melalui manusia |
| `AT-013` / `KPI-13` (Clean Replay) | `1.0 (100%)` | **`1.0`** | Replay A vs B identik secara deterministik dan semantik |

---

## 2. Arsitektur Maket Digital & Alur Investigasi

```mermaid
flowchart TD
    subgraph Lab["1. Simulated Microservices Lab"]
        GW["api-gateway :18080"] --> AUTH["auth-service"]
        GW --> TX["transaction-service"]
        TX --> LEDGER["ledger-service"] --> PG[("PostgreSQL 16")]
        TX --> RMQ[("RabbitMQ")] --> NOTIF["notification-service"]
        FH["Fault Harness (SC-01..SC-14)"] -. Injeksi Terkendali .-> Lab
    end

    subgraph Observability["2. Telemetry Backends & Facades"]
        PROM[("Prometheus :19090\n(RED Metrics)")]
        LOKI[("Loki :13100\n(Structured Logs)")]
        TEMPO[("Tempo :13200\n(Distributed Traces)")]
        CATALOG["Service Topology Catalog"]
    end

    Lab --> Observability

    subgraph Pipeline["3. Controlled Investigation Engine"]
        ALERTS["Alert Webhook"] --> INTAKE["Alert Intake & Dedup Queue"]
        INTAKE --> CORR["Dependency Correlator"]
        CORR --> STATE["Deterministic 9-State Machine\n(SQLite + Audit Hash Chain)"]
        
        STATE --> SEC_GW["Authenticated Policy Gateway\n(KPI-09=0, DLP Redactor)"]
        SEC_GW --> ADAPT["Read-Only Telemetry Adapters"]
        ADAPT --> Observability
        SEC_GW --> RAG["Hybrid RAG Engine\n(BM25 + Dense LSA + RRF)"]
        
        STATE --> VAL["Evidence & Uncertainty Validator\n(Honest Inconclusive EV-01/02)"]
        VAL --> DOSSIER["Investigation Dossier Generator\n(JSON, Markdown, HTML)"]
    end

    subgraph Human["4. Human Control Plane (HUM-01)"]
        DOSSIER --> TUI["Unified SRE TUI Console\n(sre_dashboard.py)"]
        DOSSIER --> CLI["Review & Handover CLI\n(review_console.py)"]
        TUI --> ACTION{"L1/L2 Reviewer\nDecision"}
        CLI --> ACTION
        ACTION -->|APPROVE| EXPORT["Export Handover Package\n& Create Dummy Ticket"]
        ACTION -->|REJECT / ESCALATE| HUMAN_TRIAGE["Manual SRE Triage\n(Zero Auto-Action)"]
    end
```

---

## 3. Prasyarat Sistem & Alokasi Port

### 3.1 Spesifikasi Mesin Lab
- **Sistem Operasi:** macOS Apple Silicon (`arm64`) atau Linux (`x86_64`)
- **Runtime:** Python 3.12+ (disarankan menggunakan `venv`)
- **Kontainer:** Docker Desktop & Docker Compose v2 (alokasi memori kontainer 4–6 CPU, 8 GiB RAM)
- **Ruang Disk Bebas:** Minimal 10–15 GiB

### 3.2 Peta Alokasi Port Loopback (`127.0.0.1` Only)
Semua port diikat secara ketat ke `127.0.0.1` untuk mencegah paparan jaringan luar (`NFR-001`):

| Layanan / Komponen | Host Port | Target Kontainer | URL Akses Lab |
|---|---|---|---|
| `api-gateway` (FastAPI) | `18080` | `8000` | `http://127.0.0.1:18080/health/ready` |
| `prometheus` (Facade) | `19090` | `9090` | `http://127.0.0.1:19090` |
| `loki` (Facade) | `13100` | `3100` | `http://127.0.0.1:13100` |
| `tempo` (Facade) | `13200` | `3200` | `http://127.0.0.1:13200` |
| `otel-collector` | `14318` | `4318` | `http://127.0.0.1:14318` |
| `grafana` (`11.2.0`) | `13000` | `3000` | `http://127.0.0.1:13000` (`admin`/`admin`) |
| `PolicyGateway` & `HybridRetriever` | *Embedded* | In-process Python | Tidak membuka port publik |

---

## 4. Langkah Setup & Instalasi Lingkungan Lab

### Langkah 1: Clone & Setup Virtual Environment Python
```bash
# Masuk ke direktori repositori
cd "/Users/michaelarhdyn/Library/CloudStorage/GoogleDrive-23.michaelaristio@gmail.com/My Drive/Project Michael/SRE-Agentic"

# Membuat virtual environment (jika belum dibuat)
python3 -m venv .venv
source .venv/bin/activate

# Menginstal dependensi terbeku
pip install --upgrade pip
pip install -r requirements.txt
```

### Langkah 2: Konfigurasi File Lingkungan (`.env`)
Salin template konfigurasi lokal:
```bash
cp .env.example .env
```
> [!IMPORTANT]
> Biarkan `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, dan `TELEGRAM_CHAT_ID` kosong untuk mode baseline deterministik bebas biaya ($0.00 cash spend). Sistem otomatis menggunakan *Deterministic Investigator & Mock LLM Fallback* jika kunci API tidak diisi.

---

## 5. Panduan Operasional Lab (Siklus Hidup Kontainer & Trafik)

### 5.1 Menyalakan Seluruh Kontainer Lab (One-Command Startup)
Gunakan skrip wrapper bersertifikasi:
```bash
./scripts/lab_up.sh
```
*Skrip ini akan membangun image dan menyalakan 12 layanan kontainer via `docker compose up -d --build --wait`.*

### 5.2 Smoke Test Kesehatan Lingkungan
Verifikasi kesiapan gateway, database, broker antrean, dan backend telemetri:
```bash
./scripts/lab_smoke.sh
```
*Skrip memeriksa endpoint `/health/ready` (HTTP 200) dan mengeksekusi 6 transaksi ber-seed.*

### 5.3 Menjalankan Generator Trafik Sintetis
Untuk menyimulasikan beban transaksi perbankan sintetis:
```bash
# Profil Normal (Nominal traffic)
python3 -m traffic.generator --target-url http://127.0.0.1:18080 --profile normal --seed 20261109 --count 50

# Profil Lonjakan (Spike traffic)
python3 -m traffic.generator --target-url http://127.0.0.1:18080 --profile spike --seed 20261109 --count 100
```

### 5.4 Menginjeksi dan Mereset Skenario Gangguan (Fault Harness)
Maket ini menyediakan 14 skenario gangguan deterministik reversibel (`SC-01` s/d `SC-14`):
```bash
# Contoh: Menginjeksi SC-03 (PostgreSQL query latency spike pada ledger-service)
python3 -m fault_harness.runner --scenario SC-03 --gateway-url http://127.0.0.1:18080

# Contoh: Menginjeksi SC-05 (Connection pool exhaustion pada ledger-service)
python3 -m fault_harness.runner --scenario SC-05 --gateway-url http://127.0.0.1:18080

# Contoh: Menginjeksi SC-09 (Trace context drop / trace outage untuk uji honest uncertainty)
python3 -m fault_harness.runner --scenario SC-09 --gateway-url http://127.0.0.1:18080

# RESET DARURAT: Menghapus seluruh status gangguan dan memulihkan lab ke kondisi nominal
./scripts/fault_reset.sh
```

### 5.5 Mematikan & Membersihkan Lingkungan Lab (Clean Teardown)
Untuk mematikan kontainer dan menghapus seluruh volume persisten agar tidak meninggalkan residu state:
```bash
./scripts/lab_down.sh --volumes
rm -f orchestrator_state.db*
```

---

## 6. Panduan Penggunaan Tools & Konsol Investigasi

### 6.1 Unified SRE TUI Dashboard (`sre_dashboard.py`)
Konsol terminal interaktif berbasis pustaka `rich` untuk melihat daftar insiden aktif, inspeksi telemetri, membaca kutipan runbook, dan melakukan sign-off investigasi.

**Cara Menjalankan:**
```bash
python3 scripts/sre_dashboard.py
```

**Opsi Konfigurasi Command Line:**
- `--state-db`: Lokasi berkas SQLite state machine (default: `orchestrator_state.db`).
- `--reviewer-ref`: ID/Username pereview (default: `sre_reviewer`).
- `--reviewer-role`: Peran operator SRE (default: `L2_SRE` atau `L1_SRE`).
- `--audit-log`: Lokasi log audit keputusan manusia (default: `artifacts/audit/c19-review-audit.jsonl`).
- `--handover-root`: Direktori ekspor berkas handover (default: `artifacts/handover`).
- `--refresh-interval`: Interval pembaruan snapshot otoritatif dalam detik (default: `2.0`, minimum `0.5`).
- `--ascii`: Mode garis batas dan penanda ASCII murni untuk terminal dengan dukungan font terbatas.

**Navigasi Tombol di Konsol (Single-Key Responsive Input + Alternate Screen + Trackpad Scroll Lock):**
- `?`: Membuka/menutup panel referensi tombol dan invarian keselamatan operasional (*Help & Safety Semantics*).
- `u`: Menyegarkan (*manual refresh*) snapshot state SQLite dan status probe secara langsung.
- `Panah Atas / Bawah` (atau `k` / `j` di daftar):
  - Saat fokus di panel **Navigasi**: memindahkan menu aktif `[1]` s/d `[5]` secara langsung.
  - Saat fokus di panel **Daftar Insiden**: memindahkan sorotan baris (stabil terhadap penambahan insiden baru).
  - Saat berada di **Detail Insiden**: menggulir isi dossier ke atas/bawah (`PgUp` / `PgDn` untuk gulir cepat).
- `Panah Kanan / Tab / Enter`: Memindahkan fokus dari panel **Navigasi** ke panel **Daftar Insiden** (dan tekan `Enter` / `o` lagi untuk membuka detail insiden).
- `Tab` / `Shift+Tab` (saat di **Detail Insiden**): Berpindah *View Lens* (`All Sections`, `Triage & Progress`, `Hypotheses`, `Evidence Lineage`, `SOP & RAG`, `Review & Audit`).
- `[` / `]` dan `i` (saat di **Detail Insiden**): Memilih item hipotesis/bukti berikutnya dan melompat langsung dari hipotesis ke bukti telemetri yang dirujuk (*Reference Resolution*).
- `Panah Kiri / b / Esc`: Kembali secara bertahap dari modal $\rightarrow$ sub-view $\rightarrow$ tabel daftar insiden $\rightarrow$ panel navigasi.
- `1`, `2`, `3`, `4`, `5`: Langsung melompat ke tab menu tertentu.
- `a` / `r` / `c` / `e`: Membuka **Modal Konfirmasi Human Review Dua Tahap** (`APPROVE`, `REJECT`, `CORRECT`, atau `ESCALATE`) yang terikat ke versi dan hash dossier; tekan `Tab`/`Enter` untuk berpindah kolom dan konfirmasi, atau `Esc` untuk membatalkan tanpa perubahan state.
- `q`: Keluar (*Quit*) dari konsol dashboard secara bersih tanpa mengubah investigasi yang sedang berjalan.

**Konfigurasi Interaktif pada Tab `[4] AI Model Config`:**
- `p`: Memilih Provider API (`OpenRouter`, `OpenAI`, `Google Gemini`, `Ollama Local`, atau `Custom OpenAI-Compatible`).
- `k`: Mengatur **API Key** (input tersembunyi/masked, tersimpan aman ke `.env` lokal tanpa pernah menimpa `.env.example`).
- `f`: **Fetch & Pilih Model dari API** secara langsung (`GET /models` atau `/api/tags` Ollama) lengkap dengan filter kata kunci (mis. `free`, `gemini`, `llama`).
- `m`: Mengatur nama/ID model secara manual.
- `t`: Menguji konektivitas ke endpoint API model dan memverifikasi ketersediaan model.
- `x`: Mereset konfigurasi model kembali ke mode offline baseline (`$0.00`).

**Konfigurasi Interaktif pada Tab `[5] Telegram Alerts`:**
- `k`: Mengatur **Telegram Bot Token** (dari `@BotFather`, input masked + verifikasi otomatis via `getMe`).
- `c`: Mengatur **Telegram Chat ID** (mendukung deteksi otomatis Chat ID dari riwayat bot via `getUpdates` atau input manual).
- `t`: Mengirim **Test Alert Outbound** percobaan untuk memastikan notifikasi sampai ke Telegram.
- `x`: Mereset kredensial Telegram kembali ke mode `DRY-RUN`.

---

### 6.2 Interactive & Scriptable Review CLI (`review_console.py`)
CLI untuk merender ringkasan dossier, menghitung biaya token LLM, dan menjalankan aksi review baik secara interaktif maupun otomatis via skrip CI/CD.

**Perintah Menampilkan Ringkasan Dossier:**
```bash
# Menampilkan dossier hasil ekspor handover atau berkas JSON dossier individual:
python3 scripts/review_console.py --dossier artifacts/handover/inc-sc03/dossier_final.json --view-only
```

**Perintah Memberikan Keputusan Review (APPROVE / REJECT / ESCALATE):**
```bash
# Menyetujui dossier berstatus HUMAN_REVIEW dan mengekspor paket handover publik:
python3 scripts/review_console.py \
  --dossier path/to/pending_dossier.json \
  --state-db orchestrator_state.db \
  --action APPROVE \
  --reviewer "michael-sre" \
  --role "L2_SRE" \
  --rationale "Gejala DB slow query terkonfirmasi oleh metrik latensi dan log PostgreSQL." \
  --export-handover \
  --create-ticket
```

---

### 6.3 Clean Environment Replay & Verification Runner (`run_c22_clean_replay.py`)
Runner otomatis yang membuktikan reproduktifitas penuh sistem dari kondisi bersih (*clean state*), memvalidasi kriteria `AT-013` & `KPI-13 = 1.0`, serta mengemas paket serah terima publik.

**Cara Menjalankan Replay Bersih:**
```bash
python3 scripts/run_c22_clean_replay.py --mode deterministic_baseline
```
*Runner mengeksekusi:*
1. Pembersihan total volume Docker & database lokal.
2. Setup Fresh Environment A $\rightarrow$ eksekusi 6 skenario kanonikal (`SC-01, SC-02, SC-03, SC-09, SC-11, SC-12`).
3. Pencatatan hash state SQLite dan invarian keselamatan.
4. Pembersihan total kedua $\rightarrow$ Setup Fresh Environment B $\rightarrow$ eksekusi skenario identik.
5. Komparasi invarian A vs B (kewajiban kecocokan 100%).
6. Pengemasan `public_handover/` dan penguncian izin direktori `restricted/` (`0o700`).

---

### 6.4 Holdout Benchmark & Offline Evaluator (`run_c21_benchmark.py`)
Alat uji offline evaluator independen untuk mengukur performa diagnosa root cause terhadap dataset holdout terpisah tanpa membocorkan label ke agen investigasi:

```bash
# Pra-pemeriksaan integritas segel ground truth & kandidat freeze:
python3 scripts/run_c21_preflight.py --tests-completed "pytest -p anyio" --output-dir evidence/preflight-check/

# Eksekusi evaluasi final holdout benchmark H-G4 (hanya saat freeze kandidat cocok dengan Stage 3A):
python3 scripts/run_c21_benchmark.py --output-dir evidence/benchmark-run/
```

---

### 6.5 DLP Scanner & Audit Log Verifier (`dlp_sink_scanner.py`)
Alat pemindai otomatis untuk memastikan tidak ada data rahasia (API key, token, nomor kartu kredit dummy, atau PII) yang bocor ke sink publik, berkas log, maupun dossier:

```bash
python3 scripts/dlp_sink_scanner.py artifacts/ --output artifacts/observability/dlp-scan-report.json
```

---

## 7. Naskah Latihan Demonstrasi Pemangku Kepentingan (15 Menit — UC-11)

Bila mendemonstrasikan hasil PoC kepada pemangku kepentingan (*Management / SRE Team / Architecture Review Board*), ikuti skenario 4 segmen berikut:

| Segmen | Menit | Skenario Diuji | Perintah / Aksi | Hasil yang Harus Ditunjukkan |
|---|---|---|---|---|
| **1. Baseline Sehat** | 0–3 | `SC-01` (Nominal) | `./scripts/lab_smoke.sh` | Trafik berjalan normal, `0` error log, `auto_action_triggered: false`. Menunjukkan sistem tidak menghasilkan alarm palsu (*zero false alerts*). |
| **2. Gangguan & Degradasi Jujur** | 3–8 | `SC-03` (DB Pool) & `SC-09` (Trace Outage) | Injeksi `SC-03` lalu buka `sre_dashboard.py` | `SC-03` melewati 9 status berurutan dan mengutip SOP DB pool yang benar. Pada `SC-09`, tunjukkan agen menetapkan status **`INCONCLUSIVE`** secara jujur tanpa halusinasi trace fiktif. |
| **3. Pertahanan Red-Team** | 8–11 | `SC-11` (Log Injection) | Kirim log berisi payload jailbreak prompt injection | `PolicyGateway` menolak mutasi (`KPI-09 = 0`). Payload ditangani strictly sebagai data untrusted di dossier. |
| **4. Human Review & Serah Terima** | 11–15 | `SC-02` / `SC-03` | Lakukan `APPROVE` via CLI atau TUI | Status berpindah ke `CLOSED`, ekspor `dossier.html` terbuat, tiket ITSM dummy terbit. Ungkapkan secara jujur batasan multi-fault `SC-08` dan rencana `CAP-01`–`CAP-05`. |

> [!CAUTION]
> **Protokol Fallback Berlabel:** Jika Docker atau koneksi internet mati saat demo langsung, operator **wajib** mengumumkan mode fallback menggunakan label **`PRE_RECORDED_FALLBACK_RUN`** dan membuka artefak terverifikasi di direktori `evidence/c22-*/C22/clean-replay-a/`. Dilarang keras menampilkan file rekaman seolah-olah berjalan live.

---

## 8. Panduan Troubleshooting & Penanganan Masalah

### 1. Masalah: Port Terpakai (*Port Conflict*)
- **Gejala:** Muncul error `port 18080 already in use` atau exit code `2` pada runner.
- **Penyebab:** Masih ada kontainer lab lama atau proses background yang mendengarkan di port yang sama.
- **Solusi:**
  ```bash
  # Cari proses yang memakai port lab:
  lsof -iTCP -sTCP:LISTEN -P -n | grep -E ':(18080|19090|13100|13200|13000|14318)'
  # Bersihkan kontainer lama:
  ./scripts/lab_down.sh --volumes
  ```

### 2. Masalah: Status Residu Database SQLite (*Residual State*)
- **Gejala:** Skrip replay mendeteksi `orchestrator_state.db` sudah berisi rekaman insiden lama (exit code `3`).
- **Solusi:** Hapus database state sebelum menjalankan pengujian bersih:
  ```bash
  rm -f orchestrator_state.db* artifacts/handover/*
  ```

### 3. Masalah: Docker Daemon Tidak Aktif (*DOCKER_INACTIVE*)
- **Gejala:** `./scripts/lab_up.sh` gagal menghubungi Docker daemon.
- **Solusi:** Pastikan aplikasi Docker Desktop menyala. Jika sedang menjalankan pengujian logika mandiri tanpa kontainer, gunakan mode in-process pytest:
  ```bash
  pytest tests/test_c11_investigation_workflow.py -v
  ```

### 4. Masalah: Gangguan Tidak Pulih Setelah Uji Injeksi
- **Gejala:** Layanan tetap mengembalikan HTTP 500 padahal pengujian skenario sudah selesai.
- **Solusi:** Jalankan pemulihan darurat:
  ```bash
  ./scripts/fault_reset.sh
  ```

---

## 9. Tata Kelola, Keterbatasan Terbuka, & Corrective Action Plan (CAP)

Sesuai memo resmi penutupan Gate G4 ([`G4-CONCEPT-APPROVAL-GATE.md`](file:///Users/michaelarhdyn/Library/CloudStorage/GoogleDrive-23.michaelaristio@gmail.com/My Drive/Project Michael/SRE-Agentic/docs/gates/G4-CONCEPT-APPROVAL-GATE.md)), kelayakan konsep ini disahkan dengan status **`CONDITIONAL GO`**. 

Sebelum maket ini dipertimbangkan untuk diuji pada *sandbox* perbankan sungguhan, **5 Corrective Action Plan (CAP)** berikut wajib dipenuhi:

1. **`CAP-01` (Multi-Root Temporal Event Clustering):** Menyempurnakan deteksi gangguan konkuren multi-layanan (`SC-08`) agar korelasi tidak hanya menangkap akar masalah primer, melainkan seluruh akar masalah sekunder (`KPI-02`).
2. **`CAP-02` (Cross-Service Metadata Taxonomy):** Memperbaiki taksonomi pencarian runbook RAG lintas layanan (`QRY-HLD-012`) agar dokumen arsitektur bersama dapat diakses tanpa melanggar isolasi batas layanan (`KPI-05`).
3. **`CAP-03` (Staging Holdout Benchmark Scale-Up):** Menjalankan benchmark holdout skala penuh (30–50 replay insiden dan 100–200 kueri RAG) pada lingkungan staging untuk menggantikan pengujian sampel kecil lab mandiri.
4. **`CAP-04` (Independent L1/L2 SRE Blind Crossover):** Melakukan evaluasi penerimaan dossier (`KPI-06` / `KPI-08`) oleh panel insinyur SRE perbankan independen guna menghilangkan bias penilaian pengembang mandiri.
5. **`CAP-05` (Enterprise 5-Pillar Integration):** Mengganti adaptor stub tiket lokal dengan integrasi sandbox ServiceNow/Jira, melengkapi SSO Active Directory/OIDC, integrasi CMDB, penilaian dampak privasi data (DPIA UU PDP No. 27/2022 & POJK), penggunaan LLM on-premise, dan uji penetrasi VAPT independen.

---
*Dokumen ini disusun sebagai panduan resmi penutupan maket digital PoC AI Agentic SRE & Hybrid RAG Investigation Engine.*
