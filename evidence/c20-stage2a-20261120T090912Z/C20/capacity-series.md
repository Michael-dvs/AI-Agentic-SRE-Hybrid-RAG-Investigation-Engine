# C20 Tahap 2A: Capacity Series

- Generated: `2026-11-20T09:09:12.304751Z`
- Scope: `C20_STAGE_2A_DEV_ONLY`
- Final E20 package: `False`
- Docker metrics: `UNAVAILABLE`: failed to connect to the docker API at unix:///Users/michaelarhdyn/.docker/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /Users/michaelarhdyn/.docker/run/docker.sock: connect: no such file or directory

## OPS-01: 100 Duplicate Alerts

- Status: `PASS`
- Alerts / incidents / dossiers: `100 / 1 / 1`
- Final hit count: `100`
- Throughput: `13806.434 alerts/s`

## Concurrent Unique Incidents

| Level | Status | Accepted | Rejected | Dossiers | Throughput incident/s | Queue Peak | P50 ms | P95 ms | Peak RSS MiB |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | `PASS` | 5 | 0 | 5 | 2110.446 | 5 | 0.369 | 0.408 | 210.359 |
| 20 | `PASS` | 20 | 0 | 20 | 2231.676 | 20 | 0.353 | 0.426 | 210.359 |
| 50 | `PASS` | 50 | 0 | 50 | 2233.235 | 50 | 0.349 | 0.420 | 210.359 |

> Container metrics are marked UNAVAILABLE when Docker or running lab containers are absent; process CPU/RSS metrics remain measured and are not relabeled as container metrics.
