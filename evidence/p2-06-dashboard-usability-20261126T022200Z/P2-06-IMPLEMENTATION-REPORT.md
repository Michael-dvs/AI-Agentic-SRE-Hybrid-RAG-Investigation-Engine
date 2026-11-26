# P2-06 Implementation and Verification Report: Dashboard Usability and State Consistency

- **Issue:** `P2-06` (Dashboard Usability & State Consistency, Carbon High Edition)
- **Project:** AI Agentic SRE & Hybrid RAG Investigation Engine (Scaled-Down Simulation PoC)
- **Generated At (UTC):** `2026-11-26T03:26:00Z`
- **Starting Git Baseline:** `main` at `438c31dc1a993d1e30115be62a4a934f4dd877b7`
- **Final P2-06 Decision:** **`FIXED`** (for Simulation PoC scope; not a production readiness claim)

---

## Deliverable A: Executive Summary

### 1. Original Dashboard Problems & Confirmed State-Consistency Defects
Prior to `P2-06`, the terminal SRE console (`orchestrator/usability_console.py`, `scripts/sre_dashboard.py`) and companion CLI (`scripts/review_console.py`) exhibited six state-consistency defects (`STATE-01` through `STATE-06`) and eight usability/accessibility defects (`UX-01` through `UX-08`):

1. **Invisible In-Progress & Aborted Investigations (`STATE-01`, High):** `DashboardRepository` filtered active rows exclusively to `{"HUMAN_REVIEW"}` and skipped incidents without a persisted dossier, making active investigations (`RECEIVED` through `DRAFTED`) and aborted/safe-failed runs (`FAILED_SAFE`, `CANCELLED`) invisible to operators.
2. **Unstable Row Selection Across Refreshes (`STATE-02`, High):** List selection tracked only an integer `selected_index`. Whenever a newer incident arrived at row `0`, the operator's cursor silently jumped to a different incident.
3. **Non-Atomic Multi-Query State Reads (`STATE-03`, High):** Incident rows, latest dossier revisions, checkpoints, review history, and `c13_llm_runs` metadata were queried separately (including opening separate `sqlite3.connect(str(db_path))` handles that failed on `:memory:` databases and risked torn state during concurrent writes).
4. **Unsafe Single-Key Human Review Drop-Out (`STATE-04`, Critical):** Pressing `A`, `R`, `C`, or `E` immediately exited the TUI screen into blocking `Prompt.ask("Rationale")` without displaying target incident ID, target dossier revision/hash, diagnostic summary, or administrative closure disclaimers, and re-fetched `latest_dossier()` at submit time rather than binding to the exact dossier revision the reviewer inspected.
5. **Unbounded Synchronous Subprocess Probes & Silent Refresh Failures (`STATE-05`, Medium):** `ServiceHealthInspector.inspect()` executed `docker compose ps` synchronously on every render of the Health view, and SQLite refresh errors were not surfaced with a `STALE LAST-KNOWN DATA` banner.
6. **Fabricated Confidence Numbers for Unscored Priors (`STATE-06`, High):** When `confidence_score` was `None`, the presentation helper previously mapped raw unvalidated LLM labels (`HIGH`/`MEDIUM`/`LOW`) to invented numbers (`0.8`/`0.5`/`0.2`).
7. **Terminal Input Stalls, Information Overload, & Low Contrast (`UX-01..UX-08`, High):** Toggling canonical `termios` (`ICANON`) on every loop iteration stalled buffered PTY bursts; the 172-line nested-panel dossier wall lacked sub-section lenses or hypothesis-to-evidence reference navigation; `dim` grey failed WCAG AA `4.5:1` contrast; and untrusted text lacked Unicode BiDi / Ground Truth key-value scrubbing.

### 2. Main UX Improvements & Functional Corrections
- **Authoritative Atomic Read Model (`orchestrator/console_view_models.py`):** Introduced `AuthoritativeSnapshotCoordinator` reading `incidents`, `dossiers`, `checkpoints`, `human_reviews`, and `c13_llm_runs` inside a single SQLite read transaction (`store.transaction(immediate=False)`) over the authoritative `WorkflowStateStore` connection, with monotonic generation-bound async update guards and explicit `STALE LAST-KNOWN DATA` disclosure on transient DB failure.
- **Full Lifecycle Visibility & Deterministic Priority Triage:** Active queue now surfaces both `NEEDS_REVIEW` (`HUMAN_REVIEW`) and `RUNNING(stage/9)` (`RECEIVED..DRAFTED`) incidents, deterministically ordered by actionability (`NEEDS_REVIEW` before `RUNNING`), severity (`CRITICAL > HIGH > MEDIUM > LOW > UNKNOWN`), recency, and `incident_id`, while preserving `highlighted_incident_id` across insertions and resizes.
- **Progressive Disclosure via Six Focused Detail Lenses:** Added `[Tab]` / `[Shift+Tab]` lenses (`All Sections`, `Triage & Progress`, `Hypotheses`, `Evidence Lineage`, `SOP & RAG`, `Review & Audit`) with a compact 2-line incident context bar on focused lenses, `[` / `]` item stepping, and `[I]` Hypothesis-to-Evidence jump with `[B]` return-stack restoration.
- **Version-Bound Two-Step Human Review Confirmation Modal:** Pressing `A`, `R`, `C`, or `E` opens an in-TUI confirmation modal bound to `(incident_id, viewed_dossier_version, viewed_dossier_hash)` displaying leading hypothesis, evidence balance, SOP classification, `NOT_PERFORMED` check count, reviewer trust boundary (`Local PoC caller-asserted identity (unauthenticated)`), and exact administrative closure semantics (`diagnosis_verified=False`, `technical_resolved=False`, `auto_action_triggered=False`), with `Esc` cancellation and safe conflict/DB-failure recovery.
- **Shared TUI/CLI Semantics & Terminal Safety Defense:** Both `SREDashboard` and `scripts/review_console.py` render from `build_incident_detail_vm`. `sanitize_terminal_text` strips ANSI CSI/OSC/DCS escapes, C0/C1 controls, and Unicode BiDi spoofing chars, applies `DeterministicSanitizer` (`SEC-03`), scrubs Ground Truth keys/values (`INV-11`), and neutralizes spoofed uppercase `VERIFIED` tokens in untrusted text (`RULE-007` / `INV-17`).
- **WCAG AA Accessible Visual System & Responsive Viewports:** All foreground tokens achieve `>= 5.67:1` contrast on dark terminal backgrounds (`#292929`), green (`#86efac` / `#4ade80`) is strictly banned from hypothesis confidence/support badges, monochrome terminals retain full non-color text tags (`[CRIT]`, `[SUPPORTED]`, `[CURRENT_FRESH]`, `[FOCUSED]`), and viewports adapt cleanly across `80x24`, `100x30`, `120x40`, `160x50`, plus a state-preserving `<68x16` minimum-size guard.

### 3. Visual Verification, Regression Outcomes, & PoC Sign-Off Readiness
- Captured **5 before-state** snapshots (`PNG`/`SVG`/`TXT`) + real PTY session trace and **18 after-state** snapshots (`PNG`/`SVG`/`TXT`) + real interactive PTY trace (`182,690` bytes, `exit=0`), visually inspected directly and scanned clean (`0` violations across `38` artifacts) via `scripts/dlp_sink_scanner.py`.
- All **10** multi-scenario `P2-06` verification tests (`tests/test_p2_06_dashboard_usability_state.py`), **242** focused regression tests (`C16`, `C19`, `C20`, `P0-02`, `P1-03`, `P1-04`, `P1-05`, `LiveAlertWatcher`), **6** async `anyio` simulator tests, and **811** broader offline repository tests pass with **zero** new regressions. Frozen `C02` schemas and `final-release-manifest.json` (`SHA-256: b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f`) remain byte-for-byte unchanged.
- **Sign-Off Assessment:** `P2-06` is **ready for Simulation PoC sign-off** (`FIXED`). Live Docker Compose telemetry stack interaction (`test_c03_compose_live.py`) remains environment-blocked on this host (`DOCKER_DAEMON=NOT_RUNNING`) and is explicitly documented below.

---

## Deliverable B: Repository Baseline

