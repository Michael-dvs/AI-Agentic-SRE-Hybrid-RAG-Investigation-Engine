---
document_id: "SOP-AUTH-ERR-500"
document_version: "1.0.0"
title: "SOP Penanganan Error Internal 500 pada Verifikasi Token Auth"
service_id: "auth-service"
service.name: "Auth Service"
environment: "lab"
application: "sre-simulation-poc"
component: "identity"
status: "approved"
effective_from: "2026-02-15T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-auth-owner@sim.bank"
language: "id"
updated_at: "2026-02-15T00:00:00Z"
---

# SOP-AUTH-ERR-500: Penanganan Error Internal 500 pada Layanan Autentikasi

Dokumen ini memandu penanganan khusus error HTTP 500 yang bersumber dari internal proses `auth-service`. Prosedur ini berbeda dari error HTTP 500 pada `transaction-service`.

## 1. Identifikasi Anomali Internal Auth

Error HTTP 500 pada `auth-service` ditandai dengan:
- Respons JSON berisi `status_code: 500` dan `service_id: "auth-service"`.
- Log mencatat pesan unhandled exception pada modul cryptographic decoding atau modul validasi token sintetis.
- API Gateway mencatat error pemanggilan dependency auth saat klien mencoba mengakses endpoint privat.

## 2. Tindakan Isolasi dan Pemulihan

1. **Periksa Memory dan Thread Dump:**
   - Evaluasi penggunaan RAM kontainer `sre-sim-auth-service` untuk memastikan tidak terjadi kehabisan alokasi memori (*Out Of Memory*).
2. **Restart Layanan Mandiri (Graceful Restart):**
   - Jalankan restart proses auth service secara terkendali tanpa mempengaruhi kontainer lain.
3. **Verifikasi Post-Restart:**
   - Kirim synthetic test probe ke endpoint `/health/liveness` dan `/api/v1/auth/verify`.
   - Pastikan respon kembali bernilai HTTP 200 dengan payload JSON valid.

