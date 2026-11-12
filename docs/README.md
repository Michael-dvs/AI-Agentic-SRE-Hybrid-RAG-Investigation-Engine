# Documentation Index — AI Agentic SRE & Hybrid RAG Investigation Engine (Simulation PoC)

Selamat datang di pusat dokumentasi proyek **AI Agentic SRE & Hybrid RAG Investigation Engine — Scaled-Down Simulation Proof of Concept (PoC)**.

> **Peringatan Status:** Keberadaan dokumen arsitektur dan *implementation roadmap* di dalam direktori ini menunjukkan **kesiapan panduan perencanaan**, **bukan** bukti bahwa kode aplikasi telah dibangun, pengujian penerimaan runtime (`AT-001`–`AT-017` / Lampiran A Proposal) telah dijalankan, atau Gate `G1`–`G4` telah lulus. Saat ini bukti eksekusi yang tersedia adalah tata kelola inisiasi **Gate `G0`** (`C01`) di [`../evidence/c01-20261109T043813Z/C01/`](../evidence/c01-20261109T043813Z/C01/) serta kualifikasi offline arsitektur & 20 kontrak JSON Schema (`C02`, `C02-CON-001`–`014` `PASS`) di [`../evidence/c02-20261109T070500Z/C02/`](../evidence/c02-20261109T070500Z/C02/).

---

## 1. Dokumen Acuan Utama & Kontrol Proyek

| Dokumen | Lokasi | Peran Utama |
|---|---|---|
| **Pedoman Agen (`AGENTS.md`)** | [`../AGENTS.md`](../AGENTS.md) | Aturan keselamatan proyek, batas simulasi *synthetic-only*, larangan *write/auto-remediation*, dan standar kerja. |
| **BRD Simulasi PoC v1.0** | [`../BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md`](../BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md) | Baseline 88 kebutuhan (`16 BR`, `40 FR`, `12 RULE`, `20 NFR`), 14 skenario (`SC-01`–`SC-14`), 14 KPI, dan `AT-001`–`AT-017`. |
| **Proposal Teknis Revisi 2.0** | [`../Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx`](../Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx) | Referensi arsitektur asli, kontrol keamanan MCP/RAG, empat fase, Gate `G0`–`G4`, dan 12 test Lampiran A. |
| **Master Implementation Roadmap (`C00`)** | [`roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md`](roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md) | Urutan 24 chapter (`C01`–`C24`), peta dependensi, penempatan Gate `G0`–`G4`, dan register keputusan `TBD`/`ADR`. |
| **Document Manifest** | [`roadmap/DOCUMENT-MANIFEST.md`](roadmap/DOCUMENT-MANIFEST.md) | Inventaris seluruh dokumen, pemisahan *Documentation Status* vs *Implementation Status*, dan relasi gate. |
| **Requirements Traceability Matrix (RTM)** | [`roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md`](roadmap/REQUIREMENTS-TRACEABILITY-MATRIX.md) | Pemetaan lengkap seluruh requirement dan test ID ke chapter pembangun (*build owner*), penguji (*test owner*), dan status bukti. |

---

## 2. Navigasi Implementation Roadmap per Fase (`C01`–`C24`)

### Phase 1 — Foundation ([`roadmap/phase-1-foundation/`](roadmap/phase-1-foundation/))
Fokus: Penetapan scope & Gate `G0`, kontrak arsitektur & skema, layanan simulasi & trafik sintetis, *fault harness* & isolasi *ground truth*, pipeline telemetri & *service catalog*, korpus pengetahuan sintetis, baseline *Hybrid RAG*, serta *Authenticated Policy Gateway* & Gate `G1`.

