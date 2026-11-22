# Incident Investigation Dossier — inc-sc01-nominal-001
- **Scenario label visible to reviewer:** `inc-sc01-nominal-001` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:00:00Z` / `2026-11-12T08:00:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `a75665b1b9037d99738a1bb5198e93cf681ad317ab35bd65a46969dcf9ea1327`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Routine synthetic health check verification (seed=20261109)

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`, `auth-service`, `ledger-service`, `notification-service`, `transaction-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T07:55:00Z` to `2026-11-12T08:01:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-22T06:45:48.130719Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-22T06:45:48.131859Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-22T06:45:48.133029Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-22T06:45:48.360543Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-22T06:45:48.364882Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-22T06:45:48.366017Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-22T06:45:48.367585Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

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
| `ev-inc-sc01-nominal-001-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-12T07:55:00Z s/d 2026-11-12T08:01:00Z` | `complete` | `True` | {"attributes": {}, "duration_ms": 324.5, "error": true, "operation": "HTTP POST /transactions", "parent_span_id": null, "service_name": "api-gateway", "span_id": "00f067aa0ba902b7", "status_code": "ERROR"} |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **High latency / error span observed on api-gateway** | `ev-inc-sc01-nominal-001-011` | *None* | `SUPPORTED` | Distributed trace captured span 'HTTP POST /transactions' with error status. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |
| `SOP-GW-001 v1.2.0` | `SOP-GW-001: Penanganan Lonjakan Error HTTP 5xx pada API Gateway > 2. Prosedur Mitigasi Operasional` | `kb://corpus/api-gateway/api_gateway/SOP-GW-001.md` | `True` |
| `ARCH-SIM-ECOSYSTEM v1.0.0` | `ARCH-SIM-ECOSYSTEM: Topologi Arsitektur Ekosistem Simulasi SRE > 1. Aliran Permintaan Sinkron (Synchronous Flow)` | `kb://corpus/api-gateway/security/ARCH-SIM-ECOSYSTEM.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of api-gateway. | `MEDIUM` | `True` | `SOP-GW-ERR-504` |

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
│  DOSSIER HASH     : a75665b1b9037d99738a1bb5198e93cf...                │
│  DECISION         : PENDING_REVIEW                                     │
│  REVIEWER         : Awaiting Human Review                              │
│  DATE SIGNED      : PENDING                                            │
└────────────────────────────────────────────────────────────────────────┘
```
