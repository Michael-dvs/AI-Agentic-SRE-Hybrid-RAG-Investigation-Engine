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


def test_p0_01_irrelevant_and_contradicted_alternatives_do_not_retain_false_evidence(tmp_path):
    """P0-01 regression: rate-limit / traffic-surge alternatives cannot retain downstream 503 log evidence."""
    from jsonschema import Draft202012Validator, FormatChecker
    from orchestrator.dossier import DossierSerializer

    incident_id = "inc-p0-01-gw"

    class GatewayDispatcher:
        def dispatch(self, tool_name, arguments, **kwargs):
            if tool_name == "retrieve_runbooks":
                return {"citations": []}, "ok", None, "synthetic-kb"
            if tool_name == "get_service_metrics":
                metric = arguments["metric_enum"]
                val = 0.4833 if metric == "request_rate" else 0.31
                return {
                    "records": [
                        {"service_id": "api-gateway", "metric_enum": metric, "value": val},
                        {"service_id": "api-gateway", "metric_enum": metric, "value": val},
                    ]
                }, "ok", None, "synthetic-prometheus"
            if tool_name == "search_error_logs":
                return {
                    "records": [
                        {
                            "service_id": "api-gateway",
                            "status_code": 503,
                            "error_code": "ERR_DEPENDENCY_UNAVAILABLE",
                            "message": "ERR_DEPENDENCY_UNAVAILABLE: Downstream dependency on transaction-service refused connection",
                        }
                    ]
                }, "ok", None, "synthetic-loki"
            return {
                "records": [{"service_id": "api-gateway", "span_id": "4d6de2bc32063db7", "duration_ms": 17.2, "status_code": "OK"}]
            }, "ok", None, "synthetic-tempo"

    candidate = {
        "primary_hypothesis": {
            "summary": "api-gateway degraded due to downstream transaction-service connection failures",
            "diagnosis": "Downstream dependency on transaction-service refused connection causing 503 ERR_DEPENDENCY_UNAVAILABLE.",
            "confidence": "MEDIUM",
            "estimated_root_cause": "transaction-service is refusing connections.",
        },
        "alternative_hypotheses": [
            {
                "summary": "api-gateway rate limiting or configuration change causing reduced request acceptance",
                "diagnosis": "Internal rate limiting thresholds blocking legitimate requests.",
                "confidence": "LOW",
                "estimated_root_cause": "Misconfigured rate limit threshold.",
                "supporting_evidence_ids": [f"ev-{incident_id}-002"],
                "contradicting_evidence_ids": [],
            },
            {
                "summary": "upstream client traffic surge overwhelming api-gateway capacity",
                "diagnosis": "Sudden increase in client request rate exceeding api-gateway capacity.",
                "confidence": "LOW",
                "estimated_root_cause": "Client traffic surge.",
                "supporting_evidence_ids": [f"ev-{incident_id}-001"],
                "contradicting_evidence_ids": [],
            },
        ],
        "supporting_evidence_ids": [f"ev-{incident_id}-002"],
        "contradicting_evidence_ids": [],
        "unknowns": [
            "api-gateway rate limit configuration values",
            "client traffic patterns and expected baseline request rates",
        ],
    }

    provider = ReplayProvider([ProviderReply(json.dumps(candidate), 120, 80, "synthetic-replay")])
    ledger = LLMRunLedger(tmp_path / "usage.sqlite3")
    audit = SecurityAuditLogger(tmp_path / "security.jsonl")
    llm = LLMInvestigator(provider, ledger, audit, artifact_dir=tmp_path / "io")
    store = WorkflowStateStore(":memory:")
    try:
        inv = DeterministicInvestigator(
            InvestigationStateMachine(store),
            PolicyGateway(dispatcher=GatewayDispatcher(), audit_logger=audit),
            correlator=Correlator(),
            llm_investigator=llm,
        )
        result = inv.investigate_incident({
            "incident_id": incident_id,
            "service_id": "api-gateway",
            "environment": "lab",
            "event_time": utc_now_z(),
        })
        assert result["status"] == "HUMAN_REVIEW"
        dossier = result["dossier"]
        Draft202012Validator(DossierSerializer.get_schema(), format_checker=FormatChecker()).validate(dossier)

        # Primary hypothesis keeps valid relevant log evidence and is never upgraded to VERIFIED
        h_primary, h_rate_limit, h_surge = dossier["hypotheses"]
        assert h_primary["supporting_evidence_ids"] == [f"ev-{incident_id}-002"]
        assert h_primary["support_status"] == "PARTIAL"

        # Rate-limit alternative: irrelevant 503 log stripped; dossier status INCONCLUSIVE; validation_summary UNSUPPORTED
        assert h_rate_limit["supporting_evidence_ids"] == []
        assert h_rate_limit["support_status"] == "INCONCLUSIVE"

        # Traffic-surge alternative: flat low request_rate contradicts surge; supporting empty, contradicting populated
        assert h_surge["supporting_evidence_ids"] == []
        assert f"ev-{incident_id}-001" in h_surge["contradicting_evidence_ids"]
        assert h_surge["support_status"] == "INCONCLUSIVE"

        val_map = {
            item["hypothesis_id"]: item
            for item in result["validation_summary"]["hypothesis_validations"]
        }
        assert val_map[h_rate_limit["hypothesis_id"]]["validation_status"] == "UNSUPPORTED"
        assert "IRRELEVANT_EVIDENCE" in val_map[h_rate_limit["hypothesis_id"]]["reason_codes"]
        assert val_map[h_surge["hypothesis_id"]]["validation_status"] == "CONTRADICTED"
        assert "CLAIM_CONTRADICTED" in val_map[h_surge["hypothesis_id"]]["reason_codes"]
        assert "VERIFIED" not in json.dumps(dossier).upper()
    finally:
        ledger.close()
        store.close()

