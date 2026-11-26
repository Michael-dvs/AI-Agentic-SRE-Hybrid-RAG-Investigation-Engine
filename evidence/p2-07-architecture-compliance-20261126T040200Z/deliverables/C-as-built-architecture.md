# Deliverable C — As-Built Architecture & Verified System Diagrams
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Authority Baseline:** `AGENTS.md`, `BRD_AI_Agentic_SRE_RAG_Simulation_PoC_v1.0.md`, `Proposal_AI_Agentic_SRE_RAG_Investigation_Engine_Revisi_2.0-2.docx`, `00-IMPLEMENTATION-MASTER-ROADMAP.md`, `ADR-DC02`, `ADR-S01`–`ADR-S08`, `ADR-TBD05`, `C17-evaluation-protocol-owner-decision.md`
- **Verification Basis:** Direct source inspection across all 9 Python packages, live 12-container Docker Compose runtime (`docker compose ps`, `docker stats --no-stream`), Grafana datasource proxy probes, and live `SC-01`–`SC-14` execution.

---

## 1. Component-by-Component As-Built Classification

| # | Architectural Component | Classification | Actual Repository Implementation | Runtime Verification Evidence | Architectural Nuance / Deviation |
|---|---|---|---|---|---|
| 1 | Synthetic banking microservices (overall) | **Implemented and operational** | 5 Python 3.12 / FastAPI services in `services/*/app.py` packaged via `Dockerfile` & `docker-compose.yml` | All 5 containers `Up (healthy)`; `test_c03_compose_live.py` (`4/4 PASS`); live `SC-01`–`SC-14` probes | Exceeds `FR-SIM-001` minimum of 3 interdependent services |
| 2 | API Gateway (`api-gateway`) | **Implemented and operational** | `services/api_gateway/app.py` (`127.0.0.1:18080 -> :8000`) | Live HTTP 200/201/403/500/503 routing, W3C `traceparent`, signed `/_sim/fault/*` control plane | Only service publishing microservice port to host loopback |
| 3 | Authentication service (`auth-service`) | **Implemented and operational** | `services/auth_service/app.py` (internal `:8001`) | Live token validation (`SYNTH-TOKEN-ACTIVE-001`) and `SC-06`/`SC-08` HTTP 403 policy mismatch | Internal `sim_internal_net` + `sim_obs_net` |
| 4 | Transaction service (`transaction-service`) | **Implemented and operational** | `services/transaction_service/app.py` (internal `:8002`) | Live orchestration of auth -> ledger -> RabbitMQ publish; `SC-02` 500 & `SC-04` 503 cascade | Internal network only |
| 5 | Ledger service (`ledger-service`) | **Implemented and operational** | `services/ledger_service/app.py` (internal `:8003`) | Live PostgreSQL double-entry write, idempotency check, `SC-03` slow query, `SC-05` pool exhaustion | Internal network only |
| 6 | Notification service (`notification-service`) | **Implemented and operational** | `services/notification_service/app.py` (internal `:8004`) | Live RabbitMQ consumer + `/stats` backlog telemetry; `SC-07`/`SC-08` queue lag verified | Internal network only |
| 7 | PostgreSQL (`postgres`) | **Implemented and operational** | Real upstream `postgres:16-alpine` container (`sre-sim-postgres`) | Healthy `pg_isready`; real SQL ledger persistence verified across restarts (`test_c03_compose_live.py`) | Strict `sim_internal_net` (`internal: true`) |
| 8 | RabbitMQ (`rabbitmq`) | **Implemented and operational** | Real upstream `rabbitmq:3.13-management-alpine` container (`sre-sim-rabbitmq`) | Healthy AMQP broker; queue `notifications.transaction.completed` + DLQ verified | Strict `sim_internal_net` (`internal: true`) |
| 9 | Synthetic traffic generation | **Implemented and operational** | `traffic/generator.py` (`normal` and `spike` seeded profiles) + `scripts/run_banking_simulator.py` | Seeded reproducibility (`seed=20261109`) verified in `test_c03_services.py`, `E22`, and `test_banking_simulator.py` | 100% synthetic accounts (`SYNTH-ACC-*`) |
| 10 | Controlled fault scenarios `SC-01`–`SC-14` | **Implemented and operational** | `fault_harness/scenarios.py`, `fault_harness/runner.py`, `services/common/fault_control.py` | All 14 scenarios executed live against Docker stack in `P2-07` (`sc01_sc14_live_verification.json`) with clean recovery | Signed `X-Harness-Token` + `principal:fault-harness`; completely excluded from agent tool registry |
| 11 | OpenTelemetry instrumentation | **Implemented and operational (lightweight OTLP JSON)** | `services/common/telemetry.py` + `observability/backends.py` (`otel_collector_app` on `:14318`) | Live W3C `trace_id`/`span_id` propagation, structured JSON logs, RED counters/histograms | Lightweight Python OTLP HTTP/JSON emitter & collector facade per `ADR-S02` (not heavy upstream Java/Go OTel Collector binary) |
| 12 | Prometheus metrics | **Implemented via protocol facade (PoC-approved)** | `observability/backends.py` (`prometheus_app` on `127.0.0.1:19090`) | Live `/api/v1/query`, `/api/v1/query_range`, `/api/v1/alerts`, and Grafana PromQL proxy HTTP 200 | Custom FastAPI PromQL-compatible facade (`ADR-S02`), not upstream Prometheus TSDB binary |
| 13 | Loki logs | **Implemented via protocol facade (PoC-approved)** | `observability/backends.py` (`loki_app` on `127.0.0.1:13100`) | Live `/loki/api/v1/query_range` and Grafana Loki proxy HTTP 200 | Custom FastAPI LogQL-compatible facade (`ADR-S02`), not upstream Grafana Loki binary |
| 14 | Tempo traces | **Implemented via protocol facade (PoC-approved)** | `observability/backends.py` (`tempo_app` on `127.0.0.1:13200`) | Live `/api/traces/{trace_id}`, `/api/search`, `/_sim/outage` (`SC-09`), and Grafana Tempo proxy HTTP 200 | Custom FastAPI Tempo-compatible facade (`ADR-S02`), not upstream Grafana Tempo binary |
| 15 | Grafana dashboards | **Implemented and operational** | Real upstream `grafana/grafana:11.2.0` (`127.0.0.1:13000`) with provisioned datasources & `sre-sim-overview-v1` | Live `/api/health` (200), `/api/datasources` (3 datasources), `/api/search` (200), and live datasource proxy queries all HTTP 200 | Genuine upstream Grafana container |
| 16 | Alertmanager / alerting mechanism | **Replaced via PoC-approved embedded alert evaluator** | `observability/alerts.py` + `observability/alert-rules.yml` inside `prometheus_app` + `services/alert_intake/` | Signed HMAC webhook (`X-Alert-Signature`) & `/api/v1/alerts` verified in `test_c05_*`, `test_c10_*`, and live `P2-07` | No standalone Alertmanager container (`ADR-S02`). Note: `LiveAlertWatcher` (`orchestrator/live_watcher.py`) polls `/api/v1/alerts` directly (`UNAPPROVED COUPLING DEVIATION`, documented in Deliverable O) |
| 17 | Alert deduplication & dependency correlation | **Implemented and operational (single-primary limitation on `SC-08`)** | `services/alert_intake/intake.py`, `dedup.py`, `correlation.py` | `OPS-01` 100->1 duplicate storm (`SC-12`) & `SC-04` cascade attribution (`AT-016`) verified | Concurrent independent faults (`SC-08`) isolate primary fault (`1.0`) but miss secondary root cause (`KPI-02=0.0`, tracked in `CAP-01`) |
| 18 | Deterministic investigation orchestration | **Implemented and operational** | `orchestrator/state_machine.py` (`WorkflowStateStore` SQLite WAL + 9-state `InvestigationStateMachine`), `investigator.py`, `resilience.py` | Sequential 9-state progression, quotas (`<=30` calls), circuit breaker, DLQ, and `DEF-P207-02` metadata persistence verified | Approved Option C (`ADR-TBD05`) replacing Dify |
| 19 | Authorized read-only Policy Gateway | **Implemented and operational** | `gateway/policy.py`, `auth.py`, `config.py`, `sanitizer.py`, `dispatcher.py`, `gateway/adapters/*` | 7 scoped principals, 5 read-only tools (`get_apm_health` explicit `SOURCE_UNAVAILABLE` stub per `ADR-S07`), `KPI-09=0` across all tests & live runs | In-process Python boundary rather than separate network container (`ADR-S03` consolidation nuance) |
| 20 | Hybrid RAG (`BM25 + Dense + RRF + Reranker`) | **Partially implemented (deterministic local dense fallback)** | `knowledge_base/retrieval/{embeddings,engine,prefilter,service}.py` | 4 modes (`lexical_only`, `dense_only`, `hybrid_rrf`, `hybrid_rerank`) verified on 28 DEV (`100%` Hit@5) and 6 H-G4 (`83.33%` Hit@5) | `MultilingualDenseEmbedder` defaults to `deterministic_local_384d` (TF-IDF + bilingual synonyms + 384-d Gaussian projection) because `sentence-transformers` / `fastembed` are NOT installed in `requirements.txt` or `.venv` |
| 21 | Qdrant / retrieval backend | **Replaced through approved ADR** | In-process `RetrievalEngine` (`knowledge_base/retrieval/engine.py`) | Approved in `evidence/c07-20261111T160000Z/C07/retrieval-adr.md` (`RSS ~6.89 MiB`, `P95 ~1.29 ms`) | No Qdrant container or client dependency in repository |
| 22 | SOP lifecycle & applicability validation | **Implemented and operational** | `knowledge_base/ingestion/lifecycle.py`, `knowledge_base/retrieval/prefilter.py`, `orchestrator/verification_plan.py` | Pre-retrieval + post-retrieval `RAG-01` (`obsolete` blocked), `RAG-02` (service/env isolation), `SEC-01` (`allowed_groups` ACL), and `P1-03` availability taxonomy (`KPI-11=0`) | Cross-service shared architecture doc `ARCH-SIM-ECOSYSTEM.md` filtered out on `QRY-HLD-012` (`CAP-02`) |
| 23 | Controlled LLM reasoning | **Implemented and operational (verified via controlled/replay & fallback; live cloud optional)** | `orchestrator/llm_investigator.py`, `llm_provider.py`, `context_builder.py` | Strict JSON output schema, `<UNTRUSTED_OBSERVATION_DATA>` framing, `<think>` rejection, token/latency ledger, live-telemetry RAG-to-LLM delivery verified in `P2-07` | Default `.env` leaves `OPENROUTER_API_KEY` empty (`$0.00` cash cap); `OpenRouterProvider` sets `"data_collection": "allow"` for `:free` tier (`CAP-05`) |
| 24 | Deterministic hypothesis/evidence validation | **Implemented and operational** | `orchestrator/claim_validator_contract.py` (`P0-01` + `C14`), `orchestrator/evidence_lineage.py` (`P1-05`) | Rejects irrelevant/fabricated evidence IDs, enforces `EV-01` contradiction downgrade & `EV-02` trace outage `INCONCLUSIVE`, bans `VERIFIED` (`RULE-007`) | Verified in `test_c14_*`, `test_p1_04_*`, `test_p1_05_*`, `test_p2_07_*` |
| 25 | Evidence-aware confidence scoring | **Implemented and operational** | `orchestrator/confidence.py` (`compute_evidence_confidence`, `rank_hypotheses`) | Bounded `[0.05, 0.85]`, `is_calibrated_probability=False`, duplicate-resistant, order-invariant, SOP weight `0.0` | Calibration (`evaluator/calibration.py`) explicitly labeled `EXPLORATORY ONLY` on small PoC sample |
| 26 | Structured incident dossiers | **Implemented and operational** | `orchestrator/dossier.py` (`DossierSerializer`, `DossierMarkdownRenderer`) + `orchestrator/handover.py` (`HTML` + `JSON` + `MD`) | Schema-valid against frozen `dossier.v1.schema.json`, canonical SHA-256 hash, append-only `vN+1` human revisions | Verified across all 14 live scenarios in `P2-07` |
| 27 | Human Review CLI & terminal dashboard | **Implemented and operational (with `DEF-P207-01` fix)** | `orchestrator/review.py`, `orchestrator/usability_console.py`, `orchestrator/console_view_models.py`, `scripts/sre_dashboard.py`, `scripts/review_console.py` | `APPROVE`, `REJECT`, `CORRECT`, `ESCALATE` atomic SQLite locking, 2-step confirmation modal, `SC-13` fallback review unlocked in `P2-07`, terminal escape stripping | Caller-asserted PoC identity (`sre_reviewer`) — not enterprise SSO/OIDC (`CAP-05`) |
| 28 | Append-only SHA-256 audit logging | **Implemented and operational** | `gateway/audit.py` (`SecurityAuditLogger`) + `observability/audit_chain.py` (`AuditHashChain`) + `reconcile_review_audit()` | Tamper-evident `prev_hash -> event_hash` chains verified across all gateway calls and human reviews; separated from `observability/ai_tracer.py` (`ADR-S06`) | Single-writer file lock; crash window between JSONL append & SQLite commit mitigated via `reconcile_review_audit` |
| 29 | Isolated post-closure offline evaluation | **Implemented and operational** | `evaluator/runner.py` (`join_evaluator`), `evaluator/scorer.py`, `fault_harness/gt_registry.py`, `restricted/` (`0o700`) | Zero runtime AST imports (`85` files checked), symlink traversal blocked, non-`CLOSED` incidents blocked, minimal 4-key join output, `H-G4` seal guard intact | Holdout sample size (`N=2` `H-G3`, `N=1` `H-G4`) below proposal target `30–50` (`TBD-08` / `CAP-03`) |

