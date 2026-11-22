# C20 Tahap 2A: Capacity Series

- Generated: `2026-11-20T17:42:43.771418Z`
- Scope: `C20_STAGE_2A_DEV_ONLY`
- Final E20 package: `False`
- Docker metrics: `MEASURED`: None

## OPS-01: 100 Duplicate Alerts

- Status: `PASS`
- Alerts / incidents / dossiers: `100 / 1 / 1`
- Final hit count: `100`
- Throughput: `14627.368 alerts/s`

## Concurrent Unique Incidents

| Level | Status | Accepted | Rejected | Dossiers | Throughput incident/s | Queue Peak | P50 ms | P95 ms | Peak RSS MiB |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | `PASS` | 5 | 0 | 5 | 1851.509 | 5 | 0.383 | 0.433 | 209.500 |
| 20 | `PASS` | 20 | 0 | 20 | 2089.600 | 20 | 0.361 | 0.420 | 209.500 |
| 50 | `PASS` | 50 | 0 | 50 | 2278.947 | 50 | 0.359 | 0.435 | 209.500 |

> Container metrics are marked UNAVAILABLE when Docker or running lab containers are absent; process CPU/RSS metrics remain measured and are not relabeled as container metrics.
