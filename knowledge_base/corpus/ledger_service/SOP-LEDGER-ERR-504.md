---
document_id: "SOP-LEDGER-ERR-504"
document_version: "1.0.0"
title: "SOP Penanganan Query Timeout 504 pada Komunikasi PostgreSQL Ledger"
service_id: "ledger-service"
service.name: "Ledger Service"
environment: "lab"
application: "sre-simulation-poc"
component: "persistence"
status: "approved"
effective_from: "2026-02-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-ledger-owner@sim.bank"
language: "id"
updated_at: "2026-02-01T00:00:00Z"
---

# SOP-LEDGER-ERR-504: Penanganan Query Timeout 504 pada Ledger Service

SOP ini mengatur penanganan timeout pada tingkat internal Ledger Service saat melakukan query ke database PostgreSQL (`db-dummy`). Dokumen ini tidak boleh tertukar dengan timeout ingress pada API Gateway (`SOP-GW-ERR-504`).

## 1. Perbedaan Karakteristik dengan Gateway Timeout

Meskipun sama-sama mencatat status timeout 504:
- Error pada Ledger Service bersumber dari komunikasi TCP/SQL antara `ledger-service` dan `db-dummy`.
- Trace span menunjukkan child span `storage_call` yang melebihi parameter `statement_timeout`.
- Error log pada Ledger mencatat pesan kegagalan eksekusi query SQL `ERR_DATABASE_LATENCY`.

## 2. Tindakan Penanganan Khusus Ledger

1. **Evaluasi Statement Timeout:**
   - Cek apakah terdapat query pencarian riwayat transaksi yang memindai tabel tanpa indeks memadai.
2. **Pemeriksaan Lock Table:**
   - Periksa apakah operasi update saldo mengalami baris terkunci (*row-level lock contention*) akibat transaksi paralel pada akun sintetis yang sama.
3. **Penyelarasan Pool Timeout:**
   - Pastikan nilai `checkout_timeout` connection pool tidak menyebabkan pembatalan query prematur.

