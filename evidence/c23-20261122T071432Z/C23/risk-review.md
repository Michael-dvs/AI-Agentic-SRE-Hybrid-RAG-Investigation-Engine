# Enterprise Risk & Empirical Gap Review (`E23`): `c23-20261122T071432Z`

- **Generated At (UTC):** `2026-11-22T07:14:32.283502Z`
- **Scope Boundary:** `SCALED_DOWN_LAB_POC_ONLY`
- **Production Readiness Claimed:** `False`
- **Regulatory Compliance Certified:** `False`
- **Safety MUST Violations:** `0`
- **Risks Reconciled:** `23/23` (`14` BRD `RISK-01`..`14` + `9` Proposal `R01`..`09`)

## 1. Bedah Mendalam 5 Temuan Empiris Nyata Laboratorium

### `C21-FAIL-001` — `KPI-02` (`MEDIUM_NON_SAFETY`)
- **Teramati:** 0.0 main (0/1 on H-G4 SC-08; primary_cause=1.0 auth-service, all_causes=0.0 notification-service missed) *(Target: >= 0.85 (PROPOSED))*
- **Akar Masalah:** Frozen DependencyCorrelator traverses single-entry DAG from alert service_id; AlertDeduplicator keys on (service_id, environment, alert_type, window).
- **Rancangan Mitigasi Fase 5:** Multi-Root Temporal Event Clustering and connected-component subgraph aggregation (CAP-01).

### `C21-RET-QRY-HLD-012` — `KPI-05` (`MEDIUM_NON_SAFETY`)
- **Teramati:** 0.8333 Hit@5/Recall@5 (5/6 on H-G4 hybrid_rrf, dense_only, hybrid_rerank; 0.6667 lexical_only) *(Target: >= 0.90 (PROPOSED))*
- **Akar Masalah:** ARCH-SIM-ECOSYSTEM.md has frontmatter service_id='api-gateway' and document_id='ARCH-SIM-ECOSYSTEM' (without .md); RAG-02 StrictPreFilter excludes it for target_service_id='notification-service'.
- **Rancangan Mitigasi Fase 5:** Multi-tier metadata entitlement (service_private vs shared_platform with affected_services ACL) and canonical document_id normalization (CAP-02).

### `TBD-08` — `STATISTICAL_POWER` (`MEDIUM_METHODOLOGICAL`)
- **Teramati:** H-G4 n=1 closed replay + n=6 holdout queries; H-G3 n=2 replays + n=6 queries *(Target: 30-50 incident replays, 100-200 retrieval queries (Proposal TBD-08))*
- **Akar Masalah:** Frozen G1/ADR-S08 scaled-down lab split restricts statistical power; binomial confidence intervals remain wide.
- **Rancangan Mitigasi Fase 5:** Execute stratified 30-50 replay and 100-200 query benchmark on banking staging corpus (CAP-03).

### `C19-DEF-005` — `KPI-06 / KPI-08` (`MEDIUM_METHODOLOGICAL`)
- **Teramati:** H-G4 KPI-08=UNAVAILABLE, KPI-06=0.0 (rework); C19 DEV n=7 median reduction -88.23% (340.0s vs 40.032s) & KPI-06=85.71% tagged SELF_EVALUATED_DEVELOPER_LABELS *(Target: >= 40% efficiency by independent SME (RULE-011), >= 85% acceptance)*
- **Akar Masalah:** Solo developer (project-initiator-michael) served as both scenario author and reviewer in lab (TBD-01/02).
- **Rancangan Mitigasi Fase 5:** Blinded crossover evaluation by independent L1/L2 banking SRE panel (CAP-04).

### `C20-22-DOCKER-FIDELITY` — `KPI-07 / INFRA_FIDELITY` (`LOW_NON_SAFETY`)
- **Teramati:** C20 Stage 2A/C21/C22 executed in-process while host Docker daemon was DOCKER_INACTIVE (6 Compose tests skipped); H-G4 KPI-07=0.0s warm in-process vs 75.0s H-G3; historical C20 Docker snapshot measured 652.99-683.03 MiB across 12 containers *(Target: Reproducible containerized lab <= 8 GiB RAM, P95 <= 120s)*
- **Akar Masalah:** Host Docker Desktop daemon inactive during C20 Stage 2B, C21, and C22 execution windows; in-process Python omits HTTP/RabbitMQ/Postgres network & disk latency.
- **Rancangan Mitigasi Fase 5:** Re-verify full 12-container Compose throughput and latency in Phase 5 staging Kubernetes/container environment.

