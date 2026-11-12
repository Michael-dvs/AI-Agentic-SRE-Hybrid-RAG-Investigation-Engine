---
document_id: "ARCH-SIM-ECOSYSTEM"
document_version: "1.0.0"
title: "Catatan Arsitektur: Topologi Mikroservis dan Aliran Data Sintetis SRE Lab"
service_id: "api-gateway"
service.name: "API Gateway"
environment: "lab"
application: "sre-simulation-poc"
component: "gateway"
status: "approved"
effective_from: "2026-01-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
  - "architects"
owner_ref: "lead-architect@sim.bank"
language: "id"
updated_at: "2026-01-01T00:00:00Z"
---

# ARCH-SIM-ECOSYSTEM: Topologi Arsitektur Ekosistem Simulasi SRE

Dokumen ini menjelaskan rancang bangun ekosistem lima mikroservis simulasi, backend persistence, message broker, serta pipeline telemetri observabilitas.

## 1. Aliran Permintaan Sinkron (Synchronous Flow)

Alur permintaan transaksi nasabah sintetis bergerak melalui jalur berikut:
1. Klien eksternal mengirim request HTTP POST ke `api-gateway`.
2. Gateway memvalidasi token Bearer melalui pemanggilan internal ke `auth-service`.
3. Setelah otentikasi lolos, gateway meneruskan transaksi ke `transaction-service`.
4. `transaction-service` memanggil `ledger-service` untuk pencatatan entri akuntansi ke database `db-dummy`.
5. Respons sukses dikembalikan ke klien melalui rantai pembalikan yang sama.

## 2. Aliran Peristiwa Asinkron (Asynchronous Event Flow)

Setelah commit data pada `ledger-service` selesai:
1. `transaction-service` menerbitkan event `transaction_created` ke broker RabbitMQ.
2. `notification-service` mengonsumsi event tersebut secara asinkron dari antrean `events.notifications`.
3. Notifikasi diformat dan dicatat sebagai bukti pengiriman sintetis tanpa menghambat latensi request HTTP klien.

## 3. Integrasi Telemetri Observabilitas

Seluruh mikroservis mengalirkan tiga sinyal telemetri utama:
- **Metrik RED:** Diekspos melalui endpoint `/metrics` dan di-scrape oleh Prometheus setiap 5 detik.
- **Structured Logs:** Dikirim dalam format JSON berstandar ke Loki melalui OpenTelemetry Collector.
- **Distributed Traces:** Diteruskan dengan konteks W3C `traceparent` ke Tempo untuk analisis latensi multi-hop.

