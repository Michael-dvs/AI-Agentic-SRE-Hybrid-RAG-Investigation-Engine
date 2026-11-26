# Incident Investigation Dossier — inc-20261126-case03-edc25c
- **Scenario label visible to reviewer:** `inc-20261126-case03-edc25c` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `ledger-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-26T05:03:46.581806Z` / `2026-11-26T05:03:46.581806Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`INCONCLUSIVE`**
- **Dossier Revision / SHA-256 Hash:** `v2` / `c15eb1d2b8a4c1dfeda65ad23a066fdcecf756a3783da2e226680c61068585c9`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Service ledger-service latency_p95=365.7ms exceeded high SLO threshold 250.0ms

## 2. Impact and Scope

- **Affected Microservices:** `ledger-service`, `api-gateway`, `transaction-service`, `db-dummy`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-26T05:03:14.375521Z` to `2026-11-26T05:03:51.581823Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-26T05:03:46.593067Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-26T05:03:46.594977Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-26T05:03:46.596905Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-26T05:03:47.006302Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-26T05:03:47.018344Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-26T05:03:47.021318Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-26T05:03:47.024850Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observed At & Query Window | Quality / Truncated | Referenced By | Sanitized | Summary |
|---|---|---|---|---|---|---|
| `ev-inc-20261126-case03-edc25c-001` | `get_service_metrics` (`prometheus:http://127.0.0.1:19090`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | request_rate=0.3333 req/s (rate); request_rate=0.3333 req/s (rate); request_rate=0.3333 req/s (rate) [svc=ledger-service | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.673097Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-002` | `search_error_logs` (`loki:http://127.0.0.1:13100`) | `obs: 2026-11-26T05:03:45.604692Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `#2 (supports)` | `True` | WARN_DB_SLOW_QUERY: Database query execution took 350ms (exceeded 200ms SLO) @2026-11-26T05:03:44.812995Z; WARN_DB_SLOW_QUERY: Database query execution took 350ms (exceeded 200ms SLO) @2026-11-26T05:03:45.209691Z; WARN_DB_SLOW_QUERY: Database query execution took 350ms (exceeded 200ms SLO) @2026-11-26T05:03:45.604692Z [svc=ledger-service | env=lab | obs=2026-11-26T05:03:45.604692Z | collected=2026-11-26T05:03:46.680608Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-003` | `get_service_metrics` (`prometheus:http://127.0.0.1:19090`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | request_rate=0.4333 req/s (rate); request_rate=0.4333 req/s (rate); request_rate=0.4333 req/s (rate) [svc=api-gateway | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.769005Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-004` | `search_error_logs` (`loki:http://127.0.0.1:13100`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | search_error_logs queried on api-gateway: 0 records returned. [svc=api-gateway | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.773324Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-005` | `get_service_metrics` (`prometheus:http://127.0.0.1:19090`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | request_rate=0.3833 req/s (rate); request_rate=0.3833 req/s (rate); request_rate=0.3833 req/s (rate) [svc=transaction-service | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.867949Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-006` | `search_error_logs` (`loki:http://127.0.0.1:13100`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | search_error_logs queried on transaction-service: 0 records returned. [svc=transaction-service | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.872427Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-007` | `get_service_metrics` (`prometheus:http://127.0.0.1:19090`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | get_service_metrics queried on db-dummy: 0 records returned. [svc=db-dummy | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.907003Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-008` | `search_error_logs` (`loki:http://127.0.0.1:13100`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | search_error_logs queried on db-dummy: 0 records returned. [svc=db-dummy | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:46.910524Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-009` | `get_trace_summary` (`tempo:http://127.0.0.1:13200`) | `obs: 2026-11-26T05:03:44.824157Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `partial` | `contextual` | `True` | UNKNOWN [OK 363.036ms] trace=0c9161b5bbf3.. [svc=ledger-service | env=lab | obs=2026-11-26T05:03:44.824157Z | collected=2026-11-26T05:03:46.916089Z | temporal=TEMPORALLY_RELEVANT] |
| `ev-inc-20261126-case03-edc25c-010` | `get_service_metrics` (`prometheus:http://127.0.0.1:19090`) | `obs: 2026-11-26T05:03:51.581823Z | win: 2026-11-26T05:03:14.375521Z s/d 2026-11-26T05:03:51.581823Z` | `complete` | `contextual` | `True` | error_rate=0.0 ratio (ratio); error_rate=0.0 ratio (ratio); error_rate=0.0 ratio (ratio) [svc=ledger-service | env=lab | obs=2026-11-26T05:03:51.581823Z | collected=2026-11-26T05:03:47.004287Z | temporal=TEMPORALLY_RELEVANT] |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Candidate PostgreSQL slow query on ledger-service pending explain-analyze check.** | *None* | *None* | `INCONCLUSIVE` | [Human Correction by sre_reviewer_maya (L2_SRE)] Candidate hypothesis proposed during human review; requires supporting telemetry evidence and renewed review. |
| 2 | **Service operational error in ledger-service (WARN_DB_SLOW_QUERY)** | `ev-inc-20261126-case03-edc25c-002` | *None* | `SUPPORTED` | [Original AI Finding] Error logs indicate failure: 'Database query execution took 350ms (exceeded 200ms SLO)'. |

