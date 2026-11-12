# ADR-S03: Isolasi 7 Identitas Prinsipal, 5 Trust Boundaries, dan Kontrak MCP Read-Only Gateway

- **ID Keputusan:** `ADR-S03`
- **Status:** `ACCEPTED` (Desain Kontrak & Keamanan; Pembuktian Penolakan Runtime pada C08–C18)
- **Tanggal:** `2026-11-09`
- **Pemilik / Otoritas:** `project-initiator-michael`
- **Chapter Terkait:** `C02`, `C04`, `C06`, `C08`, `C09`, `C13`, `C15`, `C18`
- **Referensi Bukti:** `evidence/c02-20261109T070500Z/C02/trust-boundaries.md`, `evidence/c02-20261109T070500Z/C02/identity-access.csv`, `evidence/c02-20261109T070500Z/C02/tool-policy-design.md`

---

## 1. Konteks & Permasalahan

Agen investigator tidak boleh memiliki kemampuan mutasi (`RULE-02`, `MCP-01`), tidak boleh mengakses ground-truth/holdout (`RULE-03`, `AT-008`), dan tidak boleh memalsukan hak akses grup melalui argumen prompt (`SEC-01`, `SEC-02`).

---

## 2. Keputusan

1. **Lima Trust Boundaries & Isolasi Jaringan Docker:**
   - `TB-01` (`net_sim`): Layanan sintetis FastAPI.
   - `TB-02` (`net_obs`): OTel, Prometheus, Loki, Tempo, Grafana.
   - `TB-03` (`net_kb`): Qdrant & pipeline ingesti KB.
   - `TB-04` (`net_control`): Alert Intake, Workflow Coordinator, MCP Read-Only Gateway, LLM Router, Evidence Validator, Dossier Generator.
   - `TB-05` (`net_eval`, host-isolated): Fault Injection Harness, Ground-Truth Registry (`restricted/gt-registry/`), dan Offline Evaluator. **Tidak ada rute jaringan atau volume mount dari `TB-04` ke `TB-05`.**
2. **Tujuh Identitas Prinsipal Terpisah (`identity-access.csv`):**
   - `principal_investigator`, `principal_intake`, `principal_tool_gateway`, `principal_kb_ingestor`, `principal_reviewer`, `principal_fault_harness`, dan `principal_evaluator` menggunakan kredensial/token terpisah.
   - Konteks otorisasi (`caller_groups`, `allowed_services`, `allowed_environments`) diturunkan di sisi server (*out-of-band*) dari token identitas—tidak pernah dibaca dari argumen JSON yang dikendalikan LLM.
3. **Permukaan Tool Read-Only & Urutan Penegakan 8 Langkah (`tool-policy-design.md`):**
   - Hanya 4 tool kanonik (`get_service_metrics`, `search_error_logs`, `get_trace_summary`, `get_service_dependencies`) yang dipublikasikan secara default.
   - Semua skema request menerapkan `"additionalProperties": false`.
   - Setiap respons wajib melewati DLP/redaction gate (`"sanitized": true` pada `tool-result.v1.schema.json`) dan dicatat ke Independent Security Audit Sink (`audit-event.v1.schema.json`) dengan kebijakan *fail-closed*.

---

## 3. Konsekuensi

- **Positif:** Menjamin pemisahan struktural antara investigator dan ground-truth serta memblokir eskalasi hak akses berbasis prompt injection bahkan sebelum menyentuh backend telemetri/KB.
- **Tindak Lanjut Wajib:** Chapter C08 harus mengeksekusi pengujian integrasi gateway untuk membuktikan penolakan nyata atas tool ilegal, jendela waktu berlebih (`MCP-02`), dan akses lintas-layanan (`SEC-01`).

