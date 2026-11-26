# Deliverable P — Frozen Baseline Integrity & Post-Stage-3A Drift Report
## P2-07 Architecture Compliance Verification

- **Machine-Readable Drift Manifest:** [`../frozen_drift_manifest.json`](../frozen_drift_manifest.json)
- **Strict Policy Compliance (`INV-18`, `INV-19`, `RLS-1`):** Zero historical frozen manifests, zero `C02` schema contracts, and zero `restricted/` holdout files were modified.

---

## 1. Cryptographic Integrity of Immutable Baselines

| Protected Artifact / Seal | File / Combined SHA-256 | Expected SHA-256 | Status |
|---|---|---|---|
| `evidence/c20-20261120T093645Z/C20/final-release-manifest.json` | `5587564a4e99ecdf0d5b71c4e21bdc31caf5e4c079418bedccc6c482238242ca` | `5587564a4e99ecdf0d5b71c4e21bdc31caf5e4c079418bedccc6c482238242ca` | **`INTACT (100%)`** |
| `evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json` | `b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f` | `b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f` | **`INTACT (100%)`** |
| `evidence/c02-20261109T070500Z/C02/contracts/*.schema.json` (`20` files) | `ef40fc00d64bad87d7f8f45ffe0af366095d9faec338815287726778c609d663` | `ef40fc00d64bad87d7f8f45ffe0af366095d9faec338815287726778c609d663` | **`INTACT (20/20)`** |
| `restricted/evaluator_queries/holdout_queries.json` | `6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6` | `6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6` | **`INTACT (SEALED)`** |
| `restricted/gt_registry/ground_truth_records.jsonl` | `149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95` | `149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95` | **`INTACT (SEALED)`** |

---

## 2. Post-Stage-3A Source Drift Summary (`Why Freeze Guard Tests Fail Expectedly`)

- **Frozen Entries Compared:** `162`
- **Unchanged Files:** `130`
- **Modified Files Since Stage 3A:** `32`
- **Added Runtime Python Modules Since Stage 3A:** `13`
- **Missing Frozen Files:** `0`

Because `tests/test_c21_benchmark.py` and `tests/test_c22_reproducibility_handover.py` explicitly verify the working tree against the historical November 22 Stage 3A manifest (`b7fcc548...`), those 5 freeze-guard checks **intentionally and correctly fail** (`RuntimeError` / `ManifestDriftError`) after the authorized `P0-01` through `P2-07` remediations. Per `P2-07` rules, the historical manifests were **not** overwritten.

### 2.1 Modified Files Since Stage 3A (`32`)

| File Path | Stage 3A SHA-256 | Current Working-Tree SHA-256 | Attribution |
|---|---|---|---|
| `gateway/adapters/base.py` | `10f3d714e6e8c229...` | `198dbc3a661520f2...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/adapters/logs.py` | `f6f04476f1a6f371...` | `a35eb5e7dd0923b0...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/adapters/metrics.py` | `21d0157301e392d8...` | `a3f2bc6a99ce9b28...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/adapters/traces.py` | `b8d50ccb60bc4c8e...` | `a97acda2800940a9...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/config.py` | `dad152594ccefe6a...` | `69fad90b24233b30...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/dispatcher.py` | `5b5625c97e835479...` | `a71898c63737d5ae...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `gateway/policy.py` | `15f5a82f7fb8301b...` | `b27c40a77049ceb8...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/ingestion/chunker.py` | `a4f08c75d01b1873...` | `226324a4a589261b...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/ingestion/validator.py` | `5ed2b64eab9cb730...` | `866560cc01691c21...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/retrieval/engine.py` | `b08b4b66be669ef6...` | `223887617a5060d9...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/retrieval/models.py` | `12b741d9e7c597b0...` | `fca0bc00a03a43bb...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/retrieval/prefilter.py` | `5b41703346b4fea6...` | `3ff5438e7430a09f...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `knowledge_base/retrieval/service.py` | `86b19dbe00479a04...` | `c04f7b051fa57934...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `observability/audit_chain.py` | `e3fab47ad9e9256b...` | `77f2a9e90abfa2e4...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/__init__.py` | `f40deef98aebec40...` | `6d985d084f20101f...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/claim_validator_contract.py` | `5fc1f4f882471c1b...` | `a5d7fd6d326aee4c...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/context_builder.py` | `e38f80a115583fe4...` | `2a9e1e296a5693e4...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/dossier.py` | `ba01445cd178ddfc...` | `ef057a06c6c45fff...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/fallback.py` | `24248dce45b7234d...` | `5f6efe003be22290...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/handover.py` | `669893a3f5abb795...` | `d28032fd6606de8c...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/investigator.py` | `904da10be1ee3101...` | `4ade27954a50b6a2...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/llm_investigator.py` | `9aaa9accc52c6453...` | `9111662d65a5b0f5...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/llm_provider.py` | `5dcb2e55c4704390...` | `a4654032eba7d3cd...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/review.py` | `ac65169c0269b681...` | `72d15c809ad7cd61...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/state_machine.py` | `ee2130c4492f4bb8...` | `8845cef07695913c...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/ticketing.py` | `6993b1deba5b89db...` | `869c6a952d7ec017...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `orchestrator/usability_console.py` | `5d5bd5c2bbe481f7...` | `2e9644cfe7e94c5b...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `scripts/review_console.py` | `2b2403547d45669a...` | `59860014c2d7c487...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `scripts/run_c20_stage2a.py` | `336140b2fe299b3a...` | `a2ba289b3061d46d...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `scripts/run_rollback_restore.py` | `38f8e314e46dee01...` | `b1d046f06d97937c...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `scripts/run_shadow_pilot.py` | `99593f3f88c2eb3b...` | `c76ee68c2dc72442...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |
| `scripts/sre_dashboard.py` | `4eb9e6f0d4e8aa4b...` | `23862a075b8eb75a...` | Authorized post-Stage-3A remediation (`P0-01`–`P2-07`) |

### 2.2 Added Runtime Modules Since Stage 3A (`13`)

| File Path | Stage 3A SHA-256 | Current Working-Tree SHA-256 | Attribution |
|---|---|---|---|
| `evaluator/calibration.py` | *(not in Stage 3A)* | `36125908d67c1130...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/confidence.py` | *(not in Stage 3A)* | `859a71f61abee50c...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/console_config.py` | *(not in Stage 3A)* | `0608a1f928777ae0...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/console_view_models.py` | *(not in Stage 3A)* | `1dd12605e70148ca...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/evidence_lineage.py` | *(not in Stage 3A)* | `3d07668a830e5e16...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/live_watcher.py` | *(not in Stage 3A)* | `e42c33200c79cfe9...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `orchestrator/verification_plan.py` | *(not in Stage 3A)* | `ecbb69efa9b71091...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `scripts/run_alert_watcher.py` | *(not in Stage 3A)* | `4887fec854902ab9...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `scripts/run_banking_simulator.py` | *(not in Stage 3A)* | `d4830d77c5ccce62...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `scripts/run_c21_benchmark.py` | *(not in Stage 3A)* | `620ef8bd469e2383...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `scripts/run_c22_clean_replay.py` | *(not in Stage 3A)* | `f2e8f3bb1e0120bb...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `scripts/run_c23_c24_governance.py` | *(not in Stage 3A)* | `b6f3bb45277bde2d...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
| `traffic/bank_simulator.py` | *(not in Stage 3A)* | `7af1d3817bc9422c...` | Added post-Stage-3A module (`RFC-F4-01` / `P0-01`–`P2-06`) |
