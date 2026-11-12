---
document_id: "SOP-NOTIF-QUEUE-001"
document_version: "1.0.0"
title: "SOP Mitigasi Backlog Pesan dan Consumer Lag RabbitMQ Notifikasi"
service_id: "notification-service"
service.name: "Notification Service"
environment: "lab"
application: "sre-simulation-poc"
component: "notification"
status: "approved"
effective_from: "2026-02-20T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-notif-owner@sim.bank"
language: "id"
updated_at: "2026-02-20T00:00:00Z"
---

# SOP-NOTIF-QUEUE-001: Mitigasi Backlog Pesan dan Consumer Lag RabbitMQ

SOP ini merupakan panduan cepat bagi operator saat laju publikasi transaksi melampaui laju konsumsi pesan oleh `notification-service`.

## 1. Ambang Batas dan Kriteria Kritis

- **Kondisi Normal:** Consumer lag kurang dari 10 pesan dengan latensi konsumsi di bawah 100ms.
- **Kondisi Peringatan (Warning):** Antrean menampung antara 50 hingga 200 pesan selama lebih dari 30 detik.
- **Kondisi Kritis:** Antrean melebihi 200 pesan atau konsumen berhenti melakukan acknowledgment pesan (`ack`), memicu alert `SimQueueConsumerLag`.

## 2. Tindakan Operasional di Lab

1. **Inspeksi Antrean:**
   - Jalankan perintah status antrean untuk melihat rasio `message_stats.publish_details.rate` terhadap `message_stats.deliver_get_details.rate`.
2. **Evaluasi Exception pada Worker:**
   - Cek log `sre-sim-notification-service` untuk memastikan tidak ada loop error JSON decoding atau koneksi terputus.
3. **Penyelarasan Prefetch Count:**
   - Sesuaikan parameter `basic_qos` prefetch menjadi 20 untuk meningkatkan throughput batching konsumen.

