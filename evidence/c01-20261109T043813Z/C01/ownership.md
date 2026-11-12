# Ownership, RACI, and Authority Matrix — Chapter C01 (Gate G0)

- **Run ID:** `c01-20261109T043813Z`
- **Decision References:** `TBD-01`, `TBD-02`, `TBD-08` (`APPROVED` untuk `TBD-01`/`TBD-02` oleh `project-initiator-michael` pada `2026-11-09T11:35:57+07:00`)
- **Primary Administrative Reference (`owner_ref`):** `project-initiator-michael` (Michael — Project Initiator, Owner, & Solo Lead Developer)

## 1. Penetapan Otoritas & Konteks Pelaksanaan Mandiri

1. **Konteks Pengembangan Mandiri (`TBD-01`, `TBD-02`):** Proyek simulasi PoC ini dilaksanakan secara mandiri (*solo developer execution*) oleh `project-initiator-michael`. Seluruh keputusan scope, alokasi resource lab lokal, kebijakan anggaran `$0 / gratis & open-source`, dan persetujuan Gate G0 berada di bawah otoritas nyata `project-initiator-michael`.
2. **Larangan Klaim Otoritas Institusi:** Dokumen ini secara tegas menyatakan bahwa **tidak ada** sign-off resmi dari unit PT Bank Negara Indonesia (Persero) Tbk (APS/IDS, InfoSec, atau komite arsitektur bank) pada tahap simulasi lab ini.
3. **Deklarasi Rangkap Peran & Mitigasi Bias (`TBD-08`):** Karena `project-initiator-michael` merangkap peran pembangun sistem sekaligus evaluator/reviewer simulasi (L1/L2), hasil review manusia dan pelabelan ground-truth berstatus **Developer-Generated / Self-Evaluated Labels** (bukan validasi SME independen), kecuali penunjukan reviewer independen (`TBD-08`) ditambahkan sebelum Gate G1 (`C08`).

## 2. Matriks Ownership & RACI per Workstream

| Workstream / Decision Area | Responsible (`R`) | Accountable (`A`) | Consulted (`C`) | Evidence Reviewer | Role Accepted? | Konflik Kepentingan / Limitasi & Mitigasi |
|---|---|---|---|---|---|---|
| **Scope, Fidelity, & Gate G0–G4 Sign-Off** (`TBD-01`, `TBD-07`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Otoritas personal proyek mandiri; tidak diklaim sebagai sign-off komite bank |
| **Technical Architecture & Contracts** (`C02`, `ADR-S01`–`S08`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Desain kontrak diverifikasi terhadap skema otomatis & tes negatif |
| **Simulated Services & Fault Harness** (`C03`, `C04`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Pembuat fault sama dengan pengembang agent; dimitigasi dengan membekukan registry GT sebelum agent run & isolasi path |
| **Telemetry, Observability, & Read-Only Adapters** (`C05`, `C08`, `C09`, `C10`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Penegakan allowlist schema secara deterministik di kode gateway |
| **Synthetic Knowledge Base & Hybrid RAG** (`C06`, `C07`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Penulis SOP sintetis dilarang menyematkan jawaban spesifik run/holdout atau exact onset time |
| **Agent Workflow, LLM Reasoning, & Evidence Validator** (`C11`–`C15`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Validator deterministik memverifikasi klaim terhadap bukti sebelum menghasilkan dossier |
| **Data Handling, Security Boundary, & Model Egress** (`TBD-04`, `TBD-12`, `TBD-13`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Hanya data sintetis tersanitasi; tidak ada klaim kepatuhan DPIA/InfoSec bank resmi |
| **Evaluation, Holdout Registry, & L1/L2 Review Simulasi** (`TBD-08`, `TBD-10`, `C16`–`C21`) | `project-initiator-michael` | `project-initiator-michael` | Candidate External SME (`TBD-08`, due G1) | `project-initiator-michael` (Self-Review Disclosed) | `ACCEPTED` (`2026-11-09`) | **Bias Self-Review Disclosed:** wajib memakai split terpisah (`Dev` / `H-G3` / `H-G4`), manifest immutable, dan tidak mengklaim validasi SME independen bila `TBD-08` tetap self-reviewed pada G1 |
| **Budget, Lab Capacity, & Operations Support** (`TBD-03`, `TBD-09`) | `project-initiator-michael` | `project-initiator-michael` | N/A (Solo PoC) | `project-initiator-michael` | `ACCEPTED` (`2026-11-09`) | Kebijakan `$0 cash outlay` (free-tier/open-source) dan lab lokal macOS best-effort (bukan on-call produksi) |

## 3. Penanganan Tindak Lanjut `TBD-08` (Menuju Gate G1)

- **Owner Penugasan `TBD-08`:** `project-initiator-michael`
- **Tenggat Keputusan Final:** Gate G1 (`C08`)
- **Aturan Disposisi:** Apabila hingga Gate G1 tidak ada rekan/SME eksternal yang ditunjuk sebagai reviewer independen, proyek tetap dapat berjalan secara sah dengan mencantumkan label **`SELF_EVALUATED_DEVELOPER_LABELS`** pada seluruh laporan UAT, rubrik dossier, dan keputusan G3/G4.
