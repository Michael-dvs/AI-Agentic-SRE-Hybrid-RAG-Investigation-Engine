"""C14 workflow tests using synthetic telemetry and an offline replay provider."""
from __future__ import annotations

import json

import pytest

from gateway.audit import SecurityAuditLogger
from gateway.policy import PolicyGateway
from orchestrator.dossier import DossierMarkdownRenderer
from orchestrator.investigator import DeterministicInvestigator
from orchestrator.llm_investigator import LLMInvestigator, LLMRunLedger
from orchestrator.llm_provider import ProviderReply, ReplayProvider
from orchestrator.state_machine import InvestigationStateMachine, WorkflowStateStore, utc_now_z


class Correlator:
    def build_impact_graph(self, **kwargs):
        return {"upstream_callers": [], "downstream_dependencies": [], "edges": []}


class Dispatcher:
    def __init__(self, conflict=False, outage=False):
        self.conflict, self.outage = conflict, outage

    def dispatch(self, tool_name, arguments, **kwargs):
        if tool_name == "retrieve_runbooks":
            return {"citations": []}, "ok", None, "synthetic-kb"
        if tool_name == "get_trace_summary" and self.outage:
            return {}, "unavailable", "SOURCE_UNAVAILABLE", "synthetic-trace"
        if tool_name == "get_service_metrics":
            metric = arguments["metric_enum"]
            records = [{"service_id": "auth-service", "metric_enum": metric,
                        "value": 0.0 if metric == "error_rate" else 1.0}]
        elif tool_name == "search_error_logs":
            records = [{"service_id": "auth-service", "status_code": 500 if self.conflict else 401,
                        "message": "server error" if self.conflict else "authentication rejected"}]
        else:
            records = [{"service_id": "auth-service", "span_id": "abcdef0123456789",
                        "duration_ms": 10, "status_code": "OK"}]
        return {"records": records}, "ok", None, "synthetic-telemetry"


def run_workflow(tmp_path, *, conflict=False, outage=False, citation=None):
    incident_id = "inc-c14-integration"
    candidate = {
        "primary_hypothesis": {"summary": "Service error", "diagnosis": "A service error was observed.",
                               "confidence": "MEDIUM", "estimated_root_cause": "Cause requires investigation."},
        "alternative_hypotheses": [], "supporting_evidence_ids": [f"ev-{incident_id}-002"],
        "contradicting_evidence_ids": [], "unknowns": ["Cause remains uncertain."],
    }
    provider = ReplayProvider([ProviderReply(json.dumps(candidate), 100, 50, "synthetic-replay")])
    ledger = LLMRunLedger(tmp_path / "usage.sqlite3")
    audit = SecurityAuditLogger(tmp_path / "security.jsonl")
    llm = LLMInvestigator(provider, ledger, audit, artifact_dir=tmp_path / "io")
    store = WorkflowStateStore(":memory:")

    class Investigator(DeterministicInvestigator):
        def _step_hypotheses(self, incident_id, context):
            context = super()._step_hypotheses(incident_id, context)
            if citation:
                # Exercise post-retrieval defense independently of C13's pre-model filter.
                context["runbook_citations"].append(citation)
            return context

    try:
        inv = Investigator(InvestigationStateMachine(store), PolicyGateway(dispatcher=Dispatcher(conflict, outage), audit_logger=audit),
                           correlator=Correlator(), llm_investigator=llm)
        result = inv.investigate_incident({"incident_id": incident_id, "service_id": "auth-service",
                                           "environment": "lab", "event_time": utc_now_z()})
        return result
    finally:
        ledger.close()
        store.close()


def test_agentic_supported_or_partial(tmp_path):
    result = run_workflow(tmp_path)
    assert result["status"] == "HUMAN_REVIEW"
    assert result["dossier"]["investigation_mode"] == "agentic_llm"
    assert result["dossier"]["hypotheses"][0]["support_status"] in {"SUPPORTED", "PARTIAL"}
    assert "VERIFIED" not in json.dumps(result["dossier"]).upper()


def test_ev01_conflicting_signals_visible(tmp_path):
    result = run_workflow(tmp_path, conflict=True)
    assert result["status"] == "HUMAN_REVIEW"
    assert result["dossier"]["hypotheses"][0]["support_status"] == "PARTIAL"
    assert any("EV-01" in item for item in result["validation_summary"]["contradictions"])
    assert "EV-01" in result["dossier_markdown"]


def test_ev02_trace_outage_abstains(tmp_path):
    result = run_workflow(tmp_path, outage=True)
    dossier = result["dossier"]
    assert dossier["hypotheses"][0]["support_status"] == "INCONCLUSIVE"
    assert result["hypotheses"][0]["confidence_score"] <= 0.40
    assert any("trace" in text.lower() for text in dossier["unknowns"])
    trace = [e for e in result["evidence_items"] if e["tool_name"] == "get_trace_summary"]
    assert len(trace) == 1 and trace[0]["error_code"] == "SOURCE_UNAVAILABLE" and not trace[0]["records"]


def test_sc10_expired_citation_is_not_active(tmp_path):
    citation = {"chunk_id": "old-auth", "document_id": "SOP-AUTH", "document_version": "1.0",
                "source_uri": "synthetic://auth/old", "service_id": "auth-service", "environment": "lab",
                "status": "obsolete", "effective_from": "2020-01-01T00:00:00Z",
                "effective_to": "2021-01-01T00:00:00Z"}
    result = run_workflow(tmp_path, citation=citation)
    assert result["status"] == "HUMAN_REVIEW"
    assert all(c.get("chunk_id") != "old-auth" for c in result["dossier"]["sop_citations"])
    assert "OBSOLETE_SOP" in json.dumps(result["validation_summary"])
    assert "OBSOLETE_SOP" in result["dossier_markdown"]
