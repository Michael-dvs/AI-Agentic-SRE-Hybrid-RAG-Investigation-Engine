# P2-06R — Dashboard UX Refinement & Progressive Disclosure Report

- **Workstream:** `P2-06R — DASHBOARD UX REFINEMENT` (Cognitive Load Reduction, Progressive Disclosure & Terminal-Native Redesign)
- **Evidence Bundle:** `evidence/p2-06r-dashboard-ux-refinement-20261126T063800Z/`
- **Baseline Commit:** `a4cb6d0` (`main` — clean working tree prior to P2-06R)
- **Runtime:** Python `3.12.14` (`.venv`), `rich`, `cairosvg`, `pytest 8.3.4`, `anyio 4.16.0`, macOS `arm64`
- **Final Status:** **`FIXED`**

---

## Deliverable A — UX Audit (Confirmed Visual & Cognitive Load Findings)

Baseline inspection of the live incident `inc-live-transaction-service-3b7751e91b` in `orchestrator_state.db` reproduced the exact `207x49` reference viewport (lines `1-38/228`) and standard `120x40` renders (`before/01`–`before/06`):

1. **Excessive information density & vertical scrolling:** Opening an incident defaulted to `all` (`All Sections`), dumping **228 lines** at `207x49` (`[Scroll: line 1-38/228]`) and **369 lines** at `120x40` (`[Scroll: line 1-29/369]`), pushing even Hypothesis #1 off-screen on `120x40`.
2. **Excessive nested borders:** `6` simultaneous boxed Rich `Panel` borders rendered at `207x49` and `5` at `120x40` (outer main panel, permanent sidebar panel, nested header/hypothesis/evidence panels, permanent yellow Review Action Bar box).
3. **Technical metadata ahead of operational triage:** Full incident ID, SHA-256 hash, LLM provider/model (`nvidia/nemotron-3.5-lightning:free`), token counts (`in=1191, out=372`), prompt fingerprint, 9-stage workflow bar, error budget, and topology appeared *above* observed symptoms and leading hypothesis.
4. **Long unbroken identifiers & raw dumps:** Full `ev-inc-live-transaction-service-3b7751e91b-001..012` IDs and all 12 full evidence cards (`164` lines) rendered simultaneously.
5. **Competing navigation & repeated chrome:** Permanent boxed sidebar (wrapping `[1] Active Incidents\n[26]`), global header, View Lens bar, persistent Review Action Bar box, and duplicate shortcut footers competed for attention simultaneously.
6. **Review actions rendered outside review context:** Full `[A] Approve / [R] Reject / [C] Correct / [E] Escalate` bar occupied vertical space even when reading Overview, Hypotheses, Evidence, or SOP views.
7. **Status semantics ambiguity (`PARTIAL` vs `status=SUPPORTED`):** Live dossier displayed `[PARTIAL]` alongside `Confidence Basis: status=SUPPORTED` without explaining why the two differed (`orchestrator/investigator.py` caps unconfirmed LLM dossier `support_status` at `PARTIAL` pending human review while `ClaimValidator` records internal claim corroboration as `SUPPORTED`).
8. **Unrecorded vs recorded RAG context telemetry gap:** Live checkpoints recorded RAG delivery diagnostics under `llm_context_diagnostics` (e.g., `retrieved=3, eligible=3, included_in_llm_prompt=0, omitted=3`, `compaction=2_1_0_0`, `sop_relevance.status=SPECIFIC_COVERAGE_GAP`), which `console_view_models.py` previously missed.
9. **Rich markup bracket stripping defect (found & fixed during visual verification):** Plain strings passed to `Table.add_row()` caused Rich to parse `[api-gateway]` and `[db-dummy, ...]` in `Topology Flow` as markup tags; fixed globally by wrapping dynamic table cells in `rich.text.Text(...)`.

---

## Deliverable B — Updated Information Architecture (Progressive Disclosure)

Reused the existing 2-tier navigation + View Lens model without introducing competing navigation systems:

