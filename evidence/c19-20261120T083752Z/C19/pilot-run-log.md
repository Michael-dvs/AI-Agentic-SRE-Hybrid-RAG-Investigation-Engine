# Rekaman Eksekusi Lab Shadow Pilot (`DEV`) — Chapter 19

- **Run ID:** `c19-20261120T083752Z`
- **Executed At (UTC):** `2026-11-20T08:37:52.498053Z`
- **Split:** `dev` (H-G4 access: `0` rows)
- **Total Pilot Incidents:** 7
- **Closed Cleanly (`CLOSED`):** 7/7
- **Telegram Notifications (`DRY_RUN`):** 7
- **Audit Chain Integrity:** `True` (`15` events)
- **Zero Auto-Remediation (`HUM-01`):** `auto_action_triggered_count == 0`
- **Ground Truth Isolation (`AT-008`):** `handover_gt_leaks == 0`

## Ringkasan Kasus Pilot

| Incident ID | Layanan | Kasus | Mode | Final State | Rev | Support Top-1 | Missing Sources | System TTI (s) | Telegram | Auto Action |
|---|---|---|---|---|---:|---|---|---:|---|---|
| `inc-pilot-dev-sc01-001` | `api-gateway` | DEV-01 Healthy Control Baseline | `deterministic_baseline` | `CLOSED` | v1 | `INCONCLUSIVE` | 0 | 0.042 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc02-002` | `transaction-service` | DEV-02 Single Fault HTTP 5xx Burst | `deterministic_baseline` | `CLOSED` | v1 | `SUPPORTED` | 0 | 0.032 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc03-003` | `ledger-service` | DEV-03 Single Fault DB Connection Pool Exhaustion | `deterministic_baseline` | `CLOSED` | v1 | `SUPPORTED` | 0 | 0.029 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc04-004` | `api-gateway` | DEV-04 Cascade Failure Gateway -> Transaction -> Ledger | `deterministic_baseline` | `CLOSED` | v1 | `SUPPORTED` | 0 | 0.034 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc06-005` | `auth-service` | DEV-05 Auth Token Mismatch & Obsolete SOP Exclusion | `deterministic_baseline` | `CLOSED` | v1 | `SUPPORTED` | 0 | 0.023 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc07-006` | `notification-service` | DEV-06 Queue Consumer Lag (Human Correction v1->v2) | `deterministic_baseline` | `CLOSED` | v2 | `INCONCLUSIVE` | 0 | 0.029 | `DRY_RUN` | `False` |
| `inc-pilot-dev-sc09-007` | `api-gateway` | DEV-07 Degraded Mode / Trace Backend Outage | `deterministic_baseline` | `CLOSED` | v1 | `INCONCLUSIVE` | 1 | 0.032 | `DRY_RUN` | `False` |