| Attribute | Verified Baseline Value |
|---|---|
| **Branch & Starting `HEAD`** | `main` @ `438c31dc1a993d1e30115be62a4a934f4dd877b7` (`feat(p1-05): implement end-to-end evidence traceability, temporal validity, and incident isolation`) |
| **Starting Working Tree** | Clean (`git status -s` empty prior to `P2-06`) |
| **Runtime Environment** | macOS (`darwin`), Python `3.12.14` (`.venv`), `rich 15.0.0`, `cairosvg 2.9.1`, `pillow 12.3.0`, POSIX `pty` + `termios` available; Docker daemon not running (`DOCKER_DAEMON=NOT_RUNNING`) |
| **P1-04 Dependency Status** | Implemented & verified passing (`tests/test_p1_04_rag_reasoning_confidence.py`: `72 passed`): monotonic confidence bands (`HIGH >= 0.70`, `MEDIUM >= 0.40`, `LOW < 0.40`, cap `0.85`), RAG delivery telemetry (`rag_diagnostics`), and uncalibrated heuristic score contract |
| **P1-05 Dependency Status** | Implemented & verified passing (`tests/test_p1_05_evidence_traceability_freshness.py`: `72 passed`): `evaluate_evidence_temporal_validity`, `verify_evidence_integrity_and_scope`, `INTEGRITY_SEMANTICS_NOTE`, and incident/cache isolation |
| **Previous Console Baseline** | `orchestrator/usability_console.py` (`C19` Rich TUI + `Live` loop), `scripts/sre_dashboard.py`, `scripts/review_console.py`, `orchestrator/console_config.py`, `orchestrator/telegram_dispatcher.py` |
| **Preserved Public Contracts** | `SREDashboard._MENU_ORDER == ("active", "archive", "health", "model", "telegram")`, `DashboardRepository`, `ReviewActionController`, `DashboardViewport`, `_ScrollableContent`, `build_grafana_incident_url`, `_bounded_sanitized_excerpt`, frozen `C02` schemas, and frozen Stage 3A manifest |
| **Baseline Focused Test Run** | `170 passed` (`test_c19`, `test_c16`, `test_p0_02_*`, `test_p1_03_verification`, `test_p1_05`) prior to `P2-06` code edits |

---

## Deliverable C: UX and State Audit

| ID | Issue | Observed Before Behavior | Operator Impact | Severity | Root Cause | Implemented Correction | Evidence |
|---|---|---|---|---|---|---|---|
| `STATE-01` | Active in-progress & aborted runs hidden | Only `HUMAN_REVIEW` incidents with saved dossiers appeared in `[1] Active` | Operators could not see running (`RECEIVED..DRAFTED`) or `FAILED_SAFE` incidents | **High** | `DashboardRepository._dossiers` filtered strictly on `{"HUMAN_REVIEW"}` and skipped `dossier is None` | `AuthoritativeSnapshotCoordinator` reads all `incidents` + `checkpoints`, rendering `RUNNING(k/9)` in Active and `FAILED_SAFE`/`CANCELLED` in Archive | `after/01_normal_overview_120x40.png`, `after/03_investigation_in_progress_120x40.png`, `test_group_a` |
| `STATE-02` | Row cursor jumped on new incident arrival | Highlighted row was stored only as `selected_index: int` | Operator inspecting/selecting row `#2` jumped to a different incident on refresh | **High** | No `highlighted_incident_id` anchor in `SREDashboard` | Added `highlighted_incident_id` synchronization on every snapshot refresh and navigation event | `test_group_a_authoritative_state_selection_stability_and_races` |
| `STATE-03` | Non-atomic multi-query state reads | Separate SQL queries & separate `sqlite3.connect(db_path)` calls per render | Risk of torn state between `incidents`, `dossiers`, and `human_reviews`; `:memory:` incompatibility for `c13_llm_runs` | **High** | Ad-hoc per-panel queries in `usability_console.py` | Single `with self.store.transaction(immediate=False):` snapshot read in `AuthoritativeSnapshotCoordinator._read_atomic_snapshot` | `orchestrator/console_view_models.py`, `test_group_a` |
| `STATE-04` | Blind single-key Human Review submission | `A/R/C/E` exited `Live` screen into raw `Prompt.ask` and re-read `latest_dossier()` | Reviewer could sign off without seeing revision/hash, summary, or administrative closure limits, or sign an unread `v2` | **Critical** | `_prompt_review` bypassed revision binding and pre-submit confirmation | Added in-TUI version-bound `open_review_modal` / `submit_review_modal` / `cancel_review_modal` passing `target_version=viewed_dossier_version` | `after/12_review_confirmation_modal_120x40.png`, `test_group_d` |
| `STATE-05` | Unbounded Docker probes & silent DB errors | `ServiceHealthInspector.inspect()` ran subprocess on every Health render; DB errors lacked stale-data warning | UI stalls when Docker daemon is down/slow; risk of mistaking stale snapshot for live state | **Medium** | No TTL cache around `health.inspect()` / `costs.read()`; no refresh fallback banner | Added `probe_ttl_seconds=10.0` cache + `[BACKEND REFRESH DEGRADED - SHOWING STALE LAST-KNOWN DATA]` banner | `after/14_degraded_stale_last_known_120x40.png`, `test_group_f` |
| `STATE-06` | Fabricated confidence numbers for unscored priors | Unscored LLM priors (`HIGH`/`MEDIUM`/`LOW`) rendered as `0.8`/`0.5`/`0.2` | Violated `INV-08` by inventing numeric confidence never computed by `confidence.py` | **High** | Fallback mapping table in old formatting helper | Removed invented numeric mapping; unscored items render honestly as `Not scored [prior: HIGH, unvalidated]` | `orchestrator/console_view_models.py`, `test_group_c` |
| `UX-01` | PTY buffered input stall in `run()` | Rapid PTY keystrokes or multi-char paste stalled until newline | Unresponsive keyboard navigation and modal typing in real terminals/PTYs | **High** | `_read_key()` restored `ICANON` between every keystroke and refreshed SQLite per typed char | Held `tty.setcbreak` across `run()`, coalesced printable bursts in `raw_text_mode`, and skipped DB refresh on modal typing | `pty/pty_after_interactive_session.ansi`, `test_real_pty_interactive_session_resize_and_review_flow` |
| `UX-02` | 172-line nested-panel wall in Incident Detail | Every section rendered simultaneously inside triple-nested boxes (`line 1-24/172`) | Operators had to scroll 7+ screens to reach Evidence Lineage or Human Review | **High** | No sub-section progressive disclosure | Added 6 detail lenses (`All`, `Overview`, `Hypotheses`, `Evidence`, `SOP & RAG`, `Review`) + compact 2-line context bar on focused lenses | `after/04..11_*.png`, `test_group_b` |
| `UX-03` | No Hypothesis-to-Evidence reference navigation | Evidence IDs listed under hypotheses could not be jumped to directly; broken refs were silent | Slow manual cross-checking of provenance & temporal validity | **Medium** | Static text rendering without item cursor or reference resolver | Added `[` / `]` item stepping, `[I]` Hypothesis-to-Evidence jump, `[B]` return stack, and explicit `[UNRESOLVED REFERENCE]` warning | `after/06_evidence_detail_lineage_120x40.png`, `test_group_b` |
| `UX-04` | Missing Global Status Strip & Triage Sorting | Header showed static boilerplate without store status, queue counts, or environment | Could not rapidly answer "What needs attention right now?" | **High** | Static 2-line banner; chronological-only list | Added Global Status Strip (`Store`, `Env`, `ReviewQueue`, `Running`, `Archive`, `Lab`, `Mode`, `Reviewer`) + priority triage sorting + Selected Symptom preview | `before/01_overview_120x40.png` vs `after/01_normal_overview_120x40.png` |
| `UX-05` | Low-contrast `dim` text & green confidence cues | `dim` text fell below `4.5:1`; green borders/text risked implying verified root cause | Accessibility failure (`WCAG AA`) and `RULE-007` ambiguity | **Medium** | Ad-hoc Rich color names (`dim`, `green`) | Centralized `ConsoleDesignTokens` (`#94a3b8` `5.67:1` min contrast on `#292929`; `#7dd3fc` sky-cyan for `SUPPORTED`; green restricted to infra health) | `test_wcag_contrast_and_no_green_for_confidence` |
| `UX-06` | Cramped/clipped `80x24` & unguarded `<68x16` | Narrow terminals truncated unique ID tails (`inc-sim-ledger...`) and corrupted below `68x16` | Incident IDs with shared prefixes became indistinguishable; tiny viewports broke tables | **Medium** | Prefix-only slicing; no min-dimension check | Added CJK-safe middle ellipsis `compact_identifier` (`inc-sim-...001`), `80x24` stacked layout, and recoverable `<68x16` guard preserving state | `after/16_compact_layout_80x24.png`, `after/18_minimum_size_guard_60x14.png`, `test_group_e` |
| `UX-07` | Poor shortcut discoverability | No in-console keyboard/semantics guide | Operators had to read source code to learn keys or closure meaning | **Low** | No help overlay | Added `[?]` Keyboard & Safety Semantics Reference modal | `after/17_keyboard_help_overlay_120x40.png`, `test_group_b` |
| `UX-08` | Adversarial escape, BiDi, & GT value exposure | Untrusted text could carry BiDi overrides, OSC links, `ground_truth=val`, or spoofed `VERIFIED` | Terminal spoofing (`INV-17`) or GT value leak (`INV-11`) | **High** | Incomplete display text scrubber | Hardened `sanitize_terminal_text` against ANSI/OSC/DCS/C0/C1, BiDi codepoints, `SEC-03`, `_GT_KEY_VALUE_RE`, and `\bVERIFIED\b` | `test_group_e_and_o10_o11_responsive_resize_monochrome_and_adversarial_safety` |

