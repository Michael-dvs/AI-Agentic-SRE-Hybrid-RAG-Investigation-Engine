# Incident Investigation Dossier — inc-fallback-at012-demo
- **Scenario label visible to reviewer:** `inc-fallback-at012-demo` (Synthetic Lab Simulation)
- **Service / Environment / Severity:** `api-gateway` / `lab` / `MEDIUM`
- **Alert received at / Dossier ready at:** `2026-11-12T08:25:00Z` / `2026-11-12T08:25:57.163890Z`
- **Investigation mode & Status:** `manual_fallback` | **`INCONCLUSIVE`**
- **Dossier Revision / SHA-256 Hash:** `v1` / `a54b4e0df340c3c6b81f066eb2f31bf7e652d12698334d48b064aec08d9972e0`
- **Workflow / KB / Tool Versions:** `1.0.0` / `kb-idx-20261111-v1` / `1.0`

---

## 1. Executive Summary & Observed Symptoms

Telemetry signals indicated anomalies in api-gateway (ERR_UNKNOWN)

## 2. Impact and Scope

- **Affected Microservices:** `api-gateway`
- **Error Budget Impact Assessment:** `MINOR`
- **Investigation Window:** `2026-11-12T08:20:00Z` to `2026-11-12T08:26:00Z`

## 3. Timeline of Observed Signals

| Timestamp (UTC) | Event Kind | Source Reference | Summary |
|---|---|---|---|
| `2026-11-12T08:25:57.163890Z` | `workflow_event` | `orchestrator:resilience` | Automated workflow aborted with DEADLINE_EXCEEDED: Global incident investigation deadline exceeded (120.0s cap reached). |

## 4. Evidence Table

| Evidence ID | Tool / Source | Observation Window | Data Quality | Sanitized | Summary |
|---|---|---|---|---|---|
| `ev-inc-fallback-at012-demo-001` | `get_service_metrics` (`prometheus`) | `2026-11-12T08:20:00Z s/d 2026-11-12T08:26:00Z` | `complete` | `True` | get_service_metrics queried on api-gateway: 1 records returned. |

## 5. Ranked Hypotheses

| Rank | Hypothesis Statement | Supporting Evidence | Contradicting Evidence | Support Status | Reasoning |
|---|---|---|---|---|---|
| 1 | **Automated investigation aborted (DEADLINE_EXCEEDED); manual triage required** | *None* | *None* | `INCONCLUSIVE` | Workflow abort triggered: 'Global incident investigation deadline exceeded (120.0s cap reached).'. Telemetry signals remain inconclusive. |

## 6. Relevant Runbooks & SOP Citations

| Document ID & Version | Section Path | Source URI | Applicability Verified |
|---|---|---|---|
| *NO_APPLICABLE_RUNBOOK* | *No matching SOP in corpus* | `kb://sop/unmapped` | `False` |

## 7. Unknowns & Telemetry Gaps

> [!WARNING] **Telemetry Uncertainty:** Automated pipeline halted due to DEADLINE_EXCEEDED: Global incident investigation deadline exceeded (120.0s cap reached).
> [!WARNING] **Telemetry Uncertainty:** Full dependency graph and span waterfall could not be verified automatically.

## 8. Proposed Next Checks (Human-Controlled Only)

> [!IMPORTANT] **HUM-01 Policy Enforcement:** All proposed actions below are strictly human-controlled. Automated remediation actions (`auto_execution_allowed: false`) are strictly prohibited in this environment.

| Check ID | Description | Risk Level | Requires Human Approval | Associated SOP |
|---|---|---|---|---|
| `chk-fb-01` | Inspect live service metrics and 5xx error rates directly on Prometheus for api-gateway. | `MEDIUM` | `True` | *None* |
| `chk-fb-02` | Perform raw error log query on Loki for api-gateway over the incident window. | `MEDIUM` | `True` | *None* |
| `chk-fb-03` | Check database connection pool utilization and pending locks on backend databases. | `HIGH` | `True` | *None* |
| `chk-fb-04` | Consult incident runbook repository and coordinate with primary service owner. | `LOW` | `True` | *None* |

## 9. Reviewer Decision, Edits, and Sign-off Box

- **Current Review Status:** **`MANUAL_TRIAGE`**
- **Latest Review Event ID:** `N/A`
- **Reviewed By / Role:** `PENDING`
- **Review Timestamp:** `PENDING`

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     OFFICIAL SRE HANDOVER SIGN-OFF                     │
├────────────────────────────────────────────────────────────────────────┤
│  INCIDENT ID      : inc-fallback-at012-demo                            │
│  DOSSIER VERSION  : v1                                                 │
│  DOSSIER HASH     : a54b4e0df340c3c6b81f066eb2f31bf7...                │
│  DECISION         : MANUAL_TRIAGE                                      │
│  REVIEWER         : Awaiting Human Review                              │
│  DATE SIGNED      : PENDING                                            │
└────────────────────────────────────────────────────────────────────────┘
```