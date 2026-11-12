# Incident Investigation Dossier — inc-sc02-5xx-burst-001
- **Scenario label visible to reviewer:** `inc-sc02-5xx-burst-001` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `transaction-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:05:00Z` / `2026-11-12T08:05:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`PARTIAL`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `e89a29cadf99a2c0b0f18cc3caa5aa439344b29c4e6169dbcea80cf7602ec59b`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Spike in HTTP 500 responses detected during customer payment processing

## 2. Impact and Scope

- **Affected Microservices:** `transaction-service`, `api-gateway`, `db-dummy`, `ledger-service`, `notification-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T08:00:00Z` to `2026-11-12T08:06:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-12T08:25:56.309184Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-12T08:25:56.310291Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-12T08:25:56.311401Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-12T08:25:56.537283Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-12T08:25:56.539058Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-12T08:25:56.540279Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-12T08:25:56.541700Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-sc02-5xx-burst-001-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 1 records returned. |
| `ev-inc-sc02-5xx-burst-001-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_service_metrics queried on db-dummy: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | search_error_logs queried on db-dummy: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-sc02-5xx-burst-001-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-12T08:00:00Z s/d 2026-11-12T08:06:00Z` | `complete` | `True` | get_trace_summary queried on transaction-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in transaction-service (ERR_TRANSACTION_FAILED)** | `ev-inc-sc02-5xx-burst-001-002` | *None* | `PARTIAL` | Error logs indicate failure: 'Transaction processing failed for transaction-service'. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| *NO_APPLICABLE_RUNBOOK* | *No matching SOP in corpus* | `kb://sop/unmapped` | `False` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** One or more telemetry backends were unavailable during investigation window.

**Unavailable Telemetry Sources:**
- Tool `retrieve_runbooks` reported `NO_APPLICABLE_RUNBOOK` at `2026-11-12T08:05:00Z`: No active approved SOP runbook found matching the observed error pattern in corpus.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of transaction-service. | `MEDIUM` | `True` | *None* |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-075f3e2da8f44fb1`
- **Reviewed By / Role:** `sre_lead_hendra (L2_SRE_REVIEWER)`
- **Review Timestamp:** `2026-11-12T08:25:56.547068Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-sc02-5xx-burst-001                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : e89a29cadf99a2c0b0f18cc3caa5aa43...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : sre_lead_hendra (L2_SRE_REVIEWER)                  │
│  DATE SIGNED      : 2026-11-12T08:25:56.547068Z                        │
└────────────────────────────────────────────────────────────────────────┘
```