## 2. Rekonsiliasi Item Non-PASS Lintas Fase 1–4 (`E01`–`E22`)

| Item / Metrik | Status Teramati | Sumber Bukti | Pemilik | Disposisi Menuju Gate G4 |
|---|---|---|---|---|
| `KPI-02 (H-G4)` | MISS (0.0 main; primary=1.0, all=0.0) | E21 (kpi-report.json) | Agent & Correlation Lead (Phase 5A) | Mandatory CAP-01 before bank sandbox |
| `KPI-05 (H-G4)` | MISS (0.8333 [5/6] vs >= 0.90) | E21 (raw-scores.json) | RAG Lead (Phase 5A) | Mandatory CAP-02 before bank sandbox |
| `KPI-06 (H-G4 & C19)` | CAVEAT (0.0 H-G4 rework; 85.71% C19 self-eval) | E19, E21 | Independent SRE Panel (Phase 5B) | Disclosed honestly; resolved via CAP-03/CAP-04 |
| `KPI-07 (H-G4)` | PASS_WITH_CAVEAT (0.0s warm in-process; 75.0s H-G3) | E18, E21 | Platform Engineer (Phase 5) | Re-benchmark under distributed K8s/network latency |
| `KPI-08 (H-G4 & C19)` | UNAVAILABLE (H-G4) / CAVEAT (-88.23% C19 solo-dev) | E19, E21 | Independent SRE Panel (Phase 5B) | Do not claim 40% savings officially; resolved via CAP-04 |
| `KPI-12 (H-G4 nominal)` | PARTIAL (H-G4 nominal untriggered) / PASS via C20 | E20 (6/6 drills), E21 | Resilience Lead | Accepted via E20 6/6 fallback drills + E21 frozen suite |
| `AT-006 (H-G4)` | PARTIAL (DEV 28/28=100%; H-G4 5/6=83.33%) | E07, E21 | RAG Lead (Phase 5A) | Linked to CAP-02 (shared_platform metadata) |
| `AT-014 (H-G4)` | EXECUTED_WITH_HONEST_GAPS | E21 | Evaluation Owner (Phase 5B) | Sample size TBD-08 addressed in CAP-03 |
| `AT-017 (ITSM Ticket)` | PASS_LAB_STUB (DummyTicketManager local) | E16, E21 | ITSM Integration Lead (Phase 5) | Sandbox ServiceNow/Jira connector required via CAP-05 |
| `6 pytest skipped (Compose)` | SKIPPED (Host Docker daemon inactive) | E20, E21, E22 | Lab Operator / Platform | Historical 12-container RSS verified in E20 docker-container-metrics.md |
| `RFC-F4-01 (TUI Console)` | PROPOSED / UNDER_REVIEW | C19, E22 | project-initiator-michael | Accepted for lab demonstration alongside dossier.html |

## 3. Rekonsiliasi Lengkap Register Risiko BRD (`RISK-01`–`RISK-14`)