---

## Deliverable D: Design Specification

### 1. Design Principles
1. **Truth Before Decoration:** Every badge, counter, and stage indicator maps to an authoritative persisted field or explicitly labeled unavailability marker.
2. **Progressive Disclosure Without Hiding Warnings:** Operators see triage essentials first, then drill into focused lenses (`Hypotheses`, `Evidence`, `SOP & RAG`, `Review`) while safety boundaries (`diagnosis_verified=False`, `NOT_PERFORMED`, `STALE LAST-KNOWN DATA`) remain visible.
3. **Strict Semantic Separation:** High heuristic confidence (`78% HIGH`), `SUPPORTED` claim validation, human `APPROVE`, and `CLOSED` handover are visually and textually distinct from verified root cause or technical remediation.
4. **Color-Independent Accessibility:** Every status combines typography + explicit bracketed ASCII labels (`[CRIT]`, `[SUPPORTED]`, `[OUTSIDE_WINDOW]`, `[FOCUSED]`) and meets `WCAG AA >= 4.5:1` contrast.

### 2. Information Architecture & Navigation Model
```
Global Status Strip (1-2 lines: Store @ HH:MM:SS | Env | ReviewQueue | Running | Archive | Lab Probe | Mode | Reviewer | [?]Help)
├── Degraded / Stale Last-Known Banner (conditional on refresh error)
├── Left Rail / Top Bar Navigation (_MENU_ORDER preserved)
│   ├── [1] Active Incidents  -> Priority Triage Queue + Selected Symptom Preview
│   │   └── [Enter/O] Incident Detail Workspace
│   │       ├── All Sections (full scrollable dossier)
│   │       ├── Triage & Progress (2-line header + 9-stage timeline + symptoms + impact graph)
│   │       ├── Hypotheses (compact context + ranked table + [ ] stepping + [I] jump to Evidence)
│   │       ├── Evidence Lineage (compact context + P1-05 provenance/temporal/hash cards + rejected refs)
│   │       ├── SOP & RAG (compact context + SOP status + P1-04 prompt delivery counts + citations + NOT_PERFORMED checks)
│   │       └── Review & Audit (eligibility + trust mode + administrative semantics + append-only review log)
│   ├── [2] Archive Dossiers  -> Finalized / Locked Historical Investigations (CLOSED, REJECTED, MANUAL_TRIAGE_REQUIRED, FAILED_SAFE)
│   ├── [3] Service Health    -> Cached read-only Docker lab container health (10s TTL, manual [U] refresh)
│   ├── [4] AI Model Config   -> Local .env provider/model configuration & masked key setup
│   └── [5] Telegram Alerts   -> Passive outbound notification preview & dry-run test
├── Modal Layer (exclusive focus trap, Esc cancels cleanly)
│   ├── [?] Keyboard & Safety Semantics Reference Overlay
│   └── [A/R/C/E] Version-Bound Two-Step Human Review Confirmation Modal
└── Contextual Action & Notice Bar (bottom 2-3 lines)
```

### 3. WCAG-Verified Visual Design Tokens (`ConsoleDesignTokens`)
Verified against dark terminal surfaces (`#292929`, `#1e1e1e`, `#14181f`) using `contrast-check.py` and `test_wcag_contrast_and_no_green_for_confidence`:

| Token Role | Hex (`TOKENS_COLOR`) | Contrast on `#292929` | Monochrome (`TOKENS_MONO`) | Operational Meaning |
|---|---|---|---|---|
| `primary` | `#f1f5f9` / `#f8fafc` | `13.18:1` / `13.90:1` | `none` | Primary identifiers, statements, active values |
| `secondary` | `#cbd5e1` | `9.80:1` | `none` | Supporting metadata and descriptions |
| `muted` | `#94a3b8` | `5.67:1` | `none` | Field labels, inactive borders, disabled hints (replaces low-contrast `dim`) |
| `accent` / Focus | `#38bdf8` (`#0f172a` on `#38bdf8` badge) | `6.79:1` (`8.33:1`) | `bold` + `[FOCUSED]` / `▶` | Active focus border, selected row, lens indicator |
| `corroborated` | `#7dd3fc` / `#67e8f9` | `8.55:1` / `10.04:1` | `bold` + `[SUPPORTED]` | Corroborated candidate hypothesis (never green; not verified) |
| `warning` | `#facc15` / `#fde047` | `9.69:1` / `11.04:1` | `bold` + `[HIGH]`/`[PARTIAL]` | High severity, partial/competing guidance, stale data |
| `critical` | `#f87171` / `#fca5a5` | `5.33:1` / `7.67:1` | `bold` + `[CRIT]`/`[CONTRADICTED]` | Critical severity, contradicted claim, backend/review error |
| `healthy_infra` | `#4ade80` / `#86efac` | `8.32:1` / `10.36:1` | `bold` + `[OK]` | **Strictly reserved** for healthy container probe status; never used on hypotheses or `CLOSED` |

### 4. Responsive Breakpoints & Accessibility
- **`160x50` (Wide):** Side-by-side navigation rail (`26` cols) + full triage table including inline `Observed Symptom` column.
- **`120x40` & `100x30` (Standard):** Side-by-side navigation rail + triage table (`No.`, `Time`, `Incident`, `Sev`, `Service`, `Mode`, `State`) + `Selected Symptom` preview footer.
- **`80x24` (Compact):** Stacked horizontal top navigation bar + compact triage columns preserving severity badge and middle-ellipsized `incident_id` suffix (`inc-sim-...001`).
- **`< 68x16` (Minimum-Size Guard):** Displays a clean `Resize Required` panel (`Current: W cols x H rows | Minimum: 68 cols x 16 rows`) while preserving `selected_incident_id`, `focus`, and unsent `review_modal` input.

### 5. Updated Keyboard Reference
| Scope | Key(s) | Action |
|---|---|---|
| **Global (outside text input)** | `1`..`5` | Jump to Active, Archive, Health, Model Config, or Telegram view |
| **Global** | `?` | Toggle Keyboard & Safety Semantics Reference modal |
| **Global** | `U` | Force immediate authoritative snapshot & health refresh |
| **Global** | `Q` | Cleanly exit console without mutating active investigations |
| **Navigation / List** | `Up`/`Down` or `k`/`j` | Move menu item or incident row selection (anchored by `incident_id`) |
| **Navigation / List** | `Left`/`Right` or `Tab` | Switch focus between Navigation Menu and Incident List |
| **Incident List** | `Enter` or `O` | Open Incident Detail workspace for highlighted incident |
| **Incident Detail** | `Tab` / `Shift+Tab` | Cycle detail lenses (`All` -> `Overview` -> `Hypotheses` -> `Evidence` -> `SOP & RAG` -> `Review`) |
| **Incident Detail** | `Up`/`Down`, `PgUp`/`PgDn` | Scroll detail viewport (`1` line or `8` lines) |
| **Hypotheses / Evidence Lens** | `[` / `]` | Step focused hypothesis or evidence card |
| **Hypotheses Lens** | `I` | Jump directly to Evidence Lineage focused on first linked evidence ID |
| **Incident Detail** | `G` | Open scoped read-only Grafana dashboard URL (`http`/`https` validated) |
| **Incident Detail (`HUMAN_REVIEW`)** | `A` / `R` / `C` / `E` | Open two-step confirmation modal for `APPROVE`, `REJECT`, `CORRECT`, or `ESCALATE` |
| **Detail / Modal** | `B` or `Esc` | Pop return stack / exit detail view / cancel modal with zero domain mutation |

---

## Deliverable E: State Consistency Specification

### 1. Authoritative Domain Sources
| Displayed State | Authoritative Source | Read Mechanism | Mutation Mechanism |
|---|---|---|---|
| Incident existence & `current_state` | `WorkflowStateStore.incidents` | `AuthoritativeSnapshotCoordinator._read_atomic_snapshot` | `InvestigationStateMachine` / `AuthorizedReviewManager` only |
| Intermediate stage progress & `rag_diagnostics` | `WorkflowStateStore.checkpoints` | Same SQLite read transaction | Investigator pipeline checkpoints only |
| Persisted dossier JSON, `dossier_version`, `dossier_hash` | `WorkflowStateStore.dossiers` | Same SQLite read transaction (`ORDER BY dossier_version DESC`) | `DossierSerializer` + `AuthorizedReviewManager.edit` (`vN+1`) |
| Review decisions & audit linkage | `WorkflowStateStore.human_reviews` + `AuditHashChain` | Same SQLite read transaction | `AuthorizedReviewManager.{approve,reject,edit,escalate}` |
| Unvalidated LLM prior / run provenance | `c13_llm_runs` (optional table) | Same `store._conn` transaction (safe if table absent) | `C13` runtime recorder |
| Container health & offline cost summary | `docker compose ps` / cost JSON | `get_cached_health` / `get_cached_costs` (`10s` TTL) | Read-only probe only |

