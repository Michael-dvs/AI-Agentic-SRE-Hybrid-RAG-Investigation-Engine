# AI Agentic SRE & Hybrid RAG Investigation Engine — Simulation PoC

> **Status Proyek:** **SELESAI (Fase 1 s/d Fase 4 — Chapter `C01` s/d `C24`)**  
> **Keputusan Resmi Gate G4:** **`CONDITIONAL GO`** (*Concept Feasibility Approved with Corrective Action Plan `CAP-01` s/d `CAP-05`*)  
> **Test Suite:** **540/540 Automated Tests Passed** (`pytest -v`)  
> **Panduan Lengkap:** Silakan baca [Handbook Operasional & Panduan Penggunaan Tools](docs/HANDBOOK_OPERASIONAL.md) untuk instruksi mendalam.  
> **Prinsip Keselamatan Utama:** Seluruh layanan, akun, transaksi, log, dan skenario adalah **100% sintetis**. Agen investigasi beroperasi secara ketat melalui **Read-Only Authenticated Policy Gateway (`KPI-09 = 0`)** tanpa akses ke Ground Truth (`KPI-10 = 0`) dan tanpa auto-remediation (`HUM-01`).

---

## 1. Arsitektur Sistem Maket Digital

Maket digital ini mensimulasikan lingkungan microservices enterprise perbankan skala kecil yang terisolasi:

```mermaid
flowchart TD
    subgraph SimulationLab["Simulated Microservices Lab (C03-C05)"]
        GW["api-gateway"] --> AUTH["auth-service"]
        GW --> TX["transaction-service"]
        TX --> LEDGER["ledger-service"] --> PG[("PostgreSQL")]
        TX --> RMQ[("RabbitMQ")] --> NOTIF["notification-service"]
        FH["Fault Harness (SC-01..SC-14)"] -. Injeksi Terkendali .-> SimulationLab
    end

    subgraph Observability["Telemetry & Service Catalog (C05)"]
        PROM[("Prometheus (RED Metrics)")]
        LOKI[("Loki (Structured Logs)")]
        TEMPO[("Tempo (Distributed Traces)")]
        CATALOG["Service Catalog & Topology Graph"]
    end

    SimulationLab --> Observability

    subgraph Phase2Control["Controlled Integration Pipeline (Phase 2: C09-C12)"]
        ALERTS["Alert Ingestion & Signed Webhook (C05/C10)"] --> INTAKE["Alert Intake & Dedup Queue (C10)"]
        INTAKE --> CORR["Dependency Impact Correlator (C10)"]
        CORR --> ORCH["Deterministic Investigation State Machine (C11)"]
        
        ORCH --> SEC_GW["Authenticated Policy Gateway (C08/C09)"]
        SEC_GW --> ADAPTERS["Read-Only Telemetry Adapters (C09)"]
        ADAPTERS --> Observability
        SEC_GW --> RAG["Hybrid RAG Service (C06/C07)"]
        
        ORCH --> DOSSIER["Investigation Dossier Generator (C12)"]
        DOSSIER --> REVIEW["Authorized Human Review Gate (HUM-01)"]
    end
```

---

## 2. Struktur Direktori Repositori

```text
.
├── AGENTS.md                  # Panduan tata kelola, aturan keselamatan, dan acceptance test
├── BRD_AI_Agentic_SRE_...md   # Business Requirements Document (BRD) v1.0
├── docker-compose.yml         # Orkestrasi 5 microservices + Postgres + RabbitMQ + Telemetri
├── docs/                      # Master Roadmap, Document Manifest, RTM, Decisions (ADR), & Gates
│   ├── decisions/             # Architecture Decision Records (ADR-S01 s/d S08, ADR-TBD05)
│   ├── gates/                 # Gate Specifications & Approval Records (G1-FOUNDATION-GATE.md)
│   └── roadmap/               # Playbook chapter per fase (C01 s/d C24)
├── evidence/                  # Paket bukti empiris per run ID (E01 s/d E11)
├── fault_harness/             # Modul injeksi gangguan reversibel (SC-01 s/d SC-14)
├── gateway/                   # Authenticated Policy Gateway, Redaktor SEC-03, Audit Trail
│   └── adapters/              # Read-only Telemetry Adapters (Prometheus, Loki, Tempo, Catalog, APM)
├── knowledge_base/            # Korpus pengetahuan sintetis, chunking, & Hybrid RAG (BM25 + Dense LSA)
├── observability/             # Konfigurasi OTel Collector, Prometheus, Loki, Tempo, & Service Catalog
├── orchestrator/              # Durable State Machine 9-status, SQLite Store, Resilience Controller
├── services/                  # Implementasi 5 microservices FastAPI sintetis & Alert Intake
│   └── alert_intake/          # Ingestion alert, fingerprint deduplicator, & dependency correlation
├── tests/                     # Suite pengujian otomatis komprehensif pytest
└── traffic/                   # Generator trafik transaksi deterministik ber-seed
```

---

## 3. Prasyarat & Menjalankan Lingkungan Lab

### Prasyarat
- macOS Apple Silicon (`arm64`) atau Linux x86_64
- Docker Desktop + Docker Compose v2 aktif
- Python 3.12+

### Menjalankan Stack Microservices Lab
```bash
# Menyalakan seluruh container lab:
docker compose up -d --build --wait

# Menjalankan generator trafik normal (seed 20261109):
python3 -m traffic.generator --target-url http://127.0.0.1:18080 --profile normal --seed 20261109
```

### Menjalankan Rangkaian Pengujian Otomatis
```bash
# Menjalankan seluruh test suite repository (540 tests passed):
pytest -v

# Menjalankan investigasi dan review console (TUI):
python3 scripts/sre_dashboard.py

# Menjalankan verifikasi clean replay (AT-013 & KPI-13):
python3 scripts/run_c22_clean_replay.py --mode deterministic_baseline
```

---

## 4. Invarian Keselamatan & Batasan Repositori

1. **Zero-Mutation (`KPI-09 = 0` / `MCP-01`, `AT-005`):**  
   Investigator hanya memiliki akses observasi *read-only*. Upaya aksi mutasi (`write`, `restart`, `deploy`, `scale`, `exec`, `shell`, `SQL`) ditolak 100% oleh Gateway.
2. **Ground Truth Isolation (`KPI-10 = 0` / `RULE-002`, `AT-008`):**  
   Direktori `restricted/` yang memuat dataset holdout dan ground truth diisolasi penuh dari runtime agen, image Docker, dan indeks RAG.
3. **Deterministic State Progression (`FR-AGT-001` / `AT-004`):**  
   Setiap alur investigasi wajib melewati 9 status berurutan secara persisten di SQLite:  
   `RECEIVED` $\rightarrow$ `CORRELATED` $\rightarrow$ `TRIAGED` $\rightarrow$ `EVIDENCE_COLLECTED` $\rightarrow$ `RETRIEVED` $\rightarrow$ `HYPOTHESES` $\rightarrow$ `VALIDATED` $\rightarrow$ `DRAFTED` $\rightarrow$ `HUMAN_REVIEW`.
4. **Honest Uncertainty (`RULE-006` / `EV-01`, `EV-02`):**  
   Jika backend telemetri mati (`SC-09`) atau bukti saling bertentangan, sistem wajib menetapkan status `INCONCLUSIVE` atau `PARTIAL` secara jujur tanpa rekayasa data.
5. **Human-in-the-Loop (`HUM-01`):**  
   Setiap rekomendasi investigasi wajib melalui persetujuan manusia. Persetujuan dossier tidak pernah mengeksekusi remediasi otomatis.
