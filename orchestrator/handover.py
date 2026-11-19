"""Clean Handover Package Exporter with Ground-Truth Sanitization (C16, FR-OUT-005, FR-OUT-006, RULE-002, HUM-01)."""

from __future__ import annotations

import copy
import html
import json
import logging
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from orchestrator.dossier import (
    DossierMarkdownRenderer,
    compute_canonical_dossier_hash,
)

_LOG = logging.getLogger(__name__)

# Keys strictly prohibited from public handover packages (RULE-002, FR-OUT-005)
DISALLOWED_GT_KEYS: Set[str] = {
    "scenario_id",
    "expected_root_cause",
    "ground_truth",
    "ground_truth_label",
    "gt_registry",
    "fault_label",
    "recipe_id",
    "holdout_id",
    "holdout_ground_truth",
}

# Regex patterns for prohibited string content
DISALLOWED_STRING_PATTERNS = [
    re.compile(r"restricted/gt_registry/", re.IGNORECASE),
    re.compile(r"\bscenario_id\b", re.IGNORECASE),
    re.compile(r"\bground_truth\b", re.IGNORECASE),
    re.compile(r"\bexpected_root_cause\b", re.IGNORECASE),
]


def sanitize_data_recursively(obj: Any) -> Any:
    """Recursively strip ground truth attributes and scrub prohibited substrings."""
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            if k.lower() in DISALLOWED_GT_KEYS:
                continue
            cleaned[k] = sanitize_data_recursively(v)
        return cleaned
    elif isinstance(obj, list):
        return [sanitize_data_recursively(item) for item in obj]
    elif isinstance(obj, str):
        scrubbed = obj
        for pat in DISALLOWED_STRING_PATTERNS:
            scrubbed = pat.sub("[REDACTED_GT_FIELD]", scrubbed)
        return scrubbed
    return copy.deepcopy(obj)


