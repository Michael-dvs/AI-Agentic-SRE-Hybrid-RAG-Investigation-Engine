# Incident Investigation Dossier — inc-pilot-dev-sc04-004
- **Scenario label visible to reviewer:** `inc-pilot-dev-sc04-004` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-20T08:15:00Z` / `2026-11-20T08:15:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `f55d549ec7850e08d081a02246869f2492ec87cf6b208eea97ee3763ce2f4e40`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

HTTP 504 cascade across api-gateway, transaction-service, and ledger-service

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`, `auth-service`, `ledger-service`, `notification-service`, `transaction-service`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-20T08:10:00Z` to `2026-11-20T08:16:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-20T08:37:52.335586Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-20T08:37:52.336877Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-20T08:37:52.338171Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-20T08:37:52.354814Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-20T08:37:52.358402Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-20T08:37:52.360235Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-20T08:37:52.361950Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-pilot-dev-sc04-004-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 25 records returned. |
| `ev-inc-pilot-dev-sc04-004-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 1 records returned. |
| `ev-inc-pilot-dev-sc04-004-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_service_metrics queried on auth-service: 25 records returned. |
| `ev-inc-pilot-dev-sc04-004-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | search_error_logs queried on auth-service: 0 records returned. |
| `ev-inc-pilot-dev-sc04-004-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 25 records returned. |
| `ev-inc-pilot-dev-sc04-004-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 1 records returned. |
| `ev-inc-pilot-dev-sc04-004-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_service_metrics queried on notification-service: 25 records returned. |
| `ev-inc-pilot-dev-sc04-004-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | search_error_logs queried on notification-service: 0 records returned. |
| `ev-inc-pilot-dev-sc04-004-009` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 25 records returned. |
| `ev-inc-pilot-dev-sc04-004-010` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 1 records returned. |
| `ev-inc-pilot-dev-sc04-004-011` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-20T08:10:00Z s/d 2026-11-20T08:16:00Z` | `complete` | `True` | get_trace_summary queried on api-gateway: 1 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Cascading failure from ledger-service propagating error to api-gateway** | `ev-inc-pilot-dev-sc04-004-010`, `ev-inc-pilot-dev-sc04-004-002`, `ev-inc-pilot-dev-sc04-004-006` | *None* | `SUPPORTED` | Downstream dependency ledger-service logged errors ('Gateway returned HTTP 504 due to downstream transaction-service timeout'), leading to upstream failure in api-gateway. |
| 2 | **High latency / error span observed on api-gateway** | `ev-inc-pilot-dev-sc04-004-011` | *None* | `SUPPORTED` | Distributed trace captured span 'HTTP POST /api/v1/transfer' with error status. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API > 1. Gejala dan Karakteristik Error` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |
| `SOP-GW-ERR-504 v1.0.0` | `SOP-GW-ERR-504: Penanganan Gateway Timeout 504 pada Ingress API` | `kb://corpus/api-gateway/api_gateway/SOP-GW-ERR-504.md` | `True` |
| `ARCH-SIM-ECOSYSTEM v1.0.0` | `ARCH-SIM-ECOSYSTEM: Topologi Arsitektur Ekosistem Simulasi SRE > 1. Aliran Permintaan Sinkron (Synchronous Flow)` | `kb://corpus/api-gateway/security/ARCH-SIM-ECOSYSTEM.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of api-gateway. | `MEDIUM` | `True` | `SOP-GW-ERR-504` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-37905643d1884273`
- **Reviewed By / Role:** `project_owner_michael (L2_SRE)`
- **Review Timestamp:** `2026-11-20T08:37:52.373615Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-pilot-dev-sc04-004                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : f55d549ec7850e08d081a02246869f24...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : project_owner_michael (L2_SRE)                     │
│  DATE SIGNED      : 2026-11-20T08:37:52.373615Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Final Reviewer:** project_owner_michael (L2_SRE)
- **Timestamp:** `2026-11-20T08:37:52.373615Z`
- **Automated Remediation Triggered:** `false` (HUM-01 Verified)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-37905643d1884273` | v1 | **APPROVE** | project_owner_michael (L2_SRE_REVIEWER) | `2026-11-20T08:37:52.373615Z` | Reviewed inc-pilot-dev-sc04-004 in Unified TUI Console; approved without auto-remediation. |
