# Lab Readiness and Resource Envelope — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision Reference:** `TBD-03` (`APPROVED` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Probe Timestamp (UTC):** `2026-11-09T04:31:39Z` (`2026-11-09T11:31:39+07:00` WIB)
- **Target Label Sintetis:** `local-macos-arm64-docker-lab`

## 1. Fakta Kapasitas Host yang Terukur vs Alokasi yang Disetujui

Pemeriksaan dilakukan menggunakan perintah *read-only* lokal sesuai Step 04 (`uname`, `sw_vers`, `sysctl`, `df -Pk .`, `command -v`). Tidak ada daemon, container, atau beban kerja aplikasi yang dijalankan pada tahap ini.

| Parameter | Nilai Terukur (Observed Host Capacity) | Satuan / Sumber Perintah / Waktu | Alokasi yang Disetujui untuk Proyek (`Approved Allocation`) | Status Approval & Owner |
|---|---|---|---|---|
| **Sistem Operasi & Arsitektur** | `Darwin` / `arm64` / macOS `27.0.1` | Output `uname -s`, `uname -m`, `sw_vers -productVersion` (`2026-11-09T04:31:39Z`) | Host pengembangan & eksekusi lokal (`macOS` + `Docker Compose lokal`) | `APPROVED` (`project-initiator-michael`) |
| **CPU** | `8` | Logical CPUs dari `sysctl -n hw.ncpu` (`2026-11-09T04:31:39Z`) | **Maksimum 4–6 logical CPUs** untuk seluruh stack Docker Compose + proses lokal proyek (menyisakan ≥2–4 CPU untuk OS & IDE) | `APPROVED` (`project-initiator-michael`) |
| **Total RAM** | `17179869184` (`16 GiB`) | Bytes dari `sysctl -n hw.memsize` (`2026-11-09T04:31:39Z`) | **Maksimum `8589934592` bytes (`8 GiB`)** untuk seluruh stack Docker Compose & model/embedding lokal (menyisakan `8 GiB` untuk macOS & IDE) | `APPROVED` (`project-initiator-michael`) |
| **Ruang Disk Tersedia** | `41418100` (`~39.50 GiB` tersedia dari total `239362496` blok) | 1024-byte blocks dari `df -Pk .` pada `/System/Volumes/Data` (`2026-11-09T04:31:39Z`) | **Maksimum `15728640` blok 1K (`15 GiB`)** untuk image container, volume DB/Qdrant/telemetry, dan artefak evidence | `APPROVED` (`project-initiator-michael`) |
| **Target Jaringan** | `local-docker-bridge-isolated` | Review konfigurasi operator (`2026-11-09`) | Isolasi bridge network lokal Docker Compose; tidak ada koneksi ke jaringan korporat/bank; egress hanya diizinkan ke endpoint LLM Free-Tier yang disahkan untuk payload sintetis tersanitasi | `APPROVED` (`project-initiator-michael`) |
| **Utilitas Lokal yang Tersedia** | `/bin/bash`, `/usr/bin/shasum`, `/usr/local/bin/docker` | `command -v` (`2026-11-09T04:31:39Z`) | Tidak ada instalasi package baru pada C01; kesiapan daemon Docker Compose baru akan diuji pada C03 | `APPROVED` (`project-initiator-michael`) |

## 2. Perbedaan Observed vs Allocated vs Future Workload Estimate

1. **Observed Host Capacity (`8 CPU / 16 GiB RAM / ~39.5 GiB Free Disk`):** Kapasitas fisik/logis mesin saat pemeriksaan; **bukan** jumlah yang seluruhnya bebas dipakai oleh proyek.
2. **Approved Allocation (`4–6 CPU / 8 GiB RAM / 15 GiB Disk`):** Batas anggaran resource (*resource budget*) tempat seluruh komponen simulasi (5 layanan ringan, koleksi telemetri, vector store, workflow agent, dan model/embedding lokal `<=3B`) wajib muat.
3. **Future Workload Estimate (Belum Diuji):** Kemampuan nyata menjalankan 5/20/50 *concurrent events* (`NFR-010`) atau *100 duplicate alert storm* (`OPS-01`) baru akan diukur secara empiris pada C03, C10, dan C20.

## 3. Implikasi Desain untuk Chapter C02 (`ADR-S01`, `ADR-S02`, `TBD-05`, `TBD-06`)

Karena alokasi RAM Docker Lab dibatasi pada **maksimum 8 GiB**:
- Pemilihan komponen pada C02/C08 wajib memprioritaskan *memory footprint* yang rendah (misalnya memilih Qdrant native hybrid dense+sparse dibanding menjalankan Qdrant + cluster Elasticsearch penuh secara bersamaan bila bukti eksperimen C07 mendukung, serta memilih layanan dummy Python/Go/Node yang hemat memori).
- Apabila model lokal Ollama (`<=3B`) digunakan sebagai fallback atau saat pengujian outage (`OPS-02`), orkestrasi memori harus memastikan total penggunaan tidak melewati plafon 8 GiB.
