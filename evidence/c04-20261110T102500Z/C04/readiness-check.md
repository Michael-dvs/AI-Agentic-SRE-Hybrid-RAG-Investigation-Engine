# Laporan Pemeriksaan Kesiapan (Readiness Check) — Chapter C04: Fault Harness & Ground Truth Isolation

> **Run ID Paket Bukti:** `c04-20261110T102500Z`  
> **Chapter:** `C04 — Fault Harness & Ground Truth Isolation` (`P1 — Foundation`)  
> **Tanggal Verifikasi:** `2026-11-10T10:25:00Z`  
> **Status Kesiapan Masuk (Entry Readiness):** `READY (PASS)`

---

## 1. Verifikasi Prasyarat Masuk (Entry Criteria)

| Prasyarat | Bukti Acuan | Status | Catatan Verifikasi |
|---|---|---|---|
| **G0 Readiness (`G0 = PASS`)** | `docs/gates/G0-PROJECT-INITIATION-AND-READINESS.md`, `evidence/c01-20261109T043813Z/C01/` | `VERIFIED` | Scope simulasi, data 100% sintetis (`RULE-001`), dan batas perangkat keras lokal (`macOS Apple Silicon 16 GB RAM`) telah disahkan oleh pemilik proyek. |
| **Kontrak C02 (`E02 = APPROVED`)** | `evidence/c02-20261109T070500Z/C02/contracts/evaluation-manifest.v1.schema.json`, `identity-access.csv`, `trust-boundaries.md` | `VERIFIED` | Skema `evaluation-manifest.v1.schema.json` (Draft 2020-12), matriks hak akses principal (`identity-access.csv`), dan batas *trust zone* (`Z2` vs `Z5` pada `trust-boundaries.md`) tersedia dan valid. |
| **Implementasi & Smoke Test C03 (`E03 = VERIFIED`)** | `evidence/c03-20261109T084600Z/C03/`, `evidence/c03-20261109T084600Z/C03/handover-to-c04-and-c05.md` | `VERIFIED` | Kelima layanan FastAPI (`api-gateway`, `auth-service`, `transaction-service`, `ledger-service`, `notification-service`) beserta PostgreSQL dan RabbitMQ berjalan sehat dengan `11/11 PASS` pada pengujian otomatis C03. |
| **Ketiadaan Blocker Kritis** | `docs/roadmap/DOCUMENT-MANIFEST.md`, `docs/roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md` | `VERIFIED` | Tidak ada blocker teknis maupun keputusan `TBD` yang menghambat implementasi *fault harness* dan isolasi *ground truth* C04. |

---

## 2. Lingkup Implementasi C04 yang Diotorisasi

1. **Mekanisme Kontrol Gangguan Reversibel (`services/common/fault_control.py`):**
   - Endpoint `/_sim/fault/inject`, `/_sim/fault/reset`, dan `/_sim/fault/status` (disembunyikan dari skema OpenAPI publik).
   - Autentikasi ketat khusus `principal:operator-harness` menggunakan `X-Harness-Token` dan tanda tangan HMAC-SHA256 (`X-Harness-Signature`).
   - Penolakan eksplisit (`403 ERR_FAULT_CONTROL_FORBIDDEN`) terhadap seluruh principal runtime/investigator (`principal:investigator-coord`, `principal:mcp-policy-gateway`, `principal:alert-intake`, `principal:kb-ingestion`, `principal:human-reviewer`).
   - Penolakan eksplisit (`422 ERR_FORBIDDEN_GROUND_TRUTH_FIELD`) terhadap setiap payload yang memuat field `scenario_id`, `ground_truth`, `expected_root_cause`, `actual_root_cause`, atau `split_id`.
   - Pembatasan *allowlist* 5 layanan, batas durasi maksimum `120.0` detik (dengan pembersihan TTL otomatis), dan batas konkurensi maksimum `2` fault aktif per layanan (`429 ERR_FAULT_CONCURRENCY_LIMIT`).
2. **Katalog 14 Skenario (`fault_harness/scenarios.py`):**
   - Pemisahan penuh antara metadata skenario publik (`get_public_scenario_manifest()`) dan *oracle* terisolasi (`get_restricted_oracle()`).
   - Skenario aktif layanan C04 (`SC-01` s.d. `SC-08`) serta resep lintas-komponen (`SC-09` s.d. `SC-14`).
3. **Registri Ground Truth Terisolasi (`fault_harness/gt_registry.py`):**
   - Penyimpanan *append-only* pada direktori host `restricted/gt_registry/` (`0o700` dir, `0o600` file) yang dikecualikan dari image Docker (`.dockerignore`) dan tidak pernah di-*mount* ke dalam kontainer.
   - Pembekuan label sebelum *onset* (`freeze_ground_truth`), jaminan imutabilitas (`GroundTruthImmutabilityError`), pencatatan audit akses (`gt_access_audit.jsonl`), dan *join* evaluasi pasca-`CLOSED` (`read_for_offline_evaluation`) yang mematuhi `evaluation-manifest.v1.schema.json`.
4. **Runner 8 Langkah & Emergency Stop (`fault_harness/runner.py`, `scripts/fault_reset.sh`):**
   - Siklus hidup: `validate -> baseline_check -> inject -> observe -> stop -> recover -> verify -> record`.
   - Pemindaian kebocoran otomatis (`scan_for_gt_leakage`) dan jaminan pemulihan (`finally: emergency_stop_all`) yang diverifikasi menggunakan *smoke test* baseline C03.

