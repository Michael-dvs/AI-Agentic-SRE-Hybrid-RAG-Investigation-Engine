---
document_id: "KNOWN-ERR-AUTH-001"
document_version: "1.0.0"
title: "Known Error: Validasi Signature Token Asinkron Mengalami Mismatch Key"
service_id: "auth-service"
service.name: "Auth Service"
environment: "lab"
application: "sre-simulation-poc"
component: "identity"
status: "approved"
effective_from: "2026-03-01T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
  - "l1-operator"
  - "l2-investigator"
owner_ref: "sre-auth-owner@sim.bank"
language: "id"
updated_at: "2026-03-01T00:00:00Z"
---

# KNOWN-ERR-AUTH-001: Mismatch Key pada Validasi Signature Token

Artikel Known Error ini mendokumentasikan insiden berulang di mana klien otentikasi mengalami kegagalan validasi signature token akibat ketidakcocokan konfigurasi verifikasi kunci.

## 1. Deskripsi Masalah

Ketika service mengalami inisialisasi ulang dengan variabel lingkungan yang tidak selaras, modul verifikator token menggunakan default signing key yang berbeda dari generator token simulasi.
- **Gejala:** 100% request yang melewati gateway menerima respons `ERR_AUTH_REJECTED` meskipun format Bearer token valid secara struktural.
- **Root Cause Historis:** Perbedaan nilai secret pada file environment lokal atau keterlambatan reload cache keystore internal.

## 2. Solusi Permanen dan Solusi Sementara (Workaround)

- **Solusi Sementara (Workaround):**
  1. Periksa variabel `AUTH_JWT_SECRET` pada konfigurasi `auth-service`.
  2. Samakan nilai variabel lingkungan dengan konfigurasi yang ditetapkan pada master profile.
  3. Lakukan reload konfigurasi proses melalui sinyal HUP atau restart kontainer auth.
- **Verifikasi:**
  Jalankan verifikasi token sintetis menggunakan request pengujian ke endpoint `/api/v1/auth/verify` dan pastikan payload mengembalikan `valid: true`.

