# Incident Investigation Dossier — inc-pilot-dev-sc03-003
- **Scenario label visible to reviewer:** `inc-pilot-dev-sc03-003` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `ledger-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-20T08:10:00Z` / `2026-11-20T08:10:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `0c905eac6ebead1bbea01c20d22683b84dfa78588ad00a391c45c570ca9889fd`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

PostgreSQL connection pool exhaustion causing checkout timeout in ledger-service

## 2. Impact and Scope

- **Affected Microservices:** `ledger-service`, `api-gateway`, `transaction-service`, `db-dummy`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-20T08:05:00Z` to `2026-11-20T08:11:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-20T08:37:52.298450Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-20T08:37:52.299836Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-20T08:37:52.301021Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-20T08:37:52.313857Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-20T08:37:52.317087Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-20T08:37:52.318692Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-20T08:37:52.320260Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-pilot-dev-sc03-003-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | get_service_metrics queried on ledger-service: 25 records returned. |
| `ev-inc-pilot-dev-sc03-003-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | search_error_logs queried on ledger-service: 1 records returned. |
| `ev-inc-pilot-dev-sc03-003-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 25 records returned. |
| `ev-inc-pilot-dev-sc03-003-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-pilot-dev-sc03-003-005` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | get_service_metrics queried on transaction-service: 25 records returned. |
| `ev-inc-pilot-dev-sc03-003-006` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | search_error_logs queried on transaction-service: 0 records returned. |
| `ev-inc-pilot-dev-sc03-003-007` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | get_service_metrics queried on db-dummy: 0 records returned. |
| `ev-inc-pilot-dev-sc03-003-008` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | search_error_logs queried on db-dummy: 0 records returned. |
| `ev-inc-pilot-dev-sc03-003-009` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-20T08:05:00Z s/d 2026-11-20T08:11:00Z` | `complete` | `True` | get_trace_summary queried on ledger-service: 1 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in ledger-service (ERR_DATABASE_LATENCY)** | `ev-inc-pilot-dev-sc03-003-002` | *None* | `SUPPORTED` | Error logs indicate failure: 'PostgreSQL connection pool checkout timeout exceeded in ledger-service'. |
| 2 | **High latency / error span observed on ledger-service** | `ev-inc-pilot-dev-sc03-003-009` | *None* | `SUPPORTED` | Distributed trace captured span 'POSTGRES_POOL_CHECKOUT' with error status. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-LEDGER-001 v2.0.0` | `SOP-LEDGER-001: Penanganan Latensi Database PostgreSQL Ledger (VERSI RESMI AKTIF) > 1. Identifikasi dan Triage Latensi Ledger` | `kb://corpus/ledger-service/ledger_service/SOP-LEDGER-001-v2.md` | `True` |
| `SOP-LEDGER-ERR-504 v1.0.0` | `SOP-LEDGER-ERR-504: Penanganan Query Timeout 504 pada Ledger Service > 1. Perbedaan Karakteristik dengan Gateway Timeout` | `kb://corpus/ledger-service/ledger_service/SOP-LEDGER-ERR-504.md` | `True` |
| `SOP-LEDGER-ERR-504 v1.0.0` | `SOP-LEDGER-ERR-504: Penanganan Query Timeout 504 pada Ledger Service` | `kb://corpus/ledger-service/ledger_service/SOP-LEDGER-ERR-504.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of ledger-service. | `MEDIUM` | `True` | `SOP-LEDGER-001` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-476b30f14ccb40e7`
- **Reviewed By / Role:** `project_owner_michael (L2_SRE)`
- **Review Timestamp:** `2026-11-20T08:37:52.330987Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-pilot-dev-sc03-003                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : 0c905eac6ebead1bbea01c20d22683b8...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : project_owner_michael (L2_SRE)                     │
│  DATE SIGNED      : 2026-11-20T08:37:52.330987Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Final Reviewer:** project_owner_michael (L2_SRE)
- **Timestamp:** `2026-11-20T08:37:52.330987Z`
- **Automated Remediation Triggered:** `false` (HUM-01 Verified)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-476b30f14ccb40e7` | v1 | **APPROVE** | project_owner_michael (L2_SRE_REVIEWER) | `2026-11-20T08:37:52.330987Z` | Reviewed inc-pilot-dev-sc03-003 in Unified TUI Console; approved without auto-remediation. |
