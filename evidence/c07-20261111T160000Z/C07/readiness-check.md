# C07 Readiness Check & Prerequisite Verification

- **Chapter:** `C07 — Hybrid Retrieval and Baselines`
- **Phase:** `F1 — Foundation`
- **Execution Run ID:** `c07-20261111T160000Z`
- **Evaluator:** SRE & RAG Implementation Engineer
- **Status:** `READY_AND_VERIFIED`

---

## 1. Prerequisite Checklist

| Item | Prerequisite Source | Target File / Artifact | Hasil Verifikasi | Status |
|---|---|---|---|---|
| **C06 Knowledge Corpus & Chunks** | Chapter C06 (`E06`) | `evidence/c06-20261111T150000Z/C06/corpus-manifest.json`, `chunk-hashes.json` | 71 chunk tervalidasi skema Draft 2020-12, SHA-256 manifest hash cocok. | `PASS` |
| **C02 Retrieval Request Contract** | Chapter C02 Contracts | `evidence/c02-20261109T070500Z/C02/contracts/retrieval-request.v1.schema.json` | Skema tervalidasi dengan Draft 2020-12 validator. | `PASS` |
| **C02 Retrieval Result Contract** | Chapter C02 Contracts | `evidence/c02-20261109T070500Z/C02/contracts/retrieval-result.v1.schema.json` | Skema tervalidasi dengan Draft 2020-12 validator. | `PASS` |
| **Ground Truth Isolation** | `AGENTS.md` RULE-002, AT-008 | `restricted/evaluator_queries/holdout_queries.json` | File holdout queries (`H-G3`/`H-G4`) **sama sekali tidak dibaca, tidak diimpor, dan tidak diindeks** oleh retrieval engine. | `PASS` |
| **DEV Query Dataset** | Chapter C06 Handover | `knowledge_base/eval_queries/dev_queries.json` | 28 kueri evaluasi berlabel untuk 6 layanan simulasi tersedia lengkap. | `PASS` |
| **Resource & Cost Policy** | `AGENTS.md` RULE-001, ADR-S04 | Python Environment & Local Memory | Biaya **$0.00**, 0 external API calls, memori RSS delta 6.89 MB (plafon lab 512 MB). | `PASS` |

---

## 2. Pre-Filter Parity & Boundary Verification

1. **Obsolete SOP Prevention (`RAG-01`, `SC-10`, `AT-007`):**
   - Query dengan `reference_time >= 2026-06-01T00:00:00Z` hanya mengembalikan `SOP-LEDGER-001` versi `2.0.0` (`status: "approved"`). Versi `1.0.0` (`status: "obsolete"`) dieliminasi total pada tahap pre-filter.
2. **Cross-Service Isolation (`RAG-02`):**
   - Query timeout HTTP 504 pada `api-gateway` hanya mengembalikan dokumen gateway (`SOP-GW-ERR-504`). Dokumen `SOP-LEDGER-ERR-504` milik `ledger-service` diblokir total.
3. **Document Entitlement Check (`SEC-01`):**
   - Dokumen `SOP-SEC-KEY-ROTATION` (`classification: "synthetic-restricted"`) diblokir bagi caller unprivileged (`sre-core-l1`), dan hanya dapat diakses oleh caller dengan grup `["sre-core-l2", "security-admin"]`.
4. **Zero-Hallucination Gap Handling (`FR-RAG-009`, `RULE-006`):**
   - Kueri topik di luar korpus mengembalikan `status: "no_match"` dan `gap_reason: "NO_APPLICABLE_RUNBOOK"` tanpa sitasi rekaan.
5. **Backend Outage Simulation (`NFR-016`, `AT-012`):**
   - Simulasi backend mati mengembalikan `status: "unavailable"` dan `gap_reason: "RETRIEVAL_UNAVAILABLE"`.

---

## 3. Kesimpulan Kesiapan

Seluruh prasyarat arsitektur, kepatuhan batas keamanan, isolasi ground truth, dan plafon sumber daya lab terpenuhi 100%. Implementasi Chapter C07 siap dilanjutkan ke benchmark komparatif dan pembentukan paket bukti `E07`.

