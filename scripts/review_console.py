#!/usr/bin/env python3
"""Interactive & Scriptable CLI Review Console for Human Review and Handover (C16, TBD-11, HUM-01, AT-010)."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, Dict, Optional

# Ensure repository root is on sys.path
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.handover import HandoverExporter
from orchestrator.review import AuthorizedReviewManager, build_human_correction_payload
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore
from orchestrator.ticketing import DummyTicketManager


def display_dossier_summary(
    dossier: Dict[str, Any],
    cost_metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Format and print an executive incident summary to standard output (TBD-11)."""
    inc_id = dossier.get("incident_id", "Unknown")
    version = dossier.get("dossier_version", 1)
    dossier_hash = dossier.get("dossier_hash", "N/A")
    review_summary = dossier.get("review_summary", {})
    status = review_summary.get("status", "PENDING_REVIEW")
    inc_sum = dossier.get("impact_summary") or dossier.get("incident_summary", {})
    severity = str(dossier.get("severity") or inc_sum.get("severity", "medium")).upper()
    services = ", ".join(dossier.get("investigation_scope", [dossier.get("service_id", "unknown")]))

    print("=" * 76)
    print("      AI AGENTIC SRE — HUMAN REVIEW AND INVESTIGATION CONSOLE (TBD-11)      ")
    print("=" * 76)
    print(f"Incident ID        : {inc_id} (Revision: v{version})")
    print(f"Severity           : {severity}")
    print(f"Scope & Services   : {services}")
    print(f"Review Status      : {status}")
    print(f"Canonical Hash     : {dossier_hash[:32]}...")
    print(f"Diagnosis Verified : False (APPROVE = Handover acceptance only)")
    print(f"Auto Remediation   : DISABLED (RULE-008 & HUM-01: auto_action_triggered=False)")
    print("-" * 76)

    # 1. Telemetry & Symptoms
    symptoms = inc_sum.get("observed_symptoms") or dossier.get("message") or "Anomalies detected in telemetry signals."
    print("TELEMETRY SYMPTOMS & OBSERVATIONS:")
    print(f"  {symptoms}")
    print("-" * 76)

    # 2. AI Observability & Cost (C15 metrics)
    print("AI REASONING & COST METRICS (C15):")
    if cost_metrics:
        total_tokens = cost_metrics.get("total_tokens", 0)
        shadow_cost = cost_metrics.get("total_cost_usd", 0.0)
        p95_lat = cost_metrics.get("p95_latency_ms", 0.0)
        print(f"  Total Tokens     : {total_tokens}")
        print(f"  Shadow Cost      : ${shadow_cost:.6f} USD")
        print(f"  P95 Latency      : {p95_lat:.2f} ms")
    else:
        meta = dossier.get("investigation_metadata", {})
        tokens = meta.get("tokens_used", "N/A")
        cost = meta.get("estimated_cost_usd", "0.000000")
        print(f"  Tokens / Cost    : {tokens} tokens | ${cost} USD")
    print("-" * 76)

    # 3. SOP & Runbook Citations (FR-RAG-005)
    rec = dossier.get("recommended_actions", {})
    sops = dossier.get("sop_citations") or rec.get("sop_citations") or []
    print(f"AUTHORITATIVE RUNBOOK CITATIONS ({len(sops)} citations):")
    if sops:
        for idx, sop in enumerate(sops, 1):
            if isinstance(sop, dict):
                title = sop.get("doc_id") or sop.get("title", sop.get("document_id", "Runbook"))
                sec = sop.get("section_path") or sop.get("section", "N/A")
                uri = sop.get("source_uri", "N/A")
                print(f"  [{idx}] {title} — Section {sec}")
                print(f"      Source: file://{uri}")
            else:
                print(f"  [{idx}] {sop}")
    else:
        print("  No relevant SOPs or runbooks cited.")
    print("-" * 76)

    # 4. Ranked Hypotheses
    rca = dossier.get("root_cause_analysis", {})
    hypos = dossier.get("hypotheses") or rca.get("ranked_hypotheses", [])
    print(f"ROOT CAUSE HYPOTHESES ({len(hypos)} ranked candidates):")
    if hypos:
        for h in hypos:
            rank = h.get("rank", 1)
            stmt = h.get("statement") or h.get("hypothesis_statement", "")
            eval_stat = h.get("support_status") or h.get("evaluation_status", "INCONCLUSIVE")
            conf = h.get("confidence_score", 0.85 if eval_stat == "SUPPORTED" else 0.5)
            print(f"  #{rank} [{eval_stat} | Conf: {conf:.2f}] {stmt}")
    else:
        pri = rca.get("primary_hypothesis") or dossier.get("primary_hypothesis", "N/A")
        print(f"  Primary: {pri}")
    print("=" * 76)


