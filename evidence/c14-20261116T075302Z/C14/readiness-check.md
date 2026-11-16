# C14 evidence: c14-20261116T075302Z

- Run time UTC: 20261116T075302Z
- Environment: local synthetic DEV replay, no live backend or holdout.
- Pytest exit code: 1; see pytest-verified-output.txt.
- Bundle status: FAIL
- EV-01, EV-02, AT-007, AT-009, AT-016, RAG-01, RAG-02: see individual test output; no full acceptance decision inferred.
- RULE-005, RULE-007, NFR-004: synthetic cases only; reviewer and full coverage pending.
- KPI-03, KPI-04, KPI-11: NOT_RUN as formal benchmarks; no claim based on this small sample.
- Code commit/model/prompt/KB version, seed and reviewer: not captured; this is not a formal acceptance run.

## Failures
- EV-01: expected agentic workflow and PARTIAL, got agentic_llm and [{'hypothesis_id': 'hyp-inc-c14-integration-001', 'rank': 1, 'statement': 'Service error', 'support_status': 'INCONCLUSIVE', 'supporting_evidence_ids': [], 'contradicting_evidence_ids': [], 'reason_summary': 'A service error was observed. Candidate cause (not proven): Cause requires investigation.', 'unknowns': ['Cause remains uncertain.']}]
- C14 pytest exited 1
