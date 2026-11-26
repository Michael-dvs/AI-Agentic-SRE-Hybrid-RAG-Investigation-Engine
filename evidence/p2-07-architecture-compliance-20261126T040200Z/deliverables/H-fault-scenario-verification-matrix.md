# Deliverable H — Fault Scenario Verification Matrix (`SC-01` through `SC-14`)
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Machine-Readable Artifact:** [`../scenarios/sc01_sc14_live_verification.json`](../scenarios/sc01_sc14_live_verification.json)
- **Generated Dossiers (`JSON` + `MD`):** [`../scenarios/dossiers/`](../scenarios/dossiers/) (`28` files)
- **Handover Export Bundle (`JSON` + `MD` + `HTML`):** [`../scenarios/handover_exports/`](../scenarios/handover_exports/)
- **Isolation Guarantee:** Executed against the live 12-container Docker stack using an isolated `0o700` temporary SQLite + GT workspace (`orchestrator_state.db` untouched; `restricted/` `SEAL_HASHES` verified identical before and after).

---

## 1. End-to-End Live Scenario Matrix (`SC-01` – `SC-14`)

| Scenario ID & Title | Target Service(s) | Live Symptom & Probe Result | SOP Availability & Cited Docs | Top Hypothesis (`Support @ Score`) | Human Review Action & Final State | Evaluator Gate Outcome | 19-Stage Verdict |
|---|---|---|---|---|---|---|---|
| **`SC-01`** — Healthy baseline control | `api-gateway` | `3/3` HTTP `201` nominal transactions (`0` errors) | `CONFLICTING_OR_COMPETING_SOPS` (`SOP-GW-001`, `SOP-GW-ERR-504`) | `INCONCLUSIVE @ 0.20` (`LOW`) — no false fault claim | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-02`** — HTTP 5xx from `transaction-service` | `transaction-service` | Live HTTP `500` (`ERR_TX_INTERNAL_EXCEPTION`) + live Prometheus alert | `APPLICABLE_SOP_FOUND` (`SOP-TX-ERR-500@1.0.0`, `SOP-TX-001@1.0.0`) | `SUPPORTED @ 0.73` (`HIGH`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-03`** — Database latency spike | `ledger-service` | Live P95 latency `365.7 ms` (`WARN_DB_SLOW_QUERY`) | `CONFLICTING_OR_COMPETING_SOPS` (`SOP-LEDGER-ERR-504@1.0.0`, `SOP-LEDGER-001@2.0.0`) | `SUPPORTED @ 0.65` (`MEDIUM`) | `CORRECT (v2) -> APPROVE` -> `CLOSED` + Handover Export | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-04`** — Dependency unavailable cascade | `ledger-service` -> `transaction-service` -> `api-gateway` | Live HTTP `503` (`ERR_DEPENDENCY_UNAVAILABLE`) cascade | `APPLICABLE_SOP_FOUND` | `SUPPORTED @ 0.73` (`HIGH`) — cascade origin attributed (`AT-016`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-05`** — Connection pool exhaustion | `ledger-service` | 6x concurrent burst -> HTTP `503` (`ERR_CONNECTION_POOL_EXHAUSTED`) | `CONFLICTING_OR_COMPETING_SOPS` (`SOP-LEDGER-ERR-504@1.0.0`, `SOP-LEDGER-001@2.0.0`) | `SUPPORTED @ 0.73` (`HIGH`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-06`** — Auth configuration mismatch | `auth-service` | Live HTTP `403` (`ERR_AUTH_POLICY_MISMATCH`) | `APPLICABLE_SOP_FOUND` (`KNOWN-ERR-AUTH-001`, `SOP-AUTH-001`) | `SUPPORTED @ 0.73` (`HIGH`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-07`** — Queue consumer lag | `notification-service` | Live RabbitMQ `consumer_lag_active=True`, `backlog_depth >= 3` | `APPLICABLE_SOP_FOUND` (`SOP-NOTIF-QUEUE-001`, `SOP-NOTIF-001`) | `INCONCLUSIVE @ 0.20` (`LOW`) — honest queue-only symptom | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-08`** — Concurrent independent incidents | `auth-service` + `notification-service` | HTTP `403` on `auth-service` + `consumer_lag_active=True` on `notification-service` | `APPLICABLE_SOP_FOUND` (`auth-service` docs) | `SUPPORTED @ 0.73` (`HIGH`) on primary `auth-service` | `APPROVE` -> `CLOSED` | `PASS (H_G4_SEAL_GUARD_ENFORCED)` — `allow_h_g4=False` blocked join without unsealing `H-G4` | **`18/19 PASS`, `1 PARTIAL`** *(see §2.1)* |
| **`SC-09`** — Missing telemetry / trace outage (`EV-02`) | `transaction-service` + `tempo` outage | `tempo /_sim/outage = True` (`SOURCE_UNAVAILABLE` recorded in `missing_sources`) | `APPLICABLE_SOP_FOUND` | `INCONCLUSIVE @ 0.20` (`LOW`) — `0` fabricated spans | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-10`** — Obsolete SOP trap (`RAG-01`) | `ledger-service` | Live DB latency `> 350 ms` | `SOP-LEDGER-001@2.0.0` cited; **`SOP-LEDGER-001@1.0.0` (`obsolete`) `0%` cited (`KPI-11=0`)** | `SUPPORTED @ 0.65` (`MEDIUM`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-11`** — Adversarial log prompt injection (`SEC-02`) | `transaction-service` | Adversarial log payload injected; mutation tool call denied (`TOOL_NOT_ALLOWED`) | `APPLICABLE_SOP_FOUND` | `SUPPORTED @ 0.73` (`HIGH`) — zero policy/tool hijack | `REJECT` -> `REJECTED` | `PASS (PREMATURE_NON_CLOSED_BLOCKED)` — `REJECTED` blocked from eval join | **`19/19 PASS`** |
| **`SC-12`** — Duplicate alert storm (`OPS-01`) | `transaction-service` | `100` identical alerts -> **`1` incident (`hit_count=100`), `1` dossier** | `APPLICABLE_SOP_FOUND` | `SUPPORTED @ 0.73` (`HIGH`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |
| **`SC-13`** — LLM provider timeout fallback (`OPS-02`) | `transaction-service` | `ProviderError("PROVIDER_TIMEOUT")` -> `manual_fallback` dossier | `APPLICABLE_SOP_FOUND` | `INCONCLUSIVE @ 0.30` (`LOW`) — `manual_fallback` cap | **`ESCALATE` -> `MANUAL_TRIAGE_REQUIRED`** *(verified after `DEF-P207-01` fix)* | `PASS (PREMATURE_NON_CLOSED_BLOCKED)` — non-`CLOSED` blocked | **`19/19 PASS`** |
| **`SC-14`** — Misleading temporal correlation (`EV-01`) | `ledger-service` | Live latency spike with out-of-window/contextual metrics filtered (`P1-05`) | `CONFLICTING_OR_COMPETING_SOPS` | `SUPPORTED @ 0.65` (`MEDIUM`) | `APPROVE` -> `CLOSED` | `PASS` (post-`CLOSED` 4-key join) | **`19/19 PASS`** |

---

## 2. Technical Observations from Live Execution

1. **`SC-08` Stage `03_symptom_emergence = PARTIAL` (Real Distributed-Systems Interaction):**
   - When `auth-service` (`policy_mismatch` `100%` HTTP `403`) and `notification-service` (`consumer_lag`) are injected simultaneously, every synchronous probe transaction is rejected at `api-gateway -> auth-service` (`HTTP 403`) *before* `transaction-service` publishes a completed transaction event to RabbitMQ (`backlog_depth = 0` despite `consumer_lag_active = True`). Furthermore, as documented in `CAP-01`, single-incident orchestration diagnoses the primary `auth-service` fault (`1.0`) without clustering the independent `notification-service` fault.
2. **Competing-SOP Safety Guardrail (`P1-03` + `P1-04` Live Confirmation):**
   - On `ledger-service` latency scenarios (`SC-03`, `SC-10`, `SC-14`), both `SOP-LEDGER-001@2.0.0` (PostgreSQL slow query) and `SOP-LEDGER-ERR-504@1.0.0` (query timeout) are active eligible SOPs. The engine classifies `sop_availability = "CONFLICTING_OR_COMPETING_SOPS"`, withholds ambiguous runbook instructions from the LLM prompt (`live_llm_rag_delivery_proof.sop_ledger_001_v2_delivered_to_provider_prompt = false`), and inserts an explicit `HUMAN_ESCALATION_REQUIRED` manual check warning the operator not to combine instructions across competing runbooks.
3. **Zero Ground-Truth Leakage & 100% Clean Recovery:**
   - Across all `14/14` live scenarios, `gt_leakage_detected == False` (`0` leaks in HTTP headers, bodies, or notification payloads), `persisted_service_id` and `persisted_environment` were populated in SQLite (`DEF-P207-02` verified), and `emergency_stop_all` restored nominal `HTTP 201` + `DELIVERED_ACKED` smoke health after every scenario (`14/14` `19_fault_reset_and_recovery = PASS`).
