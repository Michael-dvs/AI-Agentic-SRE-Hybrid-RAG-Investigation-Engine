# PROPOSED RE-FREEZE PROCEDURE (REQUIRES EXPLICIT OWNER AUTHORIZATION)
## Status: `DRAFT RELEASE CANDIDATE — NOT APPROVED / NOT FROZEN`

> [!WARNING]
> **DO NOT EXECUTE WITHOUT EXPLICIT PROJECT OWNER AUTHORIZATION.**
> Historical Stage 3A manifests (`evidence/c20-20261120T093645Z/C20/final-release-manifest.json` and `evidence/c21-preflight-20261122T051612608117Z/C21/final-release-manifest.json`) MUST remain preserved as historical records.

### Step-by-Step Owner-Authorized Re-Freeze Sequence

1. **Review P2-07 Compliance Deliverables & Diffs:**
   - Inspect `evidence/p2-07-architecture-compliance-20261126T040200Z/P2-07-EXECUTIVE-COMPLIANCE-REPORT.md`, `frozen_drift_manifest.json`, and `git status` / `git diff`.
2. **Pin Exact Dependency Lockfile (Optional Recommended Hardening `FIND-P207-07`):**
   ```bash
   .venv/bin/pip freeze > requirements.lock
   ```
3. **Commit `P2-06` and `P2-07` Working-Tree Changes Locally (Manual Owner Control — Never Auto-Push):**
   ```bash
   git add orchestrator/ scripts/ docs/ README.md .env.example tests/ evidence/p2-06-dashboard-usability-20261126T022200Z/ evidence/p2-07-architecture-compliance-20261126T040200Z/
   git commit -m "chore(compliance): complete P2-06 usability and P2-07 architecture compliance verification"
   ```
4. **Generate New Post-Remediation Stage 3B Release Freeze (Preserving Historical `C20`/`C21` Directories):**
   - Run `scripts/run_c21_preflight.py` into a **new** timestamped evidence directory (e.g., `evidence/c21-preflight-stage3b-<UTC>/`) and update only the active manifest pointer if authorized by the project owner, **without** modifying historical `c20-20261120T093645Z` or `c21-preflight-20261122T051612608117Z`.
5. **Re-Verify Full Regression Suite Including Freeze Guards:**
   ```bash
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -p anyio -v
   ```
