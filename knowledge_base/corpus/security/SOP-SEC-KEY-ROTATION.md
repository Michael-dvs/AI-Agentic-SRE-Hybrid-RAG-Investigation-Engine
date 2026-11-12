---
document_id: "SOP-SEC-KEY-ROTATION"
document_version: "1.0.0"
title: "SOP Rahasia Rotasi Master Secret dan Kunci Kriptografi Internal"
service_id: "auth-service"
service.name: "Auth Service"
environment: "lab"
application: "sre-simulation-poc"
component: "security"
status: "approved"
effective_from: "2026-01-01T00:00:00Z"
effective_to: null
classification: "synthetic-restricted"
allowed_groups:
  - "sre-core-l2"
  - "security-admin"
owner_ref: "sec-admin@sim.bank"
language: "id"
updated_at: "2026-01-01T00:00:00Z"
---

# SOP-SEC-KEY-ROTATION: Prosedur Rahasia Rotasi Kunci Kriptografi

DOKUMEN KLASIFIKASI RESTRICTED (TERBATAS).
Akses terhadap dokumen ini dibatasi hanya untuk grup otorisasi `sre-core-l2` dan `security-admin` (SEC-01). Akses oleh entitas tanpa hak otorisasi wajib ditolak oleh MCP Gateway.

## 1. Tujuan dan Ruang Lingkup Keamanan

Dokumen operasional tingkat tinggi ini mengatur tata cara penggantian kunci simetris dan pasangan kunci asimetris yang digunakan untuk penandatanganan token otentikasi internal dan enkripsi data transit di lingkungan lab.

## 2. Prosedur Rotasi Kunci Bertahap

Untuk mencegah kegagalan verifikasi mendadak pada sesi aktif:
1. **Pembangkitan Kunci Baru (Key Generation):**
   - Bangkitkan kunci baru dengan entropi tinggi dan simpan pada vault konfigurasi internal.
2. **Penerapan Dual-Key Verification Window:**
   - Daftarkan kunci baru sebagai *verification key* sekunder pada `auth-service` selama masa transisi 24 jam.
   - Layanan tetap menandatangani token baru dengan kunci lama untuk menjaga kompatibilitas mundur.
3. **Peralihan Kunci Utama (Key Switch):**
   - Alihkan penandatanganan token baru ke kunci baru.
   - Pertahankan kunci lama hanya untuk verifikasi token yang masih berada dalam masa berlaku.
4. **Pencabutan Kunci Lama (Key Revocation):**
   - Hapus kunci lama dari keystore setelah seluruh token lama kedaluwarsa.

## 3. Protokol Penanganan Kebocoran Darurat

Apabila terdeteksi indikasi kebocoran rahasia kunci:
1. Segera lakukan penarikan (*emergency revocation*) terhadap seluruh token aktif.
2. Paksa regenerasi sesi pada seluruh gateway ingress.
3. Catat audit log lengkap dan serahkan laporan investigasi kepada Kepala Keamanan Informasi.

