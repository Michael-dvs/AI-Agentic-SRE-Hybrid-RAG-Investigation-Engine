# C02 Step 10 — Kontrak Operasional, Observability Internal, Retensi, dan Rollback

> **Evidence Path:** `evidence/c02-20261109T070500Z/C02/plans/operations-contract.md`  
> **Chapter:** C02 — Architecture, Contracts, and Evaluation Design (Step 10)  
> **Status:** `SPECIFIED` (Kontrak operasional untuk implementasi C03–C20; angka batas kuota/retensi runtime dikunci via `ADR-S05` & `ADR-S06`)

---

## 1. Kontrak Health, Liveness, dan Readiness Antar-Komponen

Setiap komponen kontainer pada arsitektur simulasi wajib memisahkan status **Liveness** (proses hidup) dari **Readiness** (siap melayani kontrak dengan dependensi dan kebijakan yang sah):

| Komponen | Endpoint / Probe | Syarat Liveness (`200 OK`) | Syarat Readiness (`200 OK`) | Perilaku Saat Tidak Siap (`503`) |
|---|---|---|---|---|
| **FastAPI Synthetic Services (`CMP-SIM-01`)** | `GET /health/live`, `GET /health/ready` | Event loop Python responsif; mengembalikan `service_id` & `build_version` tanpa dump env/rahasia. | Konfigurasi katalog termuat, OTel exporter siap, dan dependensi wajib terjangkau (kecuali sedang diuji oleh fault harness). | Mengembalikan kode alasan terstruktur (`DEPENDENCY_UNAVAILABLE` / `CONFIG_MISSING`); **tidak** memicu auto-restart oleh agent. |
| **MCP Read-Only Gateway (`CMP-INV-04`)** | `GET /health/live`, `GET /health/ready` | Proses gateway hidup. | **Fail-Closed Policy Check:** `service-catalog`, `source-registry`, `policy_version` (termasuk batas window/points `ADR-S05`), dan koneksi ke Independent Audit Sink (`CMP-GOV-02`) **wajib aktif**. | Menolak semua pemanggilan tool (`status: "rejected"`) jika kebijakan atau audit sink belum siap (`RULE-02`, `NFR-SEC-004`). |
| **Retrieval Adapter (`CMP-KNOW-05`)** | `GET /health/live`, `GET /health/ready` | Proses adapter hidup. | Koleksi Qdrant terjangkau, alias `kb_active_alias` menunjuk ke `index_version` yang valid, dan filter otorisasi server aktif. | Mengembalikan `status: "unavailable"`, `gap_reason: "RETRIEVAL_UNAVAILABLE"`. |
| **Workflow Coordinator (`CMP-INV-03`)** | `GET /health/live`, `GET /health/ready` | Proses koordinator hidup. | State store SQLite/PostgreSQL siap, skema kontrak termuat, dan antrean intake terhubung. | Menahan penerimaan alert baru atau mengarahkan alert ke `MANUAL_TRIAGE_REQUIRED`. |

---

## 2. Hook Observability Operasional Internal (Self-Monitoring Hooks)

Selain telemetri layanan sintetis (`TB-01`), control plane (`TB-04`) dan knowledge layer (`TB-03`) wajib mengekspor metrik operasional internal berikut untuk dievaluasi pada C08, C15, dan C20:

| Kategori Hook | Nama Metrik Internal (Kandidat) | Tujuan & Konsumen |
|---|---|---|
| **Index & Knowledge Lag** | `sre_kb_active_index_version_info`, `sre_kb_publish_duration_ms`, `sre_kb_stale_filter_rejections_total` | Memantau sinkronisasi alias Qdrant dan jumlah chunk `obsolete`/`restricted` yang ditahan filter (`C06`–`C07`). |
| **Intake & Queue Backlog** | `sre_intake_alerts_received_total`, `sre_intake_alerts_deduplicated_total`, `sre_workflow_active_incidents_gauge` | Membuktikan ketahanan terhadap alert storm 100 duplikat (`OPS-01`, `SC-12`) dan mendeteksi penumpukan antrean. |
| **MCP Gateway & Policy Enforcement** | `sre_mcp_tool_requests_total{tool,status,error_code}`, `sre_mcp_redaction_events_total{outcome}`, `sre_mcp_latency_ms` | Mengukur proporsi penolakan guardrail (`MCP-01`, `MCP-02`, `SEC-03`), latensi adapter, dan kegagalan backend (`EV-02`). |
| **LLM Router & Token/Quota Budget** | `sre_llm_requests_total{tier,outcome}`, `sre_llm_tokens_used_total{tier,type}`, `sre_llm_fallback_activations_total{reason}` | Memantau pemakaian kuota free-tier remote, frekuensi fallback ke model lokal/manual (`OPS-02`), dan kepatuhan anggaran `$0.00`. |
| **Container Resource Footprint** | `container_memory_working_set_bytes` / `docker stats` snapshot | Memastikan total RSS di bawah plafon **8 GiB Docker Lab** pada Mac 16 GB Apple Silicon. |

---

## 3. Tanggung Jawab Retensi, Penghapusan, Backup, dan Rollback

1. **Pemisahan Penyimpanan & Retensi (`ADR-S05`, `ADR-S06`):**
   - **Telemetri Simulasi (Prometheus/Loki/Tempo):** Bersifat *ephemeral lab data*. Dapat dibersihkan atau di-reset antar-batch eksperimen setelah ringkasan bukti dan snapshot run disimpan, guna menjaga penggunaan disk di bawah anggaran **15 GiB**.
   - **Independent Security Audit Sink (`CMP-GOV-02`) & Closed Dossiers (`CMP-INV-08`):** Bersifat *immutable append-only* selama siklus hidup pengujian PoC. Dilarang dihapus oleh skrip reset fault harness.
   - **Ground-Truth & Split Registry (`TB-05`):** Disimpan di volume terpisah (`restricted/gt-registry/`) dengan izin baca khusus evaluator; di-backup melalui snapshot ber-checksum SHA-256 sebelum eksekusi Gate G3 dan G4.
2. **Prosedur Reset & Rollback Eksperimen (`C03`/`C04`):**
   - Setiap skenario fault injection wajib memiliki perintah `reset` deterministik yang mengembalikan konfigurasi layanan sintetis ke baseline sehat (`SC-01`), mengosongkan antrean duplikat sementara, dan memverifikasi `/health/ready` sebelum run berikutnya dimulai.
   - Rollback perubahan kontrak/kebijakan wajib mengembalikan tuple `(policy_version, tool_schema_version, kb_index_version)` secara serentak dan mencatat event rollback di security audit log.

