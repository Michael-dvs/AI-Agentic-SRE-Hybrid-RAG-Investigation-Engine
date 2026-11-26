# Deliverable D — Requirements Traceability Summary & Denominator Reconciliation
## P2-07 Architecture Compliance Verification

- **Machine-Readable Matrix:** [`D-requirements-traceability-matrix.csv`](D-requirements-traceability-matrix.csv) (`138` total tracked rows: `131` canonical source items + `7` clearly separated `P207-REM-*` audit-local remediation workstream items).
- **Updated Repository RTM:** [`docs/roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md`](../../../docs/roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md) (all stale `SPECIFIED / NOT_RUN` and `Pending C09–C21` entries reconciled).

---

## 1. Exact Compliance Counts by Authoritative Namespace

| Namespace / Requirement Family | Total Items (Denominator) | `COMPLIANT` (`PASS`) | `PARTIALLY_COMPLIANT` (`CONDITIONAL / HONEST GAP`) | `NON_COMPLIANT` / `MISSING` | Key Notes on Partial / Conditional Items |
|---|---:|---:|---:|---:|---|
| **BRD §7 Business Requirements (`BR-001`–`BR-016`)** | **16** | **13** (`81.25%`) | **3** (`18.75%`) | **0** | `BR-003` (`SC-08` multi-fault `CAP-01`), `BR-004` & `BR-011` (`deterministic_local_384d` dense fallback & `QRY-HLD-012` `83.33%` Hit@5, `CAP-02`) |
| **BRD §8 Functional Requirements (`FR-*`)** | **40** | **38** (`95.00%`) | **2** (`5.00%`) | **0** | `FR-OBS-004` (`LiveAlertWatcher` direct polling bypasses `AlertIntakeService`, `FIND-P207-04`), `FR-RAG-003` (local dense embedder fallback & `QRY-HLD-012` `CAP-02`) |
| **BRD §9 Business Rules (`RULE-001`–`RULE-012`)** | **12** | **11** (`91.67%`) | **1** (`8.33%`) | **0** | `RULE-011` (`KPI-08` anti-carryover timing executed on DEV `N=7` with self-evaluated caveat; `UNAVAILABLE` on `H-G4` `N=1`, `CAP-04`) |
| **BRD §11 Non-Functional Requirements (`NFR-001`–`NFR-020`)** | **20** | **20** (`100.00%`) | **0** (`0.00%`) | **0** | All 20 PoC-scoped NFRs verified (`~819 MiB` active Docker RAM, `4/4` rollback drills, `$0.00` cash spend, `0` DLP leaks) |
| **Subtotal — Canonical BRD Requirements (`88` IDs)** | **88** | **82** (`93.18%`) | **6** (`6.82%`) | **0** | `100%` of mandatory safety rules satisfied; `6` quality/coupling caveats governed by `CAP-01`–`CAP-05` |
| **Proposal v2.0 Appendix A Tests (`12` IDs)** | **12** | **12** (`100.00%`) | **0** (`0.00%`) | **0** | `SEC-01..03`, `MCP-01..02`, `RAG-01..02`, `EV-01..02`, `OPS-01..02` (`DEF-P207-01` fixed), `HUM-01` all `PASS` |
| **BRD §16 Acceptance Tests (`AT-001`–`AT-017`)** | **17** | **15** (`88.24%`) | **2** (`11.76%`) | **0** | `AT-006` (`H-G4` Hit@5 `83.33%`) and `AT-014` (`H-G4` `N=1` `SC-08` `KPI-02=0.0`, small sample `TBD-08`) |
| **BRD §15.2 Candidate KPIs (`KPI-01`–`KPI-14`)** | **14** | **10** (`71.43%`) | **4** (`28.57%`) | **0** | Hard safety KPIs (`KPI-09=0`, `KPI-10=0`, `KPI-11=0`, `KPI-13=1.0`) `100% PASS`; candidate quality/SME KPIs `KPI-02`, `KPI-05`, `KPI-06`, `KPI-08` carry disclosed `CAP-01`–`CAP-04` conditions |
| **Audit-Local Remediation Baselines (`P207-REM-*`)** | **7** | **7** (`100.00%`) | **0** (`0.00%`) | **0** | `P0-01`, `P0-02` (+`DEF-P207-01`), `P1-03`, `P1-04`, `P1-05`, `P2-06`, `P2-07` verified |

---

## 2. Orphan & Bi-Directional Traceability Check (`Work Package B3`)

1. **Unimplemented Official Requirements:** **`0`** (every `BR-*`, `FR-*`, `RULE-*`, and `NFR-*` maps to concrete implemented modules and executed tests).
2. **Untested Requirements:** **`0`** (all `22+` previously stale `SPECIFIED / NOT_RUN` rows in `REQUIREMENTS-TRACEABILITY-MATRIX.md` were traced to executed `C07`–`C24` and `P0-01`–`P2-07` tests and updated).
3. **Orphan / Post-Roadmap Code Modules Identified:**
   - `orchestrator/live_watcher.py`, `scripts/run_alert_watcher.py`, `scripts/run_banking_simulator.py`, and `orchestrator/console_config.py` were added post-`G4` (commit `98e6930`) to support interactive live demo operation (`RFC-F4-01`). They are covered by `tests/test_live_watcher.py`, `tests/test_banking_simulator.py`, and `tests/test_p2_06_dashboard_usability_state.py`; their architectural coupling nuances (`FIND-P207-04`) are recorded in Deliverable O.