---

## 2. Verified As-Built Architecture Diagrams

### 2.1 Component Architecture Diagram

```mermaid
flowchart TB
    subgraph SimPlane["Simulation & Fault Plane"]
        TG["Traffic Generator\n(traffic/generator.py)"]
        FH["Fault Harness SC-01..SC-14\n(fault_harness/runner.py)"]
        GW_SVC["api-gateway\n(FastAPI :18080->8000)"]
        AUTH_SVC["auth-service\n(FastAPI :8001)"]
        TX_SVC["transaction-service\n(FastAPI :8002)"]
        LED_SVC["ledger-service\n(FastAPI :8003)"]
        NTF_SVC["notification-service\n(FastAPI :8004)"]
        PG[("PostgreSQL 16\n(sre-sim-postgres)")]
        RMQ[("RabbitMQ 3.13\n(sre-sim-rabbitmq)")]
    end

    subgraph ObsPlane["Observability & Alert Plane"]
        OTEL["OTel Collector Facade\n(:14318->4318)"]
        PROM["Prometheus Facade + Alert Rules\n(:19090->9090)"]
        LOKI["Loki Structured Logs Facade\n(:13100->3100)"]
        TEMPO["Tempo Traces Facade\n(:13200->3200)"]
        GRAF["Grafana 11.2.0\n(:13000->3000)"]
        INTAKE["AlertIntakeService + Dedup + Correlator\n(services/alert_intake/*)"]
    end

    subgraph ControlPlane["Deterministic Agentic Control Plane (Host Python)"]
        SM["9-State Machine & SQLite WAL\n(orchestrator/state_machine.py)"]
        INV["DeterministicInvestigator\n(orchestrator/investigator.py)"]
        PGW["Authenticated PolicyGateway\n(gateway/policy.py + sanitizer.py)"]
        ADP["Read-Only Adapters\n(Metrics, Logs, Traces, Catalog, APM Stub)"]
        KB["Hybrid RAG Engine & Lifecycle\n(BM25 + Local 384-d Dense + RRF)"]
        CTX["SanitizedContextBuilder\n(orchestrator/context_builder.py)"]
        LLM["LLMInvestigator / Provider\n(OpenRouter or Offline Replay/Fallback)"]
        VAL["ClaimValidator & EvidenceLineage\n(P0-01 + P1-05)"]
        CONF["Deterministic ConfidenceScorer\n([0.05, 0.85], RULE-007)"]
        DOS["DossierSerializer & HandoverExporter\n(JSON / MD / HTML)"]
    end

    subgraph HumanEvalPlane["Human Governance, Audit & Offline Evaluation"]
        REV["AuthorizedReviewManager\n(P0-02 Atomic SQLite + Audit)"]
        TUI["Unified SRE TUI & Review CLI\n(sre_dashboard.py / review_console.py)"]
        AUD["SHA-256 Hash-Chained Security & Review Audit\n(gateway/audit.py + audit_chain.py)"]
        EVAL["Offline Evaluator & Scorer\n(evaluator/runner.py + scorer.py)"]
        GT[("Restricted GT & Holdouts\n(restricted/ 0o700)")]
    end

    TG --> GW_SVC
    FH -. "Signed X-Harness-Token" .-> GW_SVC
    FH -. "Freeze GT (principal:fault-harness)" .-> GT
    GW_SVC --> AUTH_SVC
    GW_SVC --> TX_SVC
    TX_SVC --> LED_SVC --> PG
    TX_SVC --> RMQ --> NTF_SVC
    GW_SVC & AUTH_SVC & TX_SVC & LED_SVC & NTF_SVC --> OTEL
    OTEL --> PROM & LOKI & TEMPO
    GRAF --> PROM & LOKI & TEMPO
    PROM --> INTAKE --> INV
    INV <--> SM
    INV --> PGW
    PGW --> ADP --> PROM & LOKI & TEMPO
    PGW --> KB
    PGW --> AUD
    INV --> CTX --> LLM --> VAL --> CONF --> DOS
    DOS --> TUI --> REV
    REV --> SM
    REV --> AUD
    SM -. "Post-CLOSED Only" .-> EVAL
    AUD -. "Trusted Audit Head" .-> EVAL
    GT -. "principal:JoinEvaluator" .-> EVAL
```

