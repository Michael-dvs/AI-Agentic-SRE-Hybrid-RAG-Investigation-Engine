# Incident Investigation Dossier — inc-pilot-dev-sc06-005
- **Scenario label visible to reviewer:** `inc-pilot-dev-sc06-005` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `auth-service` / `lab` / `HIGH`
- **Alert received at / Dossier ready at:** `2026-11-20T08:20:00Z` / `2026-11-20T08:20:00Z`
- **Investigation mode & Status:** `deterministic_baseline` | **`SUPPORTED`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `fcb70c3e36f7b4d56df3a2b9f18e89b00f9e8fe479ac7fa0685d03532781a828`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Authentication token verification mismatch on auth-service /verify

## 2. Impact and Scope

- **Affected Microservices:** `auth-service`, `api-gateway`
- **Error Budget Impact Assessment:** `MODERATE`
- **Investigation Window:** `2026-11-20T08:15:00Z` to `2026-11-20T08:21:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-20T08:37:52.378315Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RECEIVED |
| `2026-11-20T08:37:52.379340Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to CORRELATED |
| `2026-11-20T08:37:52.380487Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to TRIAGED |
| `2026-11-20T08:37:52.388684Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to EVIDENCE_COLLECTED |
| `2026-11-20T08:37:52.392123Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to RETRIEVED |
| `2026-11-20T08:37:52.393812Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to HYPOTHESES |
| `2026-11-20T08:37:52.395231Z` | `workflow_event` | `orchestrator:coordinator` | Workflow state transitioned to VALIDATED |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-pilot-dev-sc06-005-001` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:15:00Z s/d 2026-11-20T08:21:00Z` | `complete` | `True` | get_service_metrics queried on auth-service: 25 records returned. |
| `ev-inc-pilot-dev-sc06-005-002` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:15:00Z s/d 2026-11-20T08:21:00Z` | `complete` | `True` | search_error_logs queried on auth-service: 1 records returned. |
| `ev-inc-pilot-dev-sc06-005-003` | `get_service_metrics` (`prometheus:http://localhost:9090`) | `2026-11-20T08:15:00Z s/d 2026-11-20T08:21:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 25 records returned. |
| `ev-inc-pilot-dev-sc06-005-004` | `search_error_logs` (`loki:http://localhost:3100`) | `2026-11-20T08:15:00Z s/d 2026-11-20T08:21:00Z` | `complete` | `True` | search_error_logs queried on api-gateway: 0 records returned. |
| `ev-inc-pilot-dev-sc06-005-005` | `get_trace_summary` (`tempo:http://localhost:3200`) | `2026-11-20T08:15:00Z s/d 2026-11-20T08:21:00Z` | `complete` | `True` | get_trace_summary queried on auth-service: 1 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Service operational error in auth-service (ERR_AUTH_REJECTED)** | `ev-inc-pilot-dev-sc06-005-002` | *None* | `SUPPORTED` | Error logs indicate failure: 'Token verification failed with synthetic signing key mismatch on /verify'. |
| 2 | **High latency / error span observed on auth-service** | `ev-inc-pilot-dev-sc06-005-005` | *None* | `SUPPORTED` | Distributed trace captured span 'POST /verify' with error status. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| `SOP-AUTH-001 v1.0.0` | `SOP-AUTH-001: Investigasi Lonjakan Kegagalan Autentikasi > 1. Indikator dan Pemicu Alert` | `kb://corpus/auth-service/auth_service/SOP-AUTH-001.md` | `True` |
| `SOP-AUTH-ERR-500 v1.0.0` | `SOP-AUTH-ERR-500: Penanganan Error Internal 500 pada Layanan Autentikasi > 1. Identifikasi Anomali Internal Auth` | `kb://corpus/auth-service/auth_service/SOP-AUTH-ERR-500.md` | `True` |
| `SOP-AUTH-001 v1.0.0` | `SOP-AUTH-001: Investigasi Lonjakan Kegagalan Autentikasi` | `kb://corpus/auth-service/auth_service/SOP-AUTH-001.md` | `True` |

## 7. Unknowns & Telemetry Gaps

No material telemetry gaps reported.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-01` | Manually verify health and upstream connectivity of auth-service. | `MEDIUM` | `True` | `SOP-AUTH-001` |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`APPROVED`**
- **Latest Review Event ID:** `rev-d1300619b76c40c2`
- **Reviewed By / Role:** `project_owner_michael (L2_SRE)`
- **Review Timestamp:** `2026-11-20T08:37:52.404898Z`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-pilot-dev-sc06-005                             │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : fcb70c3e36f7b4d56df3a2b9f18e89b0...                │
│  DECISION         : APPROVED                                           │
│  REVIEWER         : project_owner_michael (L2_SRE)                     │
│  DATE SIGNED      : 2026-11-20T08:37:52.404898Z                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Reviewer Sign-Off & Audit Trail

- **Current Disposition:** `APPROVED`
- **Final Reviewer:** project_owner_michael (L2_SRE)
- **Timestamp:** `2026-11-20T08:37:52.404898Z`
- **Automated Remediation Triggered:** `false` (HUM-01 Verified)

### Review Decision History (Append-Only)

| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |
|---|---|---|---|---|---|
| `rev-d1300619b76c40c2` | v1 | **APPROVE** | project_owner_michael (L2_SRE_REVIEWER) | `2026-11-20T08:37:52.404898Z` | Reviewed inc-pilot-dev-sc06-005 in Unified TUI Console; approved without auto-remediation. |
