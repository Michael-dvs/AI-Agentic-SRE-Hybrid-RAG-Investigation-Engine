---
document_id: "ARCH-DB-001"
document_version: "1.0.0"
title: "Catatan Arsitektur: Topologi Persistence dan Bounded Connection Pool PostgreSQL"
service_id: "db-dummy"
service.name: "PostgreSQL Database"
environment: "lab"
application: "sre-simulation-poc"
component: "database"
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

# ARCH-DB-001: Arsitektur Persistence dan Connection Pool Database

Dokumen arsitektur ini memaparkan desain penyimpanan data persistent dan batas alokasi koneksi pada lingkungan lab simulasi microservices.

## 1. Topologi Persistence dan Skema Database

Instance database `sre-sim-postgres` bertindak sebagai backend persistence untuk seluruh data transaksional:
- Menggunakan mesin PostgreSQL 16 kompatibel ARM64.
- Skema terisolasi dengan tabel utama `ledger_entries`, `accounts`, dan `idempotency_keys`.
- Menggunakan volume persistent Docker untuk menjamin data tetap utuh saat kontainer di-restart.

## 2. Batas Alokasi Memori dan Resource Ceiling

- **Memory Cap:** PostgreSQL dibatasi maksimum 512 MiB RAM untuk mematuhi anggaran total lab 8 GiB.
- **Connection Sizing:** Maksimal alokasi koneksi dibatasi pada angka 100 koneksi bersama, dengan alokasi default 20 koneksi untuk `ledger-service`.
- **Statement Timeout:** Default statement timeout disetel pada 5000ms untuk mencegah thread hanging permanen.