### 2.2 Container & Host Deployment Topology (`docker-compose.yml` As-Built)

```mermaid
flowchart LR
    subgraph Host["macOS arm64 Host (Loopback 127.0.0.1 Only)"]
        PY_RT["Host Python .venv Runtime\n(Orchestrator, PolicyGateway, Hybrid RAG,\nTUI/CLI, SQLite orchestrator_state.db)"]
        RESTR["Host Restricted Vault\n(./restricted/ chmod 0o700\nGT Registry + H-G3/H-G4 Holdouts)"]
        subgraph DockerEngine["Docker Compose Stack (12 Healthy Containers, ~819 MiB Total RAM)"]
            subgraph InternalNet["sim_internal_net (internal: true — No External Egress)"]
                C_GW["sre-sim-api-gateway\n127.0.0.1:18080->8000"]
                C_AU["sre-sim-auth-service\n:8001"]
                C_TX["sre-sim-transaction-service\n:8002"]
                C_LD["sre-sim-ledger-service\n:8003"]
                C_NT["sre-sim-notification-service\n:8004"]
                C_PG[("sre-sim-postgres\npostgres:16-alpine :5432")]
                C_MQ[("sre-sim-rabbitmq\nrabbitmq:3.13 :5672")]
            end
            subgraph ObsNet["sim_obs_net (bridge — Loopback Telemetry Ports)"]
                C_OT["sre-sim-otel-collector\n127.0.0.1:14318->4318"]
                C_PR["sre-sim-prometheus\n127.0.0.1:19090->9090"]
                C_LK["sre-sim-loki\n127.0.0.1:13100->3100"]
                C_TM["sre-sim-tempo\n127.0.0.1:13200->3200"]
                C_GR["sre-sim-grafana\n127.0.0.1:13000->3000"]
            end
        end
    end

    C_GW & C_AU & C_TX & C_LD & C_NT --> C_OT
    C_OT --> C_PR & C_LK & C_TM
    C_GR --> C_PR & C_LK & C_TM
    PY_RT -- "Read-Only HTTP Adapters\n127.0.0.1:19090/13100/13200" --> C_PR & C_LK & C_TM
    PY_RT -. "Isolated Offline Join\n(evaluator/runner.py only)" .-> RESTR
```

