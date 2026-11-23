"""Chapter C07 Automated Verification Suite — Hybrid Retrieval and Baselines (AT-006, AT-007, RAG-01, RAG-02, SEC-01, SC-10)."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from knowledge_base.ingestion.lifecycle import KnowledgeLifecycleManager
from knowledge_base.retrieval import (
    RetrievalEngine,
    RetrievalRequest,
    RetrievalResult,
    RetrievalService,
    StrictPreFilter,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCHEMA_PATH = (
    _REPO_ROOT
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
    / "retrieval-result.v1.schema.json"
)
_DEV_QUERIES_PATH = _REPO_ROOT / "knowledge_base" / "eval_queries" / "dev_queries.json"
_HASHES_PATH = (
    _REPO_ROOT / "evidence" / "c06-20261111T150000Z" / "C06" / "chunk-hashes.json"
)

# Load JSON schema validator
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def retrieval_fixtures() -> tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]:
    """Build knowledge manifest and initialize engine and service."""
    manager = KnowledgeLifecycleManager()
    manifest, _ = manager.build_manifest_from_corpus(
        _REPO_ROOT / "knowledge_base" / "corpus", "kb-idx-20261111-v1"
    )
    engine = RetrievalEngine(chunks=manifest.chunks, index_version="kb-idx-20261111-v1")
    service = RetrievalService(engine=engine)
    raw_hashes = json.loads(_HASHES_PATH.read_text(encoding="utf-8"))
    hashes_dict = {item["chunk_id"]: item["content_hash"] for item in raw_hashes}
    return engine, service, manifest.chunks, hashes_dict


def test_schema_compliance_across_modes(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """Verify that retrieval results in all 4 modes validate 100% against retrieval-result.v1.schema.json."""
    _, service, _, _ = retrieval_fixtures
    modes = ["lexical_only", "dense_only", "hybrid_rrf", "hybrid_rerank"]

    for mode in modes:
        req = {
            "service_id": "api-gateway",
            "environment": "lab",
            "query_text": "Bagaimana mitigasi lonjakan error HTTP 5xx pada gateway?",
            "reference_time": "2026-11-11T16:00:00Z",
            "retrieval_mode": mode,
            "top_k": 3,
            "max_context_tokens": 1024,
            "index_version_policy": "kb-idx-20261111-v1",
        }
        result = service.execute_retrieval(req, caller_groups=["l1-operator"])
        res_dict = result.to_dict()

        errors = list(_VALIDATOR.iter_errors(res_dict))
        assert not errors, f"Mode {mode} output schema validation failed: {[e.message for e in errors]}"
        assert result.status == "ok"
        assert result.retrieval_mode_executed == mode
        assert len(result.citations) > 0
        assert result.citations[0].applicability_verified is True


def test_malformed_request_rejected(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """Verify that a malformed request is rejected gracefully with SCHEMA_INVALID."""
    _, service, _, _ = retrieval_fixtures
    malformed_req = {
        "service_id": "api-gateway",
        "environment": "lab",
        # Missing query_text, invalid top_k
        "top_k": 999,
        "retrieval_mode": "invalid_mode",
    }
    result = service.execute_retrieval(malformed_req)
    assert result.status == "rejected"
    assert result.gap_reason == "SCHEMA_INVALID"
    assert len(result.citations) == 0


def test_rag_01_sc10_obsolete_sop_prevention(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """RAG-01 / SC-10: Verify obsolete version (SOP-LEDGER-001 v1.0.0) is never returned as active citation."""
    _, service, _, _ = retrieval_fixtures
    req = {
        "service_id": "ledger-service",
        "environment": "lab",
        "query_text": "Mitigasi latensi database PostgreSQL ledger dan penanganan kueri lambat",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 5,
        "max_context_tokens": 2048,
        "index_version_policy": "latest",
    }
    result = service.execute_retrieval(req, caller_groups=["l1-operator"])
    assert result.status == "ok"
    assert len(result.citations) > 0

    for cit in result.citations:
        if cit.document_id == "SOP-LEDGER-001":
            assert cit.document_version == "2.0.0", (
                f"Obsolete SOP-LEDGER-001 version {cit.document_version} returned! Must only return v2.0.0."
            )
            assert cit.status == "approved"
            assert cit.effective_to is None


def test_rag_02_cross_service_isolation(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """RAG-02: Verify documents from another service are strictly isolated even with identical error codes (504)."""
    _, service, _, _ = retrieval_fixtures
    # Ingress Gateway timeout query
    gw_req = {
        "service_id": "api-gateway",
        "environment": "lab",
        "query_text": "Penanganan HTTP 504 Gateway Timeout pada ingress api",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 5,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }
    gw_result = service.execute_retrieval(gw_req, caller_groups=["l1-operator"])
    assert gw_result.status == "ok"
    for cit in gw_result.citations:
        assert cit.service_id == "api-gateway", f"Cross-service document {cit.document_id} from {cit.service_id} leaked to api-gateway!"
        assert cit.document_id != "SOP-LEDGER-ERR-504"

    # Ledger timeout query
    ledger_req = {
        "service_id": "ledger-service",
        "environment": "lab",
        "query_text": "Penanganan query timeout SQL 504 pada ledger service",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 5,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }
    ledger_result = service.execute_retrieval(ledger_req, caller_groups=["l1-operator"])
    assert ledger_result.status == "ok"
    for cit in ledger_result.citations:
        assert cit.service_id == "ledger-service", f"Cross-service document {cit.document_id} from {cit.service_id} leaked to ledger-service!"
        assert cit.document_id != "SOP-GW-ERR-504"


def test_sec_01_restricted_document_authorization(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """SEC-01: Verify synthetic-restricted document (SOP-SEC-KEY-ROTATION) is inaccessible to unprivileged callers."""
    _, service, _, _ = retrieval_fixtures
    sec_query = {
        "service_id": "auth-service",
        "environment": "lab",
        "query_text": "Prosedur darurat rotasi cryptographic master key and secret signing keys",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 5,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }

    # Case A: Unprivileged caller (sre-core-l1)
    unauth_result = service.execute_retrieval(
        sec_query, caller_scope_ref="sre-l1-agent", caller_groups=["sre-core-l1"]
    )
    for cit in unauth_result.citations:
        assert cit.document_id != "SOP-SEC-KEY-ROTATION", (
            f"Security violation: restricted document {cit.document_id} leaked to unprivileged caller!"
        )

    # Case B: Privileged caller (security-admin / sre-core-l2)
    auth_result = service.execute_retrieval(
        sec_query,
        caller_scope_ref="sre-l2-admin",
        caller_groups=["sre-core-l2", "security-admin"],
    )
    assert auth_result.status == "ok"
    assert any(c.document_id == "SOP-SEC-KEY-ROTATION" for c in auth_result.citations), (
        "Privileged caller should be authorized to retrieve SOP-SEC-KEY-ROTATION."
    )


def test_honest_gap_handling_no_match(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """FR-RAG-009 / RULE-006: Out-of-scope or unhandled queries return no_match without fabricating citations."""
    _, service, _, _ = retrieval_fixtures
    unrelated_req = {
        "service_id": "api-gateway",
        "environment": "lab",
        "query_text": "Troubleshooting Kubernetes CNI flannel network overlay packet loss",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "lexical_only",
        "top_k": 3,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }
    result = service.execute_retrieval(unrelated_req, caller_groups=["l1-operator"])
    assert result.status == "no_match"
    assert result.gap_reason == "NO_APPLICABLE_RUNBOOK"
    assert len(result.citations) == 0


def test_honest_gap_handling_outage(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """NFR-016 / AT-012: Induces backend outage simulation and verifies honest unavailable status."""
    engine, service, _, _ = retrieval_fixtures
    req = {
        "service_id": "api-gateway",
        "environment": "lab",
        "query_text": "Penanganan lonjakan error rate HTTP 5xx pada gateway",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 3,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }

    # Simulate outage
    engine.set_healthy(False)
    outage_result = service.execute_retrieval(req, caller_groups=["l1-operator"])
    assert outage_result.status == "unavailable"
    assert outage_result.gap_reason == "RETRIEVAL_UNAVAILABLE"
    assert len(outage_result.citations) == 0

    # Recover
    engine.set_healthy(True)
    recovered_result = service.execute_retrieval(req, caller_groups=["l1-operator"])
    assert recovered_result.status == "ok"
    assert len(recovered_result.citations) > 0


def test_citation_provenance_and_hash_integrity(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """FR-RAG-005 / AT-013: Verify all citations have authentic content_hash registered in chunk-hashes.json."""
    _, service, _, hashes_dict = retrieval_fixtures
    req = {
        "service_id": "api-gateway",
        "environment": "lab",
        "query_text": "Catatan arsitektur reverse proxy ingress gateway",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 3,
        "max_context_tokens": 1024,
        "index_version_policy": "latest",
    }
    result = service.execute_retrieval(req, caller_groups=["l1-operator"])
    assert result.status == "ok"

    for cit in result.citations:
        assert cit.chunk_id in hashes_dict, f"Unknown chunk {cit.chunk_id} returned!"
        assert cit.content_hash == hashes_dict[cit.chunk_id], (
            f"Content hash mismatch for {cit.chunk_id}: {cit.content_hash} != {hashes_dict[cit.chunk_id]}"
        )
        assert cit.source_uri.startswith("kb://")
        assert cit.status == "approved"
        assert cit.applicability_verified is True


def test_context_token_bounding_and_truncation(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """Verify context token bounds strictly throttle output and set truncated flag."""
    _, service, _, _ = retrieval_fixtures
    req = {
        "service_id": "api-gateway",
        "environment": "lab",
        "query_text": "Bagaimana penanganan error gateway",
        "reference_time": "2026-11-11T16:00:00Z",
        "retrieval_mode": "hybrid_rrf",
        "top_k": 10,
        "max_context_tokens": 120,  # very small token cap
        "index_version_policy": "latest",
    }
    result = service.execute_retrieval(req, caller_groups=["l1-operator"])
    assert result.context_tokens_used <= 120
    assert result.truncated is True


def test_dev_benchmark_reproducibility(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """AT-006: Run benchmark over all 28 DEV queries on hybrid_rrf and verify Hit-Rate@5 >= 95%."""
    _, service, _, _ = retrieval_fixtures
    dev_queries = json.loads(_DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    assert len(dev_queries) == 28, f"Expected exactly 28 DEV queries, got {len(dev_queries)}"

    hits = 0
    for q in dev_queries:
        req = {
            "service_id": q["target_service_id"],
            "environment": "lab",
            "query_text": q["query_text"],
            "reference_time": "2026-11-11T16:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 5,
            "max_context_tokens": 2048,
            "index_version_policy": "latest",
        }
        res = service.execute_retrieval(req, caller_groups=["l1-operator"])
        assert res.status == "ok", f"Query {q['query_id']} failed with status {res.status}"

        # Clean document IDs
        expected_docs = {d[:-3] if d.endswith(".md") else d for d in q["expected_document_ids"]}
        returned_docs = {c.document_id for c in res.citations}

        if expected_docs.intersection(returned_docs):
            hits += 1

    hit_rate = hits / len(dev_queries)
    assert hit_rate >= 0.95, f"Hit-rate {hit_rate:.1%} is below candidate threshold 95%!"


def test_indonesian_technical_semantic_retrieval_and_embedding_metadata(
    retrieval_fixtures: tuple[RetrievalEngine, RetrievalService, list[dict[str, Any]], dict[str, str]]
) -> None:
    """ADR-S04 / C07: Verify 384-d multilingual embedding model metadata and semantic matching on technical Indonesian queries."""
    engine, service, _, _ = retrieval_fixtures

    # 1. Verify model metadata and dimension invariants
    assert engine.embedder.dimension == 384
    assert engine.embedder.model_name == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert engine.dense_vectors.shape[1] == 384

    # 2. Test semantic query matching on technical Indonesian queries
    test_cases = [
        {
            "service_id": "db-dummy",
            "query_text": "bagaimana mitigasi sambungan database penuh",
            "expected_doc_id": "SOP-DB-001",
            "groups": ["l1-operator"],
        },
        {
            "service_id": "auth-service",
            "query_text": "prosedur rotasi kunci otentikasi darurat",
            "expected_doc_id": "SOP-SEC-KEY-ROTATION",
            "groups": ["sre-core-l2", "security-admin"],
        },
        {
            "service_id": "transaction-service",
            "query_text": "prosedur eskalasi lonjakan kegagalan transaksi",
            "expected_doc_id": "SOP-TX-001",
            "groups": ["l1-operator"],
        },
        {
            "service_id": "notification-service",
            "query_text": "mitigasi backlog pesan dan consumer lag rabbitmq",
            "expected_doc_id": "SOP-NOTIF-QUEUE-001",
            "groups": ["l1-operator"],
        },
        {
            "service_id": "notification-service",
            "query_text": "penanganan lonjakan antrean konsumen notifikasi",
            "expected_doc_id": "SOP-NOTIF-001",
            "groups": ["l1-operator"],
        },
    ]

    for tc in test_cases:
        req = {
            "service_id": tc["service_id"],
            "environment": "lab",
            "query_text": tc["query_text"],
            "reference_time": "2026-11-11T16:00:00Z",
            "retrieval_mode": "hybrid_rrf",
            "top_k": 3,
            "max_context_tokens": 1024,
            "index_version_policy": "latest",
        }
        res = service.execute_retrieval(req, caller_groups=tc["groups"])
        assert res.status == "ok", f"Query '{tc['query_text']}' failed: {res.gap_reason}"
        returned_doc_ids = [c.document_id for c in res.citations]
        assert tc["expected_doc_id"] in returned_doc_ids, (
            f"Expected {tc['expected_doc_id']} in top citations for '{tc['query_text']}', got {returned_doc_ids}"
        )

        # Validate schema compliance
        res_dict = res.to_dict()
        errors = list(_VALIDATOR.iter_errors(res_dict))
        assert not errors, f"Schema validation error: {[e.message for e in errors]}"

