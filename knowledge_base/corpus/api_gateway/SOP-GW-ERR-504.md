---
document_id: "SOP-GW-ERR-504"
document_version: "1.0.0"
title: "SOP Penanganan Gateway Timeout 504 pada Ingress API"
service_id: "api-gateway"
service.name: "API Gateway"
environment: "lab"
application: "sre-simulation-poc"
component: "gateway"
status: "approved"
effective_from: "2026-02-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-gateway-owner@sim.bank"
language: "id"
updated_at: "2026-02-01T00:00:00Z"
---

# SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API

SOP ini digunakan secara spesifik untuk menangani kode error HTTP 504 Gateway Timeout yang terjadi pada lapisan Ingress API Gateway (`api-gateway`). Dokumen ini tidak berlaku untuk timeout database internal ledger.

## 1. Gejala dan Karakteristik Error

Error HTTP 504 pada API Gateway memiliki karakteristik berikut:
- Klien eksternal menerima status `504 Gateway Timeout` dengan pesan `ERR_UPSTREAM_TIMEOUT`.
- Waktu respon transaksi melebihi batas ingress gateway timeout (konfigurasi default 3.0 detik).
- Trace context menunjukkan rentang waktu tunggu terpanjang berada pada panggilan HTTP ke downstream `transaction-service` atau `auth-service`.

## 2. Prosedur Investigasi Keterlambatan Upstream

Langkah operasional yang wajib dijalankan operator:
1. **Analisis Trace Span:**
   - Cari root span transaksi pada Tempo menggunakan `trace_id`.
   - Identifikasi child span yang belum selesai (*hanging span*) atau memakan waktu di atas ambang batas SLO latensi 250ms.
2. **Pemeriksaan Health Dependency:**
   - Verifikasi metrik latensi P95 downstream pada Prometheus (`sim_red_latency_p95_ms`).
   - Apabila downstream transaction service mengalami latensi tinggi akibat antrean database, jangan naikkan ingress timeout gateway karena akan memperparah akumulasi worker thread.
3. **Penyekatan Alur Trafik Degradasi:**
   - Aktifkan graceful degradation mode bila transaksi non-kritis mengalami antrean.

## 3. Verifikasi Pasca-Penanganan

1. Pastikan request rate normal kembali dan metrik HTTP 504 melandai ke angka 0.
2. Catat durasi insiden dan verifikasi bahwa transaksi tertunda tidak mengalami status ganda (*duplicate execution*).

