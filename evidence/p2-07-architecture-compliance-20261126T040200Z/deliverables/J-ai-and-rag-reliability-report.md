# Deliverable J — AI Reasoning, Hybrid RAG, and Confidence Reliability Report
## P2-07 Architecture Compliance Verification

- **Audit Run ID:** `p2-07-architecture-compliance-20261126T040200Z`
- **Scope:** End-to-end audit of Knowledge Base corpus integrity, Hybrid RAG architecture (`BM25 + Dense + RRF + Reranker`), SOP lifecycle/ACL governance, RAG-to-LLM context delivery vs. utilization, numeric/evidence grounding, deterministic confidence scoring, and post-closure calibration (`Work Packages H, I, J, K`).

---

## 1. Knowledge Base & Hybrid RAG Architecture Audit (`Work Package H`)

### 1.1 Corpus Inventory & Coverage Gaps (`H1`, `H6`)
- **Verified Manifest:** `20` synthetic Markdown documents chunked structure-aware into **`71` schema-valid chunks** (`manifest_hash = c9ee96dac3bb07b43a5230b1a881e63131250c8de77ca791ea002c8a810f5129`, `0` pre-ingestion redaction leaks).
- **Lifecycle & Entitlement Test Traps Present:**
  - `SOP-LEDGER-001@1.0.0` (`status: obsolete`, `effective_to: 2026-06-01T00:00:00Z`) superseded by `SOP-LEDGER-001@2.0.0` (`status: approved`) -> exercises `RAG-01` / `SC-10`.
  - `SOP-SEC-KEY-ROTATION@1.0.0` (`classification: synthetic-restricted`, `allowed_groups: ["sre-core-l2", "security-admin"]`) -> exercises `SEC-01`.
- **Honest Corpus Coverage Gaps Identified:**
  1. **`api-gateway` Fault-Specific SOP Gap:** `api-gateway` has architecture documentation (`ARCH-API-GW-ROUTING.md`, `ARCH-SIM-ECOSYSTEM.md`) rather than a dedicated gateway 5xx/rate-limit runbook; `P1-03` + `P1-04` classify this honestly as `NO_ELIGIBLE_SOP` / `GENERAL_GUIDANCE` without inflating confidence.
  2. **Cross-Service Shared Architecture Filtering (`QRY-HLD-012` / `CAP-02`):** `ARCH-SIM-ECOSYSTEM.md` is tagged `service_id: api-gateway`, so when `RetrievalService` enforces strict single-service `RAG-02` isolation for `transaction-service` -> `ledger-service` cascade queries (`QRY-HLD-012`), the shared ecosystem doc is excluded (`H-G4` Hit@5 = `5/6 = 83.33%` vs. `>=90%` candidate target). Tracked transparently under `CAP-02`.

### 1.2 Retrieval Engine & Critical Embedder Finding (`H2`–`H5`)
- **Backend (`Approved Deviation`):** Per `evidence/c07-20261111T160000Z/C07/retrieval-adr.md`, Qdrant was replaced with an in-process deterministic `RetrievalEngine` (`6.89 MiB` RSS, `1.29 ms` P95 latency on 71 chunks).
- **Dense Embedder Reality (`FIND-P207-03` — Undisclosed Fallback Now Documented):**
  - `ADR-S04` and `knowledge_base/retrieval/embeddings.py` declare `model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"`.
  - However, neither `sentence-transformers` nor `fastembed` is listed in `requirements.txt` (`12` packages) or installed in `.venv` (`283` packages).
  - At runtime, `MultilingualDenseEmbedder` falls back to `backend = "deterministic_local_384d"` (character/word TF-IDF + curated Indonesian-English SRE synonym expansion + seeded 384-d Gaussian projection).
  - **Impact Assessment:** On the 71-chunk bilingual synthetic corpus, `hybrid_rrf` (`k=60`) outperforms `lexical_only` (`100%` on 28 DEV queries; `83.33%` vs `66.67%` on 6 `H-G4` holdout queries), proving RRF mechanics and bilingual synonym bridging work deterministically offline. However, **true neural multilingual semantic retrieval is NOT exercised** unless `sentence-transformers`/`fastembed` is installed and pinned (`CAP-02` / `CAP-03`).

