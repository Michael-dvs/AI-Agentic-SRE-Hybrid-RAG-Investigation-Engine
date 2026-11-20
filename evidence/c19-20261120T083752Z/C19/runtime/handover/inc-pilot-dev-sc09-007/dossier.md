# Incident Investigation Dossier — inc-pilot-dev-sc09-007
- **Scenario label visible to reviewer:** `inc-pilot-dev-sc09-007` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-20T08:30:00Z` / `2026-11-20T08:30:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`INCONCLUSIVE`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `2cb4ef0a3b291598aa1d2c283891d194f47e57a65767207dcd8f9d65fcf7fb4f`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Gateway timeout observed while distributed tracing backend is down

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`, `auth-service`, `ledger-service`, `notification-service`, `transaction-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-20T08:25:00Z` to `2026-11-20T08:31:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-20T08:37:52.448731Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-20T08:37:52.449825Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-20T08:37:52.451183Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-20T08:37:52.466622Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-20T08:37:52.469907Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-20T08:37:52.471482Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-20T08:37:52.473225Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-pilot-dev-sc09-007-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 25 records returned. |
| `ev-inc-pilot-dev-sc09-007-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 2 records returned. |
| `ev-inc-pilot-dev-sc09-007-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | get_service_metrics queried on auth-service: 25 records returned. |
| `ev-inc-pilot-dev-sc09-007-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | search_error_logs queried on auth-service: 0 records returned. |
| `ev-inc-pilot-dev-sc09-007-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 25 records returned. |
| `ev-inc-pilot-dev-sc09-007-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 0 records returned. |
| `ev-inc-pilot-dev-sc09-007-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 25 records returned. |
| `ev-inc-pilot-dev-sc09-007-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-pilot-dev-sc09-007-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 25 records returned. |
| `ev-inc-pilot-dev-sc09-007-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:25:00Z s/d 2026-11-20T08:31:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 0 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in api-gateway (ERR_GATEWAY_TIMEOUT)** | `ev-inc-pilot-dev-sc09-007-002` | *None* | `INCONCLUSIVE` | Error logs indicate failure: 'Simulated operational error for api-gateway'. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |
| `ARCH-SIM-ECOSYSTEM v1.0.0` | `ARCH-SIM-ECOSYSTEM: Topologi Arsitektur Ekosistem Simulasi SRE > 1. Aliran Permintaan Sinkron (Synchronous Flow)` | `kb://corpus/api-gateway/security/ARCH-SIM-ECOSYSTEM.md` | `True` |
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API > 1. Gejala dan Karakteristik Error` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** Distributed trace backend is unavailable or traces are missing; causality across microservice hops cannot be proven (EV-02).

**Unavailable Telemetry Sources:**
- Tool `get_trace_summary` reported `SOURCE_UNAVAILABLE` at `2026-11-20T08:37:52.465586Z`: Telemetry backend for get_trace_summary was unavailable or timed out during observation window.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of api-gateway. | `MEDIUM` | `True` | `SOP-GW-ERR-504` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-7d8f50d328e14f9b`
- **Reviewed By / Role:** `project_owner_michael (L2_SRE)`
- **Review Timestamp:** `2026-11-20T08:37:52.484393Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-pilot-dev-sc09-007                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 2cb4ef0a3b291598aa1d2c283891d194...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : project_owner_michael (L2_SRE)                     │
│  DATE SIGNED      : 2026-11-20T08:37:52.484393Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Final Reviewer:** project_owner_michael (L2_SRE)
- **Timestamp:** `2026-11-20T08:37:52.484393Z`
- **Automated Remediation Triggered:** `false` (HUM-01 Verified)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-7d8f50d328e14f9b` | v1 | **APPROVE** | project_owner_michael (L2_SRE_REVIEWER) | `2026-11-20T08:37:52.484393Z` | Reviewed inc-pilot-dev-sc09-007 in Unified TUI Console; approved without auto-remediation. |
