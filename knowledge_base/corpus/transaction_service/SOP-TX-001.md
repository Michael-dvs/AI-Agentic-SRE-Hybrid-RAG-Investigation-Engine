---
document_id: "SOP-TX-001"
document_version: "1.0.0"
title: "SOP Penanganan Kegagalan Dependensi dan Degradasi Layanan Transaksi"
service_id: "transaction-service"
service.name: "Transaction Service"
environment: "lab"
application: "sre-simulation-poc"
component: "core-transaction"
status: "approved"
effective_from: "2026-01-20T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-transaction-owner@sim.bank"
language: "id"
updated_at: "2026-05-20T00:00:00Z"
---

# SOP-TX-001: Penanganan Kegagalan Dependensi Layanan Transaksi

SOP ini mengatur tindakan operator SRE saat `transaction-service` memicu alert `SimDependencyUnavailable` atau mengalami lonjakan error akibat kegagalan layanan downstream `ledger-service` atau antrean `notification-service`.

## 1. Indikasi Masalah dan Dampak Bisnis

Ketika dependensi downstream mengalami degradasi atau tidak dapat dihubungi:
- Transaksi pembuatan transfer dana (`POST /api/v1/transactions`) gagal dan mengembalikan respons HTTP 503 dengan kode `ERR_DOWNSTREAM_UNAVAILABLE`.
- Metrik korelasi dependensi menunjukkan error merambat (*cascade*) dari `ledger-service` menuju `transaction-service` dan berakhir pada `api-gateway`.
- Pesan transaksi tertahan dan event notifikasi asinkron tidak dapat dipublikasikan.

## 2. Prosedur Investigasi dan Mitigasi

Lakukan langkah penanganan berikut:
1. **Identifikasi Layanan Penyebab Utama:**
   - Periksa graf dependensi observabilitas (`/api/v1/topology` pada gateway) untuk mengidentifikasi apakah `ledger-service` atau `db-dummy` yang pertama kali memicu error.
   - Jangan melakukan restart pada `transaction-service` jika akar masalah berada pada downstream database atau ledger!
2. **Pengecekan Komunikasi HTTP Ledger:**
   - Cek apakah socket timeout atau connection refused terjadi saat memanggil `http://ledger-service:8000/api/v1/ledger/entries`.
3. **Penyelamatan Idempotency Key:**
   - Pastikan idempotency key dari transaksi yang gagal tidak terkunci permanen agar nasabah sintetis dapat melakukan retry tanpa error duplikasi palsu.

## 3. Eskalasi dan Handover

Jika `ledger-service` belum pulih dalam 3 menit:
- Rujuk SOP mitigasi ledger `SOP-LEDGER-001`.
- Eskalasi ke Tim SRE Data & Persistence.

