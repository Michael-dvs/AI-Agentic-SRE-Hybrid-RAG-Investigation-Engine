---
document_id: "POSTMORTEM-TX-001"
document_version: "1.0.0"
title: "Simulated Post-Mortem: Kegagalan Berantai Transaksi Saat Layanan Ledger Tidak Tersedia"
service_id: "transaction-service"
service.name: "Transaction Service"
environment: "lab"
application: "sre-simulation-poc"
component: "core-transaction"
status: "approved"
effective_from: "2026-03-10T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
  - "management"
owner_ref: "sre-lead@sim.bank"
language: "id"
updated_at: "2026-03-10T00:00:00Z"
---

# POSTMORTEM-TX-001: Kegagalan Berantai Pemrosesan Transaksi Finansial

Laporan post-mortem insiden simulasi ini mendokumentasikan analisis akar masalah, kronologi, dan tindakan preventif terhadap kegagalan berantai (*cascading failure*) yang melumpuhkan pemrosesan transaksi.

## 1. Ringkasan Insiden dan Dampak

- **Waktu Kejadian:** Simulasi Uji Ketahanan Kuartal 1 2026.
- **Gejala Utama:** Klien eksternal menerima lonjakan HTTP 503 dari API Gateway, dengan error log downstream unavailable pada Transaction Service.
- **Dampak:** 100% permintaan transaksi finansial gagal dieksekusi selama periode pemadaman 120 detik.
- **Akar Masalah (Root Cause):** Layanan `ledger-service` mengalami degradasi akibat latensi database, yang menyebabkan thread pool pada `transaction-service` terisi penuh oleh request yang menunggu respons sinkron tanpa circuit breaker aktif.

## 2. Analisis Kronologi dan Deteksi Telemetri

1. **00:00:** Latensi database PostgreSQL melonjak di atas 500ms.
2. **00:15:** `ledger-service` mulai mengalami antrean pemrosesan entri jurnal akuntansi.
3. **00:30:** `transaction-service` kehabisan koneksi worker HTTP karena panggilan sinkron ke ledger memakan waktu lebih lama dari biasanya.
4. **00:45:** API Gateway mendeteksi kegagalan upstream dan memicu alert error rate tinggi.

## 3. Tindakan Perbaikan (Action Items)

- [SELESAI] Penerapan circuit breaker pada pemanggilan antar-mikroservis dengan ambang kegagalan 50%.
- [SELESAI] Penambahan bounded timeout maksimal 1500ms pada client HTTP Transaction Service.
- [SELESAI] Penyediaan endpoint observabilitas topologi graf ketergantungan untuk deteksi cepat cascade origin.