- **Top-Level Navigation (`[1]`–`[5]`):** Borderless collapsible left rail (`[S]` toggles visibility; auto-collapsed inside incident detail) with concise non-wrapping labels: `[1] Active (N)`, `[2] Archive (N)`, `[3] Health`, `[4] Model`, `[5] Telegram`.
- **Incident Detail View Lenses (`[Tab]` / `[Shift+Tab]`):**
  1. **`Overview` (Default):** Level 1 operational summary answering *what happened, affected service, severity, lifecycle/stage, leading hypothesis, authoritative confidence, support status, evidence counts, key uncertainty, required next action, compact safety* — zero technical noise, fits without scrolling across `80x24`, `100x30`, `120x40`, `140x42`, and `207x49`.
  2. **`Hypotheses`:** Level 2 ranked summary table (collapsed by default); `[Enter]` expands ONLY the selected hypothesis to Level 3 (mechanism, Dossier vs Internal Claim Validation `Status Semantics`, confidence basis, main uncertainty, short evidence IDs, validation limits).
  3. **`Evidence`:** Level 2 scannable table (`Short ID`, `Source`, `Observation Summary`, `Status`, `Temporal`, `Hyp`); `[Enter]` or `[I]` opens Level 3 provenance view with full canonical `evidence_id`, timestamps, query window, values/units, sampling, SHA-256 note, and full observation.
  4. **`SOP & RAG`:** Separates `Retrieval & SOP Summary` (SOP applicability, eligible count, relevance status, truthful `Context Delivery` telemetry, compaction limitations) from expandable authorized citation excerpts (`[Enter]`) and `NOT_PERFORMED` manual verification checks.
  5. **`Review`:** Dedicated Human Review context (incident summary, dossier revision & hash, diagnosis status, leading candidate, key uncertainty, pending checks, reviewer identity & trust disclosure, review eligibility, append-only history, and the **ONLY** surface displaying full `[A] Approve / [R] Reject / [C] Correct / [E] Escalate` controls).
  6. **`Details` (`[D]`):** Level 4 secondary Technical Details & Audit inspector (full incident ID, SHA-256 hash, full observed symptom, provider/model, tokens, prompt fingerprint, timing/tool calls, 9-stage transition timeline, dependency/cascade topology, full confidence formulas & status semantics for all hypotheses, all unknowns & missing sources).
  7. **`All Sections` (`[V]`):** Retained strictly as an optional on-demand audit view; never default.

---

## Deliverable C — Before / After Comparison & Measurable Density Metrics

All renders captured directly from `SREDashboard` against a read-only copy of `orchestrator_state.db` (`inc-live-transaction-service-3b7751e91b` and archived `inc-live-transaction-service-82bdecc894`) as actual `.txt`, `.svg`, and `.png` files in `before/` and `after/`:

