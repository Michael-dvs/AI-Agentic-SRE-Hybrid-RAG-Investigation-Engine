# Incident Investigation Dossier — inc-sc01-nominal-001
- **Scenario label visible to reviewer:** `inc-sc01-nominal-001` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:00:00Z` / `2026-11-12T08:00:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `226978129bd96b2648b3bd1f7dbb8013a8ff365e18397672709617a2fcd7f977`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Routine synthetic health check verification

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`, `auth-service`, `ledger-service`, `notification-service`, `transaction-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T07:55:00Z` to `2026-11-12T08:01:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-12T08:25:56.078640Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-12T08:25:56.080213Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-12T08:25:56.081682Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-12T08:25:56.298578Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-12T08:25:56.300214Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-12T08:25:56.301746Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-12T08:25:56.303101Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-sc01-nominal-001-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 0 records returned. |
| `ev-inc-sc01-nominal-001-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-sc01-nominal-001-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_service_metrics queried on auth-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | search_error_logs queried on auth-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 0 records returned. |
| `ev-inc-sc01-nominal-001-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | get_trace_summary queried on api-gateway: 1 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **High latency / error span observed on api-gateway** | `ev-inc-sc01-nominal-001-011` | *None* | `SUPPORTED` | Distributed trace captured span 'HTTP POST /transactions' with error status. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| *NO_APPLICABLE_RUNBOOK* | *No matching SOP in corpus* | `kb://sop/unmapped` | `False` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** One or more telemetry backends were unavailable during investigation window.

**Unavailable Telemetry Sources:**
- Tool `retrieve_runbooks` reported `NO_APPLICABLE_RUNBOOK` at `2026-11-12T08:00:00Z`: No active approved SOP runbook found matching the observed error pattern in corpus.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of api-gateway. | `MEDIUM` | `True` | *None* |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`PENDING_REVIEW`**
- **Latest Review Event ID:** `N/A`
- **Reviewed By / Role:** `PENDING`
- **Review Timestamp:** `PENDING`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-sc01-nominal-001                               │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 226978129bd96b2648b3bd1f7dbb8013...                │
│  DECISION         : PENDING_REVIEW                                     │
│  REVIEWER         : Awaiting Human Review                              │
│  DATE SIGNED      : PENDING                                            │
└────────────────────────────────────────────────────────────────────────┘
```