### 2. Separation of Domain State, View State, and Transient State
- **Domain State (Immutable by UI Rendering):** `lifecycle_state`, `dossier_version`, `dossier_hash`, `hypotheses`, `confidence_score`, `evidence_summary`, `sop_availability`, `human_reviews`.
- **View State (UI-Owned):** `view`, `focus`, `highlighted_incident_id`, `selected_incident_id`, `detail_section`, `detail_scroll`, `focused_hypothesis_idx`, `focused_evidence_id`, `nav_return_stack`, `unsent_review_draft`.
- **Transient Operation State (UI-Owned):** `initial_loading`, `snapshot.is_stale_last_known`, `snapshot.refresh_error`, `review_modal["submitting"]`, `review_modal["error"]`, `notice`.

### 3. Generation-Bound Refresh, Revision Tracking, & Conflict Recovery
1. Every refresh increments `_next_generation`. `apply_external_snapshot(snapshot)` rejects any snapshot where `snapshot.generation < self.last_applied_generation` (`A07`) and advances `_next_generation = max(_next_generation, snapshot.generation)`.
2. `apply_async_snapshot(snapshot, expected_incident_id=...)` discards selection/scroll resets if the operator switched `selected_incident_id` while an async read was in flight (`A08`).
3. Opening a detail view records `(viewed_dossier_version, viewed_dossier_hash)`. If a background refresh detects a newer dossier revision while `review_modal` is open, the UI surfaces a revision-change warning; on submit, `submit_review_modal` passes `target_version=modal["target_version"]` and the exact `dossier_snapshot` into `AuthorizedReviewManager`, which enforces `BEGIN IMMEDIATE` SQLite locking and raises `StaleDossierVersionError` or `ReviewStateConflictError` on any concurrent review or version drift (`A09`, `A10`, `D13`, `K8`).
4. On conflict or `sqlite3.Error`/`OSError`, `submit_review_modal` never displays success: it preserves or surfaces the error safely, reloads authoritative state from `WorkflowStateStore`, and updates lock status (`D14`, `K9`).

### 4. Remaining Consistency Limitations (PoC Scope)
- Refresh between external processes uses bounded polling (`--refresh-interval`, default `2.0s`, min `0.5s`) over SQLite WAL rather than push notifications. Between polls, an external CLI review can finalize an incident up to `2.0s` before the TUI passively redraws, which is safely caught at submission time by `AuthorizedReviewManager`'s `BEGIN IMMEDIATE` transaction guard.

---

## Deliverable F: Before/After Visual Evidence

All visual artifacts are actual rendered outputs produced from live `Rich` console execution + macOS `Menlo` SVG-to-PNG rasterization (`cairosvg`) and real POSIX `pty.openpty()` sessions driving `scripts/sre_dashboard.py`. **Zero conceptual mockups or hand-edited images were used.**

- **Artifact Root:** `evidence/p2-06-dashboard-usability-20261126T022200Z/`
- **Manifest:** `evidence/p2-06-dashboard-usability-20261126T022200Z/visual_evidence_manifest.json`
- **Reproduction Command:** `.venv/bin/python evidence/p2-06-dashboard-usability-20261126T022200Z/capture_after_state.py`

### 1. Before-State Captures (`before/`)
| ID | Dimensions | Files (`.png`, `.svg`, `.txt`) | Observed Baseline Issues |
|---|---|---|---|
| `01_overview_120x40` | `120x40` | `before/01_overview_120x40.*` | No global status strip, no running incidents shown, no severity triage order, no symptom preview |
| `02_overview_compact_80x24` | `80x24` | `before/02_overview_compact_80x24.*` | Prefix-only ID truncation hiding unique suffixes; low-contrast `dim` hints |
| `03_detail_hypotheses_review_120x40` | `120x40` | `before/03_detail_hypotheses_review_120x40.*` | `line 1-24/172` triple-nested panel wall; single-key `[A] APPROVE` drops out to raw prompt |
| `04_detail_sop_evidence_120x40` | `120x40` | `before/04_detail_sop_evidence_120x40.*` | Deep manual scrolling required to reach SOP/Evidence; no RAG prompt delivery count or hypothesis jump |
| `05_detail_closed_archive_120x40` | `120x40` | `before/05_detail_closed_archive_120x40.*` | Archive detail lacked prominent header-level `technical_resolved=False` closure banner |
| `pty_before_session.ansi` | `120x40` | `before/pty_before_session.ansi` | Real PTY trace (`30,773` bytes) of baseline console |

### 2. After-State Captures (`after/` & `pty/`)
| N2 # | Capture ID | Size | Scenario & Key Visual Verification Notes |
|---|---|---|---|
| `1` | `01_normal_overview_120x40` | `120x40` | Global status strip, deterministic priority triage (`[CRIT]` -> `[HIGH]` -> `RUNNING(4/9)`), symptom preview |
| `2` | `02_multiple_active_wide_160x50` | `160x50` | Wide 160-col layout adding inline `Observed Symptom` column without wasted horizontal whitespace |
| `3` | `03_investigation_in_progress_120x40` | `120x40` | Stage `4/9` (`[*:EVD]`) running incident; `[DOSSIER PENDING - EVIDENCE_COLLECTED]`; review disabled |
| `4` | `04_supported_hypothesis_120x40` | `120x40` | `#1 [SUPPORTED] 78% (HIGH)` in sky-cyan (not green) + `#2 [CONTRADICTED] 12% (LOW)` + calibration disclaimer |
| `5` | `05_unsupported_hypothesis_120x40` | `120x40` | `#1 [UNSUPPORTED] 14% (LOW)` exposing excluded `[OUTSIDE_INCIDENT_WINDOW]` & partial evidence |
| `6` | `06_evidence_detail_lineage_120x40` | `120x40` | Evidence Lineage lens with Loki/Prometheus provenance, units, windows, and `SHA-256` consistency note |
| `7` | `07_historical_partial_and_rejected_evidence_120x40` | `120x40` | Distinguishes `[HISTORICAL_VALID] [PARTIAL]` from `REJECTED [OUTSIDE_WINDOW]` telemetry |
| `8` | `08_sop_retrieval_and_delivery_120x40` | `120x40` | `APPLICABLE_SOP_FOUND`, `retrieved=4, eligible=2, included_in_llm_prompt=2`, RRF score disclaimer |
| `9` | `09_competing_sops_and_compaction_120x40` | `120x40` | `CONFLICTING_OR_COMPETING_SOPS` warning + `omitted=1 (compaction=rung_2_trim_secondary_sops)` |
| `10` | `10_retrieval_unavailable_manual_checks_120x40` | `120x40` | `RETRIEVAL_UNAVAILABLE` distinct from `NO_APPLICABLE_RUNBOOK` + `STATUS=NOT_PERFORMED` checks |
| `11` | `11_human_review_readiness_120x40` | `120x40` | Review & Audit lens showing `L2_SRE` eligibility, caller-asserted PoC trust mode, and closure rules |
| `12` | `12_review_confirmation_modal_120x40` | `120x40` | Version-bound `v1` `APPROVE` modal with diagnostic summary, handover disclaimers, and `Cancel (Esc)` |
| `13` | `13_finalized_locked_archive_120x40` | `120x40` | `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED` (`technical_resolved=False`) + `[REVIEW LOCKED - FINALIZED]` |
| `14` | `14_degraded_stale_last_known_120x40` | `120x40` | `[BACKEND REFRESH DEGRADED - SHOWING STALE LAST-KNOWN DATA]` banner + `Lab:UNAVAILABLE` |
| `15` | `15_empty_incident_queue_100x30` | `100x30` | Empty queue explaining cause and concrete next operator steps |
| `16` | `16_compact_layout_80x24` | `80x24` | Stacked `80x24` layout preserving `[CRIT]`/`[HIGH]` tags and unique tail IDs (`inc-sim-...001`) |
| `17` | `17_keyboard_help_overlay_120x40` | `120x40` | `[?]` Keyboard & Safety Semantics Reference modal |
| `18` | `18_minimum_size_guard_60x14` | `60x14` | Clean recoverable resize prompt below `68x16` preserving active state |
| `PTY` | `pty/pty_after_interactive_session.ansi` | `120x40` -> `80x24` -> `120x40` | Real subprocess PTY trace (`182,690` bytes, `exit=0`): `?` -> `Esc` -> `Tab` -> `Enter` -> lenses -> `I` -> `B` -> `TIOCSWINSZ` resize -> `A` -> `Esc` cancel -> `A` -> rationale -> `CLOSED` -> `Q` |

---

## Deliverable G: Operator Workflow Report (`Scenarios O1–O12`)