- **C01:** [`01-SCOPE-DECISIONS-AND-G0.md`](roadmap/phase-1-foundation/01-SCOPE-DECISIONS-AND-G0.md) — *Scope, Keputusan, dan G0* (**Owner Gate `G0`** — `G0 PASS` di [`../evidence/c01-20261109T043813Z/C01/g0-record.md`](../evidence/c01-20261109T043813Z/C01/g0-record.md))
- **C02:** [`02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md`](roadmap/phase-1-foundation/02-ARCHITECTURE-CONTRACTS-AND-EVALUATION-DESIGN.md) — *Architecture, Contracts, and Evaluation Design* (`C02-CON-001`–`014` `PASS` di [`../evidence/c02-20261109T070500Z/C02/`](../evidence/c02-20261109T070500Z/C02/))
- **C03:** [`03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md`](roadmap/phase-1-foundation/03-LAB-SERVICES-AND-SYNTHETIC-TRAFFIC.md) — *Lab Services and Synthetic Traffic*
- **C04:** [`04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md`](roadmap/phase-1-foundation/04-FAULT-HARNESS-AND-GROUND-TRUTH-ISOLATION.md) — *Fault Harness and Ground Truth Isolation*
- **C05:** [`05-TELEMETRY-AND-SERVICE-CATALOG.md`](roadmap/phase-1-foundation/05-TELEMETRY-AND-SERVICE-CATALOG.md) — *Telemetry and Service Catalog*
- **C06:** [`06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md`](roadmap/phase-1-foundation/06-SYNTHETIC-KNOWLEDGE-AND-INGESTION.md) — *Synthetic Knowledge and Ingestion*
- **C07:** [`07-HYBRID-RETRIEVAL-AND-BASELINES.md`](roadmap/phase-1-foundation/07-HYBRID-RETRIEVAL-AND-BASELINES.md) — *Hybrid Retrieval and Baselines*
- **C08:** [`08-SECURE-GATEWAY-AND-FOUNDATION-G1.md`](roadmap/phase-1-foundation/08-SECURE-GATEWAY-AND-FOUNDATION-G1.md) — *Secure Gateway and Foundation G1* (**Owner Gate `G1`**)

### Phase 2 — Controlled Integration ([`roadmap/phase-2-controlled-integration/`](roadmap/phase-2-controlled-integration/))
Fokus: Adapter telemetri *read-only* ke backend lab, *alert intake* & korelasi ketergantungan (*deduplication* 100 *duplicate alerts*), *durable deterministic workflow*, serta perakitan dossier baseline, *human review* minimum, & *replay* Gate `G2`.

- **C09:** [`09-READ-ONLY-TELEMETRY-ADAPTERS.md`](roadmap/phase-2-controlled-integration/09-READ-ONLY-TELEMETRY-ADAPTERS.md) — *Read-Only Telemetry Adapters*
- **C10:** [`10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md`](roadmap/phase-2-controlled-integration/10-ALERT-INTAKE-AND-DEPENDENCY-CORRELATION.md) — *Alert Intake and Dependency Correlation*
- **C11:** [`11-DURABLE-INVESTIGATION-WORKFLOW.md`](roadmap/phase-2-controlled-integration/11-DURABLE-INVESTIGATION-WORKFLOW.md) — *Durable Investigation Workflow*
- **C12:** [`12-BASELINE-DOSSIER-AND-END-TO-END-G2.md`](roadmap/phase-2-controlled-integration/12-BASELINE-DOSSIER-AND-END-TO-END-G2.md) — *Baseline Dossier and End-to-End G2* (**Owner Gate `G2`**)

### Phase 3 — Reasoning & Observability ([`roadmap/phase-3-reasoning-observability/`](roadmap/phase-3-reasoning-observability/))
Fokus: Integrasi LLM terkendali (dengan pemisahan data *untrusted* & *outage fallback*), validator bukti & ketidakpastian deterministik, observabilitas AI tersanitasi + audit independen + pelacakan biaya, antarmuka *human review* & handover, *offline evaluation harness*, serta pengujian Red-Team, *blind holdout* `H-G3`, & Gate `G3`.

- **C13:** [`13-CONTROLLED-LLM-INVESTIGATOR.md`](roadmap/phase-3-reasoning-observability/13-CONTROLLED-LLM-INVESTIGATOR.md) — *Controlled LLM Investigator*
- **C14:** [`14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md`](roadmap/phase-3-reasoning-observability/14-EVIDENCE-VALIDATION-AND-UNCERTAINTY.md) — *Evidence Validation and Uncertainty*
- **C15:** [`15-AI-OBSERVABILITY-AUDIT-AND-COST.md`](roadmap/phase-3-reasoning-observability/15-AI-OBSERVABILITY-AUDIT-AND-COST.md) — *AI Observability, Audit, and Cost*
- **C16:** [`16-HUMAN-REVIEW-AND-HANDOVER.md`](roadmap/phase-3-reasoning-observability/16-HUMAN-REVIEW-AND-HANDOVER.md) — *Human Review and Handover*
- **C17:** [`17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md`](roadmap/phase-3-reasoning-observability/17-OFFLINE-EVALUATION-AND-UAT-HARNESS.md) — *Offline Evaluation and UAT Harness*
- **C18:** [`18-RED-TEAM-HOLDOUT-AND-G3.md`](roadmap/phase-3-reasoning-observability/18-RED-TEAM-HOLDOUT-AND-G3.md) — *Red-Team, Holdout, and G3* (**Owner Gate `G3`**)

