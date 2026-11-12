# Identity, Trust Boundaries, and Security Enforcement Design — Chapter C02

- **Run ID:** `c02-20261109T070500Z`
- **Decision References:** `ADR-S03`, `TBD-13`, `D-C02-03`, `D-C02-04`
- **Timestamp (UTC):** `2026-11-09T07:12:00Z` (`2026-11-09T14:12:00+07:00` WIB)
- **Author / Approver (`owner_ref`):** `project-initiator-michael`
- **Check ID:** `C02-CON-003` (`PASS`)

---

## 1. Prinsip Desain Keamanan: Kontrol Jaringan vs Penegakan Otorisasi Nyata

Sesuai Playbook `C02` §5.3 & Step 03, keamanan sistem **tidak boleh** bergantung pada instruksi prompt LLM, penamaan direktori semata, atau asumsi bahwa kontainer lokal saling mempercayai. Desain ini memisahkan secara eksplisit:

1. **Kontrol Tingkat Jaringan & Penyimpanan (*Network & Volume Isolation — Defense-in-Depth Layer 1*):**
   - Membatasi konektivitas soket antar-kontainer melalui segmentasi jaringan bridge Docker Compose (`internal: true` untuk jaringan backend) dan memisahkan *bind mount* sistem berkas sehingga kontainer runtime agent secara fisik **tidak memiliki mount** ke direktori `RESTRICTED_EVAL_ROOT` (Ground Truth & Split Holdout).
2. **Penegakan Otorisasi & Kebijakan Tingkat Aplikasi/Server (*Server-Side Authorization & Policy Enforcement — Authoritative Layer 2*):**
   - Sekalipun dua proses berada pada jaringan yang sama (atau dalam mode pengujian *single-process*), setiap permintaan antar-batas kepercayaan wajib diverifikasi oleh **kode deterministik di sisi server** sebelum kueri dijalankan atau konteks dirakit:
     - Identitas pemanggil (`principal_id`), daftar layanan yang diizinkan (`allowed_services`), environment (`allowed_environments`), dan grup akses dokumen (`allowed_groups`) **diturunkan oleh server dari kredensial/konteks insiden terautentikasi**, **bukan** dibaca dari argumen JSON yang dihasilkan oleh LLM (`SEC-01`, `SEC-02`, `RAG-02`).
     - Filter otorisasi dan masa berlaku dokumen (`status == "approved"`, window `effective_from`/`effective_to`) dieksekusi di dalam query engine Qdrant **sebelum** dokumen menyentuh reranker, context builder, atau LLM (`RAG-01`, `RAG-02`).
     - Sanitasi deterministik (`SEC-03`) dieksekusi pada batas keluar adapter/ingesti **sebelum** teks masuk ke index embedding, prompt LLM, AI observability sink, atau paket ekspor. Kegagalan redactor menghentikan aliran data secara `FAIL_CLOSED`.

---

## 2. Diagram Trust Boundaries & Aliran Data Terkontrol