### 2.3 End-to-End Investigation Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    participant Prom as Prometheus Alert Rules
    participant Intake as AlertIntakeService & Dedup
    participant SM as InvestigationStateMachine (SQLite)
    participant Inv as DeterministicInvestigator
    participant GW as PolicyGateway + Sanitizer
    participant RAG as RetrievalService (KB)
    participant LLM as LLMInvestigator / Fallback
    participant Val as ClaimValidator + ConfidenceScorer
    participant Rev as AuthorizedReviewManager (Human)
    participant Eval as Offline join_evaluator

    Prom->>Intake: Signed alert-event.v1 (HMAC)
    Intake->>Intake: Validate schema, deduplicate (OPS-01), correlate topology
    Intake->>Inv: Admitted correlated incident context
    Inv->>SM: RECEIVED -> CORRELATED -> TRIAGED (service_id, env persisted)
    Inv->>GW: Read-only telemetry calls (Bearer coordinator token, window <=3600s)
    GW-->>Inv: Sanitized metrics, logs, traces, catalog + provenance hashes
    Inv->>SM: -> EVIDENCE_COLLECTED
    Inv->>GW: retrieve_runbook_chunks (service, env, principal ACL, active date)
    GW->>RAG: Pre-filter (RAG-01/02, SEC-01) + BM25/Dense/RRF
    RAG-->>GW: Eligible active citations or honest gap code
    GW-->>Inv: Sanitized citations + sop_availability
    Inv->>SM: -> RETRIEVED
    alt LLM configured & healthy
        Inv->>LLM: SanitizedContextBuilder (<UNTRUSTED_OBSERVATION_DATA>)
        LLM-->>Inv: Schema-valid candidate hypotheses (no tools, no <think>)
    else Offline baseline or LLM timeout (SC-13 / OPS-02)
        Inv->>Inv: Deterministic / ManualFallbackGenerator (status=MANUAL_TRIAGE)
    end
    Inv->>SM: -> HYPOTHESES
    Inv->>Val: Validate relevance, contradictions (EV-01), missing trace (EV-02)
    Val-->>Inv: Capped support_status (never VERIFIED) + score in [0.05, 0.85]
    Inv->>SM: -> VALIDATED -> DRAFTED -> HUMAN_REVIEW
    Rev->>Rev: Human L1/L2 decision (APPROVE / REJECT / CORRECT vN+1 / ESCALATE)
    Rev->>SM: Atomic SQLite review + transition (CLOSED / REJECTED / MANUAL_TRIAGE_REQUIRED)
    Note over SM,Eval: Offline evaluation strictly blocked unless state == CLOSED
    Eval->>SM: Verify CLOSED state + AuditHashChain head + 0o700 symlink-free paths
