# Incident Investigation Dossier — inc-pilot-dev-sc02-002
- **Scenario label visible to reviewer:** `inc-pilot-dev-sc02-002` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `transaction-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-20T08:05:00Z` / `2026-11-20T08:05:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `af2d5decb5f7fc6aa3c8c2448cef70ca2a2794f8a9058c13cb3078046930024c`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Spike in HTTP 500 error rate on transaction-service payment endpoint

## 2. Impact and Scope

- **Affected Microservices:** `transaction-service`, `api-gateway`, `db-dummy`, `ledger-service`, `notification-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-20T08:00:00Z` to `2026-11-20T08:06:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-20T08:37:52.257766Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-20T08:37:52.258843Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-20T08:37:52.260032Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-20T08:37:52.276242Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-20T08:37:52.279899Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-20T08:37:52.281520Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-20T08:37:52.283255Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-pilot-dev-sc02-002-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 25 records returned. |
| `ev-inc-pilot-dev-sc02-002-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 2 records returned. |
| `ev-inc-pilot-dev-sc02-002-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 25 records returned. |
| `ev-inc-pilot-dev-sc02-002-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-pilot-dev-sc02-002-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_service_metrics queried on db-dummy: 0 records returned. |
| `ev-inc-pilot-dev-sc02-002-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | search_error_logs queried on db-dummy: 0 records returned. |
| `ev-inc-pilot-dev-sc02-002-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 25 records returned. |
| `ev-inc-pilot-dev-sc02-002-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-pilot-dev-sc02-002-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 25 records returned. |
| `ev-inc-pilot-dev-sc02-002-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-pilot-dev-sc02-002-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-20T08:00:00Z s/d 2026-11-20T08:06:00Z` | `complete` | `True` | get_trace_summary queried on transaction-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in transaction-service (ERR_TRANSACTION_FAILED)** | `ev-inc-pilot-dev-sc02-002-002` | *None* | `SUPPORTED` | Error logs indicate failure: 'Transaction processing failed for transaction-service'. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-TX-001 v1.0.0` | `SOP-TX-001: Penanganan Kegagalan Dependensi Layanan Transaksi` | `kb://corpus/transaction-service/transaction_service/SOP-TX-001.md` | `True` |
| `SOP-TX-ERR-500 v1.0.0` | `SOP-TX-ERR-500: Penanganan Error Internal 500 Pemrosesan Transaksi` | `kb://corpus/transaction-service/transaction_service/SOP-TX-ERR-500.md` | `True` |
| `SOP-TX-ERR-500 v1.0.0` | `SOP-TX-ERR-500: Penanganan Error Internal 500 Pemrosesan Transaksi > 1. Karakteristik Insiden` | `kb://corpus/transaction-service/transaction_service/SOP-TX-ERR-500.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of transaction-service. | `MEDIUM` | `True` | `SOP-TX-001` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-17d9f1a245104e40`
- **Reviewed By / Role:** `project_owner_michael (L2_SRE)`
- **Review Timestamp:** `2026-11-20T08:37:52.293886Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-pilot-dev-sc02-002                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : af2d5decb5f7fc6aa3c8c2448cef70ca...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : project_owner_michael (L2_SRE)                     │
│  DATE SIGNED      : 2026-11-20T08:37:52.293886Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Final Reviewer:** project_owner_michael (L2_SRE)
- **Timestamp:** `2026-11-20T08:37:52.293886Z`
- **Automated Remediation Triggered:** `false` (HUM-01 Verified)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-17d9f1a245104e40` | v1 | **APPROVE** | project_owner_michael (L2_SRE_REVIEWER) | `2026-11-20T08:37:52.293886Z` | Reviewed inc-pilot-dev-sc02-002 in Unified TUI Console; approved without auto-remediation. |
