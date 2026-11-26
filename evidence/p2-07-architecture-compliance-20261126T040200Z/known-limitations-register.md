# Known Limitations & Enterprise Gap Register (`Q4`)
## AI Agentic SRE & Hybrid RAG Investigation Engine — PoC Release Candidate Baseline

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **PoC Readiness Status:** **`CONDITIONAL GO`** (Concept Feasibility & Mechanistic Proof Approved for Controlled Phase 5 Study under `CAP-01`–`CAP-05`)
- **Production Banking Readiness:** **`NOT ESTABLISHED`**

---

## 1. Non-Negotiable Boundary Statement

This repository implements a **100%-synthetic, isolated local Proof of Concept (PoC)**. Passing automated tests, live local Docker scenarios (`SC-01`–`SC-14`), and Gate `G4` (`CONDITIONAL GO`) **do NOT establish**:
- Production banking operational readiness or high availability (`HA/DR`).
- Compliance with Indonesian banking/privacy regulations (`UU PDP No. 27/2022`, `POJK 11/POJK.03/2022`, `ISO/IEC 27001`, `PCI-DSS`).
- Cryptographically authenticated enterprise reviewer identity (`SSO`/`OIDC`/`RBAC`).
- Validated generalization to real bank telemetry, multi-root incident storms, or uncurated enterprise runbooks.

---

## 2. Active PoC Architectural & Empirical Limitations

| ID | Domain | Verified Current Behavior | Why It Matters | Required Phase 5 Action (`CAP`) |
|---|---|---|---|---|
| **`LIM-01`** (`CAP-01`) | Multi-Root Correlation (`SC-08`, `KPI-02`) | `DependencyCorrelator` isolates the primary root cause (`auth-service` `1.0`) during concurrent independent incidents (`SC-08`), but misses the simultaneous independent `notification-service` queue lag (`all_causes = 0.0`, `KPI-02 = 0.0` on `H-G4` `N=1`). | Real banking incidents frequently co-occur or overlap temporally without sharing a call-graph edge. | Implement multi-root temporal/topological clustering before staging gate (`CAP-01`). |
| **`LIM-02`** (`CAP-02`, `FIND-P207-03`) | Hybrid RAG Dense Embeddings & Cross-Service Docs (`KPI-05`) | (a) `sentence-transformers` / `fastembed` are not installed in `requirements.txt`/`.venv`, so `MultilingualDenseEmbedder` runs `deterministic_local_384d` (TF-IDF + bilingual synonym map + 384-d Gaussian projection) rather than neural transformer weights. (b) Strict single-service `RAG-02` filtering excludes `ARCH-SIM-ECOSYSTEM.md` on `QRY-HLD-012` (`H-G4` Hit@5 = `83.33%` vs `>=90%` candidate target). | Offline projection works well on 71 curated chunks (`100%` DEV, `83.33%` H-G4), but cannot substitute for true neural multilingual embeddings on large noisy corpora. | Pin & benchmark neural embeddings offline and introduce controlled `shared-architecture` taxonomy (`CAP-02`). |
| **`LIM-03`** (`CAP-03`, `TBD-08`) | Holdout Sample Size & Calibration | Sealed holdout splits contain `N=2` replays / `6` queries (`H-G3`) and `N=1` replay / `6` queries (`H-G4`), below proposal targets (`30–50` replays, `100–200` queries). Confidence scores in `[0.05, 0.85]` are deterministic heuristics (`is_calibrated_probability = False`); `evaluator/calibration.py` is `EXPLORATORY ONLY`. | Small holdout denominators create high variance and cannot prove statistical reliability. | Expand staging holdout benchmark to `30–50` replays and `100–200` queries (`CAP-03`). |
| **`LIM-04`** (`CAP-04`, `C19-DEF-005`) | Self-Evaluated Reviewer Baseline (`KPI-06`, `KPI-08`) | Shadow pilot acceptance (`85.71%` on `N=7` DEV) and manual timing reduction (`-88.23%`) carry `SELF_EVALUATED_DEVELOPER_LABELS`; `external_bank_sme_validated = false`. | Developer self-scoring cannot replace blind evaluation by independent L1/L2 bank SRE operators. | Conduct blinded crossover evaluation with independent SRE practitioners (`CAP-04`). |
| **`LIM-05`** (`FIND-P207-08`) | Observability Protocol Facades | `prometheus`, `loki`, `tempo`, and `otel-collector` containers run lightweight FastAPI in-memory facades (`observability/backends.py`), and Alertmanager is omitted (`observability/alerts.py`). (`postgres:16-alpine`, `rabbitmq:3.13`, and `grafana:11.2.0` are real upstream images). | Keeps 12-container footprint at `~819 MiB` RAM on a 16 GiB laptop, but lacks persistent TSDB/log retention and PromQL/LogQL full parser coverage. | Integrate against real staging Prometheus/Loki/Tempo/Alertmanager (`CAP-05` Pillar 3). |
| **`LIM-06`** (`FIND-P207-10`, `P0-02`) | Caller-Asserted Reviewer Identity & Crash Window | CLI/TUI reviewer identity (`--reviewer-ref`) defaults to caller-asserted PoC mode (`POC_CALLER_ASSERTED_UNAUTHENTICATED`). JSONL audit uses a single-host file lock, and an OS `SIGKILL` micro-window exists between JSONL audit append and SQLite transaction commit (detectable via `reconcile_review_audit()`). | Unauthenticated local flags and local file locks are insufficient for multi-operator enterprise non-repudiation. | Integrate enterprise OIDC/AD SSO + RBAC and transactional/WORM audit storage (`CAP-05` Pillar 2). |
| **`LIM-07`** (`FIND-P207-09`) | External Free-Tier LLM Data Policy | `OpenRouterProvider` (`orchestrator/llm_provider.py:343`) sets `"data_collection": "allow"` as required by OpenRouter `:free` models under the `$0` PoC budget cap. | Strictly safe ONLY for 100%-synthetic redacted lab payloads; unacceptable for real bank telemetry. | Mandate on-premise or private-VPC zero-data-retention LLM endpoints + UU PDP / POJK DPIA (`CAP-05` Pillar 4). |
| **`LIM-08`** (`FIND-P207-04`, `05`, `06`, `07`) | Post-G4 Operational Coupling & Packaging Nuances | (a) `LiveAlertWatcher` polls `/api/v1/alerts` directly rather than routing through `AlertIntakeService`; (b) 2 Docker networks + host Python consolidation instead of 5 container networks; (c) `LLMInvestigator.generate()` uses `asyncio.run()` requiring `asyncio.to_thread` in async loops; (d) `requirements.txt` uses `>=` specifiers rather than an exact lockfile; (e) `Dockerfile` runs as default container user. | Manageable in single-host PoC lab, but requires cleanup before multi-service staging deployment. | Route watcher via `AlertIntakeService`, pin `requirements.lock`, enforce Kubernetes NetworkPolicies, and add non-root `USER` in `Dockerfile` (`CAP-05` Pillar 5). |
