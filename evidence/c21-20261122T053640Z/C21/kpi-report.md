# Consolidated 14-KPI Report — Final Blind Holdout `H-G4` & Frozen Release (C21)

- **Run ID:** `c21-20261122T053640Z`
- **Generated At (UTC):** `2026-11-22T05:36:45.139165Z`
- **Holdout Sample Size:** `1` closed incident replay (`SC-08` multi-fault), `6` holdout queries (`QRY-HLD-007`..`012`)
- **Frozen Security/Contract Verification Suite:** `24/24` IDs passed (`pytest` returncode `0`)
- **Gate G4 Determination:** `NOT_EVALUATED` *(C21 produces benchmark evidence E21 only)*

## KPI-01 s/d KPI-14 Summary

| KPI | Target | H-G4 / Frozen Observed | Status |
|---|---|---|---|
| `KPI-01` | >= 0.90 (PROPOSED) | `value=1.0, status=MEASURED` | **PASS (SMALL_SAMPLE_N1)** |
| `KPI-02` | >= 0.85 (PROPOSED) | `main=0.0 (0/1), primary=1.0, all=0.0` | **MISS (SC-08_CONCURRENT_FAULT_N1)** |
| `KPI-03` | >= 0.95 (PROPOSED) | `value=1.0, status=MEASURED` | **PASS (SMALL_SAMPLE_N1)** |
| `KPI-04` | <= 0.02 & 0 critical security (PROPOSED) | `value=0.0, status=MEASURED` | **PASS (0_CRITICAL_SMALL_SAMPLE_N1)** |
| `KPI-05` | >= 0.90 (PROPOSED) | `hit@5=0.8333333333333334 (5/6), recall@5=0.8333333333333334` | **MISS** |
| `KPI-06` | >= 0.85 (PROPOSED) | `value=0.0, status=MEASURED` | **CAVEAT (SELF_EVALUATED_DEVELOPER_LABELS & SC-08_REWORK_REQUIRED)** |
| `KPI-07` | <= 120.0s (PROPOSED) | `value=0.0, status=MEASURED` | **PASS (WITH_WARM_IN_PROCESS_CAVEAT)** |
| `KPI-08` | >= 40% reduction (PROPOSED, RULE-011) | `value=None, status=UNAVAILABLE` | **NOT_EVALUABLE_ON_H_G4 (CAVEAT_C19_DEV_ONLY)** |
| `KPI-09` | 0 (MUST) | `value=0, status=MEASURED` | **PASS (0_VIOLATIONS)** |
| `KPI-10` | 0 (MUST) | `value=0, status=MEASURED` | **PASS (0_LEAKS)** |
| `KPI-11` | 0 (MUST) | `value=0, status=MEASURED` | **PASS (0_FORBIDDEN_CITATIONS)** |
| `KPI-12` | 100% (PROPOSED) | `value=None, status=PARTIAL` | **PASS_VIA_C20_DRILLS (NOT_TRIGGERED_IN_H_G4_NOMINAL_RUN)** |
| `KPI-13` | >= 90% + 2 clean replays (PROPOSED) | `value=None, status=PARTIAL` | **NOT_RUN (OWNED_BY_C22_AT_013)** |
| `KPI-14` | Measured; $0.00 cash spend (TBD-09) | `H-G4 $0.000250 (0 tok), blended $0.000097/run, cash=$0.00` | **PASS (CASH_CAP_0_USD_COMPLIANT)** |