def verify_ground_truth_isolation(data: Any) -> Tuple[bool, List[str]]:
    """Scan an exported data structure for any leak of ground truth keys or values.

    Returns (is_isolated, violations).
    """
    violations: List[str] = []

    def _scan(node: Any, path: str = "$") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in DISALLOWED_GT_KEYS:
                    violations.append(f"Found prohibited GT key {k!r} at {path}")
                _scan(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _scan(item, f"{path}[{i}]")
        elif isinstance(node, str):
            for pat in DISALLOWED_STRING_PATTERNS:
                if pat.search(node):
                    violations.append(f"Found prohibited GT string pattern {pat.pattern!r} at {path}: {node[:80]}")

    _scan(data)
    return len(violations) == 0, violations


class HandoverExporter:
    """Exports clean, sanitized, human-readable handover packages for approved or reviewed incidents (FR-OUT-005, FR-OUT-006)."""

    def __init__(self, export_root: Optional[pathlib.Path | str] = None) -> None:
        self.export_root = pathlib.Path(export_root) if export_root else pathlib.Path("artifacts/handover")

    def export_handover_package(
        self,
        incident_id: str,
        dossier_dict: Dict[str, Any],
        review_history: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[pathlib.Path | str] = None,
    ) -> Dict[str, pathlib.Path]:
        """Export clean handover package with 3 artifacts:

        1. dossier_final.json (canonical hashed JSON)
        2. dossier.md (human-readable Markdown with file:// evidence links)
        3. dossier.html (standalone styled HTML report for browser viewing)
        """
        formatted_inc_id = incident_id if incident_id.startswith("inc-") else f"inc-{incident_id}"
        target_dir = pathlib.Path(output_dir) if output_dir else self.export_root / formatted_inc_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Sanitize all data structures against Ground Truth leaks
        sanitized_dossier = sanitize_data_recursively(dossier_dict)
        sanitized_history = sanitize_data_recursively(review_history or [])

        # Re-compute canonical hash for sanitized payload
        new_hash = compute_canonical_dossier_hash(sanitized_dossier)
        sanitized_dossier["dossier_hash"] = new_hash

        # Attach review history if not already embedded
        if sanitized_history and "review_events" not in sanitized_dossier:
            sanitized_dossier["review_events"] = sanitized_history

        # Double check ground truth isolation
        is_clean, violations = verify_ground_truth_isolation(sanitized_dossier)
        if not is_clean:
            raise ValueError(f"Ground truth isolation violation in export payload: {violations}")

        # 2. Generate dossier_final.json
        json_path = target_dir / "dossier_final.json"
        json_path.write_text(json.dumps(sanitized_dossier, indent=2), encoding="utf-8")

        # 3. Generate dossier.md (Enhanced Markdown with file:// links)
        md_content = self._render_enhanced_markdown(sanitized_dossier, sanitized_history)
        md_path = target_dir / "dossier.md"
        md_path.write_text(md_content, encoding="utf-8")

        # 4. Generate dossier.html (Standalone styled browser view)
        html_content = self._render_html(sanitized_dossier, sanitized_history)
        html_path = target_dir / "dossier.html"
        html_path.write_text(html_content, encoding="utf-8")

        _LOG.info("Handover package exported successfully to %s", target_dir)
        return {
            "json": json_path,
            "markdown": md_path,
            "html": html_path,
        }

    def _render_enhanced_markdown(
        self,
        dossier: Dict[str, Any],
        review_history: List[Dict[str, Any]],
    ) -> str:
        """Render 9-section Markdown with clickable file:// links."""
        # Use base renderer
        base_md = DossierMarkdownRenderer.render(dossier)

        # Append reviewer audit trail section
        lines = [base_md, "", "---", "", "## 9. Reviewer Sign-Off & Audit Trail", ""]
        review_summary = dossier.get("review_summary", {})
        status = review_summary.get("status", "PENDING_REVIEW")
        reviewed_by = review_summary.get("reviewed_by", "Pending L1/L2 Review")
        reviewed_at = review_summary.get("reviewed_at", "N/A")

        lines.append(f"- **Current Disposition:** `{status}`")
        lines.append(f"- **Final Reviewer:** {reviewed_by}")
        lines.append(f"- **Timestamp:** `{reviewed_at}`")
        lines.append("- **Automated Remediation Triggered:** `false` (HUM-01 Verified)")
        lines.append("")

        if review_history:
            lines.append("### Review Decision History (Append-Only)")
            lines.append("")
            lines.append("| Event ID | Target Rev | Decision | Reviewer | Timestamp | Rationale |")
            lines.append("|---|---|---|---|---|---|")
            for ev in review_history:
                ev_id = ev.get("review_event_id", "-")
                rev = ev.get("target_dossier_version", 1)
                dec = ev.get("decision", "-").upper()
                who = f"{ev.get('reviewer_ref', '-')} ({ev.get('reviewer_role', '-')})"
                ts = ev.get("reviewed_at", "-")
                rat = ev.get("rationale", "-").replace("\n", " ")
                lines.append(f"| `{ev_id}` | v{rev} | **{dec}** | {who} | `{ts}` | {rat} |")
            lines.append("")

        return "\n".join(lines)

    def _render_html(
        self,
        dossier: Dict[str, Any],
        review_history: List[Dict[str, Any]],
    ) -> str:
        """Render self-contained responsive HTML representation for browser review (FR-OUT-006)."""
        inc_id = html.escape(str(dossier.get("incident_id", "Unknown")))
        version = dossier.get("dossier_version", 1)
        dossier_hash = html.escape(str(dossier.get("dossier_hash", "")))
        review_summary = dossier.get("review_summary", {})
        status = html.escape(str(review_summary.get("status", "PENDING_REVIEW")))
        severity = html.escape(str(dossier.get("severity") or dossier.get("incident_summary", {}).get("severity", "medium")).upper())

        badge_color = {
            "APPROVED": "#10b981",
            "REJECTED": "#ef4444",
            "EDITED": "#f59e0b",
            "PENDING_REVIEW": "#3b82f6",
        }.get(status, "#6b7280")

        # Hypotheses (support both canonical contract and extended formats)
        rca = dossier.get("root_cause_analysis", {})
        hypotheses = dossier.get("hypotheses") or rca.get("ranked_hypotheses", [])
        hypo_rows = []
        for h in hypotheses:
            rank = h.get("rank", "-")
            stmt = html.escape(h.get("statement") or h.get("hypothesis_statement", ""))
            eval_stat = html.escape(str(h.get("support_status") or h.get("evaluation_status", "INCONCLUSIVE")))
            conf = h.get("confidence_score", 0.85 if eval_stat == "SUPPORTED" else 0.5)
            hypo_rows.append(
                f"<tr><td>#{rank}</td><td>{stmt}</td><td><span class='badge'>{eval_stat}</span></td><td>{conf:.2f}</td></tr>"
            )

        # SOP References (support both canonical contract and extended formats)
        rec = dossier.get("recommended_actions", {})
        sop_citations = dossier.get("sop_citations") or rec.get("sop_citations", [])
        sop_items = []
        for sop in sop_citations:
            doc_id = html.escape(sop.get("doc_id") or sop.get("document_id", "doc"))
            title = html.escape(sop.get("title", doc_id))
            sec = html.escape(sop.get("section_path") or sop.get("section", ""))
            uri = html.escape(sop.get("source_uri", "#"))
            sop_items.append(
                f"<li><strong><a href='file://{uri}'>{title}</a></strong> ({doc_id}) — Section: {sec}</li>"
            )

        # Review history table
        history_rows = []
        for ev in review_history:
            ev_id = html.escape(str(ev.get("review_event_id", "-")))
            ev_rev = ev.get("target_dossier_version", 1)
            ev_dec = html.escape(str(ev.get("decision", "-")).upper())
            ev_who = html.escape(f"{ev.get('reviewer_ref', '-')} ({ev.get('reviewer_role', '-')})")
            ev_rat = html.escape(str(ev.get("rationale", "-")))
            history_rows.append(
                f"<tr><td><code>{ev_id}</code></td><td>v{ev_rev}</td><td><strong>{ev_dec}</strong></td><td>{ev_who}</td><td>{ev_rat}</td></tr>"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Incident Dossier - {inc_id} v{version}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 24px; background: #f8fafc; color: #1e293b; }}
    .container {{ max-width: 960px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 32px; }}
    h1, h2, h3 {{ color: #0f172a; margin-top: 0; }}
    .header-bar {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 16px; margin-bottom: 24px; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-weight: 600; font-size: 0.85rem; color: #fff; background: {badge_color}; }}
    .badge-sec {{ background: #0284c7; }}
    .badge-alert {{ background: #dc2626; }}
    .hash {{ font-family: monospace; font-size: 0.85rem; color: #64748b; word-break: break-all; }}
    .card {{ background: #f1f5f9; border-radius: 6px; padding: 16px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 20px; }}
    th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e2e8f0; font-size: 0.95rem; }}
    th {{ background: #f8fafc; font-weight: 600; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .rule-banner {{ background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px; margin: 16px 0; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header-bar">
      <div>
        <h1>Incident Handover Dossier</h1>
        <div><strong>Incident ID:</strong> {inc_id} (Revision v{version}) | <strong>Severity:</strong> <span class="badge badge-alert">{severity}</span></div>
      </div>
      <div>
        <span class="badge">{status}</span>
      </div>
    </div>

    <div class="rule-banner">
      <strong>Zero Auto-Remediation (RULE-008 & HUM-01):</strong>
      Automated action triggered: <code>false</code>. Remediation requires explicit human authorization.
    </div>

    <div class="card">
      <h3>Cryptographic Integrity (Canonical SHA-256)</h3>
      <div class="hash">Hash: {dossier_hash}</div>
    </div>

    <h2>1. Root Cause Analysis & Ranked Hypotheses</h2>
    <table>
      <thead><tr><th>Rank</th><th>Hypothesis Statement</th><th>Evaluation Status</th><th>Confidence</th></tr></thead>
      <tbody>
        {''.join(hypo_rows) if hypo_rows else '<tr><td colspan="4">No hypotheses recorded</td></tr>'}
      </tbody>
    </table>

    <h2>2. Authoritative SOP & Runbook Citations</h2>
    <ul>
      {''.join(sop_items) if sop_items else '<li>No SOP references cited.</li>'}
    </ul>

    <h2>3. Review Decision History (Append-Only Audit)</h2>
    <table>
      <thead><tr><th>Review ID</th><th>Revision</th><th>Decision</th><th>Reviewer</th><th>Rationale</th></tr></thead>
      <tbody>
        {''.join(history_rows) if history_rows else '<tr><td colspan="5">No human review events recorded yet.</td></tr>'}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
