# Arsitektur & Kontrak — AI Agentic SRE & Hybrid RAG Investigation Engine (Simulation PoC)

> **Status Baseline:** `C02 DESIGN & CONTRACT BASELINE APPROVED (QUALIFIED OFFLINE)`  
> **Run ID Bukti C02:** `c02-20261109T070500Z`  
> **Lokasi Paket Bukti C02:** [`evidence/c02-20261109T070500Z/C02/`](../../evidence/c02-20261109T070500Z/C02/)  
> **Status Implementasi Aplikasi:** `NOT_STARTED` (Siap memasuki Chapter C03)

---

## 1. Ringkasan Lima Layer Arsitektur & Lima Trust Boundaries

Sistem dirancang sebagai simulasi terisolasi di atas **macOS Apple Silicon (16 GB RAM)** menggunakan **Docker Compose (`linux/arm64`)** dengan plafon memori lab **8 GiB**:

1. **Simulation Layer (`TB-01` / `net_sim`):** 5 layanan sintetis Python 3.12 + FastAPI (`api-gateway`, `auth-service`, `transaction-service`, `notification-service`, `db-dummy`) dan generator trafik ber-seed (`CMP-SIM-01`..`03`).
2. **Observability Layer (`TB-02` / `net_obs`):** OpenTelemetry Collector, Prometheus, Loki, Tempo, Grafana (visualisasi saja), dan Service Catalog (`CMP-OBS-01`..`06`).
3. **Knowledge Layer (`TB-03` / `net_kb`):** Korpus SOP/runbook sintetis, pipeline ingesti & redaction, serta Qdrant-native Hybrid RAG (dense + sparse vectors) dengan pre-filtering hak akses dan masa berlaku dokumen (`CMP-KNOW-01`..`06`).
4. **Investigation Control Plane (`TB-04` / `net_control`):** Alert Intake, Deduplication & Correlation Engine, Durable Workflow Coordinator, MCP Read-Only Gateway (4 tool kanonik), Provider-Independent Hybrid LLM Router (`$0.00`), Evidence Validator, dan Dossier Generator (`CMP-INV-01`..`08`).
5. **Governance & Isolated Evaluation Layer (`TB-05` / `net_eval`):** Human Review Interface, Independent Hash-Chained Security Audit Sink, Sanitized AI Observability Sink, Fault Injection Harness, Restricted Ground-Truth Registry (`restricted/gt-registry/`), dan Post-Closure Offline Evaluator (`CMP-GOV-01`..`05`, `CMP-SIM-04`..`05`).

---

## 2. Indeks Artefak Utama C02 (`evidence/c02-20261109T070500Z/C02/`)

- **Kesiapan & Provenance Sumber (Step 01):**
  - [`readiness-assessment.md`](../../evidence/c02-20261109T070500Z/C02/readiness-assessment.md)
  - [`source-register.md`](../../evidence/c02-20261109T070500Z/C02/source-register.md)
  - [`source-hashes.sha256`](../../evidence/c02-20261109T070500Z/C02/source-hashes.sha256)
- **Spesifikasi Arsitektur & Komponen (Step 02):**
  - [`architecture.md`](../../evidence/c02-20261109T070500Z/C02/architecture.md)
  - [`component-interfaces.csv`](../../evidence/c02-20261109T070500Z/C02/component-interfaces.csv)
  - [`adr-candidates.md`](../../evidence/c02-20261109T070500Z/C02/adr-candidates.md)
- **Keamanan, Identitas, dan Threat Model (Step 03):**
  - [`trust-boundaries.md`](../../evidence/c02-20261109T070500Z/C02/trust-boundaries.md)
  - [`identity-access.csv`](../../evidence/c02-20261109T070500Z/C02/identity-access.csv)
  - [`source-registry.csv`](../../evidence/c02-20261109T070500Z/C02/source-registry.csv)
  - [`threat-model.md`](../../evidence/c02-20261109T070500Z/C02/threat-model.md)
- **Konvensi & 20 Kontrak JSON Schema Draft 2020-12 (Steps 04–09):**
  - [`contract-conventions.md`](../../evidence/c02-20261109T070500Z/C02/contract-conventions.md)
  - [`service-api-design.md`](../../evidence/c02-20261109T070500Z/C02/service-api-design.md)
  - [`tool-policy-design.md`](../../evidence/c02-20261109T070500Z/C02/tool-policy-design.md)
  - [`knowledge-lifecycle.md`](../../evidence/c02-20261109T070500Z/C02/knowledge-lifecycle.md)
  - [`workflow-contract.md`](../../evidence/c02-20261109T070500Z/C02/workflow-contract.md)
  - [`schema-manifest.csv`](../../evidence/c02-20261109T070500Z/C02/schema-manifest.csv) & [`contracts-final.sha256`](../../evidence/c02-20261109T070500Z/C02/contracts-final.sha256)
