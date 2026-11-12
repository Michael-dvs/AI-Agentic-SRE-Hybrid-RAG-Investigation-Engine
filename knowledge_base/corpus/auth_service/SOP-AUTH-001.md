---
document_id: "SOP-AUTH-001"
document_version: "1.0.0"
title: "SOP Investigasi Lonjakan Kegagalan Autentikasi dan Token Sintetis"
service_id: "auth-service"
service.name: "Auth Service"
environment: "lab"
application: "sre-simulation-poc"
component: "identity"
status: "approved"
effective_from: "2026-01-10T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
  - "security-admin"
owner_ref: "sre-auth-owner@sim.bank"
language: "id"
updated_at: "2026-05-15T00:00:00Z"
---

# SOP-AUTH-001: Investigasi Lonjakan Kegagalan Autentikasi

Prosedur standar ini digunakan ketika sistem memicu alert `SimAuthFailureSpike` pada `auth-service` yang menunjukkan tingginya tingkat kegagalan verifikasi identitas token sintetis.

## 1. Indikator dan Pemicu Alert

Alert dipicu saat metrik `sim_auth_failure_errors_total` mengalami kenaikan signifikan atau melebihi ambang batas operasional:
- Klien menerima respons HTTP 401 Unauthorized dengan error code `ERR_AUTH_REJECTED`.
- Log audit pada `auth-service` mencatat event `token_verification_failed` berulang.
- Indeks error rate `auth-service` melonjak tajam pada dashboard Prometheus.

## 2. Prosedur Investigasi dan Validasi

Lakukan tahapan investigasi terstruktur:
1. **Analisis Format Token:**
   - Periksa apakah kegagalan disebabkan oleh token kedaluwarsa (*expired token*), format Bearer yang cacat, atau manipulasi signature kriptografi.
   - Pastikan header authorization dikirimkan dengan prefiks `Bearer `.
2. **Pengecekan Sinkronisasi Waktu (Clock Skew):**
   - Verifikasi apakah terdapat pergeseran waktu sistem antara API Gateway dan Auth Service yang menyebabkan token dianggap tidak valid sebelum waktunya.
3. **Pemeriksaan Master Signing Key:**
   - Periksa apakah ada deployment baru atau perubahan konfigurasi rahasia internal yang menyebabkan perbedaan key antara penerbit dan pemverifikasi token.

## 3. Eskalasi dan Resolusi

1. Jika terbukti terjadi perbedaan konfigurasi key (*key mismatch*), rujuk dokumen `KNOWN-ERR-AUTH-001`.
2. Jika terdeteksi percobaan serangan brute force sintetis dari satu klien dummy, perintahkan operator untuk menerapkan IP blocking sementara pada gateway.

