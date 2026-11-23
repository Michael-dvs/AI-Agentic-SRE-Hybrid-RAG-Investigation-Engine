"""Read-only handover planning. This module has no tool or model client."""

from __future__ import annotations

import re
from collections import defaultdict

from orchestrator.claim_validator_contract import detect_claim_mechanisms


SOP_GAPS = {
    "NO_APPLICABLE_RUNBOOK": ("NO_APPLICABLE_RUNBOOK", "No match in the authorized index for this query. Corpus coverage is unknown."),
    "SOP_FILTERED_OUT": ("NO_APPLICABLE_RUNBOOK", "Returned references did not meet applicability checks. No eligible reference can be cited."),
    "RETRIEVAL_UNAVAILABLE": ("SOURCE_UNAVAILABLE", "Retrieval or response validation did not complete reliably. SOP availability is unknown."),
    "RETRIEVAL_REJECTED": ("SOURCE_UNAVAILABLE", "The gateway rejected the request. No conclusion about document availability is possible."),
    "INSUFFICIENT_MATCH_CONTEXT": ("SOURCE_UNAVAILABLE", "Incident scope, reference time or symptom is insufficient for matching. SOP applicability is unknown."),
    "NOT_ASSESSED": ("SOURCE_UNAVAILABLE", "No reliable SOP assessment was recorded."),
}


def sop_document_keys(citations):
    return {
        (c.get("doc_id") or c.get("document_id"), c.get("version") or c.get("document_version"))
        for c in (citations or [])
        if isinstance(c, dict)
    }


def availability_text(dossier):
    citations = dossier.get("sop_citations") or []
    if len(sop_document_keys(citations)) > 1:
        return (
            "CONFLICTING_OR_COMPETING_SOPS: multiple distinct eligible SOP sources or versions "
            "matched without established precedence; human review and escalation required before following guidance."
        )
    if citations:
        return "APPLICABLE_SOP_FOUND: see cited sections."
    return next((m["impact_note"] for m in dossier.get("missing_sources", [])
                 if m.get("tool_name") == "retrieve_runbooks" and m.get("impact_note")),
                "No SOP cited; retrieval outcome not recorded.")


def hypothesis_label(hypothesis):
    status = hypothesis.get("support_status") or hypothesis.get("evaluation_status") or hypothesis.get("status") or "INCONCLUSIVE"
    # dossier.v1 represents these two validator outcomes as INCONCLUSIVE.
    if status == "INCONCLUSIVE":
        for label in ("UNSUPPORTED", "CONTRADICTED"):
            if str(hypothesis.get("reason_summary", "")).startswith(f"[{label}]"):
                return label
    return status


# Describe what a human can compare, not what the telemetry supposedly contains.
_INSPECTIONS = {
    "search_error_logs": "Compare sanitized error codes and timestamps with the reported symptom. Matching errors strengthen a service-error explanation; a different error pattern weakens it.",
    "get_trace_summary": "Compare span status, duration and parent/child timing for a correlated request. A failing earlier hop supports propagation; healthy sampled hops weaken it for that request only.",
    "get_service_metrics": "Compare request volume and error-rate series across the incident window. An error-rate rise during traffic supports service impact; traffic volume alone does not establish failures.",
    "get_service_dependencies": "Inspect the recorded direction of the dependency edge. A matching edge makes propagation possible; an absent edge weakens that path but may reflect an incomplete inventory.",
    "get_apm_health": "Compare the scoped health observation with the alert time. A simultaneous degradation supports service impact; a healthy sample alone cannot exclude transient impact.",
}


_DISCRIMINATORS = {
    "auth_failure": ("search_error_logs", "Compare authentication rejection codes with server-side errors. Repeated authentication rejections favor an access failure; unrelated 5xx errors alone do not."),
    "db_pool": ("search_error_logs", "Look for connection checkout waits or pool exhaustion at symptom onset. Their co-occurrence supports contention; unrelated application errors do not."),
    "rate_limit": ("search_error_logs", "Compare throttle or 429 responses against other failures. Matching throttling signals favor rate limiting; 5xx responses alone do not."),
    "traffic_surge": ("get_service_metrics", "Compare request rate across the reported onset. A rise preceding degradation supports load as a contributor; stable volume weakens that explanation."),
}


