# Draft Release Candidate Supersession Notice (P2-06R)

- **Status:** `DRAFT RELEASE CANDIDATE - NOT APPROVED / NOT FROZEN`
- **Production Readiness:** `NOT ESTABLISHED`
- **New Draft Candidate ID:** `rc-p2-06r-20261126T071500Z-draft`
- **New Draft Manifest Path:** `evidence/p2-06r-dashboard-ux-refinement-20261126T063800Z/draft-release-candidate/candidate-release-manifest-p2-06r-draft.json`

## 1. Scope of Supersession

P2-06R applied presentation-layer UX refinement and progressive disclosure to the terminal SRE Investigation & Human Review Console without altering investigation logic, Hybrid RAG retrieval, evidence validation, confidence scoring, human review semantics, workflow state transitions, Policy Gateway boundaries, frozen `C02` schemas, or Ground Truth isolation.

Consequently, the earlier P2-07 draft release candidate:

- **Superseded Draft Candidate ID:** `rc-p2-07-20261126T040200Z-draft`
- **Preserved Historical Path (UNMODIFIED):** `evidence/p2-07-architecture-compliance-20261126T040200Z/draft-release-candidate/candidate-release-manifest.json`
- **Preserved SHA-256:** `bcba64c75c3239db68d03ac5cf568d2a56f348862906bb07a601995841ff2ccd`

is **superseded specifically for the affected dashboard presentation, operator handbook, and test files** listed below:

| File | Previous P2-07 Draft SHA-256 | Updated P2-06R Draft SHA-256 | Change Category |
|---|---|---|---|
| `orchestrator/console_view_models.py` | `1dd12605e70148ca894ee25d9f52a91c52a1fc1aafaabfe04b70b91e987635ce` | `b07cc544890ccc84eb6be924dcf131269cb89f28403f4efc3df28b0e22419067` | Presentation ViewModel (short evidence IDs, status semantics note, `llm_context_diagnostics` visibility, summary cap) |
| `orchestrator/usability_console.py` | `2e9644cfe7e94c5bbdf158447baa7fcc78efc9ffd6de4c50b0d502356922a2a1` | `98bc0a608a6502c3b5c4c6afb2df01a5f141df6da94a14809aa0636bc2f23076` | Terminal UI progressive disclosure, compact header, borderless collapsible sidebar, bounded measure, Rich `Text` safety |
| `docs/HANDBOOK_OPERASIONAL.md` | *(untracked in runtime hashes)* | `9aad6df23894756e5fbdaa17451a80c63b9e6c1d5c0ed0a831f31238d9533472` | Updated keyboard & View Lens operator documentation |
| `tests/test_p2_06r_dashboard_ux_refinement.py` | *(new)* | `0dde5811fb4be7a2a4cf4cbb30a7bb7963f5f85a986a882558ccd4bf4cef3c0a` | New 20-point P2-06R UX refinement regression suite (11 test cases) |
| `tests/test_p2_06_dashboard_usability_state.py` | *(test file)* | `67a7b6e5eb0504e022572033dd0fd8341c92ca4a3d821067664ff7638eba3d2d` | Updated default lens navigation assertions from `all` -> `overview` |
| `tests/test_c19_usability_console.py` | *(test file)* | `4611c23602cf894f07955e99983378ae3a0a15ecad837aa70f4b247f43421696` | Navigated legacy assertions to `technical` / `all` lenses |
| `tests/test_p1_05_evidence_traceability_freshness.py` | *(test file)* | `d7f14993d7a0fabbdf4a34fcc84f94cb9e1702b7e3cb22eb764928146e1b914c` | Navigated TUI provenance assertion to Evidence detail view |
| `tests/test_p0_02_hardening.py` | *(test file)* | `a4fe01d71f8a5eda5c7790cddd81b379f22cb36d9624aab397662551e78e8e08` | Verified closure disclosure on Overview and trust disclosure on Review view |

## 2. Historical Frozen Artifacts Preserved Untouched

- **Frozen Stage 3A Release Manifest:** `evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json` — SHA-256 `b7fcc5484b83b9f5d67766d1a1b4adb21c215f8c25430ee00ecbeb66ae3d1c4f` (**UNMODIFIED; NOT RE-FROZEN**).
- **Frozen C20 Manifest:** `evidence/c20-20261120T093645Z/C20/final-release-manifest.json` — SHA-256 `5587564a4e99ecdf0d5b71c4e21bdc31caf5e4c079418bedccc6c482238242ca` (**UNMODIFIED**).
- **Frozen C02 Contracts Combined SHA-256:** `ef40fc00d64bad87d7f8f45ffe0af366095d9faec338815287726778c609d663` (**UNMODIFIED**).
- **Restricted Holdout & Ground Truth Seals:** Both verified intact (`6c7fbc74...` and `149deae8...`).

No release re-freeze, commit, or remote push was performed. Explicit project-owner authorization remains required before any formal release freeze.