| Scenario | Preconditions | Operator Actions | Expected Behavior | Actual Verified Behavior | Result | Supporting Artifacts |
|---|---|---|---|---|---|---|
| **O1: Rapid Incident Triage** | Multiple active (`CRITICAL`, `HIGH`, `MEDIUM`) & running incidents; plus empty & degraded states | Open console, inspect queue order, move cursor, insert new `CRITICAL` incident | Highest-priority `NEEDS_REVIEW` first; `highlighted_incident_id` stays on chosen incident | `CRITICAL` sorted to row `#1`; cursor remained anchored on `inc-p206-med-010` (`index 1 -> 2`) | **PASS** | `after/01_normal_overview_120x40.png`, `after/15_empty_incident_queue_100x30.png`, `test_group_a` |
| **O2: Follow Investigation Progress** | Incident at `EVIDENCE_COLLECTED` (`4/9`) without dossier | Select running row, open detail, attempt `APPROVE` | Shows `[*:EVD]` stage `4/9`, `Dossier not yet generated`, `Stage completion != verified diagnosis`, blocks review | Rendered exact `4/9` stage bar, pending placeholders, and blocked `open_review_modal("APPROVE") == False` | **PASS** | `after/03_investigation_in_progress_120x40.png`, `test_group_a` |
| **O3: Investigate a Weak Hypothesis** | `14% (LOW)` `[UNSUPPORTED]` hypothesis with `SOURCE_UNAVAILABLE` trace | Open Hypotheses lens on weak incident | Low score & `[UNSUPPORTED]` clear; rejected/missing sources visible; zero green/verified styling | Displayed `14% (LOW)`, `[UNSUPPORTED]`, excluded `[OUTSIDE_INCIDENT_WINDOW]`, and `SOURCE_UNAVAILABLE` | **PASS** | `after/05_unsupported_hypothesis_120x40.png`, `test_group_c` |
| **O4: Inspect Evidence Provenance** | Incident with linked supporting evidence + incident with broken `ev-ghost-missing-404` | Focus Hypotheses lens -> press `I` -> inspect lineage -> press `B` | Jumps to exact evidence card with source/window/hash; `B` restores Hypotheses lens; broken ref flagged | Focused `ev-...-log-01`, `B` restored `hypotheses` -> `all` -> `list`; missing ref showed `[UNRESOLVED REFERENCE]` | **PASS** | `after/06_evidence_detail_lineage_120x40.png`, `test_group_b` |
| **O5: Inspect Missing or Competing SOPs** | Incidents with `RETRIEVAL_UNAVAILABLE` and `CONFLICTING_OR_COMPETING_SOPS` | Open `SOP & RAG` lens | Retrieval outage distinct from `NO_APPLICABLE_RUNBOOK`; competing SOPs & `NOT_PERFORMED` checks explicit | Rendered distinct status banners, compaction rung telemetry, and `STATUS=NOT_PERFORMED` guardrails | **PASS** | `after/09_*.png`, `after/10_*.png`, `test_group_c` |
| **O6: Approve a Dossier** | `HUMAN_REVIEW` dossier `v1`, `L2_SRE` reviewer | Press `A`, enter `<5` char rationale (rejected), enter valid rationale, confirm | Validates rationale, commits via `AuthorizedReviewManager`, shows `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED` | Short rationale blocked; valid submit transitioned to `CLOSED` with `diagnosis_verified=False, technical_resolved=False` | **PASS** | `after/12_review_confirmation_modal_120x40.png`, `test_group_d`, `pty_after_interactive_session.ansi` |
| **O7: Reject, Correct, or Escalate** | `HUMAN_REVIEW` dossiers | Submit `CORRECT` (testing `VERIFIED` block then valid edit), `REJECT`, and `ESCALATE` | `VERIFIED` rejected (`RULE-007`); `CORRECT` creates `v2` preserving `[ORIG AI]`; `REJECT`/`ESCALATE` lock final states | `CORRECT` spawned `v2` in `HUMAN_REVIEW` with `[HUMAN EDIT]` + `[ORIG AI]`; `ESCALATE` -> `MANUAL_TRIAGE_REQUIRED` | **PASS** | `test_group_d_human_review_modal_safety_conflicts_and_failures` |
| **O8: Concurrent Review Conflict** | Operator A has `APPROVE` modal open on `v1` while Operator B finalizes `REJECT` | Operator A submits stale modal | Submission rejected safely, authoritative `REJECTED` state reloaded, zero duplicate final review | Returned `False`, displayed `[REVIEW CONFLICT - ALREADY_FINALIZED]`, reloaded `REVIEW LOCKED - FINALIZED (REJECTED)` | **PASS** | `test_group_d` (`inc-p206-rev-race`) |
| **O9: Backend Outage** | Valid snapshot loaded, then SQLite raises `OperationalError` | Trigger refresh while DB broken, then restore DB | Retains last-known view marked `STALE LAST-KNOWN DATA` with error & last refresh timestamp; recovers cleanly | Displayed `STALE LAST-KNOWN DATA` + `Store:ERROR`, then restored `Store:CONNECTED` on recovery | **PASS** | `after/14_degraded_stale_last_known_120x40.png`, `test_group_a` |
| **O10: Resize and Navigation** | Detail view & open review modal with draft rationale | Resize `120x40 -> 60x14 -> 80x24 -> 100x30 -> 160x50` | Zero crashes or unintended domain actions; selection, focus, and draft rationale preserved | `60x14` showed recoverable guard; all 4 target sizes rendered cleanly with draft intact | **PASS** | `after/16_*.png`, `after/18_*.png`, `test_group_e`, `test_real_pty_*` |
| **O11: Adversarial Display Content** | Symptom containing ANSI CSI, OSC-8 link, BiDi `\u202e`, `[bold green]FAKE STATUS: VERIFIED`, CJK, secret, & `ground_truth=hidden_fault_label` | Render list & detail across all viewports | Escapes/BiDi stripped, markup rendered literally, secret & GT key+value redacted, `VERIFIED` neutralized | Zero raw escapes/BiDi, `supersecret999` -> `[REDACTED:SEC-03:CREDENTIAL]`, `hidden_fault_label` scrubbed, `VERIFIED` -> `[untrusted:verified]` | **PASS** | `test_group_e_and_o10_o11_responsive_resize_monochrome_and_adversarial_safety` |
| **O12: Historical Incident** | Administratively `CLOSED` dossier in Archive | Open Archive -> inspect detail -> attempt `REJECT` | Original `35% (LOW)` `PARTIAL` findings intact; controls locked; `CLOSED != technical resolution` explicit | Rendered `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED`, `technical_resolved=False`, and blocked `open_review_modal` | **PASS** | `after/13_finalized_locked_archive_120x40.png`, `test_group_d` |

---

## Deliverable H: Human Review Safety Report (`K1–K9`)

1. **Authorization & Identity Disclosure (`K1`, `D01–D03`, `D15`):** `build_incident_detail_vm` evaluates reviewer format, forbidden AI/bot prefixes (`ai_*`, `agent_*`, `llm_*`, `system_*`), role allowlist (`ALLOWED_REVIEWER_ROLES`), directory registration (when enabled), and lifecycle state (`HUMAN_REVIEW` + persisted dossier). Caller-asserted local PoC mode is explicitly disclosed as `Local PoC caller-asserted identity (unauthenticated)` unless an authenticated context is supplied. Backend `AuthorizedReviewManager` independently enforces every check.
2. **Pre-Submission Review Summary & Action Semantics (`K2–K6`, `D04`, `D08–D11`):** `REVIEW_ACTION_SEMANTICS` and `_render_review_modal` present target `incident_id`, `Revision: vN (sha256: ...)`, leading hypothesis, supporting/contradicting evidence counts, SOP status, `NOT_PERFORMED` check count, and explicit disclaimers that:
   - `APPROVE` transitions to `CLOSED` for administrative dossier handover only (`diagnosis_verified=False`, `technical_resolved=False`, `sop_compliance_confirmed=False`, `remediation_authorized=False`, `auto_action_triggered=False`).
   - `REJECT` transitions to `REJECTED` while preserving original evidence and AI hypotheses intact.
   - `CORRECT` spawns append-only `v(N+1)` in `HUMAN_REVIEW`, tags the human candidate `[HUMAN EDIT]`, preserves AI candidates as `[Original AI Finding]` / `[ORIG AI]`, and rejects `VERIFIED` (`RULE-007`) or fabricated evidence.
   - `ESCALATE` transitions to `MANUAL_TRIAGE_REQUIRED` and discloses local PoC escalation logging without external ITSM paging claims.