---

## 2. RAG-to-Reasoning Delivery & Grounding Audit (`Work Package I`)

1. **End-to-End Delivery Proof (`Incident -> Query -> Passages -> ContextBuilder -> Provider Request`):**
   - Verified in both `tests/test_p1_04_rag_reasoning_confidence.py` and the **live Docker `SC-03` LLM probe** in `P2-07` (`sc01_sc14_live_verification.json -> live_llm_rag_delivery_proof`):
     - `DeterministicInvestigator` queries `retrieve_runbooks` via `PolicyGateway` with incident-specific `service_id`, `environment`, `error_code`, and symptom keywords.
     - `RetrievalService` returns `SOP-LEDGER-001@2.0.0` (`APPLICABLE_SOP_FOUND`) and excludes obsolete `SOP-LEDGER-001@1.0.0`.
     - `SanitizedContextBuilder.build()` validates citation schemas, enforces `service_id`/`environment`/`classification == "synthetic-internal"`, wraps the payload in `<UNTRUSTED_OBSERVATION_DATA>...</UNTRUSTED_OBSERVATION_DATA>`, and delivers `SOP-LEDGER-001` `v2.0.0` directly into `messages[-1]["content"]` at the `Provider.complete()` boundary.
2. **Delivery vs. Utilization & Compaction Transparency:**
   - `PreparedContext.diagnostics` records `delivered_citation_ids` and `context_omissions` (compaction rungs when payloads approach `_MAX_INPUT_BYTES = 65,536`), which `P2-06`/`P2-07` surface directly in the `SOP & RAG` lens of `SREDashboard` (`RAGContextVM`).
   - Runbook passages are framed strictly as untrusted operational guidance — `ClaimValidator` never accepts an SOP citation as substitute proof for missing telemetry!

---

## 3. Deterministic Confidence & Calibration Audit (`Work Package J`)

1. **Formula & Guardrails (`orchestrator/confidence.py`):**
   - Strictly bounded to **`[0.05, 0.85]`** (`ConfidenceScoringConfig.min_score = 0.05`, `max_score = 0.85`, `is_calibrated_probability = False`, `score_semantics = "heuristic_evidence_aware_non_probabilistic"`).
   - **Status Ceilings Enforced:** `CONTRADICTED <= 0.15`, `UNSUPPORTED <= 0.20`, `INCONCLUSIVE (no support) <= 0.25`, `INCONCLUSIVE (with support / trace outage) <= 0.38`, `PARTIAL <= 0.45`, `manual_fallback <= 0.30`, `rule007_cap <= 0.30`.
   - **Anti-Inflation Protections:**
     - `sop_availability_weight == 0.0`: presence or absence of an SOP never inflates or penalizes diagnostic confidence.
     - Order-invariant signal fingerprinting (`evidence_signal_fingerprint`) collapses duplicate telemetry records (`duplicate_supporting_count`).
     - Cross-modal correlation discount (`trace_coupled_modality_discount = 0.05`, max `0.10`) prevents double-counting logs and trace spans sharing the same `trace_id`.
   - **Monotonic Band Mapping:** `LOW < 0.40 <= MEDIUM < 0.70 <= HIGH <= 0.85`.
   - **Deterministic Hypothesis Ranking (`rank_hypotheses`):** Sorts strictly by `(-support_tier, -confidence_score, -unique_supporting_count, original_index)` so `SUPPORTED` always outranks `PARTIAL` -> `INCONCLUSIVE` -> `UNSUPPORTED` -> `CONTRADICTED`.
2. **Post-Closure Calibration Honesty (`evaluator/calibration.py`):**
   - Operates strictly offline on post-`CLOSED` joined artifacts; never feeds Ground Truth back into runtime scoring (`INV-15`).
   - Explicitly flags sample sizes `< 30` (`N=7` DEV shadow pilot, `N=2` `H-G3`, `N=1` `H-G4`) as **`EXPLORATORY ONLY — INSUFFICIENT SAMPLE FOR STATISTICAL CALIBRATION`**, satisfying `P1-04` and `P2-07` honesty mandates.
