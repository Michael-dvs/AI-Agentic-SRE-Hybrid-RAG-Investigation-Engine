# Bounded Read-Only MCP Tool Contracts and Deterministic Policy Gateway Design — Chapter C02

- **Run ID:** `c02-20261109T070500Z`
- **Decision References:** `ADR-S03`, `ADR-S05`, `ADR-S07`, `D-C02-01`, `D-C02-02`, `D-C02-03`
- **Timestamp (UTC):** `2026-11-09T07:19:00Z` (`2026-11-09T14:19:00+07:00` WIB)
- **Author / Approver (`owner_ref`):** `project-initiator-michael`
- **Check IDs:** `C02-CON-006`, `C02-CON-007` (`PASS`)

---

## 1. Prinsip Isolasi Argumen Model vs Konteks Otorisasi Server

Sesuai Playbook `C02` §7.4 dan `RULE-003`, nama fungsi *"read-only"* tidaklah cukup apabila LLM masih diizinkan mengirimkan ekspresi kueri bebas, memalsukan grup akses (`allowed_groups`), atau meminta rentang waktu tanpa batas. Oleh karena itu, arsitektur `MCP Policy Gateway` memisahkan secara mutlak:

1. **Model-Visible Input Schema (`contracts/*-request.v1.schema.json`):**
   - Hanya berisi parameter target observasi yang tertutup (`additionalProperties: false`), ber-enum ketat (`metric_enum`, `error_code` berpola aman), dan bertipe waktu UTC `Z`.
   - **Tidak pernah** memuat field `principal_id`, `allowed_groups`, `role`, `credential`, `raw_query`, `promql`, `logql`, atau `sql`.
2. **Server-Derived Trusted Context (Out-of-Band Session Binding):**
   - Gateway mengekstrak `principal_id`, `incident_id`, `allowed_services`, `allowed_environments`, `allowed_groups`, sisa `tool_call_budget`, dan `deadline_at` langsung dari token sesi Coordinator (`COORD_SERVICE_TOKEN`) serta registri insiden aktif di server.

---

## 2. Katalog Tool Read-Only yang Diizinkan (`Allowlisted Tool Registry`)

Hanya **4 tool observasi read-only** berikut yang dipublikasikan pada baseline (`get_apm_health` berstatus *conditional* di bawah `ADR-S07` dan tidak diaktifkan kecuali sumber mock APM tersedia; tidak ada hasil APM palsu yang boleh dibuat):

| Tool Name | Input Schema ID | Backend Target | Template Kueri Berparameter (Bebas Injeksi) | Batas Kebijakan Semantik (`Semantic Policy Caps`) |
|---|---|---|---|---|
| **`get_service_metrics`** | `urn:sre-sim:contract:metrics-request:1` (`metrics-request.v1.schema.json`) | `src-prom-metrics` (Prometheus) | Dipetakan secara statis dari `metric_enum`: <br>- `request_rate` $\rightarrow$ `rate(http_requests_total{service_id=$1,env=$2}[1m])` <br>- `error_rate` $\rightarrow$ `sum(rate(http_requests_total{service_id=$1,env=$2,status=~"5.."}[1m])) / clamp_min(sum(rate(http_requests_total{service_id=$1,env=$2}[1m])), 1e-9)` <br>- `latency_p95` $\rightarrow$ `histogram_quantile(0.95, sum(rate(http_request_duration_ms_bucket{service_id=$1,env=$2}[1m])) by (le))` | `start < end`; `(end - start) <= max_window_seconds`; `1 <= max_points <= policy_max_points`; `service_id` & `environment` wajib masuk dalam scope insiden |
| **`search_error_logs`** | `urn:sre-sim:contract:logs-request:1` (`logs-request.v1.schema.json`) | `src-loki-logs` (Loki) | Template LogQL statis: <br>`{service_id=$1, environment=$2, severity=~"WARN|ERROR|CRITICAL"}` ditambah filter kesamaan tepat `| json | error_code = $3` bila `error_code != null` | `start < end`; `(end - start) <= max_window_seconds`; `1 <= max_hits <= policy_max_hits`; `error_code` hanya mengizinkan pola `^[A-Z0-9_:-]{2,64}$` (menolak regex/pipe LogQL); hasil wajib melewati redactor `SEC-03` |
| **`get_trace_summary`** | `urn:sre-sim:contract:trace-request:1` (`trace-request.v1.schema.json`) | `src-tempo-traces` (Tempo) | Lookup REST/gRPC berdasarkan `trace_id` 32-hex tervalidasi (`GET /api/traces/$trace_id`), lalu difilter agar hanya mengembalikan ringkasan span dalam jendela `[start, end)` tanpa body payload transaksi | `trace_id` 32-hex non-zero; `start < end`; `(end - start) <= max_window_seconds`; jumlah span dipotong secara eksplisit (`truncated=true`) jika melampaui `policy_max_spans`; jika Tempo mati, kembalikan `SOURCE_UNAVAILABLE` (`EV-02`) |
| **`get_service_dependencies`** | `urn:sre-sim:contract:dependencies-request:1` (`dependencies-request.v1.schema.json`) | `src-service-catalog` (Service Catalog & Edge Store) | Traversal graf berbatas BFS/DFS dari `service_id` pada `environment` dan `reference_time` hingga kedalaman `max_depth` | `1 <= max_depth <= policy_max_dependency_depth`; setiap edge menyertakan `source_kind` (`catalog_declared` vs `trace_observed`) dan `freshness_status` (`fresh` vs `stale`) |

**Penolakan Mutlak (`MCP-01` & `KPI-09`):**
Setiap permintaan untuk memanggil nama fungsi selain keempat tool di atas (mis. `restart_service`, `deploy_service`, `scale_deployment`, `execute_shell`, `run_sql`, `raw_promql_query`, `read_ground_truth`) ditolak pada langkah ke-2 dengan `status="rejected"` dan `error_code="TOOL_NOT_ALLOWED"`.

