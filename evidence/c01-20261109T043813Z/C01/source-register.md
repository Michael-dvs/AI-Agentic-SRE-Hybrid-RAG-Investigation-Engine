# Source Register — Chapter C01 (Scope, Decisions, and G0)

- **Run ID:** `c01-20261109T043813Z`
- **Snapshot Timestamp (UTC):** `2026-11-09T04:38:13Z` (`2026-11-09T11:38:13+07:00` WIB)
- **Hash Manifest Pointer:** `source-hashes.sha256` (algoritma: `SHA-256` melalui `/usr/bin/shasum -a 256`)

## 1. Urutan Otoritas Sumber

Sesuai `AGENTS.md` §2 dan `docs/roadmap/01-SCOPE-DECISIONS-AND-G0.md` §1.1:
1. Keputusan eksplisit yang telah disetujui pemilik proyek (`owner_ref: project-initiator-michael`).
2. Ruang lingkup dan kebutuhan pada **BRD v1.0** (`BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md`).
3. Urutan implementasi, dependensi, dan matriks cakupan pada **Master Implementation Roadmap v0.1** (`docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md`).
4. Referensi arsitektur dan 12 acceptance test asli Lampiran A pada **Proposal Teknis v2.0** (`Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx`).
5. Playbook operasional Chapter C01 (`docs/roadmap/01-SCOPE-DECISIONS-AND-G0.md`).

## 2. Inventaris Dokumen Sumber

| Kode | Path Relatif | Versi Aktual | Status pada Sumber | SHA-256 Checksum | Bagian yang Mengikat pada C01 |
|---|---|---|---|---|---|
| `B` | `BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md` | `1.0` (9 Nov 2026) | Draft for Stakeholder Review (`CONFIRMED` untuk ruang lingkup simulasi mandiri `DEC-001`–`DEC-005`) | `eafc44b7f7cb24aed9cb5dcc4f061590ab3e0cc22a7327e373f3316829d6c59f` | §0–5, §7–11 (16 BR, 40 FR, 12 RULE, 20 NFR), §13–24, Appendix A–D |
| `P` | `Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx` | `2.0` (6 Nov 2026) | Referensi konsep teknis pengusul (`SOURCE`) | `844d435837ec39c30f4da272af64cb66d0c37d4ab4fb1c06813918bcb26b93f0` | Bab 11–15, Lampiran A (12 Acceptance Tests: SEC/MCP/RAG/EV/OPS/HUM) |
| `M` | `docs/roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md` | `0.1` (9 Nov 2026) | Master Roadmap (`APPROVED` strukturnya oleh pemilik proyek dalam percakapan) | `95366b781e809424e8be37c064e474d2e58206a743c17eaf48554544e1fd72fc` | §1–3, §4–6 (C01), §7–8 (RTM & Test Coverage), §9 |
| `C01` | `docs/roadmap/01-SCOPE-DECISIONS-AND-G0.md` | `0.1` (9 Nov 2026) | Playbook operasional C01 (diinstruksikan pengguna untuk dieksekusi menghasilkan paket G0) | `85e4a0f2084858028bb8ab4b9019ff88b4b2f3e7359b3c71aaee05fdd57845bd` | §1–14 (Step 01 s/d Step 11 dan C01-GOV-001 s/d C01-GOV-011) |

## 3. Catatan Integritas Sumber

- Keempat berkas sumber tidak dimodifikasi selama pelaksanaan C01.
- Verifikasi ulang terhadap `source-hashes.sha256` menggunakan `shasum -a 256 -c` wajib bernilai `OK` pada seluruh berkas.
- Keberadaan `AGENTS.md` di root repository telah dicatat sebagai pedoman operasional agen/pengembang dan tidak mengubah hash keempat sumber baseline di atas.
