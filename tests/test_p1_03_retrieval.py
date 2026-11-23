"""P1-03: retrieval-time eligibility and post-retrieval citation integrity."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

import pytest

from gateway.audit import SecurityAuditLogger
from gateway.dispatcher import ToolDispatcher
from gateway.policy import PolicyGateway
from knowledge_base.ingestion.lifecycle import KnowledgeLifecycleManager
from knowledge_base.ingestion.parser import parse_markdown_document
from knowledge_base.ingestion.validator import validate_document_metadata
from knowledge_base.retrieval import RetrievalEngine, RetrievalService
from knowledge_base.retrieval.service import _RES_VALIDATOR, unavailable_result
from orchestrator.claim_validator_contract import ClaimValidator


CORPUS = Path(__file__).resolve().parents[1] / "knowledge_base" / "corpus"
INDEX = "p1-03-unit-index"
GROUP = "l1-operator"
REQUEST = dict(service_id="api-gateway", environment="lab", reference_time="2026-11-15T10:00:00Z",
               query_text="Identifikasi dan Triage Awal HTTP 5xx SimHighErrorRate ingress API Gateway",
               retrieval_mode="hybrid_rrf", top_k=10, max_context_tokens=2048, index_version_policy="kb_active_alias")


@pytest.fixture(autouse=True)
def offline_embedder(monkeypatch):
    # Exercise the real local projection without downloading optional models.
    for module in ("sentence_transformers", "fastembed"):
        monkeypatch.setitem(sys.modules, module, None)


@pytest.fixture(scope="module")
def chunks(tmp_path_factory):
    root = tmp_path_factory.mktemp("p1-03-corpus")
    directory = root / "api_gateway"
    directory.mkdir()
    for name in ("SOP-GW-001.md", "ARCH-GW-001.md"):
        shutil.copyfile(CORPUS / "api_gateway" / name, directory / name)
    manifest, _ = KnowledgeLifecycleManager().build_manifest_from_corpus(root, INDEX)
    return manifest.chunks


def retrieve(chunks, *, groups=(GROUP,), **overrides):
    service = RetrievalService(RetrievalEngine(chunks, index_version=INDEX))
    return service.execute_retrieval({**REQUEST, **overrides}, caller_groups=list(groups), runbooks_only=True)


def validate(citations, **overrides):
    return ClaimValidator().validate_sop_citations(citations, **{
        "incident_service": REQUEST["service_id"], "incident_environment": REQUEST["environment"],
        "event_time_iso": REQUEST["reference_time"], **overrides,
    })


@pytest.mark.parametrize("mode", ["lexical_only", "dense_only", "hybrid_rrf", "hybrid_rerank"])
def test_a01_active_citations_keep_source_section_and_hash(chunks, mode):
    result = retrieve(chunks, retrieval_mode=mode)
    assert (result.status, result.gap_reason, result.index_version) == ("ok", None, INDEX)
    assert result.citations
    sources = {row["chunk_id"]: row for row in chunks}
    for citation in result.citations:
        source = sources[citation.chunk_id]
        assert citation.document_id == "SOP-GW-001"
        assert (citation.document_version, citation.section_path) == (source["document_version"], source["section_path"])
        assert citation.content_hash == sha256(source["content"].encode()).hexdigest()
        assert source["content"].startswith(citation.sanitized_excerpt)
        assert citation.source_uri == "kb://corpus/api_gateway/SOP-GW-001.md"
        assert (CORPUS / citation.source_uri.removeprefix("kb://corpus/")).is_file()
    accepted, rejected, _ = validate([c.to_dict() for c in result.citations])
    assert len(accepted) == len(result.citations) and not rejected


def test_a02_architecture_note_is_not_a_runbook(chunks):
    notes = [row for row in chunks if row["document_id"].startswith("ARCH-")]
    result = retrieve(notes, query_text=notes[0]["title"])
    assert (result.status, result.gap_reason, result.citations) == ("no_match", "NO_APPLICABLE_RUNBOOK", [])


@pytest.mark.parametrize("outage", ["uninitialized", "simulated", "timeout"])
def test_a03_dispatcher_outage_is_not_a_completed_empty_search(chunks, monkeypatch, outage):
    dispatcher = ToolDispatcher.__new__(ToolDispatcher)
    dispatcher.simulated_outages = {"retrieve_runbooks"} if outage == "simulated" else set()
    dispatcher.retrieval_service = RetrievalService(RetrievalEngine(chunks, index_version=INDEX))
    if outage == "uninitialized":
        dispatcher.retrieval_service = None
    if outage == "timeout":
        def timed_out(*args, **kwargs):
            raise TimeoutError("private backend detail")
        monkeypatch.setattr(dispatcher.retrieval_service.engine, "query", timed_out)
    result, status, gap, _ = dispatcher.dispatch("retrieve_runbooks", REQUEST, caller_groups=[GROUP])
    assert (result["status"], status, result["gap_reason"], gap) == ("unavailable", "unavailable", "RETRIEVAL_UNAVAILABLE", "RETRIEVAL_UNAVAILABLE")
    assert result["citations"] == [] and result["index_version"] is None
    assert "private backend detail" not in str(result)


@pytest.mark.parametrize("changes", [
    {"service_id": "auth-service"}, {"environment": "sim-prod-like"}, {"status": "obsolete"},
    {"status": "draft"}, {"effective_from": "2027-01-01T00:00:00Z"}, {"effective_to": REQUEST["reference_time"]},
])
def test_a04_a05_a07_ineligible_even_with_exact_query(chunks, changes):
    row = next(c for c in chunks if c["document_id"] == "SOP-GW-001")
    result = retrieve([{**row, **changes}], query_text=row["title"])
    assert result.status == "no_match" and not result.citations


@pytest.mark.parametrize("classification", ["synthetic-internal", "synthetic-confidential", "synthetic-restricted"])
def test_a08_denied_acl_never_returns_private_metadata(chunks, classification):
    row = next(c for c in chunks if c["document_id"] == "SOP-GW-001")
    private = {**row, "classification": classification, "allowed_groups": ["private-team"], "title": "Private sentinel title"}
    result = retrieve([private], groups=["sre-core-l1"])
    public = json.dumps(result.to_dict())
    assert result.status == "no_match" and not result.citations
    assert all(secret not in public for secret in (private["chunk_id"], private["title"], private["source_uri"], "private-team"))


def test_a08_no_groups_cannot_be_upgraded_by_dispatcher(chunks):
    dispatcher = ToolDispatcher.__new__(ToolDispatcher)
    dispatcher.retrieval_service = RetrievalService(RetrievalEngine(chunks, index_version=INDEX))
    dispatcher.simulated_outages = set()
    result, status, reason, _ = dispatcher.dispatch("retrieve_runbooks", REQUEST, caller_groups=[])
    assert (status, reason, result["citations"]) == ("rejected", "FORBIDDEN_SCOPE", [])


def test_a09_a10_identical_sections_deduplicate_but_conflicting_sources_remain(chunks):
    row = next(c for c in chunks if c["document_id"] == "SOP-GW-001")
    alternate = {**row, "chunk_id": "chk-other-guidance", "document_id": "SOP-UNIT-OTHER",
                 "source_uri": "kb://unit/other.md", "content": "Review upstream latency before inspecting ingress errors."}
    alternate["content_hash"] = sha256(alternate["content"].encode()).hexdigest()
    result = retrieve([row, row, {**row, "chunk_id": "chk-duplicate"}, alternate], query_text=row["title"])
    assert sorted(c.document_id for c in result.citations) == ["SOP-GW-001", "SOP-UNIT-OTHER"]
    assert len({c.content_hash for c in result.citations}) == 2


@pytest.mark.parametrize("field", ["service_id", "document_version", "document_id", "environment", "allowed_groups", "effective_to"])
def test_a11_ingestion_does_not_invent_required_metadata(field):
    source = parse_markdown_document(CORPUS / "api_gateway/SOP-GW-001.md")
    raw = {k: v for k, v in source.metadata.items() if k != field}
    with pytest.raises(ValueError):
        validate_document_metadata(raw)


@pytest.mark.parametrize("changes", [{"service_id": ""}, {"query_text": "   "}, {"environment": ""}, {"reference_time": ""}])
def test_a11_missing_matching_context_is_rejected_not_empty(chunks, changes):
    result = retrieve(chunks, **changes)
    assert (result.status, result.gap_reason, result.citations) == ("rejected", "SCHEMA_INVALID", [])


@pytest.mark.parametrize("defect", ["empty", "pinned_elsewhere", "mixed_version", "missing_version", "missing_acl", "hash_mismatch", "ambiguous_chunk"])
def test_a06_a12_unreliable_index_is_not_coverage_absence(chunks, defect):
    row = dict(chunks[0])
    batch = [row]
    policy = INDEX
    if defect == "empty":
        batch = []
    elif defect == "pinned_elsewhere":
        policy = "unloaded-index"
    elif defect == "mixed_version":
        batch.append({**chunks[1], "index_version": "stale-index"})
    elif defect == "missing_version":
        del row["document_version"]
    elif defect == "missing_acl":
        del row["allowed_groups"]
    elif defect == "hash_mismatch":
        row["content"] += "Modified after hashing."
    else:
        batch.append({**row, "allowed_groups": ["different-team"]})
    result = retrieve(batch, index_version_policy=policy)
    assert (result.status, result.gap_reason, result.citations) == ("unavailable", "RETRIEVAL_UNAVAILABLE", [])


def test_c14_rechecks_metadata_and_rejections_are_nonidentifying(chunks):
    good = retrieve(chunks).citations[0].to_dict()
    for field in ("document_version", "effective_from", "effective_to", "status", "content_hash", "applicability_verified", "sanitized_excerpt"):
        bad = {k: v for k, v in good.items() if k != field}
        valid, rejected, reasons = validate([bad])
        assert not valid and reasons and set(rejected[0]) == {"rejection_reason", "details"}
        assert good["document_id"] not in str(rejected)
    assert not validate([good], event_time_iso="unavailable")[0]
    assert not validate([{**good, "source_uri": "kb://corpus/../private.md"}])[0]
    assert not validate([{**good, "document_id": "ARCH-GW-001"}])[0]
    assert not validate([good, {**good, "content_hash": "0" * 64}])[0]


def test_gateway_default_coordinator_retrieves_internal_sop_and_blocks_restricted(tmp_path):
    gw = PolicyGateway(audit_logger=SecurityAuditLogger(tmp_path / "audit.jsonl"))
    res_ledger = gw.execute_tool(
        tool_name="retrieve_runbooks",
        arguments={
            "service_id": "ledger-service",
            "environment": "lab",
            "query_text": "PostgreSQL connection pool exhaustion latensi database",
            "reference_time": "2026-11-20T10:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 5,
            "max_context_tokens": 1024,
            "index_version_policy": "kb_active_alias",
        },
        token="Bearer sre-sim-coord-token-secret-2026",
        incident_id="inc-p1-03-gw-ledger",
    )
    assert res_ledger["status"] == "ok"
    assert any(
        c["document_id"] == "SOP-LEDGER-001" and c["document_version"] == "2.0.0"
        for c in res_ledger["citations"]
    )
    assert all(
        c["status"] == "approved"
        and not (c["document_id"] == "SOP-LEDGER-001" and c["document_version"] == "1.0.0")
        for c in res_ledger["citations"]
    )

    res_auth = gw.execute_tool(
        tool_name="retrieve_runbooks",
        arguments={
            "service_id": "auth-service",
            "environment": "lab",
            "query_text": "SOP Rahasia Rotasi Master Secret Kunci Kriptografi Internal",
            "reference_time": "2026-11-20T10:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 5,
            "max_context_tokens": 1024,
            "index_version_policy": "kb_active_alias",
        },
        token="Bearer sre-sim-coord-token-secret-2026",
        incident_id="inc-p1-03-gw-auth",
    )
    assert all(c["document_id"] != "SOP-SEC-KEY-ROTATION" for c in res_auth["citations"])
    serialized = json.dumps(res_auth)
    assert "SOP-SEC-KEY-ROTATION" not in serialized
    assert "sec-admin@sim.bank" not in serialized


def test_unavailable_result_handles_incomplete_request():
    res = unavailable_result({}, "principal:investigator-coord").to_dict()
    assert _RES_VALIDATOR.is_valid(res)
    assert (res["status"], res["gap_reason"], res["citations"], res["index_version"]) == (
        "unavailable",
        "RETRIEVAL_UNAVAILABLE",
        [],
        None,
    )