def run_review_action(
    dossier: Dict[str, Any],
    action: str,
    reviewer_ref: str,
    reviewer_role: str,
    rationale: str,
    corrections: Optional[Dict[str, Any]] = None,
    store: Optional[WorkflowStateStore] = None,
    review_manager: Optional[AuthorizedReviewManager] = None,
    export_handover: bool = True,
    create_ticket: bool = True,
    *,
    escalation_target: Optional[str] = None,
    corrected_hypothesis: Optional[str] = None,
    audit_chain: Any = None,
    handover_root: Optional[pathlib.Path | str] = None,
    ticket_storage_path: Optional[pathlib.Path | str] = None,
) -> Dict[str, Any]:
    """Execute review action (APPROVE, REJECT, CORRECT, ESCALATE) programmatically or interactively."""
    rm = review_manager or AuthorizedReviewManager(store=store, audit_chain=audit_chain)
    inc_id = dossier.get("incident_id", "inc-unknown")
    target_version = int(dossier.get("dossier_version", 1))

    effective_corrections = corrections
    if action.upper() == "CORRECT" and effective_corrections is None and corrected_hypothesis:
        effective_corrections = build_human_correction_payload(
            dossier=dossier,
            corrected_statement=corrected_hypothesis,
            reviewer_ref=reviewer_ref,
            reviewer_role=reviewer_role,
        )

    res = rm.submit_review(
        incident_id=inc_id,
        dossier_dict=dossier,
        reviewer_ref=reviewer_ref,
        reviewer_role=reviewer_role,
        decision=action,
        rationale=rationale,
        edited_dossier_data=effective_corrections,
        escalation_target=escalation_target,
        target_version=target_version,
    )

    artifacts_generated = {}
    if action.lower() in ("approve",) and export_handover:
        exporter = HandoverExporter(export_root=handover_root)
        history = rm.get_review_history(inc_id)
        exported = exporter.export_handover_package(
            incident_id=inc_id,
            dossier_dict=res["updated_dossier"],
            review_history=history,
        )
        artifacts_generated["handover_export"] = {k: str(v) for k, v in exported.items()}

    ticket = None
    if action.lower() in ("approve",) and create_ticket:
        tm = DummyTicketManager(storage_path=ticket_storage_path)
        ticket = tm.create_ticket_from_dossier(res["updated_dossier"])
        artifacts_generated["ticket"] = ticket

    return {
        "review_result": res,
        "approval_semantics": res.get("approval_semantics"),
        "artifacts": artifacts_generated,
        "action": action,
        "incident_id": inc_id,
    }


