---
document_id: "KNOWN-ERR-LEDGER-001"
document_version: "1.0.0"
title: "Known Error: Kebocoran Koneksi pada Idle Session Pool Database"
service_id: "ledger-service"
service.name: "Ledger Service"
environment: "lab"
application: "sre-simulation-poc"
component: "persistence"
status: "approved"
effective_from: "2026-03-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-ledger-owner@sim.bank"
language: "id"
updated_at: "2026-03-01T00:00:00Z"
---

# KNOWN-ERR-LEDGER-001: Kebocoran Koneksi Idle pada Pool Database Ledger

Dokumen Known Error ini mencatat masalah teknis di mana koneksi PostgreSQL tidak dikembalikan ke pool saat terjadi timeout pada sisi klien sebelum respons selesai dikirim.

## 1. Uraian Masalah dan Gejala

- **Deskripsi:** Ketika klien memutus koneksi di tengah transaksi baca yang lambat, connection pooler tidak menerima event penutupan soket sehingga status sesi di database tetap berada pada `idle in transaction`.
- **Dampak:** Jumlah koneksi aktif terakumulasi hingga mencapai batas `max_connections` (alert `SimConnectionPoolExhausted`).
- **Log Error:** Pesan `ERR_POOL_EXHAUSTED` muncul pada request mutasi berikutnya.

## 2. Prosedur Workaround dan Mitigasi

1. **Jalankan Pembersihan Sesi Idle:**
   - Gunakan query pembersihan sesi `idle in transaction` yang berdurasi lebih dari 60 detik.
2. **Aktifkan Konfigurasi TCP Keepalive:**
   - Terapkan parameter `idle_in_transaction_session_timeout = 30000` (30 detik) pada konfigurasi database PostgreSQL.
3. **Verifikasi:**
   - Amati metrik koneksi aktif dan pastikan jumlah connection pool kembali berada di bawah 50% kapasitas.