```mermaid
flowchart TB
  subgraph Z_RESTRICTED["TRUST ZONE 0: RESTRICTED HARNESS & OFFLINE EVALUATION (Host-Isolated / Zero Agent Access)"]
    P_OP["Principal: principal:operator-harness<br/>(Traffic & Fault Harness CLI)"]
    GT_STORE[("RESTRICTED_EVAL_ROOT<br/>Frozen Ground Truth &<br/>Sealed Splits DEV/H-G3/H-G4")]
    P_EVAL["Principal: principal:offline-evaluator<br/>(Post-CLOSED Scoring Harness)"]
    P_OP -->|1. Write Frozen GT Pre-Run| GT_STORE
    GT_STORE -->|10. Read Labels Only After status=CLOSED| P_EVAL
  end

  subgraph Z_SIM["TRUST ZONE 1: SYNTHETIC SERVICE RUNTIME (net-sim-internal)"]
    SVC_CHAIN["5 FastAPI Synthetic Services<br/>(api-gateway, auth, tx, notif, db-dummy)"]
    P_OP -->|2. Seeded Traffic & Signed Fault Hook| SVC_CHAIN
  end

  subgraph Z_OBS_RAG["TRUST ZONE 2: TELEMETRY & KNOWLEDGE BACKENDS (net-backend-isolated, internal: true)"]
    OBS_STORE[("Prometheus / Loki / Tempo<br/>+ Service Catalog")]
    QDR_STORE[("Qdrant Hybrid Index<br/>(Dense + Sparse + ACL Payload)")]
    P_INGEST["Principal: principal:kb-ingestion<br/>(Validated & SEC-03 Redacted Ingest)"]
    SVC_CHAIN -->|3. OTLP Spans, RED Metrics, JSON Logs| OBS_STORE
    P_INGEST -->|Publish Version-Fenced Chunks| QDR_STORE
  end

  subgraph Z_GATEWAY["TRUST ZONE 3: DETERMINISTIC POLICY & SANITIZATION GATEWAY (net-control-plane)"]
    P_GW["Principal: principal:mcp-policy-gateway<br/>(8-Step Policy + Parameterized Query + SEC-03 Redactor)"]
    RAG_GATE["Authorized Retrieval Service<br/>(Server-Derived ACL & Lifecycle Pre-Filter)"]
    P_GW -->|4a. Parameterized Read-Only Query| OBS_STORE
    RAG_GATE -->|4b. Pre-Filtered Hybrid Search| QDR_STORE
  end

  subgraph Z_COORD["TRUST ZONE 4: INVESTIGATION CONTROL PLANE (net-control-plane)"]
    P_INTAKE["Principal: principal:alert-intake<br/>(Signature Check, Normalization & Dedup)"]
    P_COORD["Principal: principal:investigator-coord<br/>(Deterministic State Machine & Validator)"]
    LLM_ROUTER["Controlled Hybrid LLM Router<br/>(Sanitized Untrusted Data Only)"]
    OBS_STORE -->|Signed Alert Webhook| P_INTAKE
    P_INTAKE -->|Normalized incident_id + Trusted Scope| P_COORD
    P_COORD -->|5a. Bounded Tool Call (No Privilege Fields)| P_GW
    P_COORD -->|5b. Scoped Retrieval Call| RAG_GATE
    P_COORD -->|6. SEC-03 Sanitized Evidence Context| LLM_ROUTER
  end

  subgraph Z_EXTERNAL["TRUST ZONE 5: MODEL INFERENCE PROVIDERS (Egress Guarded)"]
    REM_API["Remote Free-Tier LLM API<br/>(Synthetic Sanitized Payload Only)"]
    LOC_OLLAMA["Local Ollama <=3B Fallback<br/>(Host/Container Loopback)"]
    LLM_ROUTER -->|7a. Primary Route ($0 Free-Tier)| REM_API
    LLM_ROUTER -->|7b. Fallback Route (OPS-02)| LOC_OLLAMA
  end

  subgraph Z_GOV["TRUST ZONE 6: HUMAN GOVERNANCE, INDEPENDENT AUDIT & AI OBSERVABILITY"]
    P_REV["Principal: principal:human-reviewer<br/>(Approve / Edit / Reject Exact Hash)"]
    SEC_AUDIT[("Independent Append-Only<br/>Security Audit Ledger (SQLite/JSONL)")]
    AI_SINK[("Sanitized AI Observability Sink<br/>(Langfuse Candidate / Local Trace)")]
    P_COORD -->|8. Validated Dossier (JSON + MD + SHA-256)| P_REV
    P_INTAKE & P_GW & RAG_GATE & P_COORD & P_REV -->|9a. Synchronous Immutable Audit| SEC_AUDIT
    P_COORD & LLM_ROUTER -->|9b. Sanitized Trace Projection| AI_SINK
    P_REV -->|10. Closed Immutable Dossier Ref (status=CLOSED)| P_EVAL
  end
```

---

