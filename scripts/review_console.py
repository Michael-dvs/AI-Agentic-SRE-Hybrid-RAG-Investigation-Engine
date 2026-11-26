#!/usr/bin/env python3
"""Interactive & Scriptable CLI Review Console for Human Review and Handover (C16, P2-06, TBD-11, HUM-01, AT-010)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, Optional

# Ensure repository root is on sys.path
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.console_view_models import (
    CALIBRATION_LIMITATION_NOTE,
    REVIEW_ACTION_SEMANTICS,
    build_incident_detail_vm,
    sanitize_terminal_text,
)
from orchestrator.handover import HandoverExporter
from orchestrator.review import AuthorizedReviewManager, build_human_correction_payload
from orchestrator.state_machine import WorkflowStateStore
from orchestrator.ticketing import DummyTicketManager


def display_dossier_summary(
    dossier: Dict[str, Any],
    cost_metrics: Optional[Dict[str, Any]] = None,
    *,
    store: Optional[WorkflowStateStore] = None,
    reviewer_ref: str = "sre_reviewer",
    reviewer_role: str = "L2_SRE",
) -> None:
    """Format and print an executive incident summary sharing authoritative P2-06 TUI semantics."""
    inc_id_raw = str(dossier.get("incident_id") or "")
    incident_row = None
    checkpoint_row = None
    transitions = ()
    reviews = ()
    if store is not None and inc_id_raw:
        try:
            with store.transaction(immediate=False):
                incident_row = store.get_incident(inc_id_raw)
                checkpoint_row = store.get_checkpoint(inc_id_raw)
                transitions = store.get_transitions(inc_id_raw)
                reviews = store.get_reviews(inc_id_raw)
        except Exception:
            pass

    vm = build_incident_detail_vm(
        incident=incident_row,
        dossier=dossier,
        checkpoint=checkpoint_row,
        transitions=transitions,
        reviews=reviews,
        reviewer_ref=reviewer_ref,
        reviewer_role=reviewer_role,
    )

    closure_meaning = (
        "ADMINISTRATIVE_DOSSIER_HANDOVER_CLOSED"
        if vm.review_eligibility.dossier_review_status == "APPROVED" or vm.lifecycle_state == "CLOSED"
        else vm.review_eligibility.dossier_review_status
    )

    print("=" * 76)
    print("      AI AGENTIC SRE - HUMAN REVIEW AND INVESTIGATION CONSOLE (TBD-11)      ")
    print("=" * 76)
    print(f"Incident ID        : {vm.incident_id} (Revision: v{vm.dossier_version})")
    print(f"Severity           : {vm.severity_badge}")
    print(f"Scope & Services   : {', '.join(vm.affected_services)} (env={vm.environment})")
    print(f"Lifecycle / Review : {vm.lifecycle_display} / {vm.review_eligibility.dossier_review_status}")
    print(f"Closure Semantics  : {closure_meaning} (technical_resolved=False)")
    print(f"Canonical Hash     : {vm.dossier_hash[:32]}...")
    print("Diagnosis Verified : False (APPROVE = Handover acceptance only)")
    print("Identity Trust     : Local PoC caller-asserted identifier (unauthenticated)")
    print("Auto Remediation   : DISABLED (RULE-008 & HUM-01: auto_action_triggered=False)")
    print("-" * 76)

    # 1. Telemetry & Symptoms
    print("TELEMETRY SYMPTOMS & OBSERVATIONS:")
    print(f"  {vm.observed_symptoms}")
    print("-" * 76)

    # 2. AI Observability & Cost (C15 metrics)
    print("AI REASONING & COST METRICS (C15):")
    print(f"  Reasoning Mode   : {vm.mode_headline} ({vm.provider_name} / {vm.model_version})")
    if cost_metrics:
        total_tokens = cost_metrics.get("total_tokens", 0)
        shadow_cost = cost_metrics.get("total_cost_usd", 0.0)
        p95_lat = cost_metrics.get("p95_latency_ms", 0.0)
        print(f"  Total Tokens     : {total_tokens}")
        print(f"  Shadow Cost      : ${shadow_cost:.6f} USD")
        print(f"  P95 Latency      : {p95_lat:.2f} ms")
    else:
        meta = dossier.get("investigation_metadata") if isinstance(dossier.get("investigation_metadata"), dict) else {}
        if meta:
            tokens = sanitize_terminal_text(meta.get("tokens_used", "N/A"), max_chars=40)
            cost = sanitize_terminal_text(meta.get("estimated_cost_usd", "0.000000"), max_chars=40)
            print(f"  Tokens / Cost    : {tokens} tokens | ${cost} USD")
        else:
            print(f"  Token Usage      : {vm.token_usage_display}")
    print("-" * 76)

    # 3. SOP & Runbook Citations (FR-RAG-005, P1-03, P1-04)
    print(f"AUTHORITATIVE RUNBOOK CITATIONS ({len(vm.rag.citations)} citations):")
    print(f"  {vm.rag.availability_banner}")
    print(f"  RAG Delivery     : {vm.rag.delivery_summary}")
    if vm.rag.competing_sop_warning:
        print(f"  [WARNING] {vm.rag.competing_sop_warning}")
    if vm.rag.citations:
        for idx, sop in enumerate(vm.rag.citations, 1):
            print(f"  [{idx}] {sop.doc_id} v{sop.version} | {sop.section_path} | {sop.chunk_id}")
            print(f"      Source: {sop.source_uri}")
            if sop.retrieval_score_note:
                print(f"      {sop.retrieval_score_note}")
    else:
        print("  No relevant SOPs or runbooks cited.")
    print("-" * 76)

    print("MANUAL VERIFICATION (human review only):")
    for check in vm.rag.manual_checks:
        print(f"  {check.check_id} [{check.status} | {check.provenance_tag}]: {check.description}")
    for item in vm.unknowns:
        print(f"  Unknown: {item}")

    # 4. Ranked Hypotheses & Evidence-Aware Confidence
    print("-" * 76)
    print(f"ROOT CAUSE HYPOTHESES ({len(vm.hypotheses)} ranked candidates):")
    print(f"  Calibration      : {CALIBRATION_LIMITATION_NOTE}")
    if vm.hypotheses:
        for h in vm.hypotheses:
            print(f"  #{h.rank} [{h.support_label} | Conf: {h.confidence_display}] {h.statement}")
            print(f"      Evidence(+/-): +{len(h.supporting_ids)} / -{len(h.contradicting_ids)} | Uncertainty: {h.main_uncertainty}")
    else:
        rca = dossier.get("root_cause_analysis") if isinstance(dossier.get("root_cause_analysis"), dict) else {}
        pri = sanitize_terminal_text(rca.get("primary_hypothesis") or dossier.get("primary_hypothesis", "N/A"), max_chars=240)
        print(f"  Primary: {pri}")

    # 5. Evidence Provenance & Temporal Scope (P1-05)
    print("-" * 76)
    print(f"EVIDENCE PROVENANCE & TEMPORAL SCOPE ({len(vm.evidence_items)} evidence item(s)):")
    for uref in vm.unresolved_evidence_refs:
        print(
            f"  - [UNRESOLVED] Hypothesis #{uref.hypothesis_rank} cites {uref.role} '{uref.evidence_id}' (absent from authorized evidence)"
        )
    if vm.evidence_items:
        for ev in vm.evidence_items:
            qual = ev.data_quality + ("/truncated" if ev.truncated else "")
            refs = ", ".join(ev.associated_hypotheses) or "contextual"
            print(
                f"  - {ev.evidence_id} [{ev.disposition}] {ev.temporal_badge} | "
                f"{ev.tool_name} ({ev.source_ref}) | obs={ev.observed_at} | win={ev.query_window_str} | "
                f"quality={qual} | refs={refs}"
            )
            if ev.summary:
                print(f"    Summary: {ev.summary[:220]}")
    else:
        print("  No positive telemetry evidence items recorded.")
    for ms in vm.missing_sources:
        print(f"  - [MISSING] {ms['tool_name']} ({ms['error_code']}): {ms['impact_note']}")
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
    auth_context: Any = None,
    reviewer_directory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute review action (APPROVE, REJECT, CORRECT, ESCALATE) programmatically or interactively."""
    rm = review_manager or AuthorizedReviewManager(
        store=store,
        audit_chain=audit_chain,
        reviewer_directory=reviewer_directory,
    )
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
        auth_context=auth_context,
    )

    artifacts_generated: Dict[str, Any] = {}
    if action.lower() in ("approve",) and export_handover:
        exporter = HandoverExporter(export_root=handover_root)
        history = rm.get_review_history(inc_id)
        exported = exporter.export_handover_package(
            incident_id=inc_id,
            dossier_dict=res["updated_dossier"],
            review_history=history,
        )
        artifacts_generated["handover_export"] = {k: str(v) for k, v in exported.items()}

    if action.lower() in ("approve",) and create_ticket:
        tm = DummyTicketManager(storage_path=ticket_storage_path)
        ticket = tm.create_ticket_from_dossier(res["updated_dossier"])
        artifacts_generated["ticket"] = ticket

    return {
        "review_result": res,
        "approval_semantics": res.get("approval_semantics"),
        "authorization_context": res.get("authorization_context"),
        "artifacts": artifacts_generated,
        "action": action,
        "incident_id": inc_id,
    }


