# Incident Investigation Dossier — inc-sc12-storm-51702f10dd8a
- **Scenario label visible to reviewer:** `inc-sc12-storm-51702f10dd8a` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `transaction-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:20:00Z` / `2026-11-12T08:20:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`PARTIAL`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `716a6e92e49d9205e462487ded881a4b3a321d097f608d55529ffb63f0df5281`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

100 duplicate alert storm merged on transaction-service (seed=20261109)

## 2. Impact and Scope

- **Affected Microservices:** `transaction-service`, `api-gateway`, `db-dummy`, `ledger-service`, `notification-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T08:15:00Z` to `2026-11-12T08:21:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-22T06:45:49.043013Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-22T06:45:49.045098Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-22T06:45:49.046801Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-22T06:45:49.228371Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-22T06:45:49.231878Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-22T06:45:49.233312Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-22T06:45:49.234528Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-sc12-storm-51702f10dd8a-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | Transaction processing failed for transaction-service |
| `ev-inc-sc12-storm-51702f10dd8a-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_service_metrics queried on db-dummy: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | search_error_logs queried on db-dummy: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-sc12-storm-51702f10dd8a-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-12T08:15:00Z s/d 2026-11-12T08:21:00Z` | `complete` | `True` | get_trace_summary queried on transaction-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in transaction-service (ERR_TRANSACTION_FAILED)** | `ev-inc-sc12-storm-51702f10dd8a-002` | *None* | `PARTIAL` | Error logs indicate failure: 'Transaction processing failed for transaction-service'. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-TX-ERR-500 v1.0.0` | `SOP-TX-ERR-500: Penanganan Error Internal 500 Pemrosesan Transaksi > 1. Karakteristik Insiden` | `kb://corpus/transaction-service/transaction_service/SOP-TX-ERR-500.md` | `True` |
| `SOP-TX-001 v1.0.0` | `SOP-TX-001: Penanganan Kegagalan Dependensi Layanan Transaksi` | `kb://corpus/transaction-service/transaction_service/SOP-TX-001.md` | `True` |
| `SOP-TX-ERR-500 v1.0.0` | `SOP-TX-ERR-500: Penanganan Error Internal 500 Pemrosesan Transaksi` | `kb://corpus/transaction-service/transaction_service/SOP-TX-ERR-500.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of transaction-service. | `MEDIUM` | `True` | `SOP-TX-ERR-500` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`PENDING_REVIEW`**
- **Latest Review Event ID:** `N/A`
- **Reviewed By / Role:** `PENDING`
- **Review Timestamp:** `PENDING`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-sc12-storm-51702f10dd8a                        │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 716a6e92e49d9205e462487ded881a4b...                │
│  DECISION         : PENDING_REVIEW                                     │
│  REVIEWER         : Awaiting Human Review                              │
│  DATE SIGNED      : PENDING                                            │
└────────────────────────────────────────────────────────────────────────┘
```
