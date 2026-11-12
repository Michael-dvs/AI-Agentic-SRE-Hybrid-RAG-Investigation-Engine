# Incident Investigation Dossier — inc-sc03-db-exhaustion-001
- **Scenario label visible to reviewer:** `inc-sc03-db-exhaustion-001` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `ledger-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:10:00Z` / `2026-11-12T08:10:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`INCONCLUSIVE`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `3169a96eee90501064cac3d9e58f31b47115473b8b4902a27bc3913d60b988d8`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Database connection checkout timeout exceeded in ledger-service

## 2. Impact and Scope

- **Affected Microservices:** `ledger-service`, `api-gateway`, `transaction-service`, `db-dummy`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T08:05:00Z` to `2026-11-12T08:11:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-12T08:25:56.550096Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-12T08:25:56.551215Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-12T08:25:56.552456Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-12T08:25:56.713748Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-12T08:25:56.715582Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-12T08:25:56.716807Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-12T08:25:56.718291Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-sc03-db-exhaustion-001-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | get_service_metrics queried on db-dummy: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | search_error_logs queried on db-dummy: 0 records returned. |
| `ev-inc-sc03-db-exhaustion-001-009` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-12T08:05:00Z s/d 2026-11-12T08:11:00Z` | `complete` | `True` | get_trace_summary queried on ledger-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Transient or unobserved anomaly on ledger-service** | *None* | *None* | `INCONCLUSIVE` | No definitive error patterns or metric anomalies captured in observation window. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| *NO_APPLICABLE_RUNBOOK* | *No matching SOP in corpus* | `kb://sop/unmapped` | `False` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** One or more telemetry backends were unavailable during investigation window.

**Unavailable Telemetry Sources:**
- Tool `retrieve_runbooks` reported `NO_APPLICABLE_RUNBOOK` at `2026-11-12T08:10:00Z`: No active approved SOP runbook found matching the observed error pattern in corpus.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of ledger-service. | `MEDIUM` | `True` | *None* |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-a77fb877a622430a`
- **Reviewed By / Role:** `sre_lead_hendra (L2_SRE_REVIEWER)`
- **Review Timestamp:** `2026-11-12T08:25:56.723662Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-sc03-db-exhaustion-001                         │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 3169a96eee90501064cac3d9e58f31b4...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : sre_lead_hendra (L2_SRE_REVIEWER)                  │
│  DATE SIGNED      : 2026-11-12T08:25:56.723662Z                        │
└────────────────────────────────────────────────────────────────────────┘
```