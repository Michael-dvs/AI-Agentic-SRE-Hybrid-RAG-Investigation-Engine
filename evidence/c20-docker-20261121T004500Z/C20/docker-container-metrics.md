# C20 Supplemental Live Docker Container Telemetry (`c20-docker-20261121T004500Z`)

- **Run ID:** `c20-docker-20261121T004500Z`
- **Observed At (UTC):** `2026-11-20T17:46:47Z`
- **Status Docker Container Stats:** `MEASURED` (`12/12` kontainer `sre-sim-*` sehat)
- **Frozen Release Integrity:** `source_tree_sha256` (`10c3235882ab75e1286f18cc1204792009d053b5ee1677c4a202fd3bcc74f665`) dan segel `H-G4` (`VERIFIED_SEALED`) tetap **100% utuh** tanpa modifikasi kode sumber.
- **Full Pytest Suite (dengan Docker Compose aktif):** `482 passed, 0 skipped, 0 failed in 34.88s` (seluruh 6 tes live Compose/observability yang sebelumnya `skipped` kini lulus).

## 1. Ringkasan Konsumsi Sumber Daya Stack Lab (12 Kontainer `sre-sim-*`)

| Kondisi Pengukuran | Total Memori Kontainer | Limit Compose | Persen Limit Lab (`8192 MiB`) | Total CPU Kontainer |
|---|---:|---:|---:|---:|
| Selama Run C20 Stage 2A (`capacity-series.json`) | `652.99 MiB` | `2,944.00 MiB` | `7.97%` | `5.89%` |
| Pasca Live Spike Burst (`100` req `SC-01`, `25 RPS`) | `683.03 MiB` | `2,944.00 MiB` | `8.34%` | `6.41%` |

> **Catatan Isolasi:** Empat kontainer non-proyek yang kebetulan berjalan di host (`botseri-dashboard`, `botseri-n8n`, `botseri-waha`, `botseri-db`) dipisahkan dan tidak dimasukkan ke dalam total konsumsi memori/CPU maket `sre-sim-*`.

## 2. Detail Live Spike Burst (`SC-01`)

- **Profil:** `spike` (`seed=20261121`, `rate=25.0 RPS`, `concurrency_cap=12`, target `http://127.0.0.1:18080`)
- **Hasil:** `100/100` HTTP `201`, `error_count=0`, `P50=409.07 ms`, `P95=556.80 ms`, durasi `4.09s`.

## 3. Metrik per Kontainer (Pasca Live Spike Burst)

| Kontainer | CPU % | Mem Usage | Mem Limit | Mem % | Net I/O | PIDs |
|---|---:|---:|---:|---:|---|---:|
| `sre-sim-api-gateway` | `0.28%` | `78.88 MiB` | `128.00 MiB` | `61.63%` | `759kB / 1.1MB` | `9` |
| `sre-sim-transaction-service` | `0.43%` | `65.22 MiB` | `128.00 MiB` | `50.96%` | `870kB / 1.23MB` | `9` |
| `sre-sim-auth-service` | `0.23%` | `42.14 MiB` | `128.00 MiB` | `32.92%` | `327kB / 590kB` | `2` |
| `sre-sim-ledger-service` | `0.24%` | `47.14 MiB` | `128.00 MiB` | `36.83%` | `725kB / 1.02MB` | `2` |
| `sre-sim-notification-service` | `1.19%` | `47.57 MiB` | `128.00 MiB` | `37.17%` | `462kB / 983kB` | `3` |
| `sre-sim-postgres` | `0.06%` | `20.59 MiB` | `192.00 MiB` | `10.72%` | `434kB / 456kB` | `6` |
| `sre-sim-rabbitmq` | `0.64%` | `105.80 MiB` | `256.00 MiB` | `41.31%` | `967kB / 562kB` | `38` |
| `sre-sim-otel-collector` | `0.28%` | `58.80 MiB` | `192.00 MiB` | `30.63%` | `1.95MB / 1.99MB` | `6` |
| `sre-sim-prometheus` | `0.24%` | `53.60 MiB` | `512.00 MiB` | `10.47%` | `22.1kB / 15.3kB` | `3` |
| `sre-sim-loki` | `0.26%` | `43.70 MiB` | `512.00 MiB` | `8.54%` | `889kB / 134kB` | `2` |
| `sre-sim-tempo` | `0.24%` | `45.82 MiB` | `384.00 MiB` | `11.93%` | `830kB / 146kB` | `2` |
| `sre-sim-grafana` | `2.32%` | `73.77 MiB` | `256.00 MiB` | `28.81%` | `21.5kB / 7.63kB` | `18` |
| **TOTAL (12 Kontainer Lab)** | **`6.41%`** | **`683.03 MiB`** | **`2,944.00 MiB`** | **`23.20%`** | — | **`100`** |
