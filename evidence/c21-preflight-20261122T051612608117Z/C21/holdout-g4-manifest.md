# C21 holdout preflight

Source hashes match the C20/G1 baseline. Hashing reads opaque bytes; it does not establish access history, isolation, or authorization. No holdout payload or label was parsed.

- `restricted/evaluator_queries/holdout_queries.json`: `6c7fbc74a4fb3f630374183c97e261ecccf7e824034049ae4b4437919a7513b6`
- `restricted/gt_registry/ground_truth_records.jsonl`: `149deae896aa78f18238958b974f08508307c0a6e52bd39dd667dc435fab7b95`

- Isolation: `NOT_VERIFIED`
- Authorization: `NOT_VERIFIED`
- Access history: `NOT_VERIFIED`
- Actual GT partition: `NOT_CREATED` (only after per-incident CLOSED)
- Benchmark: `NOT_RUN`
- Query source permissions: `NOT_OWNER_ONLY`
- Full source tree matches C20: `false`; evaluator and scripts may differ.
- Tests completed: caller attestation, not independently verified.
