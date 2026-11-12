---
document_id: "SOP-NOTIF-001"
document_version: "1.0.0"
title: "SOP Pemantauan dan Penanganan Antrean Konsumen Notifikasi Asinkron"
service_id: "notification-service"
service.name: "Notification Service"
environment: "lab"
application: "sre-simulation-poc"
component: "notification"
status: "approved"
effective_from: "2026-01-25T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-notif-owner@sim.bank"
language: "id"
updated_at: "2026-05-10T00:00:00Z"
---

# SOP-NOTIF-001: Pemantauan dan Penanganan Antrean Konsumen Notifikasi

SOP ini mengatur tindakan SRE saat terjadi kegagalan pemrosesan event asinkron pada `notification-service` atau terpicunya alert antrean.

## 1. Identifikasi Anomali Konsumen Notifikasi

Gejala kegagalan pada lapisan notifikasi asinkron meliputi:
- Alert `SimQueueConsumerLag` aktif pada Prometheus atau metrik log mencatat akumulasi pesan tertahan.
- Transaksi finansial berhasil dicatat di Ledger, namun notifikasi pengiriman email/SMS sintetis tidak terkirim.
- Log notification service mencatat error socket timeout atau channel closure saat mengonsumsi event dari antrean `events.notifications`.

## 2. Prosedur Investigasi dan Mitigasi

1. **Periksa Status Worker RabbitMQ:**
   - Periksa kesehatan antrean pesan RabbitMQ melalui port manajemen lab (15672) atau status kontainer `sre-sim-rabbitmq`.
   - Pastikan worker konsumen aktif dan tidak berada dalam status deadlock atau crash loop.
2. **Pengecekan Dead Letter Queue (DLQ):**
   - Periksa apakah terdapat pesan berformat cacat yang terlempar berulang kali dan memicu retries berlebih (*poison pill message*).
   - Pindahkan pesan cacat ke dead-letter exchange agar tidak menghambat aliran antrean utama.
3. **Penyelarasan Skala Worker:**
   - Jika backlog pesan diakibatkan oleh lonjakan trafik spike yang sah, naikkan concurrency prefetch count konsumen secara terukur.

## 3. Verifikasi Pasca-Penanganan

1. Pastikan jumlah pesan tidak terkirim (*unacknowledged messages*) melandai ke angka 0.
2. Verifikasi idempotensi event notifikasi agar nasabah sintetis tidak menerima pesan ganda.

