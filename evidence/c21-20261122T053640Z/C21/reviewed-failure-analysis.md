# Reviewed Failure Analysis (`reviewed-failure-analysis`) — C21

- **Generated At (UTC):** `2026-11-22T05:36:45.084042Z`
- **Post-Hoc Tuning Performed:** `False`
- **Findings Recorded:** `7`

## C21-FAIL-001 — `KPI-02_MISS_CONCURRENT_MULTI_FAULT` (`HIGH`)
- **Target:** `inc-20261118-514a0d9758`
- **Root Cause / Analysis:** H-G4 incident run-20261118-514a0d9758 injects concurrent faults on two topologically disconnected service branches (auth-service and notification-service, scenario SC-08). The frozen DependencyCorrelator only traverses directed dependency edges from the single alert's primary service_id (api-gateway <- auth-service), and AlertDeduplicator keys per (service_id, environment, alert_type, window). Consequently, DeterministicInvestigator correctly diagnosed auth-service (primary_cause=1.0) with valid provenance, but never expanded scope to notification-service in the same incident dossier.
- **Governance Note:** Per RULE-012 and BRD §21.1, frozen runtime code and KPI thresholds were NOT modified after observing this miss. Logged for Chapter 23 architectural gap review.

## C21-RET-LEXICAL_ONLY-QRY-HLD-009 — `RETRIEVAL_MISS_OR_FALSE_POSITIVE` (`MEDIUM`)
- **Target:** `lexical_only:QRY-HLD-009`
- **Root Cause / Analysis:** Mode lexical_only returned outcome=MISS (retrieved=['SOP-NOTIF-QUEUE-001', 'SOP-NOTIF-QUEUE-001', 'SOP-NOTIF-QUEUE-001', 'KNOWN-ERR-NOTIF-001', 'KNOWN-ERR-NOTIF-001'], expected=['SOP-NOTIF-001']).
- **Governance Note:** Recorded verbatim without corpus or query tuning.

## C21-RET-LEXICAL_ONLY-QRY-HLD-012 — `RETRIEVAL_MISS_OR_FALSE_POSITIVE` (`MEDIUM`)
- **Target:** `lexical_only:QRY-HLD-012`
- **Root Cause / Analysis:** Mode lexical_only returned outcome=MISS (retrieved=['SOP-NOTIF-001', 'SOP-NOTIF-001', 'SOP-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'KNOWN-ERR-NOTIF-001'], expected=['ARCH-SIM-ECOSYSTEM.md']). Specific corpus/prefilter factor: ARCH-SIM-ECOSYSTEM.md has frontmatter document_id='ARCH-SIM-ECOSYSTEM' (without '.md') and service_id='api-gateway', so RAG-02 StrictPreFilter on target_service_id='notification-service' excludes it at pre-filter stage before ranking.
- **Governance Note:** Recorded verbatim without corpus or query tuning.

## C21-RET-DENSE_ONLY-QRY-HLD-012 — `RETRIEVAL_MISS_OR_FALSE_POSITIVE` (`MEDIUM`)
- **Target:** `dense_only:QRY-HLD-012`
- **Root Cause / Analysis:** Mode dense_only returned outcome=MISS (retrieved=['SOP-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'SOP-NOTIF-001', 'SOP-NOTIF-001'], expected=['ARCH-SIM-ECOSYSTEM.md']). Specific corpus/prefilter factor: ARCH-SIM-ECOSYSTEM.md has frontmatter document_id='ARCH-SIM-ECOSYSTEM' (without '.md') and service_id='api-gateway', so RAG-02 StrictPreFilter on target_service_id='notification-service' excludes it at pre-filter stage before ranking.
- **Governance Note:** Recorded verbatim without corpus or query tuning.

## C21-RET-HYBRID_RRF-QRY-HLD-012 — `RETRIEVAL_MISS_OR_FALSE_POSITIVE` (`MEDIUM`)
- **Target:** `hybrid_rrf:QRY-HLD-012`
- **Root Cause / Analysis:** Mode hybrid_rrf returned outcome=MISS (retrieved=['SOP-NOTIF-001', 'SOP-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'SOP-NOTIF-001'], expected=['ARCH-SIM-ECOSYSTEM.md']). Specific corpus/prefilter factor: ARCH-SIM-ECOSYSTEM.md has frontmatter document_id='ARCH-SIM-ECOSYSTEM' (without '.md') and service_id='api-gateway', so RAG-02 StrictPreFilter on target_service_id='notification-service' excludes it at pre-filter stage before ranking.
- **Governance Note:** Recorded verbatim without corpus or query tuning.

## C21-RET-HYBRID_RERANK-QRY-HLD-012 — `RETRIEVAL_MISS_OR_FALSE_POSITIVE` (`MEDIUM`)
- **Target:** `hybrid_rerank:QRY-HLD-012`
- **Root Cause / Analysis:** Mode hybrid_rerank returned outcome=MISS (retrieved=['SOP-NOTIF-001', 'SOP-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'KNOWN-ERR-NOTIF-001', 'SOP-NOTIF-001'], expected=['ARCH-SIM-ECOSYSTEM.md']). Specific corpus/prefilter factor: ARCH-SIM-ECOSYSTEM.md has frontmatter document_id='ARCH-SIM-ECOSYSTEM' (without '.md') and service_id='api-gateway', so RAG-02 StrictPreFilter on target_service_id='notification-service' excludes it at pre-filter stage before ranking.
- **Governance Note:** Recorded verbatim without corpus or query tuning.

## C21-LIMIT-001 — `STATISTICAL_POWER_AND_BASELINE_LIMITATION` (`MEDIUM`)
- **Target:** `H-G4 / KPI-06 / KPI-08 / KPI-13`
- **Root Cause / Analysis:** H-G4 sample size (n=1 replay, n=6 queries) cannot establish narrow confidence intervals against TBD-08 (30-50 replays, 100-200 queries); human baseline KPI-08 is DEV-only solo-developer self-assessment; reproducibility clean replays AT-013 await Chapter 22.
- **Governance Note:** Disclosed explicitly for Gate G4 feasibility decision in Chapter 24.
