"""Automated unit, schema compliance, redaction, lifecycle, and isolation tests for C06."""

from __future__ import annotations

import json
import pathlib
import re
import tempfile
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from knowledge_base.ingestion import (
    IndexManifest,
    KnowledgeLifecycleManager,
    RedactionReport,
    StructureAwareChunker,
    parse_markdown_document,
    sanitize_document_text,
    validate_document_metadata,
)

CORPUS_DIR = pathlib.Path(__file__).resolve().parent.parent / "knowledge_base" / "corpus"
DEV_QUERIES_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "knowledge_base"
    / "eval_queries"
    / "dev_queries.json"
)
HOLDOUT_QUERIES_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "restricted"
    / "evaluator_queries"
    / "holdout_queries.json"
)
CONTRACT_SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
    / "knowledge-chunk.v1.schema.json"
)


@pytest.fixture(scope="module")
def chunk_schema_validator() -> Draft202012Validator:
    assert CONTRACT_SCHEMA_PATH.exists(), f"Missing contract: {CONTRACT_SCHEMA_PATH}"
    schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def default_manifest() -> IndexManifest:
    mgr = KnowledgeLifecycleManager()
    manifest, _ = mgr.build_manifest_from_corpus(CORPUS_DIR, index_version="kb-idx-20261111-v1")
    return manifest


def test_c06_corpus_structure_and_document_count():
    """Verify that the synthetic knowledge base corpus contains >= 15 documents across all 6 services."""
    assert CORPUS_DIR.is_dir(), f"Corpus dir not found: {CORPUS_DIR}"
    doc_files = sorted(
        [p for p in CORPUS_DIR.rglob("*.md") if not p.name.startswith(".")]
    )
    assert len(doc_files) >= 15, f"Expected at least 15 corpus docs, got {len(doc_files)}"

    # Ensure all services from Service Catalog C05 are represented
    service_ids = set()
    for doc_file in doc_files:
        parsed = parse_markdown_document(doc_file)
        meta = validate_document_metadata(parsed.metadata, file_path=doc_file.name)
        service_ids.add(meta.service_id)

    expected_services = {
        "api-gateway",
        "auth-service",
        "transaction-service",
        "ledger-service",
        "notification-service",
        "db-dummy",
    }
    missing_services = expected_services - service_ids
    assert not missing_services, f"Corpus is missing coverage for services: {missing_services}"


def test_c06_all_chunks_schema_compliance(default_manifest: IndexManifest, chunk_schema_validator: Draft202012Validator):
    """Verify that every chunk produced strictly satisfies knowledge-chunk.v1.schema.json Draft 2020-12."""
    assert default_manifest.chunk_count > 0, "No chunks generated in manifest!"
    for chunk in default_manifest.chunks:
        errors = list(chunk_schema_validator.iter_errors(chunk))
        assert not errors, (
            f"Chunk {chunk.get('chunk_id')} failed schema validation: "
            + "; ".join(e.message for e in errors)
        )


def test_c06_redaction_sanitizer_sec03():
    """Verify pre-ingestion sanitizer redacts synthetic JWT, DB passwords, Bearer, API keys, and PAN (SEC-03)."""
    dirty_text = """
    # Prosedur Konfigurasi Rahasia
    DB Connection: postgres://sre_admin:superSecretPassword123@postgres.internal:5432/ledger
    JWT Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
    Bearer Token: Bearer sim-sec-bearer-token-fixture-abc-987
    API Key: sim-key-auth-secret-key-12345
    Card Number: 4111-2222-3333-4444
    Config Assignment: auth_token = "dummy-secret-payload-xyz"
    """

    report = RedactionReport()
    result = sanitize_document_text(dirty_text, document_id="TEST-DOC-001", report=report)

    # Assert 0 raw secrets remain
    assert "superSecretPassword123" not in result.sanitized_text
    assert "eyJhbGciOiJIUzI1Ni" not in result.sanitized_text
    assert "sim-sec-bearer-token-fixture" not in result.sanitized_text
    assert "sim-key-auth-secret-key-12345" not in result.sanitized_text
    assert "4111-2222-3333-4444" not in result.sanitized_text
    assert "dummy-secret-payload-xyz" not in result.sanitized_text

    # Assert neutral tokens were inserted
    assert "[REDACTED_PASSWORD]" in result.sanitized_text
    assert "[REDACTED_JWT_TOKEN]" in result.sanitized_text
    assert "[REDACTED_BEARER_TOKEN]" in result.sanitized_text
    assert "[REDACTED_API_KEY]" in result.sanitized_text
    assert "[REDACTED_CARD_PAN]" in result.sanitized_text
    assert "[REDACTED_SECRET]" in result.sanitized_text

    assert result.redaction_count >= 6
    assert report.total_redactions >= 6
    assert "synthetic_db_password" in report.redactions_by_type
    assert "synthetic_jwt" in report.redactions_by_type
    assert "synthetic_bearer_token" in report.redactions_by_type
    assert "synthetic_api_key" in report.redactions_by_type
    assert "synthetic_card_pan" in report.redactions_by_type