def interactive_console(
    dossier_path: pathlib.Path,
    reviewer_ref: str = "sre_reviewer",
    reviewer_role: str = "L2_SRE",
) -> None:
    """Run interactive terminal review session."""
    data = json.loads(dossier_path.read_text(encoding="utf-8"))
    display_dossier_summary(data)

    print("\nSELECT REVIEWER ACTION:")
    print("  [1] APPROVE   - Accept dossier for handover closure (CLOSED; does not verify root cause or authorize remediation)")
    print("  [2] REJECT    - Reject findings and close dossier as REJECTED")
    print("  [3] CORRECT   - Propose human correction and spawn append-only revision v(N+1)")
    print("  [4] ESCALATE  - Route to human incident commander (MANUAL_TRIAGE_REQUIRED)")
    print("  [Q] QUIT      - Exit without modifying state")

    choice = input("\nEnter choice [1/2/3/4/Q]: ").strip().upper()
    if choice == "1":
        rat = input("Approval rationale [press enter for default]: ").strip() or (
            "Dossier accepted for handover by human reviewer (administrative acceptance only)."
        )
        res = run_review_action(data, "APPROVE", reviewer_ref, reviewer_role, rat)
        print("\n[SUCCESS] Dossier APPROVED for handover. State transitioned to CLOSED (remediation NOT authorized).")
        if "handover_export" in res["artifacts"]:
            print(f"Handover package exported to: {res['artifacts']['handover_export']['markdown']}")
        if "ticket" in res["artifacts"]:
            print(f"ITSM dummy ticket created: {res['artifacts']['ticket']['ticket_id']}")
    elif choice == "2":
        rat = input("Rejection rationale (required): ").strip() or "Hypothesis contradicts observed telemetry."
        run_review_action(data, "REJECT", reviewer_ref, reviewer_role, rat)
        print("\n[SUCCESS] Dossier REJECTED. State transitioned to REJECTED.")
    elif choice == "3":
        new_hypo = input("Enter corrected primary hypothesis: ").strip() or "Root cause candidate updated by L2 SRE."
        rat = input("Correction notes: ").strip() or "Hypothesis statement updated by human reviewer."
        res = run_review_action(
            data,
            "CORRECT",
            reviewer_ref,
            reviewer_role,
            rat,
            corrected_hypothesis=new_hypo,
        )
        new_rev = res["review_result"]["new_dossier_revision"]
        print(f"\n[SUCCESS] Correction accepted. New append-only revision v{new_rev['dossier_version']} generated (PENDING_REVIEW).")
    elif choice == "4":
        target = input("Escalation target [e.g. SRE_LEAD_ONCALL]: ").strip() or "SRE_LEAD_ONCALL"
        rat = input("Escalation notes: ").strip() or "Ambiguous signals require manual team triage."
        run_review_action(data, "ESCALATE", reviewer_ref, reviewer_role, rat, escalation_target=target)
        print(f"\n[SUCCESS] Escalated to manual triage ({target}).")
    else:
        print("\nExiting review console.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Human Review Console CLI (C16, TBD-11)")
    parser.add_argument("--dossier-path", type=str, help="Path to dossier JSON file")
    parser.add_argument("--reviewer-ref", type=str, default="sre_alex", help="Reviewer identity ref")
    parser.add_argument("--reviewer-role", type=str, default="L2_SRE", help="Reviewer authorized role")
    parser.add_argument("--action", type=str, choices=["APPROVE", "REJECT", "CORRECT", "ESCALATE"], help="Direct action (non-interactive)")
    parser.add_argument("--rationale", type=str, default="CLI review action recorded.", help="Action rationale")
    parser.add_argument("--corrected-hypothesis", type=str, default=None, help="Corrected hypothesis statement for CORRECT")
    parser.add_argument("--escalation-target", type=str, default=None, help="Escalation target for ESCALATE")
    parser.add_argument("--state-db", type=str, default=None, help="Path to WorkflowStateStore SQLite DB")
    parser.add_argument("--audit-log", type=str, default=None, help="Path to SHA-256 audit log JSONL")
    parser.add_argument("--handover-root", type=str, default=None, help="Output directory for handover exports")
    parser.add_argument("--ticket-store", type=str, default=None, help="Path to dummy ITSM ticket JSON store")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts")
    args = parser.parse_args()

    if not args.dossier_path:
        print("Usage: python3 scripts/review_console.py --dossier-path <path_to_dossier.json>")
        return 1

    path = pathlib.Path(args.dossier_path)
    if not path.exists():
        print(f"Error: Dossier file not found: {path}")
        return 1

    if args.non_interactive or args.action:
        action = args.action or "APPROVE"
        data = json.loads(path.read_text(encoding="utf-8"))
        store = WorkflowStateStore(args.state_db) if args.state_db else None
        audit_chain = None
        if args.audit_log:
            from observability.audit_chain import AuditHashChain
            audit_chain = AuditHashChain(log_path=args.audit_log)
        try:
            res = run_review_action(
                data,
                action,
                args.reviewer_ref,
                args.reviewer_role,
                args.rationale,
                store=store,
                corrected_hypothesis=args.corrected_hypothesis,
                escalation_target=args.escalation_target,
                audit_chain=audit_chain,
                handover_root=args.handover_root,
                ticket_storage_path=args.ticket_store,
            )
        finally:
            if store is not None:
                store.close()
        print(
            json.dumps(
                {
                    "status": "SUCCESS",
                    "incident_id": res["incident_id"],
                    "action": action,
                    "approval_semantics": res.get("approval_semantics"),
                },
                indent=2,
            )
        )
        return 0

    interactive_console(path, reviewer_ref=args.reviewer_ref, reviewer_role=args.reviewer_role)
    return 0


if __name__ == "__main__":
    sys.exit(main())