| Comparison View & Viewport | Before Artifact | After Artifact | Unclipped Content Lines | Boxed Panels | Vertical Scroll? | Bracket Tokens |
|---|---|---|---:|---:|---|---:|
| **Reference Wide Default (`207x49`)** | `before/01_before_reference_all_207x49.png` | `after/03_wide_overview_207x49.png` | **`228` -> `20` (`-91.2%`)** | **`6` -> `0`** | **`YES (1-38/228)` -> `NO`** | `26` -> `11` |
| **Standard Default Detail (`120x40`)** | `before/03_before_dense_all_sections_120x40.png` | `after/02_default_overview_120x40.png` | **`369` -> `20` (`-94.6%`)** | **`5` -> `0`** | **`YES (1-29/369)` -> `NO`** | `25` -> `11` |
| **Incident Queue List (`120x40`)** | `before/02_before_incident_overview_120x40.png` | `after/01_incident_list_120x40.png` | `40` -> `37` rendered | **`3` -> `0`** | `NO` -> `NO` | `49` -> `39` |
| **Hypotheses View (`120x40`)** | `before/04_before_hypothesis_details_120x40.png` | `after/04_hypotheses_list_120x40.png` (collapsed) / `after/05_expanded_hypothesis_120x40.png` (expanded #1) | **`45` -> `19` (`-57.8%`)** / `36` expanded | **`4` -> `0`** | **`YES (1-29/45)` -> `NO`** | `27` -> `14` |
| **Evidence View (`120x40`)** | `before/05_before_evidence_details_120x40.png` | `after/06_evidence_list_120x40.png` (list) / `after/07_evidence_detail_120x40.png` (detail #2) | **`164` -> `23` (`-86.0%`)** / `24` detail | **`4` -> `0`** | **`YES (1-29/164)` -> `NO`** | `26` -> `9` |
| **Human Review View (`120x40`)** | `before/06_before_human_review_120x40.png` | `after/09_human_review_120x40.png` | `14` -> `23` (consolidated full review context + actions) | **`4` -> `0`** | `NO` -> `NO` | `25` -> `15` |
| **Compact Overview (`80x24`)** | *(unusable dense scroll)* | `after/11a_compact_overview_80x24.png` | **`17` content lines (`21` total)** | **`0`** | **`NO`** | `8` |
| **Responsive Mid (`100x30`)** | *(n/a)* | `after/12a_responsive_overview_100x30.png` | **`24` content lines (`28` total)** | **`0`** | **`NO`** | `10` |
| **Responsive Wide (`140x42`, `160x50`)** | *(n/a)* | `after/12b_responsive_overview_140x42.png`, `after/12c_wide_list_160x50.png` | `20` content lines / bounded `156`-col table | **`0`** | **`NO`** | `11` / `39` |
| **Operational Edge States** | *(n/a)* | `after/13_empty_state_100x30.png`, `after/14_degraded_stale_120x40.png`, `after/15a_finalized_overview_120x40.png`, `after/15b_finalized_review_120x40.png`, `after/16_review_confirmation_modal_120x40.png` | All cleanly formatted, zero overflow | `0` (`1` deliberate modal border on confirmation dialog) | `NO` | `3`–`39` |

---

## Deliverable D — Design Specification (Terminal-Native System)

- **Layout Measure:** `_MaxWidthRenderable` caps detail prose at `MAX_DETAIL_READING_WIDTH = 124` cols and list tables at `MAX_LIST_TABLE_WIDTH = 156` cols so wide (`160x50`, `207x49`) viewports stay calm and scannable.
- **Border & Chrome Discipline:** Horizontal thin rules (`─`) and whitespace replace nested box borders (`0` boxed panels across all primary views; `Panel` reserved strictly for modal dialogs: Help, Two-Step Human Review Confirmation, Minimum-Size Guard).
- **Color Palette (WCAG AA >= 4.5:1 verified + monochrome fallback):** Neutrals (`#f8fafc` primary, `#cbd5e1` secondary, `#94a3b8` muted), restrained semantic colors (`#fca5a5` critical/error, `#fde047` warning/unverified, `#38bdf8` focus accent, `#67e8f9` corroborated observation, `#86efac` strictly reserved for infra connectivity—never confidence or `CLOSED` diagnosis). Zero em dashes (`—`), zero decorative ASCII banners.
- **Short Display Evidence IDs:** `build_short_evidence_ids()` formats long IDs as suffix-preserving `ev-...-002` with deterministic collision widening while preserving full canonical `evidence_id` untouched in domain records and Evidence Detail.
- **Safe Text Rendering:** Every dynamic cell in `Table.add_row()` is wrapped in `rich.text.Text(...)` after `sanitize_terminal_text()` (stripping ANSI CSI/OSC/DCS, C0/C1, BiDi overrides, SEC-03 secrets, Ground Truth keys, and spoofed `VERIFIED` tokens) so literal brackets (`[api-gateway]`, `[bold red]`) are never parsed or stripped by Rich markup.

---

## Deliverable E — Functional & Interactive Verification

- **Real Subprocess PTY Walkthrough (`pty_interactive_verification.json`):** Drove `scripts/sre_dashboard.py` over `pty.openpty()` against a temporary copy of `orchestrator_state.db` through:
  1. Boot into Incident List (`SRE INVESTIGATION CONSOLE`, `Active Incidents`).
  2. Focus list (`RIGHT`) -> open incident (`ENTER`) -> landed in `Overview` with Leading Hypothesis, Key Uncertainty, Next Action, zero review action buttons, zero token usage.
  3. `TAB` -> `Hypotheses` (collapsed) -> `ENTER` (expanded with `Status Semantics` & `Confidence Basis`).
  4. `I` -> jumped directly to canonical Evidence Detail (`ev-inc-live-transaction-service-3b7751e91b-002`, `Source / Tool`).
  5. `B` -> returned to Hypotheses -> `TAB` through `Evidence`, `SOP & RAG` (`Context Delivery`), `Review` (`[A] Approve`, `Authorized Review Actions`), and `Details` (full ID + intact `[api-gateway]` topology).
  6. Live PTY resize `80x24` -> `207x49` -> `Q` clean exit (`returncode=0`, `"closed without automated actions"`).
- **Render Performance (`120x40`, 10-frame average per lens, zero LLM calls):**
  - `overview`: **`1.02 ms/frame`**
  - `hypotheses`: **`1.84 ms/frame`**
  - `review`: **`1.86 ms/frame`**
  - `technical`: **`2.67 ms/frame`**
  - `sop`: **`3.08 ms/frame`**
  - `evidence`: **`3.43 ms/frame`**
- **DLP Sink Scan (`dlp-scan-after-report.json`, `dlp-scan-before-report.json`):** `scripts/dlp_sink_scanner.py` scanned all `21` after-state targets (`after/`) and `7` before-state targets (`before/`) -> **`clean: true`, `0 violations`**. *(Note: `draft-release-candidate/candidate-release-manifest-p2-06r-draft.json` stores filename/SHA-256 inventory entries matching P2-07's manifest schema, containing no ground-truth payload content.)*

---

## Deliverable F — Test Execution Report

| Suite | Executed Command | Exit Code | Passed | Failed | Skipped | Duration |
|---|---|---:|---:|---:|---:|---:|
| **P2-06R New UX Suite** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -v tests/test_p2_06r_dashboard_ux_refinement.py --tb=short` | `0` | **`11`** | `0` | `0` | `2.63s` |
| **Focused Dashboard & Remediation Suite (10 files)** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -q tests/test_p2_06r_dashboard_ux_refinement.py tests/test_p2_06_dashboard_usability_state.py tests/test_p2_07_architecture_compliance.py tests/test_c19_usability_console.py tests/test_c16_human_review.py tests/test_p0_02_hardening.py tests/test_p1_03_verification.py tests/test_p1_04_rag_reasoning_confidence.py tests/test_p1_05_evidence_traceability_freshness.py tests/test_c20_capacity_resilience.py --tb=short` | `0` | **`228`** | `0` | `0` | `26.29s` |
| **Full Active Offline Suite (`S3-Active`)** | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -q tests --ignore=tests/test_c03_compose_live.py --ignore=tests/test_c21_benchmark.py --ignore=tests/test_c22_reproducibility_handover.py --tb=short` | `0` | **`823`** | `0` | `0` | `66.05s` |

*(Excluded `test_c03_compose_live.py` live Docker suite and `test_c21_benchmark.py` / `test_c22_reproducibility_handover.py` intentional Stage 3A freeze-guard suites per P2-07 Deliverable M convention; frozen Stage 3A manifest integrity verified directly via SHA-256 `b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f`.)*

---

## Deliverable G — Modified & Added Files

- **Modified Runtime Presentation Files (2):**
  - `orchestrator/console_view_models.py` (`b07cc544890ccc84...`)
  - `orchestrator/usability_console.py` (`98bc0a608a6502c3...`)
- **Modified Operator Documentation (1):**
  - `docs/HANDBOOK_OPERASIONAL.md` (`9aad6df23894756e...`)
- **Added / Updated Test Files (5):**
  - `tests/test_p2_06r_dashboard_ux_refinement.py` *(new — covers all 20 Section 12 items)*
  - `tests/test_p2_06_dashboard_usability_state.py` *(updated legacy `all` -> `overview` navigation assertions; deterministic evidence jump check)*
  - `tests/test_c19_usability_console.py` *(navigated legacy provenance/detail checks to `technical`/`all`)*
  - `tests/test_p1_05_evidence_traceability_freshness.py` *(navigated TUI evidence provenance check to Evidence Detail)*
  - `tests/test_p0_02_hardening.py` *(verified closure on Overview and trust mode on Review)*
- **New Self-Contained Evidence Artifacts:**
  - `evidence/p2-06r-dashboard-ux-refinement-20261126T063800Z/` (`before/`, `after/`, `capture_p2_06r_after.py`, `pty_interactive_verification.json`, `dlp-scan-after-report.json`, `dlp-scan-before-report.json`, `draft-release-candidate/`, `P2-06R-UX-REFINEMENT-REPORT.md`)

---

## Deliverable H — Release Candidate Impact

- **P2-07 Draft RC (`rc-p2-07-20261126T040200Z-draft`):** Preserved unmodified at `evidence/p2-07-architecture-compliance-20261126T040200Z/draft-release-candidate/candidate-release-manifest.json` (`bcba64c7...`) and formally marked superseded for the affected dashboard/test components.
- **Updated Draft RC (`rc-p2-06r-20261126T071500Z-draft`):** Written separately to `draft-release-candidate/candidate-release-manifest-p2-06r-draft.json` with `SUPERSESSION-NOTICE.md`, clearly labeled **`DRAFT RELEASE CANDIDATE - NOT APPROVED / NOT FROZEN`**.
- **Historical Frozen Artifacts:** `C02` schemas (`ef40fc00...`), `C20` manifest (`5587564a...`), `C21` Stage 3A manifest (`b7fcc548...`), `restricted/` holdout & GT seals (`6c7fbc74...`, `149deae8...`), and `orchestrator_state.db` are all **100% unmodified**. No commit, push, or release freeze executed.

---

## Acceptance Criteria Matrix (`AC-01` – `AC-24`)

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| `AC-01` | Default incident detail view is Overview (not All Sections) | **PASS** | `after/02_default_overview_120x40.png`, `test_p206r_01_to_04`, PTY trace |
| `AC-02` | Representative Overview fits standard viewports without unnecessary vertical scrolling | **PASS** | `requires_vertical_scroll=false` at `80x24`, `100x30`, `120x40`, `140x42`, `207x49` |
| `AC-03` | Overview answers essential operational questions without technical clutter | **PASS** | `after/02_default_overview_120x40.png`, `test_p206r_01_to_04` |
| `AC-04` | Technical metadata omitted from Overview and accessible in Technical Details (`[D]`) | **PASS** | `after/10_technical_details_120x40.png`, `test_p206r_01_to_04` |
| `AC-05` | Visual noise, boxed panels, and vertical density measurably reduced | **PASS** | `-91.2%` lines & `6 -> 0` boxes (`207x49`); `-94.6%` lines & `5 -> 0` boxes (`120x40`) |
| `AC-06` | Clear reading hierarchy, restrained palette, meaningful whitespace, no decorative slop | **PASS** | Inspected PNGs `01`–`16`, WCAG AA tokens, `0` em dashes |
| `AC-07` | Wide viewports constrain reading width (`124` detail / `156` list) cleanly | **PASS** | `after/03_wide_overview_207x49.png`, `after/12c_wide_list_160x50.png` |
| `AC-08` | Compact header shows essential global state only; zero fabricated health indicators | **PASS** | `after/01`, `after/02`, `after/14_degraded_stale_120x40.png` |
| `AC-09` | Sidebar collapsible (`[S]`), auto-collapsed in detail, concise non-wrapping labels | **PASS** | `after/01_incident_list_120x40.png`, `after/02_default_overview_120x40.png` |
| `AC-10` | Hypotheses view lists concisely collapsed by default; selected hypothesis expands on `[Enter]` | **PASS** | `after/04_hypotheses_list_120x40.png`, `after/05_expanded_hypothesis_120x40.png`, `test_p206r_05_06_08_09` |
| `AC-11` | Evidence list uses short display IDs resolving cleanly to full canonical ID & provenance | **PASS** | `after/06_evidence_list_120x40.png`, `after/07_evidence_detail_120x40.png`, `test_p206r_05_06_08_09` |
| `AC-12` | SOP & RAG separates summary from excerpts; truthful context delivery (`llm_context_diagnostics` & unrecorded fallback) | **PASS** | `after/08_sop_and_rag_120x40.png`, `test_p206r_07_10_11_12` |
| `AC-13` | Full Human Review action controls shown ONLY in Review view; concise next-action elsewhere | **PASS** | `after/02`, `after/09_human_review_120x40.png`, `test_p206r_07_10_11_12` |
| `AC-14` | Two-step confirmation modal preserved; never auto-submits; preserves cancel/guards/reload | **PASS** | `after/16_review_confirmation_modal_120x40.png`, `test_p2_06` Group D |
| `AC-15` | `PARTIAL` (frozen dossier) vs `SUPPORTED` (internal ClaimValidator) faithfully explained | **PASS** | `after/02`, `after/05`, `after/10`, `test_p206r_05_06_08_09` |
| `AC-16` | Authoritative confidence score, band, and hypothesis ordering untouched by presentation | **PASS** | `test_p206r_05_06_08_09`, `test_p1_04_rag_reasoning_confidence.py` |
| `AC-17` | Core safety invariants (`RULE-007`, zero auto-remediation, read-only PolicyGateway, GT isolation, frozen contracts) intact | **PASS** | `test_p206r_18_19_20`, `test_p2_07_architecture_compliance.py` |
| `AC-18` | Safety-critical warnings (competing SOPs, retrieval outage, missing sources, unresolved refs, stale data) remain visible in Overview | **PASS** | `after/14_degraded_stale_120x40.png`, `test_p206r_18_19_20` |
| `AC-19` | Finalized incidents (`CLOSED`/`REJECTED`/`ESCALATED`) remain clearly locked with handover disclaimer | **PASS** | `after/15a_finalized_overview_120x40.png`, `after/15b_finalized_review_120x40.png`, `test_p206r_07_10_11_12` |
| `AC-20` | Navigation/expand/resize cause zero domain mutations or LLM calls; stable refresh selection & stale async rejection | **PASS** | `test_p206r_07_10_11_12`, `test_p206r_13_14_15`, `test_p206r_16_17` |
| `AC-21` | Responsive layouts verified across `80x24`, `100x30`, `120x40`, `140x42`, `160x50`, `207x49` + min-size guard | **PASS** | `after/11a`–`12c`, `test_p206r_16_17` (`6/6` parametrized) |
| `AC-22` | Untrusted ANSI, BiDi, Rich markup tags, secrets, GT keys, and spoofed `VERIFIED` safely sanitized | **PASS** | `test_p206r_18_19_20`, `after/10` (`[api-gateway]` preserved literally) |
| `AC-23` | Actual before/after renders + real PTY walkthrough captured, visually inspected, and DLP-clean | **PASS** | `26` captures (`6` before + `20` after), `pty_interactive_verification.json`, `dlp-scan-after-report.json` (`21/21` clean) & `dlp-scan-before-report.json` (`7/7` clean) |
| `AC-24` | All targeted & full active regression suites pass; P2-07 draft RC superseded cleanly without re-freeze/commit/push | **PASS** | `11/11`, `228/228`, `823/823`, `draft-release-candidate/SUPERSESSION-NOTICE.md` |

---

## Deliverable I — Final Status

**`FIXED`** — All `24/24` acceptance criteria (`AC-01`–`AC-24`) passed with real visual renders, real PTY interaction verification, `823/823` active offline regression passes, and `0` DLP violations, while strictly preserving all investigation, safety, and frozen contract boundaries.
