---
document_id: "SOP-LEDGER-001"
document_version: "2.0.0"
title: "SOP Penanganan Latensi Database PostgreSQL Ledger (Versi Aktif)"
service_id: "ledger-service"
service.name: "Ledger Service"
environment: "lab"
application: "sre-simulation-poc"
component: "persistence"
status: "approved"
effective_from: "2026-06-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-ledger-owner@sim.bank"
language: "id"
updated_at: "2026-06-01T00:00:00Z"
---

# SOP-LEDGER-001: Penanganan Latensi Database PostgreSQL Ledger (VERSI RESMI AKTIF)

Prosedur Operasional Standar resmi ini mengatur mitigasi anomali latensi tinggi dan saturasi koneksi database PostgreSQL pada `ledger-service`. Dokumen ini menggantikan seluruh versi sebelumnya.

## 1. Identifikasi dan Triage Latensi Ledger

Alert `SimHighLatencyP95` atau `SimConnectionPoolExhausted` pada `ledger-service` mengindikasikan:
- Latensi P95 pemrosesan jurnal akuntansi melebihi ambang batas 250ms.
- Terjadi akumulasi koneksi pada PostgreSQL pool (`db-dummy`).
- Klien upstream mengalami error `ERR_DATABASE_LATENCY` atau timeout pada request mutasi saldo.

## 2. Prosedur Mitigasi Bertahap yang Aman

DILARANG melakukan kill paksa atau restart mendadak pada database! Ikuti prosedur bertahap berikut:
1. **Inspeksi Aktivitas Database:**
   - Periksa sesi aktif pada tabel `pg_stat_activity` untuk mengidentifikasi apakah terdapat query yang mengalami lock contention atau transaksi berdurasi panjang.
2. **Penerapan Graceful Connection Drain:**
   - Atur connection pool ledger agar menolak koneksi baru sementara dan menyelesaikan transaksi aktif yang sedang berjalan (*connection draining*).
3. **Penyelarasan Pool Limit:**
   - Verifikasi apakah parameter `LEDGER_DB_POOL_SIZE` telah mencapai batas maksimal (default 20 koneksi). Jika terjadi saturasi akibat lonjakan trafik sesaat, tingkatkan batas pool secara terkendali.
4. **Reload Konfigurasi Tanpa Downtime:**
   - Terapkan reload konfigurasi runtime melalui sinyal standar tanpa mematikan proses PostgreSQL server.

## 3. Verifikasi Pasca-Mitigasi dan Eskalasi

1. Pastikan latensi P95 kembali turun di bawah 100ms dan error rate kembali ke 0%.
2. Lakukan audit integritas mutasi saldo untuk memastikan seluruh jurnal debet dan kredit tercatat seimbang.
3. Jika degradasi berlangsung lebih dari 10 menit, eskalasi ke Tim DBA Spesialis PostgreSQL.