def test_c06_zero_ground_truth_leakage_at008(default_manifest: IndexManifest):
    """Verify zero ground truth leakage (SC-01..SC-14, fault_harness) in corpus & chunks (AT-008, RULE-002)."""
    gt_patterns = [
        re.compile(r"\bSC-\d{2}\b", re.IGNORECASE),
        re.compile(r"\bfault_harness\b", re.IGNORECASE),
        re.compile(r"\bground_truth\b", re.IGNORECASE),
        re.compile(r"\brecipe_hooks\b", re.IGNORECASE),
    ]

    # Check corpus raw files
    for doc_path in CORPUS_DIR.rglob("*.md"):
        content = doc_path.read_text(encoding="utf-8")
        for pat in gt_patterns:
            match = pat.search(content)
            assert match is None, (
                f"Ground truth leak found in corpus file {doc_path.name}: '{match.group(0)}'"
            )

    # Check generated chunks
    for chunk in default_manifest.chunks:
        chunk_text = f"{chunk['title']} {chunk['section_path']} {chunk['content']}"
        for pat in gt_patterns:
            match = pat.search(chunk_text)
            assert match is None, (
                f"Ground truth leak found in chunk {chunk['chunk_id']}: '{match.group(0)}'"
            )


def test_c06_obsolete_lifecycle_and_version_transition_sc10_rag01(default_manifest: IndexManifest):
    """Verify obsolete SOP trap: v1.0.0 is obsolete with effective_to, and v2.0.0 is approved (SC-10, RAG-01)."""
    ledger_v1_chunks = [
        c
        for c in default_manifest.chunks
        if c["document_id"] == "SOP-LEDGER-001" and c["document_version"] == "1.0.0"
    ]
    ledger_v2_chunks = [
        c
        for c in default_manifest.chunks
        if c["document_id"] == "SOP-LEDGER-001" and c["document_version"] == "2.0.0"
    ]

    assert len(ledger_v1_chunks) > 0, "Missing SOP-LEDGER-001 v1.0.0 chunks"
    assert len(ledger_v2_chunks) > 0, "Missing SOP-LEDGER-001 v2.0.0 chunks"

    # All v1 chunks must be obsolete
    for c in ledger_v1_chunks:
        assert c["status"] == "obsolete", f"v1 chunk {c['chunk_id']} must have status 'obsolete'"
        assert c["effective_to"] is not None, f"v1 chunk {c['chunk_id']} must have effective_to set"
        assert c["effective_to"] == "2026-06-01T00:00:00Z"

    # All v2 chunks must be approved
    for c in ledger_v2_chunks:
        assert c["status"] == "approved", f"v2 chunk {c['chunk_id']} must have status 'approved'"
        assert c["effective_from"] == "2026-06-01T00:00:00Z"
        assert c["effective_to"] is None, f"v2 chunk {c['chunk_id']} must have effective_to null"


def test_c06_multi_service_and_access_isolation_rag02_sec01(default_manifest: IndexManifest):
    """Verify similar error codes map to distinct service_id (RAG-02) and restricted classification (SEC-01)."""
    # 1. RAG-02: Similar timeout codes across services
    gw_504_chunks = [c for c in default_manifest.chunks if c["document_id"] == "SOP-GW-ERR-504"]
    ledger_504_chunks = [c for c in default_manifest.chunks if c["document_id"] == "SOP-LEDGER-ERR-504"]

    assert len(gw_504_chunks) > 0
    assert len(ledger_504_chunks) > 0
    assert all(c["service_id"] == "api-gateway" for c in gw_504_chunks)
    assert all(c["service.name"] == "API Gateway" for c in gw_504_chunks)
    assert all(c["service_id"] == "ledger-service" for c in ledger_504_chunks)
    assert all(c["service.name"] == "Ledger Service" for c in ledger_504_chunks)

    # 2. SEC-01: Restricted document with specific allowed_groups
    sec_chunks = [c for c in default_manifest.chunks if c["document_id"] == "SOP-SEC-KEY-ROTATION"]
    assert len(sec_chunks) > 0
    for sc in sec_chunks:
        assert sc["classification"] == "synthetic-restricted"
        assert set(sc["allowed_groups"]) == {"sre-core-l2", "security-admin"}