3. **Confirmation, Focus Trap, Duplicate Guard, & Cancellation (`K7`, `D05–D07`):** Global shortcuts (`q`, `a`, `1..5`) are isolated while typing inside modal fields. Rationales `< 5` chars (and empty `CORRECT`/`ESCALATE` targets) are rejected before backend invocation. `modal["submitting"]` blocks duplicate submissions. Pressing `Esc` cancels with zero SQLite transitions or audit events.
4. **Concurrency Conflict & Persistence Failure Safety (`K8`, `K9`, `D12–D14`):** Concurrent external finalization or revision updates trigger `ReviewStateConflictError` / `StaleDossierVersionError` inside `AuthorizedReviewManager`'s `BEGIN IMMEDIATE` transaction; the TUI catches the conflict, reloads the finalized state (`REVIEW LOCKED - FINALIZED`), and never creates a second final review. Simulated `sqlite3.OperationalError` during commit keeps the modal open with `Persistence/audit failure (no changes committed)` and never displays false success. `reconcile_review_audit` confirms `chain_valid == True` and `unreconciled_orphans == []`.

---

## Deliverable I: Performance and Responsiveness

Reproducible measurements captured via `.venv/bin/python evidence/p2-06-dashboard-usability-20261126T022200Z/measure_performance.py` (`evidence/p2-06-dashboard-usability-20261126T022200Z/performance_metrics.json`) on Python `3.12.14` with `16` seeded incidents (`12` `HUMAN_REVIEW` dossiers + `4` `EVIDENCE_COLLECTED` running incidents):

| Metric | Median | P95 | Max | Notes |
|---|---|---|---|---|
| **Cold CLI Startup (`sre_dashboard.py --help`)** | `1523.82 ms` | `1600.76 ms` | `1600.76 ms` | One-time Python interpreter + Rich/schema module import |
| **Atomic SQLite Snapshot Refresh (`16` incidents)** | `6.83 ms` | `7.67 ms` | `8.98 ms` | Single `store.transaction(immediate=False)` across 4 tables |
| **Overview Render (`80x24` / `100x30` / `120x40` / `160x50`)** | `9.77–14.06 ms` | `11.81–15.65 ms` | `12.42–16.37 ms` | Sub-17 ms full frame across all supported terminal sizes |
| **Full Detail Render (`80x24` / `100x30` / `120x40` / `160x50`)** | `11.08–12.22 ms` | `12.85–20.18 ms` | `13.36–23.09 ms` | Includes lineage, temporal evaluation, and sanitization |
| **Keystroke Dispatch (`100` navigation steps)** | `0.00 ms` | `0.03 ms` | `68.21 ms` | Non-blocking in-memory view-state transitions |
| **Memory Across `100` Navigation Steps (`tracemalloc`)** | — | — | `805.99 KiB` peak | Net retained delta `+317.20 KiB` (bounded snapshot cache) |
| **Backend Probe Frequency (`25` Health Tab Renders)** | `1` probe | — | `1` probe | Cached within `10.0s` TTL (`0` LLM calls triggered by UI rendering) |

---

## Deliverable J: Modified and Added Files

All changes below are new `P2-06` uncommitted work on top of `438c31dc1a993d1e30115be62a4a934f4dd877b7`:

| File Path | Action | Purpose & Defect Addressed | Compatibility Implications | Related Tests |
|---|---|---|---|---|
| `orchestrator/console_view_models.py` | **Added** | Atomic `AuthoritativeSnapshotCoordinator`, shared `IncidentDetailVM` / `build_incident_detail_vm`, `ConsoleDesignTokens` (`TOKENS_COLOR`, `TOKENS_MONO`), CJK-safe `compact_identifier`, and `sanitize_terminal_text` (`STATE-01..06`, `UX-04..08`) | Pure additive presentation/read-model module; zero changes to backend schemas or domain classes | `test_p2_06_dashboard_usability_state.py`, `test_c19_usability_console.py` |
| `orchestrator/usability_console.py` | **Modified** | Global Status Strip, priority triage queue, 6 detail lenses, `[` / `]` / `I` / `B` navigation, `[?]` help modal, version-bound 2-step review confirmation modal, persistent `cbreak` PTY loop, `<68x16` min-size guard (`STATE-01..05`, `UX-01..07`) | Preserves `_MENU_ORDER`, `DashboardRepository`, `ReviewActionController`, `DashboardViewport`, `_ScrollableContent`, `build_grafana_incident_url`, `_dossier_detail` | `test_p2_06_dashboard_usability_state.py`, `test_c19_usability_console.py`, `test_p1_05` (`J14`) |
| `scripts/review_console.py` | **Modified** | Unified CLI rendering with `build_incident_detail_vm`, added documented CLI flag aliases (`--dossier`, `--reviewer`, `--role`, `--view-only`, `--export-handover`, `--create-ticket`), and explicit interactive confirmation (`AC-46`, `K7`) | Backward-compatible with existing `--incident-id`, `--dossier-file`, `--reviewer-ref`, `--reviewer-role`, `--rationale` flags | `test_c16_human_review.py`, `test_p1_04`, `test_p1_05`, `test_p2_06` |
| `scripts/sre_dashboard.py` | **Modified** | Added `--refresh-interval` and `--ascii` CLI options (`F10`, `E09`) | Backward-compatible defaults preserved | `test_p2_06_dashboard_usability_state.py` |
| `docs/HANDBOOK_OPERASIONAL.md` | **Modified** | Updated documented TUI keyboard shortcuts, detail lenses, two-step review confirmation workflow, and `--refresh-interval`/`--ascii` flags (`D2`, `Gate 9`) | Documentation-only update | Manual & link inspection |
| `tests/test_p2_06_dashboard_usability_state.py` | **Added** | `10` comprehensive behavioral, race/conflict, adversarial display, WCAG, live in-process stack, CLI/TUI parity, and real subprocess PTY tests covering `Groups A–G` & `Scenarios O1–O12` | Additive pytest module | Self (`10 passed`) |
| `evidence/p2-06-dashboard-usability-20261126T022200Z/*` | **Added** | Before/after `PNG`/`SVG`/`TXT` captures, real PTY `.ansi` traces, `capture_after_state.py`, `measure_performance.py`, `performance_metrics.json`, `dlp-sink-scan.json`, and this report | Isolated under new `P2-06` evidence folder; historical `C02`/`C21` artifacts untouched | `dlp_sink_scanner.py` (`PASS`) |

---

## Deliverable K: Test Results

 suites are reported separately below without overlapping aggregate inflation:

| Suite | Exact Command | Passed | Failed | Errors | Skipped | Duration | Notes |
|---|---|---|---|---|---|---|---|
| **1. New P2-06 Suite** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -q tests/test_p2_06_dashboard_usability_state.py --tb=short` | `10` | `0` | `0` | `0` | `10.54s` | Covers `Groups A–G`, `Scenarios O1–O12`, live FastAPI+Watcher parity, WCAG AA, and real subprocess PTY |
| **2. Async Banking Simulator** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p anyio -q tests/test_banking_simulator.py --tb=short` | `6` | `0` | `0` | `0` | `6.44s` | Requires `-p anyio` when plugin autoload is disabled |
| **3. Broader Offline Repository Suite (`Gate 8`)** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -q tests --ignore=tests/test_c03_compose_live.py --tb=short` | `811` | `1`* | `4`* | `3`** | `50.37s` | **Zero new regressions.** Includes `C16`, `C19`, `C20`, `P0-01`, `P0-02`, `P1-03`, `P1-04`, `P1-05`, and `P2-06` |
| **4. Multi-Sink DLP Scan** | `.venv/bin/python scripts/dlp_sink_scanner.py evidence/p2-06-dashboard-usability-20261126T022200Z/... -o .../dlp-sink-scan.json` | `38` files | `0` | `0` | `0` | `<1.0s` | `clean: true`, `total_violations: 0` |
| **5. Live Docker Compose Suite (`Not Executed`)** | `tests/test_c03_compose_live.py` | — | — | — | — | Not run | **Environment Blocker:** `docker info` non-zero (`DOCKER_DAEMON=NOT_RUNNING` on host) |

*\*Historical Stage 3A Freeze Guard Classification (`1 failed, 4 errors`):* `tests/test_c21_benchmark.py::test_preflight_freeze_reverification_matches_stage_3a` and the 4 setup fixtures in `tests/test_c22_reproducibility_handover.py` intentionally compare working-tree `orchestrator/` file hashes against the frozen Stage 3A snapshot (`evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json`), which drifted as soon as authorized `P0-01`, `P0-02`, `P1-03`, `P1-04`, `P1-05`, and `P2-06` fixes modified `orchestrator/`. Per `INV-15`, `final-release-manifest.json` was **not** regenerated and remains byte-identical (`SHA-256: b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f`).  
*\*\*Skipped (`3`):* The 3 async coroutines in `tests/test_banking_simulator.py` when `-p anyio` is omitted; verified `6/6` passing in Suite #2 above.

---

## Deliverable L: Safety and Acceptance Matrix

### 1. Non-Negotiable Safety Invariants (`INV-01` through `INV-18`)
| ID | Invariant | Status | Concrete Evidence |
|---|---|---|---|
| `INV-01` | Zero Auto-Remediation | **PASS** | `PolicyGateway` rejects `restart_service` (`test_group_g`); UI exposes only read-only navigation + human review (`auto_action_triggered=False`) |
| `INV-02` | `RULE-007` (Never `VERIFIED` via UI/AI) | **PASS** | `CALIBRATION_LIMITATION_NOTE`, `build_human_correction_payload` blocks `VERIFIED`, `sanitize_terminal_text` neutralizes spoofed `\bVERIFIED\b` (`test_group_c`, `test_group_d`, `test_group_e`) |
| `INV-03` | Authoritative State | **PASS** | `AuthoritativeSnapshotCoordinator` reads strictly from `WorkflowStateStore`; zero secondary domain state machine (`test_group_a`) |
| `INV-04` | Human Authority | **PASS** | `open_review_modal` + `AuthorizedReviewManager` enforce human role & caller-asserted identity disclosure (`test_group_d`) |
| `INV-05` | Review Integrity | **PASS** | `BEGIN IMMEDIATE` atomicity, `target_version` conflict guard, `[ORIG AI]` preservation, `reconcile_review_audit` (`test_group_d`, `test_p0_02_*`) |
| `INV-06` | Administrative Closure | **PASS** | `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED` (`diagnosis_verified=False, technical_resolved=False`) across TUI, CLI, MD, HTML (`after/13_*.png`, `test_live_synthetic_stack_*`) |
| `INV-07` | Evidence Integrity | **PASS** | Calls `evaluate_evidence_temporal_validity` & `verify_evidence_integrity_and_scope` directly; unresolved refs flagged `[UNRESOLVED REFERENCE]` (`test_group_b`, `after/06..07_*.png`) |
| `INV-08` | Confidence Integrity | **PASS** | Never recalculates or invents `0.8/0.5/0.2` for unscored priors; bans green on `SUPPORTED` (`test_group_c`, `test_wcag_*`) |
| `INV-09` | SOP Integrity | **PASS** | Preserves `SOP_GAPS` classifications, competing-SOP warnings, and RRF score disclaimers (`after/08..10_*.png`, `test_group_c`) |
| `INV-10` | Manual Verification (`NOT_PERFORMED`) | **PASS** | Renders `STATUS=NOT_PERFORMED | auto_execution_allowed=False` without fake checkoff controls (`after/10_*.png`, `test_group_c`) |
| `INV-11` | Ground Truth Isolation | **PASS** | `_GT_KEY_VALUE_RE` + `DISALLOWED_STRING_PATTERNS` + `verify_ground_truth_isolation` (`test_group_e`, `test_live_synthetic_stack_*`) |
| `INV-12` | Policy Gateway | **PASS** | `MCP-01` & `MCP-02` verified in `test_group_g`; zero gateway changes |
| `INV-13` | Sensitive Data Protection | **PASS** | `DeterministicSanitizer` (`SEC-03`) in `sanitize_terminal_text` + `dlp_sink_scanner.py` (`0` violations across `38` artifacts) |
| `INV-14` | Frozen Contracts | **PASS** | All `19` `evidence/c02-20261109T070500Z/C02/contracts/*.json` SHA-256 hashes verified unchanged |
| `INV-15` | Frozen Release Baseline | **PASS** | `final-release-manifest.json` SHA-256 verified unchanged (`b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f`) |
| `INV-16` | Historical Integrity | **PASS** | Zero historical DBs or prior evidence folders modified (`git status -s`) |
| `INV-17` | Safe Display | **PASS** | Strips ANSI CSI/OSC/DCS, C0/C1, BiDi `\u202e`, renders Rich markup literally via `Text(...)`, neutralizes spoofed `VERIFIED` (`test_group_e`) |
| `INV-18` | Scope Control | **PASS** | Retained Rich TUI framework; zero backend architecture redesign; stopped cleanly before `P2-07` |

### 2. Acceptance Criteria (`AC-01` through `AC-55`)
| AC | Criterion | Status | Supporting Evidence |
|---|---|---|---|
| `AC-01` | Current dashboard and repository baseline established | **PASS** | Deliverable B, `before/01..05_*`, `before/pty_before_session.ansi` |
| `AC-02` | P1-04 and P1-05 dependencies inspected | **PASS** | Deliverable B; `test_p1_04` (`72 passed`) & `test_p1_05` (`72 passed`) |
| `AC-03` | Actual operator workflows documented | **PASS** | Deliverable C, D, G (`Scenarios O1–O12`) |
| `AC-04` | Confirmed UX defects identified and addressed | **PASS** | Deliverable C (`STATE-01..06`, `UX-01..08`) |
| `AC-05` | Information hierarchy supports rapid incident triage | **PASS** | Global Status Strip + priority triage sorting + symptom preview (`after/01_*.png`, `test_group_a`) |
| `AC-06` | Detailed investigation information remains accessible | **PASS** | 6 detail lenses (`All`, `Overview`, `Hypotheses`, `Evidence`, `SOP`, `Review`) (`test_group_b`) |
| `AC-07` | Visual styling is consistent and terminal-native | **PASS** | `ConsoleDesignTokens` (`console_view_models.py`), `after/01..18_*.png` |
| `AC-08` | Important statuses do not rely solely on color | **PASS** | Bracketed ASCII tags (`[CRIT]`, `[SUPPORTED]`, `[FOCUSED]`) + monochrome test (`test_group_e`) |
| `AC-09` | Navigation and keybindings are predictable | **PASS** | `[?]` help modal, `HANDBOOK_OPERASIONAL.md`, `test_group_b` |
| `AC-10` | Focus management is coherent | **PASS** | Explicit `[FOCUSED]` border/title, modal input isolation, return stack (`test_group_b`, `test_group_d`) |
| `AC-11` | Long content handled without hiding essential warnings | **PASS** | Scrollable detail viewports, compact 2-line lens header, middle-ellipsis IDs (`test_group_e`) |
| `AC-12` | Incident selection remains stable across refreshes | **PASS** | `highlighted_incident_id` anchor verified across priority insertions (`test_group_a`) |
| `AC-13` | Domain and transient UI states remain distinct | **PASS** | `initial_loading`, `review_modal`, `is_stale_last_known` never mutate `WorkflowStateStore` (`test_group_a`, `test_group_f`) |
| `AC-14` | Dashboard displays authoritative incident state | **PASS** | Single-transaction SQLite snapshot from `WorkflowStateStore` (`test_group_a`) |
| `AC-15` | Dossier and review revisions remain consistent | **PASS** | Atomic read of `dossiers` + `human_reviews`; `v1 -> v2` `CORRECT` verified (`test_group_d`) |
| `AC-16` | Stale asynchronous results cannot overwrite newer views | **PASS** | `apply_external_snapshot` generation guard & `apply_async_snapshot` incident guard (`test_group_a`) |
| `AC-17` | Concurrent final reviews are reflected accurately | **PASS** | Concurrent `REJECT` caught on stale `APPROVE` submit and reloaded (`test_group_d`) |
| `AC-18` | Review actions cannot falsely report success | **PASS** | Simulated `sqlite3.OperationalError` & conflict tests (`test_group_d`) |
| `AC-19` | Closed incidents remain locked against incompatible review actions | **PASS** | `REVIEW LOCKED - FINALIZED (CLOSED/REJECTED)` + `open_review_modal == False` (`after/13_*.png`, `test_group_d`) |
| `AC-20` | Loading, empty, partial, and failure states are understandable | **PASS** | `after/03_*.png`, `after/10_*.png`, `after/14_*.png`, `after/15_*.png`, `test_group_f` |
| `AC-21` | Last-known data is not falsely represented as current | **PASS** | `STALE LAST-KNOWN DATA` banner + `Store:ERROR` (`after/14_*.png`, `test_group_a`) |
| `AC-22` | Refresh behavior is bounded and responsive | **PASS** | `10s` probe TTL (`1` probe across `25` renders), `6.83 ms` median DB snapshot (`performance_metrics.json`) |
| `AC-23` | Rendering does not trigger unnecessary LLM investigations | **PASS** | Pure SQLite read-only snapshot; `0` LLM requests (`performance_metrics.json`, `test_group_f`) |
| `AC-24` | Investigation progress reflects actual workflow stages | **PASS** | 9-stage `MANDATORY_STATES` bar (`[x:RCV]->...->[*:EVD]`) (`after/03_*.png`, `test_group_a`) |
| `AC-25` | Runtime model and fallback mode displayed accurately | **PASS** | Distinguishes `AI MODEL (ONLINE)`, `FALLBACK (RULE ENGINE)`, `OFFLINE (DETERMINISTIC)` (`test_c19`, `test_p2_06`) |
| `AC-26` | Confidence values preserve authoritative backend results | **PASS** | Exact persisted `confidence_score` rendered; unscored priors never mapped to `80%` (`test_group_c`) |
| `AC-27` | Confidence labels and rank semantics are coherent | **PASS** | Uses `confidence_label_for_score` (`HIGH >= 0.70`, `MEDIUM >= 0.40`, `LOW < 0.40`) & persisted rank order (`test_group_c`) |
| `AC-28` | Calibration limitations are not misrepresented | **PASS** | `CALIBRATION_LIMITATION_NOTE` (`[5%-85% cap], uncalibrated`) visible on hypotheses view (`after/04_*.png`, `test_group_c`) |
| `AC-29` | Hypothesis support and contradiction status remain visible | **PASS** | `[SUPPORTED]`, `[PARTIAL]`, `[UNSUPPORTED]`, `[CONTRADICTED]` + `+sup / -contra` counts (`after/04..05_*.png`) |
| `AC-30` | Evidence source and identity are inspectable where authorized | **PASS** | `evidence_id`, `tool_name`, `source_ref`, `service_id`, `sha256` in Evidence Lineage (`after/06_*.png`) |
| `AC-31` | Evidence temporal relevance and freshness remain accurate | **PASS** | `[CURRENT_FRESH]`, `[HISTORICAL_VALID]`, `[STALE_AT_ASSESSMENT]`, `[OUTSIDE_WINDOW]` from `evidence_lineage.py` (`after/06..07_*.png`) |
| `AC-32` | Missing evidence metadata is disclosed honestly | **PASS** | Explicit `unavailable` / `not recorded` / `[MISSING SOURCE]` / `[UNRESOLVED REFERENCE]` (`test_group_b`, `test_group_c`) |
| `AC-33` | SOP availability classifications remain accurate | **PASS** | `APPLICABLE_SOP_FOUND`, `CONFLICTING_OR_COMPETING_SOPS`, `RETRIEVAL_UNAVAILABLE`, `NO_APPLICABLE_RUNBOOK` (`after/08..10_*.png`) |
| `AC-34` | Retrieval and context delivery are distinguished where supported | **PASS** | `retrieved`, `eligible`, `included_in_llm_prompt`, `omitted` (`compaction` rung) vs `not recorded` (`after/08..09_*.png`, `test_group_c`) |
| `AC-35` | Restricted SOP and evidence data remain protected | **PASS** | Sanitized excerpts only + `SEC-03` + GT scrubbing + `dlp_sink_scanner.py` (`test_group_e`, `test_group_g`) |
| `AC-36` | Manual verification remains visibly pending (`NOT_PERFORMED`) | **PASS** | `STATUS=NOT_PERFORMED` + `SOP_BACKED` vs `GENERAL_GUIDANCE` badges (`after/08..10_*.png`, `test_group_c`) |
| `AC-37` | Human Review decisions preserve existing semantics | **PASS** | `APPROVE`, `REJECT`, `CORRECT` (`v2`), `ESCALATE` verified end-to-end (`test_group_d`, `test_c16`) |
| `AC-38` | Administrative closure is distinguished from technical resolution | **PASS** | `ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED (diagnosis_verified=False, technical_resolved=False, ...)` (`after/12..13_*.png`, `test_live_synthetic_stack_*`) |
| `AC-39` | Review confirmation, cancellation, and failure handling are safe | **PASS** | Modal rationale validation, `Esc` zero-mutation cancel, conflict & DB error handling (`test_group_d`) |
| `AC-40` | Compact, standard, and wide terminal layouts are verified | **PASS** | Verified at `80x24`, `100x30`, `120x40`, `160x50`, and `<68x16` (`after/01,02,15,16,18_*.png`, `test_group_e`) |
| `AC-41` | Dynamic resize is handled safely | **PASS** | Preserves selection, focus, and unsent modal rationale across resizes + `TIOCSWINSZ` PTY resize (`test_group_e`, `test_real_pty_*`) |
| `AC-42` | Untrusted terminal content cannot manipulate authoritative presentation | **PASS** | ANSI/OSC/BiDi/Rich-markup/`VERIFIED` spoofing neutralized (`test_group_e`) |
| `AC-43` | Actual representative rendering artifacts are produced | **PASS** | `5` before + `18` after `PNG`/`SVG`/`TXT` snapshots + `2` real PTY `.ansi` traces (`visual_evidence_manifest.json`) |
| `AC-44` | Before/after visual differences are documented honestly | **PASS** | Deliverables C & F |
| `AC-45` | Operator workflow tests pass | **PASS** | `Scenarios O1–O12` (`10/10` tests in `test_p2_06_dashboard_usability_state.py`) |
| `AC-46` | CLI/TUI/dossier presentation remains consistent | **PASS** | `test_live_synthetic_stack_tui_cli_dossier_consistency_and_frozen_contracts` (`TUI == CLI == MD == HTML`) |
| `AC-47` | P0-01 regressions remain passing | **PASS** | Included in Gate 8 run (`811 passed`) |
| `AC-48` | P0-02 regressions remain passing | **PASS** | `test_p0_02_human_review_semantics.py` & `test_p0_02_hardening.py` passing (`100%`) |
| `AC-49` | P1-03 regressions remain passing | **PASS** | `test_p1_03_verification.py` passing (`100%`) |
| `AC-50` | P1-04 and P1-05 regressions remain passing | **PASS** | `test_p1_04_rag_reasoning_confidence.py` (`72 passed`) & `test_p1_05_evidence_traceability_freshness.py` (`72 passed`) |
| `AC-51` | `RULE-007` and zero auto-remediation remain enforced | **PASS** | `INV-01` & `INV-02` verified across all 4 output surfaces + `PolicyGateway` (`test_group_g`) |
| `AC-52` | Ground Truth isolation and authorization remain intact | **PASS** | `verify_ground_truth_isolation` + `_GT_KEY_VALUE_RE` + reviewer role checks (`test_group_d`, `test_group_e`, `test_live_synthetic_stack_*`) |
| `AC-53` | Frozen contracts and release manifest remain unchanged | **PASS** | `shasum -a 256` verified on `final-release-manifest.json` and all `19` `C02` schemas |
| `AC-54` | Focused and broader regression outcomes are recorded accurately | **PASS** | Deliverable K (including explicit classification of Stage 3A manifest file-list drift & `DOCKER_DAEMON=NOT_RUNNING`) |
| `AC-55` | No unauthorized scope expansion occurs | **PASS** | Stopped after `P2-06`; no web migration, no auto-remediation, no `git commit`/`git push`, no `P2-07` work |

---

## Deliverable M: Remaining Risks and Final Decision

### 1. Remaining Limitations & Environment Boundaries
1. **Docker Compose Live Stack Blocker (`Environment`):** `docker info` returned non-zero (`DOCKER_DAEMON=NOT_RUNNING`) on this workstation, so `tests/test_c03_compose_live.py` (live containerized Prometheus/Loki/Tempo/Qdrant stack) was not executed. End-to-end runtime pipeline parity was verified via in-process `FastAPI` + `LiveAlertWatcher` + `DeterministicInvestigator` + real SQLite + real POSIX PTY (`test_live_synthetic_stack_tui_cli_dossier_consistency_and_frozen_contracts`).
2. **Polling-Based Cross-Process Refresh (`Architecture`):** `SREDashboard` polls SQLite at a bounded interval (`2.0s` default) rather than using OS file-watch or IPC push events. Concurrent state transitions occurring between polls are enforced authoritatively by `AuthorizedReviewManager`'s SQLite `BEGIN IMMEDIATE` transaction lock on submission.
3. **Caller-Asserted Local PoC Reviewer Identity (`PoC vs Production`):** Unless external OIDC/SSO `auth_context` is configured, CLI/TUI reviewer identity (`--reviewer-ref`, `--reviewer-role`) is caller-asserted for local lab simulation and is explicitly labeled `Local PoC caller-asserted identity (unauthenticated)` in both detail views and confirmation modals. Production deployment would require cryptographic SSO/mTLS identity binding.
4. **Terminal Accessibility Scope (`Platform`):** Screen readers interacting with full-screen ANSI `Live` TUIs vary across terminal emulators; `--ascii` mode (`scripts/sre_dashboard.py --ascii`) and linear CLI output (`scripts/review_console.py --view-only`) provide clean plain-text alternatives.
5. **Post-Stage-3A Release Manifest Obligation (`Release Governance`):** Because `P0-01` through `P2-06` modified `orchestrator/` while `final-release-manifest.json` remained frozen per `INV-15`, a formal release-manifest re-baselining step will be required only when authorized in a future release gate after `P2-07`.

### 2. Final Implementation Status
**`FIXED`**

All mandatory `P2-06` functional, state-consistency, UX, responsive layout, accessibility, visual verification, and safety invariant requirements are implemented and verified within the Simulation PoC boundary. Stopping here as instructed and awaiting explicit authorization before `P2-07 — Architecture Compliance Verification`.