```

### 2.4 Data-Flow & Multi-Stage Sanitization Diagram

```mermaid
flowchart LR
    RAW_SIM["Synthetic App Logs / Metrics / Spans\n& Raw KB Markdown"] --> ING_SAN["Stage 1: Pre-Ingestion Sanitizer\n(knowledge_base/ingestion/sanitizer.py)\nSEC-03 Redaction before Chunking"]
    RAW_SIM --> GW_SAN["Stage 2: Pre-Sink Gateway Sanitizer\n(gateway/sanitizer.py — FAIL_CLOSED)\nJWT, Bearer, API Key, Password, PAN"]
    ING_SAN --> KB_CHUNKS["71 Hashed KB Chunks\n(content_hash SHA-256)"]
    KB_CHUNKS --> GW_SAN
    GW_SAN --> CTX_BLD["Stage 3: SanitizedContextBuilder\n(Field allowlist + _RESTRICTED regex block\n+ <UNTRUSTED_OBSERVATION_DATA> tags)"]
    CTX_BLD --> MODEL_OUT["Stage 4: Output Boundary Validator\n(Rejects tool keys, mutation verbs,\n<think> CoT, GT markers)"]
    GW_SAN --> AI_TRACE["Sanitized AI Observability Sink\n(observability/ai_tracer.py)"]
    MODEL_OUT --> DOS_OUT["Dossier JSON / MD / HTML\n+ Terminal Escape Sanitizer\n(sanitize_terminal_text)"]
    DOS_OUT --> DLP_SCAN["Stage 5: Multi-Sink DLP & GT Isolation Verifier\n(scripts/dlp_sink_scanner.py + handover.py)"]