## 3. Definisi 7 Identitas Principal Lab (`Principal & Entitlement Model`)

Setiap komponen beroperasi di bawah identitas (`principal_id`) yang terpisah dengan kredensial ber-scope khusus (dikonfigurasi melalui variabel lingkungan runtime di luar folder sinkronisasi cloud). Satu identitas **tidak pernah** mewarisi hak akses identitas lain:

1. **`principal:operator-harness` (Operator & Fault Injection Harness):**
   - **Wewenang:** Menjalankan generator trafik ber-seed; memanggil endpoint administrasi fault internal (`/_sim/fault/inject`, `/_sim/fault/reset`) pada 5 layanan simulasi menggunakan token khusus `HARNESS_CONTROL_TOKEN`; menulis record Ground Truth yang dibekukan ke `RESTRICTED_EVAL_ROOT` sebelum `alert_received_at`.
   - **Larangan Mutlak:** Kredensial ini dilarang keras dimuat ke dalam environment container Coordinator, MCP Gateway, RAG Service, maupun LLM Router (`KPI-09`, `RULE-003`).
2. **`principal:alert-intake` (Alert Intake & Correlation Service):**
   - **Wewenang:** Menerima webhook alert yang ditandatangani (`X-Alert-Signature`), memvalidasi `service_id` terhadap `Service Catalog`, melakukan deduplikasi fingerprint (`OPS-01`), dan menerbitkan konteks insiden terpercaya (`incident_id`, `service_id`, `environment`, `allowed_groups`) ke Coordinator.
   - **Larangan Mutlak:** Dilarang membaca `RESTRICTED_EVAL_ROOT`; dilarang menerima `scenario_id` atau petunjuk root-cause di dalam payload alert; dilarang melakukan broad query jika `service_id` tidak terpetakan (`SERVICE_UNMAPPED` $\rightarrow$ *manual triage*).
3. **`principal:investigator-coord` (Durable Investigation Coordinator / Agent Runtime):**
   - **Wewenang:** Mengelola state machine investigasi (`RECEIVED` s/d `HUMAN_REVIEW`), memanggil 4 tool read-only melalui `principal:mcp-policy-gateway`, memanggil retrieval melalui `RAG Service`, memanggil `LLM Router` dengan bukti yang telah disanitasi, menjalankan `Evidence Validator`, dan menulis draf dossier.
   - **Larangan Mutlak:** Tidak memiliki akses jaringan langsung ke Prometheus/Loki/Tempo/Qdrant tanpa melewati Policy Gateway; tidak memiliki akses shell/SQL/PromQL/write/restart; tidak memiliki mount atau izin baca ke `RESTRICTED_EVAL_ROOT` (`AT-008`, `MCP-01`).
4. **`principal:mcp-policy-gateway` (Read-Only MCP Policy Gateway & Adapters):**
   - **Wewenang:** Memverifikasi identitas `principal:investigator-coord`, mengikat *trusted incident scope* dari sesi server-side, mengeksekusi 8 langkah validasi deterministik (termasuk penolakan `WINDOW_EXCEEDED` `MCP-02`), menjalankan kueri read-only berparameter ke Prometheus/Loki/Tempo/Catalog, menerapkan redactor `SEC-03`, dan mencatat audit ke `Independent Security Audit Store`.
   - **Larangan Mutlak:** Tidak memiliki metode HTTP `POST/PUT/DELETE/PATCH` mutasi ke layanan simulasi; tidak memiliki kredensial `HARNESS_CONTROL_TOKEN`; tidak boleh meneruskan kueri string mentah dari model ke backend.
5. **`principal:kb-ingestion` (Knowledge Base Ingestion & Lifecycle Publisher):**
   - **Wewenang:** Membaca korpus dokumen sintetis yang terdaftar di `source-registry.csv`, menjalankan validasi metadata dan redactor `SEC-03`, menghitung dense+sparse vectors, dan mempublikasikan koleksi ber-fence (`index_version`) ke Qdrant.
   - **Larangan Mutlak:** Dilarang mengindeks berkas di dalam `RESTRICTED_EVAL_ROOT`, kueri holdout `H-G3`/`H-G4`, atau berkas tata kelola administratif `E01`/`E02`.
