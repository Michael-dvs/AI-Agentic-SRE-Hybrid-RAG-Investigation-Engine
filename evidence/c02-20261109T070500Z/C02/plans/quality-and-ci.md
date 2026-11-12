# C02 Step 10 — Rencana Kualifikasi Kontrak Bertahap, Quality Gates, dan Desain CI

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/plans/quality-and-ci.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 10 & §8.1)  
> **Status:** `SPECIFIED` (Tahap 1–4 dieksekusi secara offline pada C02 Step 11; Tahap 5 tetap `NOT_RUN` hingga implementasi runtime C03–C21)

---

## 1. Lima Tahap Kualifikasi Kontrak (Contract Qualification Stages)

Sesuai C02 Step 10 Action 1, pembuktian kualitas kontrak dibagi menjadi lima tahap eksplisit agar validasi skema statis tidak pernah disamakan dengan kelulusan runtime:

| Stage | Nama Tahap | Cakupan Pemeriksaan | Metode & Alat | Status pada C02 | Chapter Eksekusi Runtime |
|---|---|---|---|---|---|
| **Stage 1** | **JSON Syntax & Hash Integrity** | Memastikan seluruh file `.schema.json` dan fixture `.json` adalah JSON valid (UTF-8), tidak kosong, dan memiliki SHA-256 terdaftar di `schema-manifest.csv`. | `python3 -m json.tool`, `shasum -a 256` | `EXECUTED & PASS` (Step 11) | Dipertahankan di semua chapter |
| **Stage 2** | **Meta-Schema & Local Registry Check** | Memastikan seluruh 20 skema patuh pada `https://json-schema.org/draft/2020-12/schema`, memiliki `$id` unik `urn:sre-sim:contract:<name>:1`, dan melarang resolusi `$ref` eksternal ke internet (`deny_external`). | Python `jsonschema.Draft202012Validator.check_schema` + `referencing.Registry(retrieve=deny_external)` | `EXECUTED & PASS` (Step 11) | C03–C17 |
| **Stage 3** | **Positive & Negative Instance Qualification** | Setiap skema diuji terhadap minimal 1 instance positif (`expected_valid: true`) dan 1 instance negatif (`expected_valid: false`) dengan `FORMAT_CHECKER` aktif pada `examples/schema-cases.json`. | Runner kualifikasi C02 §8.2 (`validation-runner.log`) | `EXECUTED & PASS` (Step 11 — 42/42 kasus lulus) | C03–C17 |
| **Stage 4** | **Cross-Contract Semantic & Policy Oracle Review** | Pemeriksaan aturan semantik lintas kontrak yang tidak dapat ditangkap oleh JSON Schema murni (batas durasi jendela waktu, urutan `start < end`, kuota poin, otorisasi `service_id`/`environment`, predikat waktu SOP, isolasi GT, dan penolakan join evaluasi sebelum `CLOSED`). | Tabletop review terstruktur pada `examples/policy-cases.csv` (11 kasus) + `contract-coverage.csv` | `EXECUTED & PASS` (Step 11) | Diimplementasikan sebagai kode deterministik di C06–C16 |
| **Stage 5** | **Runtime Integration & Security Acceptance** | Pengujian aplikasi berjalan di lab Docker Compose terhadap 12 ID Proposal (`SEC-01`..`HUM-01`) dan 17 ID BRD (`AT-001`..`AT-017`). | Pytest integration suite, fault harness replay, MCP gateway runtime tests | **`NOT_RUN` (SPECIFIED ONLY)** | C03–C21 (Gate G1–G4) |

---

## 2. Desain Pemeriksaan Kualitas Otomatis (Local Quality Gate / CI Blueprint)

Ketika kode aplikasi mulai ditulis pada C03+, pipeline pemeriksaan lokal (Makefile / pre-commit / CI runner) wajib menerapkan 5 gerbang berurutan berikut (tidak dibuat sebagai workflow GitHub Actions aktif pada C02 sesuai batasan Step 10 Action 2):

1. **`check-schema-manifest`:**
   - Memverifikasi bahwa setiap perubahan pada `contracts/*.schema.json` disertai pembaruan `schema-manifest.csv` dan `contracts-final.sha256`, serta tidak mengubah kontrak versi mayor `1` secara diam-diam tanpa bump revisi.
2. **`check-offline-contracts`:**
   - Menjalankan skrip validator Draft 2020-12 C02 §8.2 terhadap seluruh skema dan `schema-cases.json` dengan `deny_external` aktif. Gagal jika ada 1 skema pun yang kehilangan pasangan kasus positif/negatif.
3. **`check-secret-and-gt-boundary`:**
   - Memindai direktori runtime (`services/`, `mcp/`, `kb/corpus/`, `prompts/`) untuk memastikan:
     - Tidak ada file `.env` atau kredensial nyata yang ter-commit.
     - Tidak ada referensi path ke `restricted/gt-registry/` atau `evidence/c01-*` / `evidence/c02-*` di dalam korpus RAG atau kode tool investigator (`RULE-03`).
     - Tidak ada kata kunci skenario/holdout (`H-G3`, `H-G4`, `gt_oracle_token`) di dalam fixture prompt atau log contoh.
4. **`check-readonly-tool-surface`:**
   - Linter statis terhadap pendaftaran tool MCP (`C08`/`C09`) yang memastikan hanya 4 tool kanonik (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`) dan 1 tool kondisional (`get_apm_health` bila diaktifkan ADR-S07) yang diekspos; gagal jika ditemukan fungsi mutasi, `subprocess`, `os.system`, atau klien HTTP tanpa batas ke luar lab (`RULE-02`).
5. **`check-evidence-integrity`:**
   - Memastikan tidak ada skrip atau laporan yang menuliskan status `PASS` pada tabel acceptance test (`SEC-*`, `MCP-*`, `RAG-*`, `EV-*`, `OPS-*`, `HUM-*`, `AT-*`) tanpa merujuk pada `run_id` dan file bukti nyata di bawah `evidence/`.