### Phase 4 — Pilot & Hardening ([`roadmap/phase-4-pilot-hardening/`](roadmap/phase-4-pilot-hardening/))
Fokus: *Lab shadow pilot* & pengukuran *matched manual baseline*, pengujian kapasitas/resilience/rollback & pembekuan rilis final, evaluasi *final blind holdout* `H-G4`, serta bab penutup reproduktifitas, analisis kesenjangan enterprise, dan keputusan Gate `G4`.

- **C19:** [`19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md`](roadmap/phase-4-pilot-hardening/19-LAB-SHADOW-PILOT-AND-MANUAL-BASELINE.md) — *Lab Shadow Pilot and Manual Baseline*
- **C20:** [`20-CAPACITY-RESILIENCE-AND-ROLLBACK.md`](roadmap/phase-4-pilot-hardening/20-CAPACITY-RESILIENCE-AND-ROLLBACK.md) — *Capacity, Resilience, and Rollback*
- **C21:** [`21-FINAL-HOLDOUT-AND-BENCHMARK.md`](roadmap/phase-4-pilot-hardening/21-FINAL-HOLDOUT-AND-BENCHMARK.md) — *Final Holdout and Benchmark* (Kontributor bukti benchmark final menuju Gate `G4`)
- **C22:** `22-REPRODUCIBILITY-OPERATIONS-AND-DEMO.md` — *Reproducibility, Operations, and Demo* (`NOT_STARTED — Pending Future Generation`; didefinisikan di [`00-IMPLEMENTATION-MASTER-ROADMAP.md`](roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md))
- **C23:** `23-RISK-AND-ENTERPRISE-GAP-REVIEW.md` — *Risk and Enterprise Gap Review* (`NOT_STARTED — Pending Future Generation`; didefinisikan di [`00-IMPLEMENTATION-MASTER-ROADMAP.md`](roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md))
- **C24:** `24-ACCEPTANCE-AND-FEASIBILITY-DECISION-G4.md` — *Acceptance and Feasibility Decision G4* (**Owner Gate `G4`**; `NOT_STARTED — Pending Future Generation`; didefinisikan di [`00-IMPLEMENTATION-MASTER-ROADMAP.md`](roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md))

---

## 3. Direktori Gate, Keputusan Arsitektur (ADR), Arsitektur, dan Evidence

- **Direktori Gate ([`gates/`](gates/)):** Tempat penyimpanan spesifikasi/rekaman mandiri `G0`–`G4` ketika dieksekusi. Saat ini kriteria setiap gate terdokumentasi di dalam [`roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md`](roadmap/00-IMPLEMENTATION-MASTER-ROADMAP.md) serta chapter pemiliknya (`C01` untuk `G0`, `C08` untuk `G1`, `C12` untuk `G2`, `C18` untuk `G3`, dan `C24` untuk `G4`). Bukti eksekusi aktual Gate `G0` (`PASS`) tersimpan di [`../evidence/c01-20261109T043813Z/C01/g0-record.md`](../evidence/c01-20261109T043813Z/C01/g0-record.md).
- **Direktori Keputusan / ADR ([`decisions/`](decisions/)):** Berisi *Architecture Decision Records* hasil pelaksanaan C02 (`ADR-S01` s/d `ADR-S08`, `ADR-TBD05`, dan `ADR-DC02`). Register keputusan awal Gate `G0` (`TBD-01` s/d `TBD-13`) yang telah disahkan tersimpan di [`../evidence/c01-20261109T043813Z/C01/decision-log.md`](../evidence/c01-20261109T043813Z/C01/decision-log.md).
- **Direktori Arsitektur ([`architecture/`](architecture/)):** Berisi indeks arsitektur dan kontrak [`architecture/README.md`](architecture/README.md) yang merujuk ke paket bukti C02.
- **Direktori Bukti Eksekusi ([`../evidence/`](../evidence/)):** Berisi paket bukti per-run yang tersanitasi (`E01` pada [`../evidence/c01-20261109T043813Z/C01/`](../evidence/c01-20261109T043813Z/C01/) dan `E02` pada [`../evidence/c02-20261109T070500Z/C02/`](../evidence/c02-20261109T070500Z/C02/)).
