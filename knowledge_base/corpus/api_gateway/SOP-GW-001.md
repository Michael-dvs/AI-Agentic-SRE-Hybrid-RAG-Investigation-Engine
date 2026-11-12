---
document_id: "SOP-GW-001"
document_version: "1.2.0"
title: "SOP Penanganan Lonjakan Error HTTP 5xx pada Ingress API Gateway"
service_id: "api-gateway"
service.name: "API Gateway"
environment: "lab"
application: "sre-simulation-poc"
component: "gateway"
status: "approved"
effective_from: "2026-01-15T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-gateway-owner@sim.bank"
language: "id"
updated_at: "2026-06-01T00:00:00Z"
---

# SOP-GW-001: Penanganan Lonjakan Error HTTP 5xx pada API Gateway

Dokumen Prosedur Operasional Standar ini mengatur langkah-langkah mitigasi dan investigasi saat API Gateway mengalami lonjakan respon HTTP 5xx (500, 502, 503, 504) yang melampaui Service Level Objective (SLO) error rate ratio 0.20 (20%).

## 1. Identifikasi dan Triage Awal

Saat alert `SimHighErrorRate` atau `SimDependencyUnavailable` terpicu pada API Gateway:
1. Periksa dashboard metrik RED pada Grafana (`sre-sim-overview-v1`) untuk memastikan endpoint mana yang mengalami kegagalan.
2. Identifikasi distribusi status code apakah didominasi oleh HTTP 500 (Internal Server Error), 502 (Bad Gateway), 503 (Service Unavailable), atau 504 (Gateway Timeout).
3. Periksa korelasi `trace_id` pada sampel log API Gateway untuk mengetahui apakah error bersumber dari gateway itu sendiri atau propagasi dari upstream service (`auth-service` atau `transaction-service`).

## 2. Prosedur Mitigasi Operasional

Lakukan langkah penanganan bertahap sesuai hasil triage:
1. **Pemeriksaan Upstream Connectivity:**
   - Jalankan pengecekan kesehatan upstream menggunakan endpoint internal `/health/readiness` pada layanan terkait.
   - Apabila upstream mengalami kegagalan total, pastikan circuit breaker gateway telah membuka sambungan agar tidak membebani upstream.
2. **Penerapan Rate Limiting Sementara:**
   - Jika lonjakan error diakibatkan oleh banjir request trafik, sesuaikan konfigurasi rate limit ingress melalui parameter konfigurasi gateway.
3. **Penyelarasan Timeout Ingress:**
   - Pastikan nilai timeout client ingress tidak lebih pendek daripada deadline pemrosesan upstream transaction service.

## 3. Langkah Eskalasi dan Handover

Apabila error rate tidak turun dalam waktu 5 menit setelah tindakan mitigasi:
1. Kumpulkan 5 sampel `trace_id` terbaru yang merepresentasikan transaksi gagal.
2. Lampirkan log error gateway dan grafik RED ke dalam dossier investigasi insiden.
3. Lakukan eskalasi ke Tim SRE L2 Core Banking dan pemilik layanan upstream terdampak.

