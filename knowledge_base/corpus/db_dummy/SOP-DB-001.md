---
document_id: "SOP-DB-001"
document_version: "1.0.0"
title: "SOP Penanganan Saturasi Connection Pool dan Latensi Tinggi PostgreSQL Lab"
service_id: "db-dummy"
service.name: "PostgreSQL Database"
environment: "lab"
application: "sre-simulation-poc"
component: "database"
status: "approved"
effective_from: "2026-01-05T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
  - "dba-team"
owner_ref: "sre-dba-owner@sim.bank"
language: "id"
updated_at: "2026-04-01T00:00:00Z"
---

# SOP-DB-001: Penanganan Saturasi Connection Pool Database PostgreSQL

SOP ini mengatur tindakan operator basis data ketika instance PostgreSQL (`db-dummy`) mengalami lonjakan latensi eksekusi query atau saturasi pada jumlah koneksi aktif.

## 1. Identifikasi dan Pengawasan Sinyal Database

Kondisi kritis pada lapisan basis data diindikasikan oleh:
- Metrik alert `SimConnectionPoolExhausted` aktif dengan error code `ERR_POOL_EXHAUSTED`.
- Latensi commit transaksi pada tabel `ledger_entries` melonjak di atas 500ms.
- Log container `sre-sim-postgres` mencatat pesan `FATAL: remaining connection slots are reserved for non-replication superuser connections`.

## 2. Tindakan Diagnostik dan Remediasi

1. **Inspeksi Kueri Terlama (Long-Running Queries):**
   - Jalankan pemeriksaan terhadap kueri aktif yang berjalan lebih dari 5 detik menggunakan kueri sistem:
     `SELECT pid, now() - query_start AS duration, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC;`
2. **Penghentian Kueri Macet Secara Aman:**
   - Hentikan proses kueri yang mengalami deadlock menggunakan `SELECT pg_cancel_backend(pid);`.
   - Hindari penggunaan `pg_terminate_backend()` kecuali kueri tersebut tidak merespons sinyal cancel dalam 30 detik.
3. **Penyelarasan Konfigurasi Connection Limits:**
   - Pastikan konfigurasi `max_connections` pada PostgreSQL lab disetel seimbang dengan memory ceiling (kapasitas 100 koneksi pada RAM 512 MiB).

## 3. Verifikasi Pasca-Remediasi

1. Pastikan persentase penggunaan koneksi kembali di bawah 60% dari batas maksimum.
2. Konfirmasikan bahwa `ledger-service` dapat kembali melakukan pembacaan dan penulisan jurnal secara normal.