def interactive_console(
    dossier_path: pathlib.Path,
    reviewer_ref: str = "sre_reviewer",
    reviewer_role: str = "L2_SRE",
    *,
    store: Optional[WorkflowStateStore] = None,
) -> None:
    """Run interactive terminal review session with explicit confirmation and cancellation."""
    data = json.loads(dossier_path.read_text(encoding="utf-8"))
    display_dossier_summary(data, store=store, reviewer_ref=reviewer_ref, reviewer_role=reviewer_role)

    print("\nSELECT REVIEWER ACTION:")
    print("  [1] APPROVE   - Accept dossier for handover closure (CLOSED; does not verify root cause or authorize remediation)")
    print("  [2] REJECT    - Reject findings and close dossier as REJECTED (preserves original AI findings)")
    print("  [3] CORRECT   - Propose human correction and spawn append-only revision v(N+1)")
    print("  [4] ESCALATE  - Route to human incident commander (MANUAL_TRIAGE_REQUIRED; local PoC log only)")
    print("  [Q] QUIT      - Exit without modifying state")

    choice = input("\nEnter choice [1/2/3/4/Q]: ").strip().upper()
    action_map = {"1": "APPROVE", "2": "REJECT", "3": "CORRECT", "4": "ESCALATE"}
    if choice not in action_map:
        print("\nExiting review console without modifying state.")
        return

    action = action_map[choice]
    sem = REVIEW_ACTION_SEMANTICS[action]
    print(f"\nACTION MEANING ({action}): {sem['summary']}")

    new_hypo = None
    target = None
    if action == "CORRECT":
        new_hypo = input("Enter corrected primary hypothesis (min 5 chars, or Enter to cancel): ").strip()
        if not new_hypo:
            print("\nCancelled: no changes submitted.")
            return
    elif action == "ESCALATE":
        target = input("Escalation target [default: SRE_LEAD_ONCALL]: ").strip() or "SRE_LEAD_ONCALL"

    rat = input(f"{action} rationale (required, min 5 chars, or type 'cancel' to abort): ").strip()
    if not rat or rat.lower() in ("cancel", "batal", "esc"):
        print("\nCancelled: no changes submitted.")
        return

    confirm = input(
        f"Confirm {action} on {data.get('incident_id')} v{data.get('dossier_version', 1)}? [y/N]: "
    ).strip().lower()
    if confirm not in ("y", "yes"):
        print("\nCancelled before submission: no changes submitted.")
        return

    res = run_review_action(
        data,
        action,
        reviewer_ref,
        reviewer_role,
        rat,
        store=store,
        corrected_hypothesis=new_hypo,
        escalation_target=target,
    )
    if action == "APPROVE":
        print("\n[CONFIRMED] Dossier APPROVED for administrative handover (CLOSED; diagnosis_verified=False; remediation NOT authorized).")
        if "handover_export" in res["artifacts"]:
            print(f"Handover package exported to: {res['artifacts']['handover_export']['markdown']}")
        if "ticket" in res["artifacts"]:
            print(f"ITSM dummy ticket created: {res['artifacts']['ticket']['ticket_id']}")
    elif action == "REJECT":
        print("\n[CONFIRMED] Dossier REJECTED. State transitioned to REJECTED; original AI findings preserved.")
    elif action == "CORRECT":
        new_rev = res["review_result"]["new_dossier_revision"]
        print(f"\n[CONFIRMED] Correction accepted. Append-only revision v{new_rev['dossier_version']} created (PENDING_REVIEW).")
    elif action == "ESCALATE":
        print(f"\n[CONFIRMED] Escalated to manual triage ({target}); no external paging triggered.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Human Review Console CLI (C16, P2-06, TBD-11)")
    parser.add_argument("--dossier-path", "--dossier", dest="dossier_path", type=str, help="Path to dossier JSON file")
    parser.add_argument("--reviewer-ref", "--reviewer", dest="reviewer_ref", type=str, default="sre_alex", help="Reviewer identity ref")
    parser.add_argument("--reviewer-role", "--role", dest="reviewer_role", type=str, default="L2_SRE", help="Reviewer authorized role")
    parser.add_argument("--action", type=str, choices=["APPROVE", "REJECT", "CORRECT", "ESCALATE"], help="Direct action (non-interactive)")
    parser.add_argument("--rationale", type=str, default="CLI review action recorded.", help="Action rationale")
    parser.add_argument("--corrected-hypothesis", type=str, default=None, help="Corrected hypothesis statement for CORRECT")
    parser.add_argument("--escalation-target", type=str, default=None, help="Escalation target for ESCALATE")
    parser.add_argument("--state-db", type=str, default=None, help="Path to WorkflowStateStore SQLite DB")
    parser.add_argument("--audit-log", type=str, default=None, help="Path to SHA-256 audit log JSONL")
    parser.add_argument("--handover-root", type=str, default=None, help="Output directory for handover exports")
    parser.add_argument("--ticket-store", type=str, default=None, help="Path to dummy ITSM ticket JSON store")
    parser.add_argument("--export-handover", action="store_true", default=True, help="Export handover package on APPROVE")
    parser.add_argument("--no-export-handover", action="store_false", dest="export_handover", help="Skip handover export")
    parser.add_argument("--create-ticket", action="store_true", default=True, help="Create local dummy ITSM ticket on APPROVE")
    parser.add_argument("--no-create-ticket", action="store_false", dest="create_ticket", help="Skip dummy ticket creation")
    parser.add_argument("--view-only", action="store_true", help="Print dossier summary and exit without mutating state")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts")
    args = parser.parse_args()

    if not args.dossier_path:
        print("Usage: python3 scripts/review_console.py --dossier-path <path_to_dossier.json> [--view-only]")
        return 1

    path = pathlib.Path(args.dossier_path)
    if not path.exists():
        print(f"Error: Dossier file not found: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    store = WorkflowStateStore(args.state_db) if args.state_db else None
    try:
        if args.view_only:
            display_dossier_summary(data, store=store, reviewer_ref=args.reviewer_ref, reviewer_role=args.reviewer_role)
            return 0

        if args.non_interactive or args.action:
            action = args.action or "APPROVE"
            audit_chain = None
            if args.audit_log:
                from observability.audit_chain import AuditHashChain

                audit_chain = AuditHashChain(log_path=args.audit_log)
            res = run_review_action(
                data,
                action,
                args.reviewer_ref,
                args.reviewer_role,
                args.rationale,
                store=store,
                export_handover=args.export_handover,
                create_ticket=args.create_ticket,
                corrected_hypothesis=args.corrected_hypothesis,
                escalation_target=args.escalation_target,
                audit_chain=audit_chain,
                handover_root=args.handover_root,
                ticket_storage_path=args.ticket_store,
            )
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

        interactive_console(path, reviewer_ref=args.reviewer_ref, reviewer_role=args.reviewer_role, store=store)
        return 0
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
