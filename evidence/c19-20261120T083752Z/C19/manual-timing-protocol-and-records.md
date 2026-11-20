# Protokol Anti-Carryover & Rekaman Blinded Manual Baseline (C19)

- **Run ID:** `c19-20261120T083752Z`
- **Split Dataset:** `dev` (100% terisolasi dari `H-G3` dan `H-G4`)
- **Assessment Kind:** `self_review_lab_owner`
- **Label Source:** `SELF_EVALUATED_DEVELOPER_LABELS`
- **Anti-Carryover Lock Enforced:** `True`

## 1. Deklarasi Batas Validitas (`RULE-011`, `TBD-02`, `TBD-08`, `ADR-S08`)

> Pengukuran baseline manual dan review dijalankan di lab simulasi oleh pengembang tunggal (project-initiator-michael). Meskipun urutan stempel waktu anti-carryover dikunci dengan lock_sha256 sebelum membuka dossier AI, bias familiaritas penyusun skenario tetap melekat dan hasil ini tidak diklaim sebagai uji validasi SME perbankan independen.

- **Independent SME Validated:** `false` (solo developer lab evaluation)
- **Perbedaan Metrik Waktu:**
  - `manual_seconds`: Durasi investigasi manual AS-IS (alert -> query log/metrik/trace manual -> grep SOP -> rumusan hipotesis), dikunci (`manual_locked_at` + `lock_sha256`) **sebelum** dossier AI dibuka.
  - `system_tti_seconds`: Latensi runtime mesin investigasi agentic (`KPI-07`: intake -> dossier `PENDING_REVIEW`).
  - `human_review_seconds`: Durasi penelaahan manusia di Unified TUI Console hingga keputusan final.
  - `assisted_seconds`: Total waktu investigasi berbantuan AI (`system_tti_seconds + human_review_seconds`) yang dipasangkan ke `KPI-08`.

## 2. Ringkasan Perbandingan Waktu (`KPI-08`)

| Metrik | Nilai Terukur |
|---|---|
| Jumlah Pasangan Matched (`DEV`) | 7 |
| Median Manual AS-IS (`manual_seconds`) | 340.000 s |
| Median System TTI (`KPI-07`) | 0.032 s |
| Median Human Review Effort | 40.000 s |
| Median AI-Assisted Total (`assisted_seconds`) | 40.032 s |
| Pengurangan Waktu Relatif (`KPI-08`) | 88.23% (`0.8823`) |
| Rata-Rata Langkah Manual | 9.14 langkah |

## 3. Rekaman Pasangan Kasus `DEV` & Bukti Lock Anti-Carryover

| Incident ID | Layanan | Kasus | Manual (s) | System TTI (s) | Human Review (s) | Assisted (s) | Locked Before AI | Lock Timestamp (UTC) | AI Opened (UTC) |
|---|---|---|---:|---:|---:|---:|---|---|---|
| `inc-pilot-dev-sc01-001` | `api-gateway` | DEV-01 Healthy Control Baseline | 185.00 | 0.042 | 22.00 | 22.042 | `True` | `2026-11-20T07:11:04Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc02-002` | `transaction-service` | DEV-02 Single Fault HTTP 5xx Burst | 340.00 | 0.032 | 38.00 | 38.032 | `True` | `2026-11-20T07:17:06Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc03-003` | `ledger-service` | DEV-03 Single Fault DB Connection Pool Exhaustion | 410.00 | 0.029 | 45.00 | 45.029 | `True` | `2026-11-20T07:24:18Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc04-004` | `api-gateway` | DEV-04 Cascade Failure Gateway -> Transaction -> Ledger | 520.00 | 0.034 | 62.00 | 62.034 | `True` | `2026-11-20T07:33:20Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc06-005` | `auth-service` | DEV-05 Auth Token Mismatch & Obsolete SOP Exclusion | 295.00 | 0.023 | 35.00 | 35.023 | `True` | `2026-11-20T07:38:37Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc07-006` | `notification-service` | DEV-06 Queue Consumer Lag (Human Correction v1->v2) | 365.00 | 0.029 | 78.00 | 78.029 | `True` | `2026-11-20T07:45:04Z` | `2026-11-20T08:37:52Z` |
| `inc-pilot-dev-sc09-007` | `api-gateway` | DEV-07 Degraded Mode / Trace Backend Outage | 270.00 | 0.032 | 40.00 | 40.032 | `True` | `2026-11-20T07:49:56Z` | `2026-11-20T08:37:52Z` |

## 4. Catatan Hambatan Pencarian Dokumen Manual

- **`inc-pilot-dev-sc01-001` (5 langkah):** Harus memeriksa log Loki, metrik RED Prometheus, dan memastikan tidak ada error tersembunyi lintas gateway. (Lock SHA-256: `e7af853d7fb5821d...`)
- **`inc-pilot-dev-sc02-002` (9 langkah):** Pencarian grep manual pada korpus markdown untuk mencocokkan error code ERR_TRANSACTION_FAILED dengan SOP-TX-ERR-500. (Lock SHA-256: `33e641e9b7364b32...`)
- **`inc-pilot-dev-sc03-003` (11 langkah):** Perlu memilah manual antara SOP-LEDGER-001-v1 yang obsolete dan SOP-LEDGER-001-v2 yang masih aktif. (Lock SHA-256: `cbb3b12a6b6cf6ff...`)
- **`inc-pilot-dev-sc04-004` (14 langkah):** Korelasi manual trace_id melintasi 3 layanan dan pembacaan 3 dokumen SOP terpisah memakan waktu lama. (Lock SHA-256: `3e2634a22d955b3e...`)
- **`inc-pilot-dev-sc06-005` (8 langkah):** Harus memverifikasi tanggal efektif dan status approved pada metadata front-matter SOP-AUTH secara manual. (Lock SHA-256: `a1dbbde8a0be7ead...`)
- **`inc-pilot-dev-sc07-006` (10 langkah):** Memerlukan pemeriksaan backlog RabbitMQ dan penyuntingan hipotesis agar rincian consumer lag terekam akurat. (Lock SHA-256: `0f21bfd1d5d90354...`)
- **`inc-pilot-dev-sc09-007` (7 langkah):** Waktu habis menguji endpoint Tempo yang down sebelum memastikan bahwa trace memang tidak tersedia. (Lock SHA-256: `fe491f3726c5f8b6...`)
