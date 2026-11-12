# Model Route, Egress, and License Review — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision References:** `TBD-04`, `TBD-12` (`APPROVED` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Approver Reference:** `project-initiator-michael`

## 1. Evaluasi Opsi Jalur Model & Embedding (`TBD-04`)

Berdasarkan batasan kapasitas host (`macOS arm64`, total RAM 16 GiB dengan alokasi lab maksimum 8 GiB pada `lab-readiness.md`) dan kebijakan anggaran pengguna (`Gratis / open-source saja`, `$0 cash outlay`), dilakukan perbandingan opsi:

| Opsi | Deskripsi | Dampak Resource Lab (Plafon 8 GiB RAM) | Dampak Egress & Privasi Data | Biaya | Status Keputusan |
|---|---|---|---|---|---|
| **Opsi A: 100% Lokal Berukuran Menengah/Besar (`>=7B` LLM + Embedding Lokal)** | Menjalankan LLM 7B–14B di Ollama bersama 5 container layanan + Qdrant + telemetri | **Berisiko tinggi melampaui plafon 8 GiB RAM** (model 7B Q4 memerlukan ~4.5–5.5 GiB RAM sendiri, menyisakan terlalu sedikit memori untuk Docker stack) | Tidak ada egress keluar host lokal | `$0` | `REJECTED` sebagai jalur tunggal utama karena risiko OOM pada RAM 16 GiB |
| **Opsi B: 100% Cloud API Berbayar (Commercial Paid Tier)** | Menggunakan API komersial berbayar untuk seluruh LLM & embedding | Penggunaan RAM lokal sangat ringan | Egress keluar ke provider eksternal | Berbayar (`>$0`) | `REJECTED` karena melanggar mandat pengguna: `Budget policy: Gratis / open-source saja` |
| **Opsi C: Rute Hybrid Free-Tier Cloud API + Model/Embedding Lokal Ringan (`<=3B`)** | **LLM Utama:** Free-tier Cloud API (mis. Google Gemini API Free Tier / OpenRouter Free models) hanya untuk payload sintetis yang telah lulus sanitizer. **Embedding & Fallback Lokal:** Model embedding ringan lokal (`FastEmbed` / `sentence-transformers` kelas 384-dim, ~150–300 MB RAM) atau free-tier embedding + LLM lokal ringan (`Ollama <=3B`, mis. `qwen2.5:1.5b`/`3b` atau `llama3.2:1b`/`3b`) untuk fallback/offline mode | **Kompatibel penuh dengan plafon 8 GiB RAM** (inference berat di-offload ke Free-tier API; embedding lokal <300 MB; LLM lokal <=3B hanya dimuat saat dibutuhkan) | Egress hanya berisi **data sintetis yang telah disanitasi (`SEC-03`)**; zero PII/secret asli; zero GT | **`$0.00`** (Gratis / Free-Tier & Open-Source) | **`SELECTED & APPROVED` (`TBD-04`)** |

## 2. Tabel Keputusan Otorisasi Model & Embedding (`TBD-04`)

| Field | Nilai yang Disahkan pada Gate G0 |
|---|---|
| **Route / Authorized Option** | **Hybrid Route (`TBD-04`):** (1) **Primary LLM Inference:** Authorized Free-Tier External Cloud API (kandidat utama: Google Gemini Free Tier API / OpenRouter Free Tier; versi model eksak dikunci sebelum `C13`); (2) **Primary Embedding:** Local lightweight open-source embedding (`FastEmbed` / `all-MiniLM-L6-v2` / `BAAI/bge-small` di lokal) atau Free-Tier API yang kompatibel (dikunci sebelum `C06`); (3) **Local LLM Fallback / Outage Mode:** Local `Ollama` model ringan `<=3B` (`qwen2.5:1.5b-instruct` / `llama3.2:3b` atau setara) ditambah *deterministic rule-based fallback* (`C11`/`C13`). |
| **Allowed Input Classes** | **Hanya `SYNTHETIC_INTERNAL_LAB` yang telah lulus redactor/sanitizer (`SEC-03`)**. Dilarang keras mengirimkan Ground Truth (`RULE-002`), label holdout, kredensial/secret, atau data non-sintetis. |
| **Residency / Retention / Training Policy** | Karena 100% data bersifat sintetis/dummy dan telah disanitasi dari fixture PII/secret, risiko kebocoran data organisasi/nasabah adalah **nol**. Namun demikian, konfigurasi provider eksternal tetap wajib menonaktifkan opsi training/logging opsional bila tersedia pada tier gratis, dan batasan retensi provider untuk free-tier dicatat secara transparan sebagai *Enterprise Gap* pada `C23`. |
| **Access Status** | `AVAILABLE` untuk perencanaan arsitektur; **tidak ada** API key/token yang disimpan di repository atau di dalam paket evidence `E01`. |
| **Budget Linkage** | Terikat ketat pada `TBD-09` (`$0.00` / Gratis & Open-Source saja) yang disahkan pada `budget-and-schedule.md`. Penggunaan berbayar (`paid billing`) **diblokir**. Jika kuota rate-limit harian/menit free-tier tercapai, sistem wajib melakukan *throttling/backoff* atau beralih ke jalur lokal/fallback sesuai kebijakan stop/fallback. |
| **Approver / Date / Decision Ref** | `project-initiator-michael` / `2026-11-09T11:35:57+07:00` / `TBD-04` |

## 3. Kebijakan Lisensi & Self-Hosting (`TBD-12`)

1. **Kebijakan Lisensi yang Disahkan pada G0 (`TBD-12`):**
   - Seluruh komponen perangkat lunak, library, dan kontainer yang digunakan dalam lab wajib tersedia secara **gratis** di bawah lisensi **Open-Source Permissive** (`MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `MPL-2.0`) atau lisensi *community/self-hosted free edition* yang mengizinkan penggunaan pengembangan/evaluasi lokal tanpa biaya lisensi.
   - Dilarang menggunakan komponen berpemilik (*proprietary paid license*) atau layanan cloud berbayar.
2. **Status Kandidat Komponen Referensi (Versi Eksak & SBOM Dikunci pada ADR C02/C08):**
   - **Vector Store / Hybrid Search (`TBD-06`):** `Qdrant` (Apache-2.0) — dievaluasi mode native hybrid (dense + sparse BM25/SPLADE) vs pasangan Elasticsearch/OpenSearch pada `C06`–`C07` dengan mempertimbangkan batas RAM 8 GiB.
   - **Observability & Telemetry (`ADR-S02`):** `OpenTelemetry` (Apache-2.0), `Prometheus` (Apache-2.0), `Grafana` / `Loki` / `Tempo` atau `Jaeger` (Apache-2.0 / AGPLv3 free local container — dievaluasi di `C02`).
   - **Orchestration / Workflow (`TBD-05`, `ADR-S01`):** Custom Python deterministic state machine (MIT/Apache-2.0 libraries) vs `LangGraph` (MIT) vs `Dify Community Self-Hosted` (dievaluasi kelayakan resource & lisensinya pada `C02`/`C08`, mengingat Dify memiliki ketentuan lisensi tambahan dan footprint container yang cukup besar untuk plafon 8 GiB RAM).
   - **AI Observability (`ADR-S06`):** `Langfuse` self-hosted (MIT untuk core open-source) atau local structured trace + audit sink yang setara (dievaluasi pada `C08` sebelum `C15`).
3. **Pernyataan Kebenaran Saat Ini:** Tidak ada container, SDK model, atau paket aplikasi yang diinstal atau dipanggil selama pelaksanaan Chapter C01 ini.