## 6. Relevant Runbooks & SOP Citations

CONFLICTING_OR_COMPETING_SOPS: multiple distinct eligible SOP sources or versions matched without established precedence; human review and escalation required before following guidance.

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-LEDGER-ERR-504 v1.0.0` (`chk-SOP-LEDGER-ERR-504-v1.0.0-001`) | `SOP-LEDGER-ERR-504: Penanganan Query Timeout 504 pada Ledger Service` | `kb://corpus/ledger_service/SOP-LEDGER-ERR-504.md` | `True` |
| `SOP-LEDGER-ERR-504 v1.0.0` (`chk-SOP-LEDGER-ERR-504-v1.0.0-002`) | `SOP-LEDGER-ERR-504: Penanganan Query Timeout 504 pada Ledger Service > 1. Perbedaan Karakteristik dengan Gateway Timeout` | `kb://corpus/ledger_service/SOP-LEDGER-ERR-504.md` | `True` |
| `SOP-LEDGER-001 v2.0.0` (`chk-SOP-LEDGER-001-v2.0.0-001`) | `SOP-LEDGER-001: Penanganan Latensi Database PostgreSQL Ledger (VERSI RESMI AKTIF)` | `kb://corpus/ledger_service/SOP-LEDGER-001-v2.md` | `True` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** Multiple distinct eligible SOP sources or versions matched without established precedence; human review is required before acting on either source.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | NOT_PERFORMED · HUMAN ESCALATION REQUIRED: Compare the cited sources with the service owner before using their guidance. Precedence is not established; do not combine instructions. | `LOW` | `True` | *None* |
| `chk-02` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): hypothesis #1: ledger-service, search_error_logs (authorized read-only view). Compare sanitized error codes and timestamps with the reported symptom. Matching errors strengthen a service-error explanation; a different error pattern weakens it. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |
| `chk-03` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): source coverage gap: api-gateway, search_error_logs (authorized read-only view). Compare sanitized error codes and timestamps with the reported symptom. Matching errors strengthen a service-error explanation; a different error pattern weakens it. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |
| `chk-04` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): source coverage gap: transaction-service, search_error_logs (authorized read-only view). Compare sanitized error codes and timestamps with the reported symptom. Matching errors strengthen a service-error explanation; a different error pattern weakens it. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |
| `chk-05` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): source coverage gap: db-dummy, get_service_metrics (authorized read-only view). Compare request volume and error-rate series across the incident window. An error-rate rise during traffic supports service impact; traffic volume alone does not establish failures. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |
| `chk-06` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): source coverage gap: db-dummy, search_error_logs (authorized read-only view). Compare sanitized error codes and timestamps with the reported symptom. Matching errors strengthen a service-error explanation; a different error pattern weakens it. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |
| `chk-07` | NOT_PERFORMED · GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED): source coverage gap: ledger-service, get_trace_summary (authorized read-only view). Compare span status, duration and parent/child timing for a correlated request. A failing earlier hop supports propagation; healthy sampled hops weaken it for that request only. Window: 2026-11-26T05:03:14.375521Z to 2026-11-26T05:03:51.581823Z. Record source, interval and observed signal or missing coverage. | `LOW` | `True` | *None* |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-258db9c54c334d1a`
- **Reviewed By / Role:** `sre_reviewer_maya (L2_SRE)`
- **Review Timestamp:** `2026-11-26T05:03:47.617082Z`
- **Diagnosis Verified:** `false` (APPROVE signifies dossier handover acceptance only; does not prove unconfirmed root causes)
- **Remediation Authorized / Auto-Action Triggered:** `false` (HUM-01 & RULE-008)

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-20261126-case03-edc25c                         │
│  DOSSIER VERSION  : v2                                                 │
│  DOSSIER HASH     : c15eb1d2b8a4c1dfeda65ad23a066fdc...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : sre_reviewer_maya (L2_SRE)                         │
│  DATE SIGNED      : 2026-11-26T05:03:47.617082Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Closure Semantics:** `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED`
- **Final Reviewer:** sre_reviewer_maya (L2_SRE)
- **Timestamp:** `2026-11-26T05:03:47.617082Z`
- **Diagnostic Support Statuses:** hyp-inc-20261126-case03-edc25c-human-v02: `INCONCLUSIVE`, hyp-inc-20261126-case03-edc25c-001: `SUPPORTED`
- **Diagnosis Verified:** `false` (Dossier approval indicates handover acceptance only)
- **Technical Incident Resolved:** `false`
- **Remediation Authorized:** `false`
- **SOP Compliance Confirmed:** `false`
- **Missing Sources / SOP Disclosure:** 0 missing source(s), 3 applicable SOP citation(s)
- **Automated Remediation Triggered:** `false` (RULE-008 & HUM-01 Enforced)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-f8abcafee3e54cf2` | v1 | **EDIT** | sre_reviewer_maya (L2_SRE_REVIEWER) | `2026-11-26T05:03:47.613273Z` | Added specific slow-query note while preserving AI finding. |
| `rev-258db9c54c334d1a` | v2 | **APPROVE** | sre_reviewer_maya (L2_SRE_REVIEWER) | `2026-11-26T05:03:47.617082Z` | Accepted v2 dossier for administrative handover. |
