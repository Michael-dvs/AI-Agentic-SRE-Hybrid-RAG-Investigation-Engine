"""Tests for runbook/SOP citation applicability, lifecycle dates, and scope isolation (C14).

Acceptance coverage:
- RAG-01 & SC-10: Obsolete SOP versions (effective_to <= event_time) are strictly rejected (KPI-11 = 0).
- RAG-02: Cross-service and cross-environment SOP citations are dropped (SCOPE_MISMATCH).
- AT-007: SOP applicability verification against incident event time.
- FR-RAG-009: Graceful handling of empty applicable runbooks without fictitious citations.
- RULE-005: Defense-in-depth post-retrieval SOP validation.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from orchestrator.claim_validator_contract import (
    ClaimValidator,
    HypothesisStatus,
    ValidationReasonCode,
)


@pytest.fixture
def validator():
    return ClaimValidator()


def test_rag01_sc10_obsolete_runbook_citation_rejected(validator):
    """Rekomendasi mengutip SOP versi kedaluwarsa (effective_to <= event_time) -> digugurkan dengan OBSOLETE_SOP."""
    excerpt = "Compare the latency signal in the ledger test fixture."
    citations = [
        {
            "chunk_id": "chk-ledger-v1-obsolete",
            "document_id": "SOP-LEDGER-001",
            "document_version": "1.0.0",
            "source_uri": "synthetic://runbooks/ledger-service/v1.md",
            "service_id": "ledger-service",
            "environment": "lab",
            "status": "obsolete",
            "effective_from": "2025-01-01T00:00:00Z",
            "effective_to": "2026-06-01T00:00:00Z",  # Expired before event_time
        },
        {
            "chunk_id": "chk-ledger-v2-active",
            "document_id": "SOP-LEDGER-001",
            "document_version": "2.0.0",
            "source_uri": "kb://unit/runbooks/ledger-service/v2.md",
            "title": "Synthetic ledger runbook",
            "section_path": "Latency checks",
            "content_hash": sha256(excerpt.encode()).hexdigest(),
            "sanitized_excerpt": excerpt,
            "applicability_verified": True,
            "score": 1.0,
            "score_type": "bm25_sparse",
            "source_branch": "sparse",
            "service_id": "ledger-service",
            "environment": "lab",
            "status": "approved",
            "effective_from": "2026-06-01T00:00:00Z",
            "effective_to": "2027-01-01T00:00:00Z",  # Active during event_time
        },
    ]

    event_time = "2026-11-16T10:00:00Z"
    valid_citations, rejected_citations, reason_codes = validator.validate_sop_citations(
        citations=citations,
        incident_service="ledger-service",
        incident_environment="lab",
        event_time_iso=event_time,
    )

    # Obsolete v1 must be rejected
    assert len(rejected_citations) == 1
    assert "chunk_id" not in rejected_citations[0]
    assert rejected_citations[0]["rejection_reason"] == ValidationReasonCode.OBSOLETE_SOP.value
    assert ValidationReasonCode.OBSOLETE_SOP.value in reason_codes

    # Active v2 must be preserved
    assert len(valid_citations) == 1
    assert valid_citations[0]["chunk_id"] == "chk-ledger-v2-active"


def test_rag02_cross_service_or_environment_citation_rejected(validator):
    """Rekomendasi mengutip SOP milik layanan atau environment berbeda -> ditolak dengan SCOPE_MISMATCH."""
    citations = [
        {
            "chunk_id": "chk-notif-sop",
            "document_id": "SOP-NOTIF-001",
            "document_version": "1.0.0",
            "source_uri": "synthetic://runbooks/notification-service/v1.md",
            "service_id": "notification-service",  # Different service
            "environment": "lab",
            "status": "approved",
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_to": None,
        },
        {
            "chunk_id": "chk-auth-prod-sop",
            "document_id": "SOP-AUTH-002",
            "document_version": "1.0.0",
            "source_uri": "synthetic://runbooks/auth-service/prod.md",
            "service_id": "auth-service",
            "environment": "sim-prod-like",  # Different environment
            "status": "approved",
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_to": None,
        },
    ]

    event_time = "2026-11-16T10:00:00Z"
    valid_citations, rejected_citations, reason_codes = validator.validate_sop_citations(
        citations=citations,
        incident_service="auth-service",
        incident_environment="lab",
        event_time_iso=event_time,
    )

    assert len(valid_citations) == 0
    assert len(rejected_citations) == 2
    assert all(c["rejection_reason"] == ValidationReasonCode.SCOPE_MISMATCH.value for c in rejected_citations)
    assert ValidationReasonCode.SCOPE_MISMATCH.value in reason_codes


def test_empty_applicable_runbooks_handled_gracefully(validator):
    """Hasil retrieval menyatakan no_applicable_runbook -> validator tidak membuat rekomendasi fiktif."""
    context = {
        "incident_id": "inc-no-runbook",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "no_applicable_runbook": True,
        "runbook_citations": [],
        "evidence_items": [
            {
                "evidence_id": "ev-gw-trace-ok",
                "tool_name": "get_trace_summary",
                "service_id": "api-gateway",
                "source_ref": "tempo",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"span_id": "span-01", "duration_ms": 10.0, "status_code": "OK"}],
            }
        ],
    }

    hypothesis = {
        "hypothesis_id": "hyp-no-sop",
        "title": "Nominal gateway state",
        "summary": "Gateway operating normally",
        "diagnosis": "No degradation observed",
        "confidence": "LOW",
        "supporting_evidence_ids": ["ev-gw-trace-ok"],
        "contradicting_evidence_ids": [],
    }

    report = validator.validate_hypothesis(hypothesis, context)
    assert report.valid_sop_citations == []
    assert report.rejected_sop_citations == []
    assert ValidationReasonCode.NO_APPLICABLE_RUNBOOK.value in report.reason_codes