6. **`principal:human-reviewer` (Simulated L1/L2 Human Reviewer):**
   - **Wewenang:** Membaca dossier dan bukti tervalidasi, serta mengirimkan keputusan `approve`, `reject`, atau `edit` (`review-event.v1.schema.json`) yang terikat secara kriptografis pada `target_dossier_version` dan `target_dossier_hash`.
   - **Larangan Mutlak:** Keputusan `approve` dilarang memicu eksekusi tool remediasi otomatis (`HUM-01`); dilarang mengubah rekaman observasi telemetri asli atau mengubah Ground Truth.
7. **`principal:offline-evaluator` (Isolated Offline Evaluator):**
   - **Wewenang:** Berjalan sebagai proses terpisah di luar container runtime agent untuk membaca dossier yang telah berstatus terminal `CLOSED`, memverifikasi `dossier_hash`, lalu melakukan *delayed join* terhadap `RESTRICTED_EVAL_ROOT` (`Ground Truth Registry` dan `Split Registry`) guna menghasilkan `evaluation-result.v1.schema.json`.
   - **Larangan Mutlak:** Dilarang melakukan *join* atau membuka label untuk insiden yang masih aktif (`status != "CLOSED"`); dilarang mengirimkan umpan balik skor/jawaban kembali ke memori agent atau indeks RAG.

---

## 4. Segmentasi Jaringan Docker & Penyimpanan (`Network & Storage Boundary Rules`)

| Zona / Jaringan / Volume | Komponen yang Terhubung | Aturan Isolasi Jaringan & Filesystem | Mekanisme Penegakan Saat Implementasi (`C03`–`C08`) |
|---|---|---|---|
| **`net-sim-internal`** (`internal: true`) | `api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`, `otel-collector` | Terisolasi dari internet eksternal; hanya `api-gateway` yang dapat menerima trafik dari `traffic-generator` | Konfigurasi `networks` Docker Compose dengan `internal: true` pada `C03` |
| **`net-backend-isolated`** (`internal: true`) | `prometheus`, `loki`, `tempo`, `qdrant`, `mcp-policy-gateway`, `rag-gateway-service`, `grafana` | Container `investigator-coord` (atau Dify worker) **tidak** terhubung ke jaringan ini sehingga tidak dapat mem-bypass `mcp-policy-gateway` untuk mengkueri Prometheus/Loki/Tempo/Qdrant secara langsung | Pemisahan network attachment pada `docker-compose.yml` di `C05`/`C07`/`C08` |
| **`net-control-plane`** | `alert-intake`, `investigator-coord`, `mcp-policy-gateway`, `rag-gateway-service`, `human-review-api` | Hanya mengekspos port lokal yang diotorisasi untuk intake/review; komunikasi antar-komponen menggunakan token autentikasi per-principal | Verifikasi header `Authorization: Bearer <scoped-token>` & HMAC di `C08` |
| **`net-model-egress`** | Hanya `llm-router` (dan `ollama` lokal) | Satu-satunya komponen yang memiliki rute keluar ke endpoint HTTPS Free-Tier Cloud LLM API; hanya boleh mengirim payload yang memiliki flag `sanitized == true` dari redactor `SEC-03` | Firewall/network assignment khusus `llm-router` + pemeriksaan pre-condition `assert envelope.sanitized is True` di `C08`/`C13` |
| **`RESTRICTED_EVAL_ROOT`** (Host Filesystem Path di luar Volume Agent) | Hanya `fault-harness` (write append-only) dan `offline-evaluator` (read-only post-`CLOSED`) | **Zero Docker Volume Mount** ke dalam container `investigator-coord`, `mcp-policy-gateway`, `rag-gateway-service`, `qdrant`, atau `dify`. Percobaan baca path oleh agent menghasilkan `FORBIDDEN_SCOPE` / `FileNotFoundError` | Diuji secara aktif pada `C04` dan `C08` (`AT-008`, `C02-CON-003`) |