- **Rencana Evaluasi, Operasional, dan Capability Spike C08 (Steps 09–10):**
  - [`plans/evaluation-protocol.md`](../../evidence/c02-20261109T070500Z/C02/plans/evaluation-protocol.md)
  - [`plans/scenario-oracles.csv`](../../evidence/c02-20261109T070500Z/C02/plans/scenario-oracles.csv)
  - [`plans/quality-and-ci.md`](../../evidence/c02-20261109T070500Z/C02/plans/quality-and-ci.md)
  - [`plans/operations-contract.md`](../../evidence/c02-20261109T070500Z/C02/plans/operations-contract.md)
  - [`plans/c08-orchestrator-spike.md`](../../evidence/c02-20261109T070500Z/C02/plans/c08-orchestrator-spike.md)
- **Bukti Kualifikasi Kontrak Offline & Handover C03 (Steps 11–12):**
  - [`validation-runner.log`](../../evidence/c02-20261109T070500Z/C02/validation-runner.log)
  - [`contract-validation-results.csv`](../../evidence/c02-20261109T070500Z/C02/contract-validation-results.csv)
  - [`contract-coverage.csv`](../../evidence/c02-20261109T070500Z/C02/contract-coverage.csv)
  - [`review-findings.md`](../../evidence/c02-20261109T070500Z/C02/review-findings.md)
  - [`design-approval.md`](../../evidence/c02-20261109T070500Z/C02/design-approval.md)
  - [`handover-to-c03.md`](../../evidence/c02-20261109T070500Z/C02/handover-to-c03.md)

---

## 3. Indeks Architecture Decision Records (`docs/decisions/`)

- [`ADR-S01-service-runtime-and-state-store.md`](../decisions/ADR-S01-service-runtime-and-state-store.md) (`ACCEPTED` untuk Layanan C03 & Kontrak State Store)
- [`ADR-S02-telemetry-backends-and-alert-transport.md`](../decisions/ADR-S02-telemetry-backends-and-alert-transport.md) (`ACCEPTED` untuk Desain C05; Validasi Kapasitas Pending)
- [`ADR-S03-gateway-transport-and-identities.md`](../decisions/ADR-S03-gateway-transport-and-identities.md) (`ACCEPTED` untuk Desain Keamanan; Pembuktian Runtime di C08)
- [`ADR-S04-rag-chunking-fusion-and-reranker.md`](../decisions/ADR-S04-rag-chunking-fusion-and-reranker.md) (`PROPOSED` — Arah Qdrant-Native Dense+Sparse Terpilih; Parameter Dikunci di C06–C08 / G1)
- [`ADR-S05-quotas-deadlines-and-correlation-bounds.md`](../decisions/ADR-S05-quotas-deadlines-and-correlation-bounds.md) (`PROPOSED` — Mekanisme Disetujui; Angka Runtime Dikunci di C08/C10)
- [`ADR-S06-ai-observability-sink-and-buffering.md`](../decisions/ADR-S06-ai-observability-sink-and-buffering.md) (`PROPOSED` — Audit Independen & Kebijakan Hybrid LLM Disetujui; Sink AI Dievaluasi di C08)
- [`ADR-S07-optional-ticket-and-apm-disposition.md`](../decisions/ADR-S07-optional-ticket-and-apm-disposition.md) (`PROPOSED` — Disposisi Fitur Opsional di C08/C16)
- [`ADR-S08-holdout-sizing-and-scoring-rules.md`](../decisions/ADR-S08-holdout-sizing-and-scoring-rules.md) (`PROPOSED` — Isolasi 3-Split & Post-CLOSED Join Disetujui; Ukuran Sampel di G1)
- [`ADR-TBD05-workflow-orchestration-dify-evaluation.md`](../decisions/ADR-TBD05-workflow-orchestration-dify-evaluation.md) (`PROPOSED` — Protokol Capability Spike Dify C08)
- [`ADR-DC02-contract-conventions-and-qualification.md`](../decisions/ADR-DC02-contract-conventions-and-qualification.md) (`ACCEPTED` — `D-C02-01`..`D-C02-06`)

