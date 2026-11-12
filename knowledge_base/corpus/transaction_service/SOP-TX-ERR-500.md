---
document_id: "SOP-TX-ERR-500"
document_version: "1.0.0"
title: "SOP Penanganan Error Internal 500 Pemrosesan Transaksi Finansial"
service_id: "transaction-service"
service.name: "Transaction Service"
environment: "lab"
application: "sre-simulation-poc"
component: "core-transaction"
status: "approved"
effective_from: "2026-02-10T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-transaction-owner@sim.bank"
language: "id"
updated_at: "2026-02-10T00:00:00Z"
---

# SOP-TX-ERR-500: Penanganan Error Internal 500 Pemrosesan Transaksi

Dokumen operasional ini menangani kode error HTTP 500 Internal Server Error yang terjadi secara spesifik di dalam komponen logika bisnis `transaction-service`. Prosedur ini berbeda dari error internal autentikasi.

## 1. Karakteristik Insiden

- Respons HTTP 500 dikembalikan oleh endpoint transaksi finansial simulasi.
- Error disebabkan oleh anomali kalkulasi saldo, kegagalan serialisasi data event transaksi, atau race condition pada cache idempotensi lokal.
- Metrik `sim_red_error_rate_ratio` pada `transaction-service` melampaui 0.20.

## 2. Tindakan Diagnostik

1. **Periksa Trace dan Correlation ID:**
   - Ekstrak `correlation_id` dari header respons gagal.
   - Telusuri alur eksekusi span internal transaction service untuk melihat fungsi Python mana yang melempar exception tak tertangani.
2. **Pengecekan Konsistensi Format Data:**
   - Pastikan tipe data nominal transaksi memenuhi skema numerik (bukan string atau nilai negatif).
3. **Penyelarasan Komunikasi Event Queue:**
   - Cek apakah koneksi publisher ke RabbitMQ mengalami hambatan channel buffer saat menerbitkan event `transaction_created`.

## 3. Resolusi dan Pemulihan

1. Jika kegagalan terkait channel antrean, lakukan reset koneksi publisher RabbitMQ.
2. Pastikan transaksi yang berstatus `INCONCLUSIVE` tidak menimbulkan inkonsistensi saldo ganda.

