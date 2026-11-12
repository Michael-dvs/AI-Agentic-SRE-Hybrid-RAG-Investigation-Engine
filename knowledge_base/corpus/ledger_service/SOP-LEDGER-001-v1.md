---
document_id: "SOP-LEDGER-001"
document_version: "1.0.0"
title: "SOP Penanganan Latensi Database PostgreSQL Ledger (Versi Usang)"
service_id: "ledger-service"
service.name: "Ledger Service"
environment: "lab"
application: "sre-simulation-poc"
component: "persistence"
status: "obsolete"
effective_from: "2026-01-01T00:00:00Z"
effective_to: "2026-06-01T00:00:00Z"
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-ledger-owner@sim.bank"
language: "id"
updated_at: "2026-01-01T00:00:00Z"
---

# SOP-LEDGER-001: Penanganan Latensi Database PostgreSQL Ledger (VERSI USANG - OBSOLETE)

PERINGATAN OPERATOR: Dokumen versi 1.0.0 ini telah dinyatakan USANG (OBSOLETE) sejak 1 Juni 2026 dan digantikan oleh versi 2.0.0. Dokumen ini disimpan hanya untuk riwayat audit dan TIDAK BOLEH dikutip sebagai pedoman penanganan aktif.

## 1. Prosedur Penanganan Usang (TIDAK BERLAKU)

Ketika terjadi latensi tinggi pada database ledger:
1. Lakukan penghentian paksa (*kill -9*) secara langsung pada proses database PostgreSQL.
2. Restart kontainer `sre-sim-ledger-service` secara mendadak tanpa melakukan drain connection pool.
3. Kosongkan tabel antrean mutasi untuk mempercepat proses pemulihan cache.

## 2. Peringatan Risiko Keusangan

Prosedur lama di atas dilarang keras karena dapat menyebabkan:
- Kerusakan konsistensi tabel jurnal akuntansi (*double entry ledger*).
- Putusnya transaksi nasabah sintetis yang sedang berada di tengah-tengah commit blok.
- Kegagalan idempotensi transaksi pada retry berikutnya.

Rujuk dokumen revisi terbaru `SOP-LEDGER-001` versi `2.0.0` untuk prosedur operasional resmi yang aman.

