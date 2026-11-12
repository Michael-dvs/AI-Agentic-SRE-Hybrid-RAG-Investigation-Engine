---
document_id: "ARCH-GW-001"
document_version: "1.1.0"
title: "Catatan Arsitektur: Reverse Proxy, Routing Ingress, dan Circuit Breaking Gateway"
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
updated_at: "2026-04-10T00:00:00Z"
---

# ARCH-GW-001: Arsitektur Reverse Proxy Ingress Gateway

Dokumen arsitektur ini menjelaskan topologi perutean, manajemen konteks korelasi, dan mekanisme proteksi sirkuit pada API Gateway lab simulasi.

## 1. Topologi Jaringan dan Tanggung Jawab

API Gateway berfungsi sebagai gerbang tunggal untuk seluruh lalu lintas klien eksternal ke dalam cluster microservices simulasi:
- Menerima request HTTP REST pada port publik lab (18080).
- Membangkitkan `X-Correlation-Id` acak bila klien tidak menyertakannya.
- Membaca atau menginisiasi header W3C `traceparent` untuk didistribusikan ke setiap downstream call.
- Memverifikasi otentikasi token Bearer melalui `auth-service` sebelum meneruskan ke endpoint bisnis `transaction-service`.

## 2. Kebijakan Circuit Breaking dan Timeout

- **Batas Timeout Default:** Batas waktu eksekusi request ke downstream dibatasi maksimum 3000 ms.
- **Circuit Breaker Threshold:** Jika tingkat kegagalan pemanggilan downstream melampaui 50% dalam interval 10 detik, sirkuit berpindah ke status `OPEN` selama 15 detik.
- **Fail-Fast Behaviour:** Pada status `OPEN`, gateway langsung mengembalikan respons `503 Service Unavailable` tanpa melakukan koneksi socket ke downstream, mencegah kehabisan file descriptor lokal.

