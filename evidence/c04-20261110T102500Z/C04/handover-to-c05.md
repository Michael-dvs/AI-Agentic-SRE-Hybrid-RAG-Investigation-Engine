# Dokumen Serah Terima (Handover) — Chapter C04 ke Chapter C05 (Observability Pipeline)

> **Run ID Paket Bukti:** `c04-20261110T102500Z`  
> **Chapter Asal:** `C04 — Fault Harness & Ground Truth Isolation` (`VERIFIED`)  
> **Chapter Tujuan:** `C05 — Observability & Alert Pipeline (Prometheus, Loki, Tempo, Grafana)`  
> **Tanggal Serah Terima:** `2026-11-10T10:27:30Z`

---

## 1. Ringkasan Artefak & Bukti E04 yang Diserahterimakan

| Artefak / File | Lokasi Aktual | Status |
|---|---|---|
| Middleware & kontrol gangguan reversibel | `services/common/fault_control.py` | `VERIFIED` |
| Katalog 14 skenario (`SC-01`..`SC-14`) | `fault_harness/scenarios.py`, `evidence/c04-20261110T102500Z/C04/scenario-manifest.json` | `VERIFIED` |
| Registri Ground Truth terisolasi (`AT-008`) | `fault_harness/gt_registry.py`, `restricted/gt_registry/` | `VERIFIED` |
| Runner siklus hidup 8 langkah & pemindai kebocoran | `fault_harness/runner.py` | `VERIFIED` |
| Skrip *emergency stop* operator | `scripts/fault_reset.sh` | `VERIFIED` |
| Bukti eksekusi & pemulihan `SC-01`..`SC-08` | `evidence/c04-20261110T102500Z/C04/reset-proof.json` | `VERIFIED` |
| Bukti penolakan akses *ground truth* & isolasi kontainer | `evidence/c04-20261110T102500Z/C04/gt-access-denials.json` | `VERIFIED` |
| Hasil uji otomatis penuh (`17/17 PASS`) | `tests/test_c04_fault_harness.py`, `evidence/c04-20261110T102500Z/C04/test-results.txt` | `VERIFIED` |

---

## 2. Kontrak Sinyal & Perilaku Gangguan untuk C05 (Observability Pipeline)

Saat C05 mengintegrasikan **Prometheus, Loki, Tempo, dan Grafana**, pipeline observabilitas dapat langsung mengandalkan sinyal deterministik berikut yang telah diuji pada C04 tanpa kebocoran label *ground truth*:

1. **Sinyal Metrik RED (`GET /metrics` & Prometheus Scrape):**
   - `SC-02` (`http_5xx` pada `transaction-service`): lonjakan HTTP `500` (`ERR_TX_INTERNAL_EXCEPTION`) dan `503` (`ERR_TRANSACTION_UPSTREAM_UNAVAILABLE` pada `api-gateway`).
   - `SC-03` (`db_latency` pada `ledger-service`): kenaikan durasi P95 pada `ledger-service`, `transaction-service`, dan `api-gateway` (`+350ms`) dengan status HTTP tetap `201`.
   - `SC-04` (`dependency_unavailable` pada `ledger-service`): kegagalan berantai (`503 ERR_DEPENDENCY_UNAVAILABLE` -> `503 ERR_LEDGER_UPSTREAM_UNAVAILABLE`) serta kesiapan `/health/ready` berubah menjadi `503`.
   - `SC-05` (`pool_exhausted` pada `ledger-service`): HTTP `503 ERR_CONNECTION_POOL_EXHAUSTED` disertai penundaan tunggu *pool*.
   - `SC-06` (`auth_config_mismatch` pada `auth-service`): lonjakan HTTP `403 ERR_AUTH_POLICY_MISMATCH` tanpa lonjakan `5xx`.
   - `SC-07` (`queue_consumer_lag` pada `notification-service`): transaksi sinkron tetap `201`, tetapi `GET /api/v1/notifications` menunjukkan `consumer_lag_active=true` dan kenaikan `backlog_depth`.
   - `SC-08`: gabungan independen `SC-06` + `SC-07`.
2. **Sinyal Log Terstruktur (JSON ke `stdout` untuk Loki):**
   - Seluruh log mematuhi `telemetry-log.v1.schema.json` dan telah lulus pemindaian `scan_for_gt_leakage` (`0` kebocoran `scenario_id` / `ground_truth`).
   - Mode resep `trace_context_drop` (`SC-09`), `adversarial_log_payload` (`SC-11`), dan `misleading_noise_log` (`SC-14`) sudah tersedia pada `services/common/fault_control.py` untuk pengujian C05/C09/C14.
3. **Jaminan Isolasi untuk C05:**
   - Kolektor log/metrik/trace di C05 **dilarang** membaca atau me-*mount* direktori host `restricted/gt_registry/` maupun `fault_harness/`.
   - Endpoint `/_sim/fault/*` dikecualikan dari metrik bisnis supaya aktivitas operator tidak mengotori deteksi anomali.