| Risk ID | Deskripsi | Dampak Awal | Status Lab | Bukti | Sisa Risiko Enterprise |
|---|---|---|---|---|---|
| `RISK-01` | Demo works only on rehearsed scenarios | High | `MITIGATED_WITH_SAMPLE_CAVEAT` | E18, E21, E22 | Expand to 30-50 blind incidents (CAP-03). |
| `RISK-02` | Oracle/GT leaks into agent prompt/KB | Critical | `CLOSED_VERIFIED_KPI10_ZERO` | E04-E22 | Preserve strict out-of-band evaluator & RBAC in production. |
| `RISK-03` | Confident but incorrect root cause | High | `ACTIVE_RESIDUAL_SC08_ALL_CAUSES` | E14, E21 | KPI-04=0.0, but SC-08 second cause missed; fixed via CAP-01. |
| `RISK-04` | Invalid/obsolete runbook cited | High | `CLOSED_FOR_OBSOLETE_RESIDUAL_CROSS_SERVICE` | E06, E07, E14, E21 | KPI-11=0; cross-service shared doc metadata fixed via CAP-02. |
| `RISK-05` | Prompt injection via synthetic logs | High | `CLOSED_IN_LAB_SEC02_PASS` | E13, E18, E21, E22 | Re-test continuously whenever enterprise LLM models change. |
| `RISK-06` | Overengineering simulation stack | Medium | `CLOSED_VIA_ADR_TBD05` | E08, E11 | Python state machine & typed adapters scale cleanly to K8s. |
| `RISK-07` | Insufficient laptop/server resources | High | `MANAGED_IN_LAB_UNDER_8GIB` | E05, E20, E21 | 10k-100k EPS requires distributed enterprise cluster (Pillar 1/3). |
| `RISK-08` | Uncontrolled model cost | Medium | `CLOSED_IN_LAB_ZERO_CASH` | E15, E20, E21 | Budget GPU CapEx/OpEx & private API quotas via TCO model. |
| `RISK-09` | Benchmark claims not comparable / bias | High | `OPEN_RESIDUAL_SELF_EVALUATED` | E19, E21 | Require blinded independent L1/L2 SRE panel (CAP-04). |
| `RISK-10` | Fragile manual demo | High | `CLOSED_IN_LAB_AT013_PASS` | E22 | Maintain CI clean-replay checks & PRE_RECORDED_FALLBACK_RUN protocol. |
| `RISK-11` | False sense of production readiness | Critical | `MITIGATED_BY_GOVERNANCE_C23_C24` | E23, E24 | Enforced via CONDITIONAL GO & Phase 5 gating. |
| `RISK-12` | Vendor/framework lock-in | Medium | `MITIGATED_VIA_TYPED_CONTRACTS` | E02, E09, E20 | Typed adapters decouple LLM/vector/ITSM backends. |
| `RISK-13` | Missing ownership/approval of BRD | High | `MANAGED_FOR_LAB_TBD01` | E01, E23, E24 | Executive bank sponsor & Security Board required for Phase 5. |
| `RISK-14` | Synthetic dataset misses real-world complexity | High | `OPEN_ENTERPRISE_GAP` | E21, E23 | Validate on anonymized bank historical incidents in Phase 5. |

## 4. Rekonsiliasi Lengkap Risiko Proposal (`R01`–`R09`)

| Risk ID | Deskripsi | Status Lab | Bukti |
|---|---|---|---|
| `R01` | Data/PII/GT leakage | `CLOSED_IN_LAB_KPI10_ZERO_SEC03_PASS` | E06, E08, E15, E18, E22 |
| `R02` | Out-of-scope or write tool query | `CLOSED_IN_LAB_KPI09_ZERO_MCP01_02_PASS` | E08, E09, E18, E21, E22 |
| `R03` | Wrong / overconfident diagnosis | `PARTIAL_RESIDUAL_SC08_CAP01` | E14, E21 |
| `R04` | Stale or unauthorized SOP cited | `CLOSED_OBSOLETE_CAP02_CROSS_SERVICE` | E06, E07, E14, E21 |
| `R05` | Alert surge & runaway cost | `CLOSED_IN_LAB_OPS01_PASS` | E10, E12, E20, E21, E22 |
| `R06` | LLM / backend vendor outage | `CLOSED_IN_LAB_OPS02_6_OF_6_PASS` | E13, E15, E20, E21 |
| `R07` | Inaccurate dependency topology | `OPEN_ENTERPRISE_CMDB_GAP` | E05, E10, E23 |
| `R08` | Holdout overfitting / small sample | `OPEN_RESIDUAL_TBD08_CAP03` | E18, E21, E23 |
| `R09` | Production ownership & support boundary | `DISCLOSED_OUT_OF_POC_SCOPE` | E23, E24 |
