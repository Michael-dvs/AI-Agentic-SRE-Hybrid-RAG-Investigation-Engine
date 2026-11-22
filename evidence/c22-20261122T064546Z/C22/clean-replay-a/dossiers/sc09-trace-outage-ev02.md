# Incident Investigation Dossier — inc-sc09-trace-outage-001
- **Scenario label visible to reviewer:** `inc-sc09-trace-outage-001` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-12T08:15:00Z` / `2026-11-12T08:15:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`INCONCLUSIVE`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `434b8f9b66050d8b8f8e764f3f0c668dc07475162664514415dfe6f87bec1dc5`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Gateway timeout with downstream tracing pipeline unavailable (seed=20261109)

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`, `auth-service`, `ledger-service`, `notification-service`, `transaction-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-12T08:10:00Z` to `2026-11-12T08:16:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-22T06:45:48.743297Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-22T06:45:48.744398Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-22T06:45:48.745834Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-22T06:45:48.930664Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-22T06:45:48.933759Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-22T06:45:48.934858Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-22T06:45:48.936049Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-sc09-trace-outage-001-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | Simulated operational error for api-gateway |
| `ev-inc-sc09-trace-outage-001-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | get_service_metrics queried on auth-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | search_error_logs queried on auth-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 0 records returned. |
| `ev-inc-sc09-trace-outage-001-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-12T08:10:00Z s/d 2026-11-12T08:16:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in api-gateway (ERR_GATEWAY_TIMEOUT)** | `ev-inc-sc09-trace-outage-001-002` | *None* | `INCONCLUSIVE` | Error logs indicate failure: 'Simulated operational error for api-gateway'. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |
| `ARCH-SIM-ECOSYSTEM v1.0.0` | `ARCH-SIM-ECOSYSTEM: Topologi Arsitektur Ekosistem Simulasi SRE > 1. Aliran Permintaan Sinkron (Synchronous Flow)` | `kb://corpus/api-gateway/security/ARCH-SIM-ECOSYSTEM.md` | `True` |
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API > 1. Gejala dan Karakteristik Error` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** Distributed trace backend is unavailable or traces are missing; causality across microservice hops cannot be proven (EV-02).

**Unavailable Telemetry Sources:**
- Tool `get_trace_summary` reported `SOURCE_UNAVAILABLE` at `2026-11-22T06:45:48.929587Z`: Telemetry backend for get_trace_summary was unavailable or timed out during observation window.

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
│  INCIDENT ID      : inc-sc09-trace-outage-001                          │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 434b8f9b66050d8b8f8e764f3f0c668d...                │
│  DECISION         : PENDING_REVIEW                                     │
│  REVIEWER         : Awaiting Human Review                              │
│  DATE SIGNED      : PENDING                                            │
└────────────────────────────────────────────────────────────────────────┘
```
