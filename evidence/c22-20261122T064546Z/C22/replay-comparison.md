# Dual Clean Environment Replay Comparison (`AT-013` / `KPI-13`)

- **Generated At (UTC):** `2026-11-22T06:45:50.394198Z`
- **Seed / Mode:** `20261109` / `deterministic_baseline`
- **Release Manifest File SHA-256:** `b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f`
- **Release Manifest Self SHA-256:** `fc7e6a702b73f5185d09aca19c5c55a9fb56ead3864531c6c8d46970d1131b9e`
- **KB Manifest Hash:** `c9ee96dac3bb07b43a5230b1a881e63131250c8de77ca791ea002c8a810f5129`
- **Host Docker Status:** `DOCKER_INACTIVE` (Executed via fresh isolated in-process SQLite workspaces with full wipe between runs (Docker daemon inactive on host).)
- **Inter-Replay Total Wipe Verified:** `True`
- **KPI-13 Reproducibility Rate:** **`1.00`** (`6/6` scenarios identical; target `>= 0.90`)
- **Overall `AT-013` Status:** **`PASS`**

## 1. Global Invariant Verification

| Dimension | Match / Pass |
|---|---|
| `state_sequences_match` | `True` |
| `schema_validation_all_pass` | `True` |
| `evidence_ids_match` | `True` |
| `sop_citation_hashes_match` | `True` |
| `support_status_match` | `True` |
| `normalized_dossier_hashes_match` | `True` |
| `safety_invariants_zero_violation` | `True` |
| `ground_truth_stable` | `True` |

## 2. Per-Scenario Comparison (`clean-replay-a` vs `clean-replay-b`)

| Scenario | State Seq Match | Evidence IDs Match | SOP Hash Match | Support Status Match | Normalized Dossier Hash Match | Overall |
|---|---|---|---|---|---|---|
| `SC-01` | `True` | `True` | `True` | `True` | `True` | `PASS` |
| `SC-02` | `True` | `True` | `True` | `True` | `True` | `PASS` |
| `SC-03` | `True` | `True` | `True` | `True` | `True` | `PASS` |
| `SC-09` | `True` | `True` | `True` | `True` | `True` | `PASS` |
| `SC-11` | `True` | `True` | `True` | `True` | `True` | `PASS` |
| `SC-12` | `True` | `True` | `True` | `True` | `True` | `PASS` |

## 3. Volatile Fields Normalized (C22 §5 Step 2)

Timestamp wall-clock & review event UUID fields excluded before canonical invariant hashing: `generated_at_utc`, `dossier_ready_at`, `timeline[].timestamp`, `evidence[].observed_at`, `missing_sources[].recorded_at`, `review_summary.latest_review_event_id`, `review_summary.reviewed_at`.
