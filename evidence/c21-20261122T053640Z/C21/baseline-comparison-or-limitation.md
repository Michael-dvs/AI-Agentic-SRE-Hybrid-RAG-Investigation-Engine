# Baseline Comparison & Methodological Limitations (C21)

## 1. H-G4 4-Mode Retrieval Ablation (`QRY-HLD-007`..`012`)

| Mode | Pos Queries | Neg Safe | Doc Hit@5 | Doc Recall@5 | Sec Hit@5 | Sec Recall@5 | P50 (ms) | P95 (ms) | Mean (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `lexical_only` | 6 | None | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.647 | 1.2305 | 0.7715 |
| `dense_only` | 6 | None | 0.8333 | 0.8333 | 0.5 | 0.5 | 0.5822 | 0.621 | 0.5952 |
| `hybrid_rrf` | 6 | None | 0.8333 | 0.8333 | 0.6667 | 0.6667 | 0.5879 | 0.6223 | 0.5994 |
| `hybrid_rerank` | 6 | None | 0.8333 | 0.8333 | 0.8333 | 0.8333 | 0.6432 | 0.697 | 0.659 |

## 2. Sample Size vs `TBD-08` & Solo-Developer Bias Disclosures
- **Sample Size Limitation:** C21 H-G4 sample (6 holdout queries + 1 closed multi-fault replay) meets Frozen G1/ADR-S08 PoC split size, but sits far below Proposal TBD-08 statistical target (100-200 queries, 30-50 replays). Confidence intervals remain wide and cannot support statistical generalization claims.
- **KPI-06 / KPI-08 Disclosure:** C19 manual baseline (n=7) used anti-carryover SHA-256 locking before AI view, yet both manual and rubric assessments were executed by the solo lab developer (project-initiator-michael) on DEV cases, NOT independent banking L1/L2 SREs on blind H-G4.
- **Holdout ID Note:** Preflight holdout-g4-manifest cited historical note 'run-20261118-e39b744a19' line 7. Actual file line 8 is `run-20261118-514a0d9758`.
