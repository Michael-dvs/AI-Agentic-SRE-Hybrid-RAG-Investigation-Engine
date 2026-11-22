# Conceptual High Availability & Disaster Recovery Plan (`E23`): `c23-20261122T071432Z`

- **Generated At (UTC):** `2026-11-22T07:14:32.283502Z`
- **Status Label:** **`CONCEPTUAL_TARGET_UNPROVEN_IN_LAB`** *(bukan bukti implementasi HA/DR atau pencapaian SLA produksi)*
- **Related Requirements:** `NFR-009`, `BRD §23`, `RISK-07`, `RISK-11`

## 1. Perbandingan Topologi Lab vs Target Konseptual HA/DR

| Komponen | Baseline Lab (`C01`–`C22`) | Arsitektur Target Konseptual Enterprise (Fase 5+) |
|---|---|---|
| **Orkestrasi & Worker** | Single-process Python + `docker-compose.yml` lokal | Multi-zone Kubernetes (min. 2–3 Availability Zones) dengan stateless worker autoscaling |
| **Workflow & State Store** | `orchestrator_state.db` SQLite lokal | Replicated PostgreSQL cluster (Patroni/Cloud SQL HA) dengan idempotent leasing & PITR |
| **Queue & Dedup Registry** | In-memory `AlertDeduplicator` & single RabbitMQ | HA RabbitMQ / Kafka terklaster + Redis Sentinel/Cluster terdistribusi |
| **Vector DB & Knowledge Index** | In-process Hybrid RAG (20 docs / 71 chunks) | Distributed Qdrant cluster dengan snapshot lintas-zona & blue/green alias rollback |
| **Target Pemulihan (Konseptual)** | Best-effort manual reset (`lab_down.sh` / `fault_reset.sh`) | **Target konseptual:** `RTO < 15 menit`, `RPO < 1 menit` (belum diuji di lab) |

## 2. Langkah Validasi Wajib Sebelum Produksi (Fase 5)
1. Migrasi `WorkflowStateStore` dari SQLite ke PostgreSQL HA dengan uji konkurensi lintas worker.
2. Simulasi chaos/failover multi-zona untuk memverifikasi `RTO < 15 menit` dan `RPO < 1 menit`.
3. Uji restorasi snapshot Vector DB & audit chain hash SHA-256 lintas data center.