---

## 5. Verifikasi Tabletop Jalur Terlarang (`C02-CON-003 Verification`)

Lima skenario akses terlarang diuji secara *tabletop* terhadap arsitektur di atas:

1. **Kasus 1 (`Investigator -> Ground Truth Registry`):** `principal:investigator-coord` mencoba membaca berkas Ground Truth atau memanggil tool untuk melihat `scenario_id`.
   - **Titik Penolakan:** (a) Tidak ada tool di dalam allowlist `mcp-policy-gateway` yang membaca GT (`TOOL_NOT_ALLOWED`); (b) Container investigator tidak memiliki mount volume ke `RESTRICTED_EVAL_ROOT`; (c) `runtime-manifest.v1.schema.json` tidak memuat field `scenario_id`/`expected_root_cause`. **Hasil: DITOLAK SEBELUM DISPATCH (`PASS`).**
2. **Kasus 2 (`Investigator -> Fault Harness Control Endpoint`):** Model mencoba memanggil `/_sim/fault/reset` atau tool `restart_service`.
   - **Titik Penolakan:** (a) Tool `restart_service` tidak terdaftar di `mcp-policy-gateway` (`TOOL_NOT_ALLOWED`, `MCP-01`); (b) Container investigator/gateway tidak memiliki `HARNESS_CONTROL_TOKEN` (`UNAUTHENTICATED`/`FORBIDDEN_SCOPE`). **Hasil: DITOLAK SEBELUM DISPATCH (`PASS`).**
3. **Kasus 3 (`Cross-Service / Cross-Environment Restricted SOP Access — SEC-01 & RAG-02`):** Insiden terjadi pada `transaction-service` (`env=lab`), namun kueri mencoba mengambil SOP `restricted` milik `auth-service` atau `env=prod-sim`.
   - **Titik Penolakan:** `RAG Service` mengabaikan klaim grup dari body request dan menurunkan filter wajib `must: [{key: "service_id", match: "transaction-service"}, {key: "environment", match: "lab"}, {key: "allowed_groups", match: <server_derived_groups>}]` langsung pada query Qdrant sebelum pencocokan vektor dan sebelum reranker/LLM. **Hasil: DOKUMEN TIDAK TERAMBIL & TIDAK MASUK CACHE/LOG (`PASS`).**
4. **Kasus 4 (`Forged Privilege Groups in Tool Arguments — SEC-02`):** Prompt injection di dalam log memicu LLM mengirimkan `"allowed_groups": ["admin"]` atau `"raw_query": " {job=~\".*\"}"` pada argumen `get_service_metrics`.
   - **Titik Penolakan:** (a) JSON Schema `metrics-request.v1.schema.json` menetapkan `additionalProperties: false` sehingga request langsung ditolak pada langkah validasi skema (`SCHEMA_INVALID`); (b) Sekalipun skema dilewati, Gateway menurunkan `allowed_groups` murni dari token sesi server-side. **Hasil: DITOLAK DENGAN `SCHEMA_INVALID` + AUDIT RECORD (`PASS`).**
5. **Kasus 5 (`Raw Unsanitized Synthetic Secret/PII Fixture -> External LLM / AI Trace — SEC-03`):** Baris log mengandung token JWT dummy atau nomor kartu sintetis dan redactor mengalami kegagalan regex/exception.
   - **Titik Penolakan:** Kebijakan Gateway & Ingestion menetapkan perilaku `FAIL_CLOSED`: ketika redactor gagal atau menghasilkan `sanitized=false`, payload diblokir total (`error_code="REDACTION_FAILED"`), event keamanan ditulis ke `Independent Security Audit Store`, dan tidak ada 1 byte pun payload mentah yang dikirim ke LLM eksternal maupun Langfuse. **Hasil: DIBLOKIR `FAIL_CLOSED` (`PASS`).**