def build_pending_checks(context, hypotheses, citations, *, fallback=False):
    checks = []
    prefix = "chk-fb" if fallback else "chk"

    def add(origin, text, doc=None):
        checks.append({"check_id": f"{prefix}-{len(checks) + 1:02d}",
                       "description": f"NOT_PERFORMED · {origin}: {text}",
                       "risk_level": "low", "requires_human_approval": True,
                       "auto_execution_allowed": False, "related_sop_doc_id": doc})

    documents = sop_document_keys(citations)
    if len(documents) > 1:
        add("HUMAN ESCALATION REQUIRED", "Compare the cited sources with the service owner before using their guidance. Precedence is not established; do not combine instructions.")
    elif citations:
        for c in citations:
            doc_id = c.get("doc_id") or c.get("document_id")
            version = c.get("version") or c.get("document_version")
            add("SOP-BACKED (source reference only)",
                f"Review cited section {c['chunk_id']} of {doc_id} v{version} for diagnostic criteria. Record which criteria match the incident and which do not. If sections disagree, escalate; no procedure is authorized for execution.", doc_id)

    by_evidence = defaultdict(set)
    predictions = defaultdict(lambda: defaultdict(set))
    for h in hypotheses:
        link = f"hypothesis #{h['rank']}"
        for field in ("supporting_evidence_ids", "contradicting_evidence_ids"):
            for eid in h[field]:
                by_evidence[eid].add(link)
        for mechanism in detect_claim_mechanisms(h["statement"]):
            if mechanism in _DISCRIMINATORS:
                tool, instruction = _DISCRIMINATORS[mechanism]
                predictions[tool][instruction].add(link)

    # Group by inspected signal and service, not by recommendation wording.
    targets = defaultdict(set)
    primary = context.get("service_id")
    scope = set(context.get("investigation_scope") or [primary])
    evidence_context = context.get("evidence_items")
    raw_evidence = evidence_context if isinstance(evidence_context, list) else context.get("evidence", [])
    for ev in raw_evidence:
        tool = ev.get("tool_name")
        svc = ev.get("service_id") or primary
        if (tool not in _INSPECTIONS or svc not in scope or not isinstance(svc, str)
                or not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", svc) or context.get("has_match_context") is False):
            continue
        links = by_evidence.get(ev.get("evidence_id"), set())
        covered = set()
        if svc == primary and tool in predictions:
            for instruction, questions in predictions[tool].items():
                targets[tool, svc, instruction].update(questions)
                covered.update(questions)
        remaining_links = links - covered
        has_records = bool(ev.get("records")) if "records" in ev else bool(ev.get("summary"))
        if remaining_links:
            targets[tool, svc, _INSPECTIONS[tool]].update(remaining_links)
        elif not covered and (ev.get("data_quality") in ("partial", "unavailable") or not has_records):
            targets[tool, svc, _INSPECTIONS[tool]].add("source coverage gap")

    window = context.get("query_window") or {}
    timing = (f"Window: {window['start']} to {window['end']}." if window.get("start") and window.get("end")
              else "Window not recorded; obtain the incident interval before comparing signals.")
    for (tool, svc, instruction), links in targets.items():
        add("GENERAL DIAGNOSTIC GUIDANCE (NOT SOP-BACKED)",
            f"{', '.join(sorted(links))}: {svc}, {tool} (authorized read-only view). {instruction} {timing} Record source, interval and observed signal or missing coverage.")

    if not targets and not documents:
        add("HUMAN ESCALATION REQUIRED (NOT SOP-BACKED)",
            "Ask the authorized incident owner to identify the service, incident interval and a scoped telemetry source for the unresolved diagnosis. No evidence-linked inspection is available yet.")
    return checks