---

## 3. Urutan Penegakan 8 Langkah Deterministik (`8-Step Policy Enforcement Order`)

Setiap panggilan tool melewati pipeline sekuensial di `MCP Policy Gateway` (implementasi pada `C08`/`C09`):

1. **Step 1 — Authenticate Caller & Bind Trusted Scope:** Verifikasi `COORD_SERVICE_TOKEN` dan muat konteks insiden (`incident_id`, `allowed_services`, `allowed_environments`, `allowed_groups`, `policy_version`). Jika gagal $\rightarrow$ tolak dengan `UNAUTHENTICATED` (tanpa menyentuh backend).
2. **Step 2 — Tool Allowlist & Version Check:** Pastikan `tool_name` ada di dalam allowlist read-only dan `schema_version == "1.0"`. Jika tidak $\rightarrow$ tolak dengan `TOOL_NOT_ALLOWED` atau `UNSUPPORTED_SCHEMA` (`MCP-01`).
3. **Step 3 — Strict JSON Schema & Format Validation:** Validasi argumen terhadap `*-request.v1.schema.json` menggunakan `Draft202012Validator` + `FORMAT_CHECKER`. Field tambahan (`allowed_groups`, `query`) atau tanggal invalid langsung ditolak dengan `SCHEMA_INVALID` (`SEC-02`).
4. **Step 4 — Server-Side Service & Environment Authorization:** Periksa apakah `request.service_id` berada di dalam `trusted_context.allowed_services` (atau merupakan dependency langsung yang telah terotorisasi oleh graf korelasi insiden) dan `request.environment == trusted_context.environment`. Jika melanggar $\rightarrow$ tolak dengan `FORBIDDEN_SCOPE` (`SEC-01`).
5. **Step 5 — Semantic Window, Count, Quota & Deadline Enforcement:**
   - Pastikan `start < end` (jika `start >= end` $\rightarrow$ tolak dengan `INVALID_TIME_RANGE`).
   - Pastikan `(end - start) <= policy.max_window_seconds`. **Sesuai `MCP-02`, jendela waktu yang melebihi batas wajib ditolak dengan `WINDOW_EXCEEDED` (dilarang keras melakukan *silent clamping*).**
   - Pastikan `max_points <= policy.max_points`, `max_hits <= policy.max_hits`, atau `max_depth <= policy.max_dependency_depth` (jika melampaui $\rightarrow$ tolak dengan `LIMIT_EXCEEDED`).
   - Pastikan kuota panggilan tool per insiden (`remaining_tool_calls > 0`) dan sisa waktu (`now < incident_deadline_at`) masih mencukupi (jika habis $\rightarrow$ tolak dengan `BUDGET_EXHAUSTED` atau `DEADLINE_EXCEEDED`).
6. **Step 6 — Parameterized Read-Only Dispatch:** Bangun kueri backend dari template statis dan kirim ke endpoint Prometheus/Loki/Tempo/Catalog yang terdaftar di `source-registry.csv` dengan batas timeout ketat. Jika backend mati atau timeout $\rightarrow$ tangkap exception secara aman dan bentuk envelope `status="unavailable"`, `data_quality="unavailable"`, `records=[]`, `error_code="SOURCE_UNAVAILABLE"` atau `"BACKEND_TIMEOUT"` (`EV-02`).
7. **Step 7 — Mandatory `SEC-03` Deterministic Redaction & Response Bounding:**
   - Jalankan redactor deterministik atas seluruh field teks (khususnya `message` log dan atribut span) untuk menyamarkan pola JWT (`eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`), Bearer/API key (`(?i)(bearer|api[_-]?key|secret|password|token)\s*[:=]\s*\S+`), dan nomor kartu/akun sintetis (`\b\d{13,19}\b`) menjadi token `[REDACTED:SEC-03:<TYPE>]`.
   - **Perilaku `FAIL_CLOSED`:** Jika fungsi redactor gagal atau melempar error, blokir seluruh respons, kembalikan `status="rejected"`, `records=[]`, `sanitized=false`, `error_code="REDACTION_FAILED"`, dan tulis alert keamanan ke `GOV-02`.
8. **Step 8 — Synchronous Independent Audit & Envelope Return:** Tulis record `audit-event.v1.schema.json` ke `Independent Security Audit Store` (`GOV-02`). Hanya setelah penulisan audit berhasil, kembalikan `tool-result.v1.schema.json` ke pemanggil.

---

## 4. Pemisahan Fixture `TEST-ONLY` vs Kebijakan Runtime (`ADR-S05`)

- **Profil Fixture Kontrak (`TEST-ONLY` — Playbook §7.4 & §8.3):**
  ```json
  {
    "fixture_kind": "contract-test-only",
    "allowed_services": ["svc-a", "transaction-service"],
    "allowed_environments": ["lab"],
    "max_window_seconds": 900,
    "max_points": 100,
    "max_hits": 50,
    "max_dependency_depth": 2
  }
  ```
  Profil di atas digunakan secara eksklusif untuk memverifikasi kasus batas kualifikasi kontrak offline (`C02-CON-007` di `examples/policy-cases.csv`: 900 detik diterima vs 901 detik ditolak `WINDOW_EXCEEDED`; 100 poin diterima vs 101 poin ditolak `LIMIT_EXCEEDED`).
- **Kebijakan Runtime Lab (`ADR-S05`):**
  Gateway runtime wajib menolak startup apabila konfigurasi `policy_version` yang disahkan belum dimuat; tidak ada angka *hardcoded unlimited* di kode aplikasi.

