# ADR-TBD05: Evaluasi Kapabilitas Koordinator Workflow Dify-First vs Alternatif (`TBD-05`)

- **ID Keputusan:** `ADR-TBD05` (Menangani `TBD-05`)
- **Status:** `PROPOSED` (`CANDIDATE` — Menunggu Eksekusi 7 Eksperimen Capability Spike pada Chapter C08 sebelum Gate G1)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C08`, `C11`, `C12`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/plans/c08-orchestrator-spike.md`, `evidence/c02-20261109T070500Z/C02/workflow-contract.md`

---

## 1. Konteks & Permasalahan

Pemilik proyek menetapkan **Dify-first** sebagai kandidat pilihan untuk orkestrasi workflow (`CANDIDATE; requires capability evaluation`). Namun, stack Docker Dify self-hosted membutuhkan banyak layanan pendukung (API, worker, web, sandbox, PostgreSQL, Redis) yang berisiko melampaui anggaran **8 GiB Docker Lab** pada Mac 16 GB Apple Silicon serta harus dibuktikan kemampuannya dalam menegakkan state deterministik, idempotency, pembatalan deadline, dan penolakan review basi (`VERSION_CONFLICT`).

---

## 2. Keputusan Protokol Evaluasi

1. **Jangan Mengklaim Dify Lulus atau Gagal Tanpa Bukti C08:**
   - Pada C02, seluruh kontrak workflow (`workflow-event.v1`, `dossier.v1`, `review-event.v1`, `audit-event.v1`) dirancang bebas-vendor (*engine-agnostic*).
2. **Eksekusi Wajib 7 Spike Cases di Chapter C08 (`plans/c08-orchestrator-spike.md`):**
   - `SPK-C08-01`: Jejak memori gabungan di bawah plafon 8 GiB (`RSS <= 7.0 GiB`).
   - `SPK-C08-02`: Pemulihan state setelah restart worker di tengah `EVIDENCE_COLLECTED`.
   - `SPK-C08-03`: Idempotensi pada 10 alert duplikat dan replay transisi.
   - `SPK-C08-04`: Penegakan allowlist tool dan penolakan injeksi grup via MCP Gateway.
   - `SPK-C08-05`: Penegakan kuota panggilan tool dan pembatalan deadline.
   - `SPK-C08-06`: Penolakan persetujuan manusia terhadap revisi dossier yang sudah usang (`VERSION_CONFLICT`).
   - `SPK-C08-07`: Kelangsungan fallback deterministik saat LLM mati (`OPS-02`) dan kelengkapan Independent Security Audit Sink.
3. **Aturan Pemilihan Arsitektur pada Gate G1:**
   - Jika Dify lulus seluruh `SPK-C08-01`..`07`, gunakan **Opsi A (Full Dify Orchestration)**.
   - Jika Dify terkendala RAM atau penegakan state/hash secara native, gunakan **Opsi B (Hybrid Thin-Coordinator Python + Dify Node)** atau **Opsi C (Deterministic Python State Machine / LangGraph + SQLite)** dengan persetujuan eksplisit pemilik proyek pada Gate G1.