```

### 2.5 Security & Trust-Boundary Diagram

```mermaid
flowchart TB
    subgraph TB1["TB-01: Untrusted Synthetic Workload & Telemetry Data"]
        U_SVC["5 Simulated Services + Postgres + RabbitMQ"]
        U_OBS["Prometheus / Loki / Tempo Facades\n(May contain adversarial log payloads SC-11\nor synthetic secrets SEC-03)"]
    end

    subgraph TB2["TB-02: Authenticated Read-Only Policy Gateway"]
        AUTH["Scoped Token Verifier (gateway/auth.py)\nPrincipals: investigation-coordinator, retrieval-worker,\nalert-intake, human-reviewer, fault-harness, evaluator"]
        POL["Deterministic Policy Engine (gateway/policy.py)\n5 Read-Only Tools Only | Window <= 3600s |\nMax Hits <= 500 | Service/Env/ACL Scope"]
        RED["DeterministicSanitizer (FAIL_CLOSED)"]
    end

    subgraph TB3["TB-03: Unprivileged Reasoning Boundary"]
        MOD["Controlled LLM / Deterministic Synthesizer\nZero Tool Access | Zero Shell/SQL | Zero Network Write\nMax Confidence <= 0.85 | Never VERIFIED"]
    end

    subgraph TB4["TB-04: Human Governance Boundary (HUM-01)"]
        HUM["AuthorizedReviewManager + TUI/CLI\nCaller-Asserted PoC Reviewer Identity\nauto_action_triggered == False\nAdministrative Closure != Technical Resolution"]
    end

    subgraph TB5["TB-05: Restricted Ground Truth & Holdout Vault"]
        VLT["restricted/ (chmod 0o700)\nZero AST Imports from Runtime Modules\nPost-CLOSED + Trusted Audit Head Gate"]
    end

    TB1 -- "HTTP Loopback Read-Only" --> TB2
    TB2 -- "Projected & Redacted Context" --> TB3
    TB3 -- "Validated Draft Dossier" --> TB4
    TB4 -. "Closed Dossier + Audit Head" .-> TB5
