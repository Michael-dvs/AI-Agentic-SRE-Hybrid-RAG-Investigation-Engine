# Budget, Schedule, and Workload Envelope — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision References:** `TBD-09`, `TBD-03` (`APPROVED` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Approver Reference:** `project-initiator-michael`

## 1. Kebijakan Anggaran & Plafon Biaya (`TBD-09`)

1. **Mata Uang & Plafon Biaya Tunai (`Cash Outlay Cap`):** **`$0.00 USD` (`Rp 0`)** — **Gratis / Open-Source & Free-Tier Saja**.
2. **Funding Owner:** `project-initiator-michael`.
3. **Aturan Penggunaan Layanan & Infrastruktur:**
   - **Komputasi & Storage:** Menggunakan perangkat keras lokal yang sudah dimiliki (`macOS arm64`, alokasi proyek maks `4–6 CPU`, `8 GiB RAM`, `15 GiB Disk`). Tidak ada penyewaan VM cloud/VPS berbayar.
   - **Model LLM & Embedding:** Hanya menggunakan kuota **Free-Tier API** (tanpa mengaktifkan penagihan berbayar / *auto-charge*) yang dikombinasikan dengan model open-source lokal ringan (`FastEmbed` / `Ollama <=3B`).
   - **Perangkat Lunak Pendukung:** 100% open-source / community self-hosted tanpa biaya langganan.

## 2. Kategori Biaya & Formula Unit Economics (`NFR-013`, `KPI-14`, `AT-015`)

Meskipun biaya tunai yang dikeluarkan adalah `$0.00`, sistem tetap wajib mencatat konsumsi resource aktual dan menghitung **Shadow / Reference Unit Cost** pada `C15`, `C20`, dan `C21` agar dapat memproyeksikan biaya secara transparan pada laporan evaluasi (`C23`/`C24`):

| Komponen Biaya | Status Saat Ini (C01) | Cara Pengukuran pada C15 / C20 / C21 | Basis Perhitungan Unit Economics |
|---|---|---|---|
| **LLM Inference Tokens** | `MEASURED_AT_RUNTIME = NOT_RUN` (Saat ini `$0` free-tier / lokal) | Mencatat `prompt_tokens`, `completion_tokens`, `total_tokens`, jumlah panggilan API, dan durasi per `incident_id` |1) Biaya aktual = `$0.00` (free-tier/lokal); 2) *Shadow commercial equivalent cost* dihitung menggunakan tarif referensi publik per 1 juta token (`input_tokens * ref_input_rate + output_tokens * ref_output_rate`) untuk analisis skala enterprise di `C23` |
| **Embedding Tokens / Chunks** | `MEASURED_AT_RUNTIME = NOT_RUN` | Mencatat jumlah dokumen/chunk yang di-embed saat ingesti awal dan saat re-index (`FR-RAG-008`) | `new_or_updated_tokens * ref_embedding_rate` (serta waktu CPU lokal untuk local embedding) |
| **Compute & Memory Usage** | Alokasi disetujui: `≤4–6 CPU`, `≤8 GiB RAM` | Mengukur puncak dan rata-rata CPU (%) serta RSS/Container Memory (MiB) per layanan selama run normal dan burst | Dilaporkan sebagai profil pemakaian resource per insiden (`CPU-seconds` dan `MiB-peak`) |
| **Storage & Index Footprint** | Alokasi disetujui: `≤15 GiB Disk` | Mengukur ukuran disk Qdrant index, log/metric/trace store, dan direktori `evidence/` | Dilaporkan dalam `MiB` per 1.000 log/spans dan per 100 dokumen KB |
| **Developer / Reviewer Effort** | `TBD` — dicatat per chapter/gate | Mencatat waktu aktual pengerjaan dan durasi review manual vs AI-assisted (`C19`) | Dilaporkan dalam satuan jam/menit kerja manusia |

**Aturan Denominator Biaya (`KPI-14`):**
- Biaya dan penggunaan token dari run yang **gagal, timeout, atau dibatalkan (`FAILED / TIMED_OUT / CANCELLED`) wajib tetap dicatat dan diungkapkan** sebagai *total experiment consumption*, serta dilaporkan berdampingan dengan *cost per completed incident* agar tidak memoles angka efisiensi.

## 3. Kebijakan Penghentian Saat Kuota / Kapasitas Tercapai (`Stop & Quota Exhaustion Policy`)

1. **Kuota Free-Tier API Tercapai (`Rate Limit / Daily Quota Exhausted`):**
   - Dilarang beralih ke API berbayar tanpa perubahan keputusan resmi.
   - Orchestrator menjalankan *bounded backoff* atau mengalihkan eksekusi ke model lokal ringan (`Ollama <=3B`) / *deterministic fallback* untuk pengujian ketahanan (`OPS-02`), atau menjeda batch evaluasi hingga jendela kuota free-tier berikutnya sambil menyimpan bukti audit lengkap.
2. **Plafon Resource Lab Tercapai (`>8 GiB RAM` atau `>15 GiB Disk`):**
   - Hentikan penambahan tingkat konkurensi baru, bersihkan kontainer/volume sementara yang sudah diarsipkan sesuai prosedur reset, dan catat batas tertinggi yang berhasil sebagai **Observed Lab Resource Ceiling** (`NFR-010`). Tingkat beban yang tidak muat (mis. 50 concurrent events jika melampaui 8 GiB RAM) wajib dilaporkan secara jujur sebagai `NOT_RUN / CAPACITY_CEILING_REACHED`, bukan dihapus atau dipalsukan.

## 4. Jadwal Berbasis Gate & Workload Envelope

1. **Jadwal Berbasis Gate (`Gate-Driven Progression`):**
   - Rentang 16 minggu pada Proposal v2.0 diperlakukan semata-mata sebagai **ilustrasi referensi**, bukan SLA atau tenggat kalender kaku.
   - Perpindahan antar-fase dikendalikan sepenuhnya oleh kesiapan bukti dan kelulusan Gate:
     - **Fase 1 (Foundation):** `C01` (`G0`) $\rightarrow$ `C02`–`C08` (`G1`)
     - **Fase 2 (Controlled Integration):** `C09`–`C12` (`G2`)
     - **Fase 3 (Reasoning & Observability):** `C13`–`C18` (`G3`)
     - **Fase 4 (Pilot & Hardening):** `C19`–`C24` (`G4`)
2. **Workload Envelope Perencanaan:**
   - Mencakup 14 skenario (`SC-01` s/d `SC-14`), uji burst *100 duplicate alerts* (`OPS-01` / `SC-12`), serta uji bertingkat `5 / 20 / 50 concurrent events` (`NFR-010`) sejauh kapasitas alokasi `8 GiB RAM` mendukung.
   - Ukuran korpus final (kandidat referensi: 100–200 query retrieval dan 30–50 incident replays) akan dikunci pada **Gate G1 (`C08`)** setelah profil kecepatan dan memori lokal terukur pada `C03`–`C07`.