def test_c06_determinism_and_lifecycle_rollback():
    """Verify 100% deterministic chunking and atomic alias rollback with cryptographic hash integrity."""
    mgr = KnowledgeLifecycleManager()
    m1, _ = mgr.build_manifest_from_corpus(CORPUS_DIR, index_version="kb-idx-20261111-v1")
    m2, _ = mgr.build_manifest_from_corpus(CORPUS_DIR, index_version="kb-idx-20261111-v1")

    # Determinism
    assert m1.manifest_hash == m2.manifest_hash
    assert len(m1.chunks) == len(m2.chunks)
    for c1, c2 in zip(m1.chunks, m2.chunks):
        assert c1["chunk_id"] == c2["chunk_id"]
        assert c1["content_hash"] == c2["content_hash"]

    # Dynamic supersede
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(
            """---
document_id: "SOP-AUTH-001"
document_version: "2.0.0"
title: "SOP Investigasi Lonjakan Kegagalan Autentikasi (Revisi 2)"
service_id: "auth-service"
service.name: "Auth Service"
environment: "lab"
application: "sre-simulation-poc"
component: "identity"
status: "approved"
effective_from: "2026-11-15T00:00:00Z"
effective_to: null
classification: "synthetic-internal"
allowed_groups:
  - "sre-team"
owner_ref: "sre-auth-owner@sim.bank"
language: "id"
updated_at: "2026-11-15T00:00:00Z"
---

# SOP-AUTH-001: Revisi Baru
Langkah mitigasi baru versi 2.0.0...
"""
        )
        temp_file = f.name

    m_updated, supersede_rec = mgr.supersede_document(
        current_manifest=m1,
        new_document_path=temp_file,
        new_index_version="kb-idx-20261111-v2",
    )
    assert supersede_rec["operation"] == "supersede_document"
    assert supersede_rec["chunks_superseded_to_obsolete"] > 0
    assert m_updated.manifest_hash != m1.manifest_hash

    # Rollback to m1
    m_restored, rollback_rec = mgr.rollback_manifest(m1, rollback_reason="test_rollback")
    assert rollback_rec["manifest_hash_verified"] is True
    assert m_restored.manifest_hash == m1.manifest_hash


def test_c06_evaluation_queries_separation_fr_rag_006():
    """Verify evaluation queries are strictly partitioned into DEV (70%) and isolated HOLDOUT (30%)."""
    assert DEV_QUERIES_PATH.is_file(), f"Missing DEV queries: {DEV_QUERIES_PATH}"
    assert HOLDOUT_QUERIES_PATH.is_file(), f"Missing HOLDOUT queries: {HOLDOUT_QUERIES_PATH}"

    dev_data = json.loads(DEV_QUERIES_PATH.read_text(encoding="utf-8"))
    holdout_data = json.loads(HOLDOUT_QUERIES_PATH.read_text(encoding="utf-8"))

    assert len(dev_data) >= 20, f"Expected at least 20 DEV queries, got {len(dev_data)}"
    assert len(holdout_data) >= 10, f"Expected at least 10 HOLDOUT queries, got {len(holdout_data)}"

    total = len(dev_data) + len(holdout_data)
    dev_ratio = len(dev_data) / total
    assert 0.65 <= dev_ratio <= 0.75, f"DEV ratio should be ~70%, got {dev_ratio:.2f}"

    dev_ids = {q["query_id"] for q in dev_data}
    holdout_ids = {q["query_id"] for q in holdout_data}
    overlap = dev_ids & holdout_ids
    assert not overlap, f"Query ID overlap between DEV and HOLDOUT: {overlap}"

    # Verify holdout directory is outside knowledge_base/
    assert "restricted" in str(HOLDOUT_QUERIES_PATH)
    assert "knowledge_base" not in str(HOLDOUT_QUERIES_PATH)