```

### 2.6 Human Review & Post-Closure Evaluator Isolation Diagram

```mermaid
stateDiagram-v2
    [*] --> HUMAN_REVIEW: Draft Dossier Persisted (v1)\n(PENDING_REVIEW or unreviewed MANUAL_TRIAGE fallback)
    HUMAN_REVIEW --> HUMAN_REVIEW: CORRECT (edit)\nAppends Revision vN+1 (PENDING_REVIEW)\nOriginal AI findings preserved
    HUMAN_REVIEW --> CLOSED: APPROVE\nAdministrative Handover Closure\n(diagnosis_verified=False, auto_action=False)
    HUMAN_REVIEW --> REJECTED: REJECT\nTerminated Rejected\n(Evaluator Join BLOCKED)
    HUMAN_REVIEW --> MANUAL_TRIAGE_REQUIRED: ESCALATE\nlatest_review_event_id recorded\n(Evaluator Join BLOCKED)

    CLOSED --> OFFLINE_JOIN: join_evaluator()\nRequires state==CLOSED + valid AuditHashChain head\n+ split guard (H-G4 sealed unless authorized)
    OFFLINE_JOIN --> MINIMAL_4KEY_ARTIFACT: Emits ONLY\n{incident_id, run_id, dossier, ground_truth}
```
