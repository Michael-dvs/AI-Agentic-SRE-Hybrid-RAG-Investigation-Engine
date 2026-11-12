---
document_id: "KNOWN-ERR-NOTIF-001"
document_version: "1.0.0"
title: "Known Error: Blocking Socket I/O pada Consumer Event Notifikasi"
service_id: "notification-service"
service.name: "Notification Service"
environment: "lab"
application: "sre-simulation-poc"
component: "notification"
status: "approved"
effective_from: "2026-03-05T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-notif-owner@sim.bank"
language: "id"
updated_at: "2026-03-05T00:00:00Z"
---

# KNOWN-ERR-NOTIF-001: Blocking Socket I/O pada Consumer Event

Artikel Known Error ini mendokumentasikan anomali di mana worker konsumen notifikasi berhenti merespons heartbeat broker RabbitMQ saat menerima batch event dalam jumlah besar.

## 1. Penyebab Masalah

- **Deskripsi:** Ketika proses konsumen memproses pemformatan template notifikasi secara sinkron di main thread, loop event asyncio terblokir selama lebih dari ambang batas heartbeat RabbitMQ (default 60 detik). Broker kemudian menganggap koneksi terputus dan menutup channel secara sepihak.
- **Gejala:** Pesan tidak di-ack dan kembali ke antrean (*re-queued*), menyebabkan lonjakan antrean tak berujung.

## 2. Solusi Sementara dan Penanganan

1. Gunakan thread terpisah atau worker non-blocking untuk rendering konten notifikasi.
2. Tingkatkan nilai `heartbeat` pada koneksi AMQP menjadi 120 detik pada lingkungan lab simulasi.
3. Restart proses konsumen notifikasi bila channel terlanjur ditutup oleh broker.

