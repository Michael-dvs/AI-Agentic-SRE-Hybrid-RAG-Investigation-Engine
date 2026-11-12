# ADR-S08: Isolasi 3-Split Dataset (`dev`, `H-G3`, `H-G4`), Post-CLOSED Ground-Truth Join, dan Aturan Scoring KPI (`TBD-08`, `TBD-10`)

- **ID Keputusan:** `ADR-S08` (Mencakup `TBD-08` dan `TBD-10`)
- **Status:** `PROPOSED` (Kontrak Isolasi Split & Delayed GT Join Disetujui; Ukuran Sampel Final & Ambang Acceptance Dikunci pada Gate G1)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C04`, `C07`, `C08`, `C17`, `C18`, `C21`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/plans/evaluation-protocol.md`, `evidence/c02-20261109T070500Z/C02/plans/scenario-oracles.csv`, `evidence/c02-20261109T070500Z/C02/contracts/runtime-manifest.v1.schema.json`, `evidence/c02-20261109T070500Z/C02/contracts/evaluation-manifest.v1.schema.json`, `evidence/c02-20261109T070500Z/C02/contracts/evaluation-result.v1.schema.json`

---

## 1. Konteks & Permasalahan

Evaluasi konsep pada G3 dan G4 menjadi tidak valid apabila label ground-truth bocor ke runtime investigator (`RULE-03`), apabila dataset holdout digunakan untuk tuning prompt/RAG, atau apabila definisi numerator/denominator KPI diubah setelah melihat hasil eksperimen.

---

## 2. Keputusan

1. **Pemisahan Kontrak Manifest (`ACCEPTED`):**
   - `runtime-manifest.v1.schema.json` (publik/runtime) menggunakan `run_id`, `incident_id`, dan `replay_seed_ref` yang bersifat opaque; dilarang memuat `scenario_id`, `split_id`, atau `expected_root_cause`.
   - `evaluation-manifest.v1.schema.json` dan `evaluation-result.v1.schema.json` disimpan secara eksklusif di `TB-05` (`restricted/gt-registry/`) dan hanya dapat diakses oleh `principal_evaluator`.
2. **Gerbang Post-CLOSED Ground-Truth Join (`ACCEPTED`):**
   - Evaluator wajib menolak setiap percobaan join sebelum insiden mencapai `terminal_state == "CLOSED"` dan `closed_dossier_hash` terverifikasi (`PREMATURE_EVALUATION_BLOCKED`).
3. **Tiga Split Terpisah (`ACCEPTED`):**
   - `dev` (tuning C04–C17), `H-G3` (locked holdout untuk Gate G3), dan `H-G4` (locked blind holdout untuk Gate G4) dibedakan berdasarkan seed dan parameter injeksi serta dikunci dengan `split_freeze_hash` (SHA-256).
4. **Aturan Pelaporan KPI (`ACCEPTED`) & Ukuran Sampel Kandidat (`PROPOSED` untuk G1):**
   - **Retrieval (`KPI-01`):** `retrieval_hit_rate_at_5` dan `retrieval_classical_recall_at_5` wajib dilaporkan keduanya secara terpisah.
   - **Diagnosis (`KPI-02`):** `top3_primary_cause_match` dan `top3_all_causes_match` dilaporkan terpisah; skenario sehat (`SC-01`) dan abstention aman (`INCONCLUSIVE` pada `SC-09`) tidak dimasukkan sebagai diagnosis positif palsu.
   - **Human Rubric (`KPI-06`, `TBD-10`):** Mencatat `assessment_kind: "self_review_lab_owner"` untuk membedakan review pemilik proyek independen dari validasi SME bank eksternal.
   - **Ukuran Sampel (`TBD-08`):** Kandidat proposal (100–200 kueri retrieval, 30–50 replay insiden) akan ditetapkan ukuran finalnya pada Gate G1 berdasarkan kapasitas eksekusi nyata di lab 16 GB RAM.

