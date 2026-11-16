"""Unit tests for material claim validation, provenance checks, and time bounds (C14).

Acceptance coverage:
- FR-AGT-006: Deterministic claim-to-evidence validation.
- NFR-004: Evidence provenance verification.
- RULE-007: Strict prohibition of 'VERIFIED' status.
- SC-14: Misleading correlation outside incident time window.
"""

from __future__ import annotations

import pytest

from orchestrator.claim_validator_contract import (
    ClaimValidator,
    HypothesisStatus,
    ValidatedClaim,
    ValidationReasonCode,
    ValidationReport,
)


@pytest.fixture
def validator():
    return ClaimValidator(value_tolerance_pct=0.15)


@pytest.fixture
def base_context():
    return {
        "incident_id": "inc-c14-test",
        "service_id": "auth-service",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "query_window": {
            "start": "2026-11-16T09:55:00Z",
            "end": "2026-11-16T10:05:00Z",
        },
        "evidence_items": [
            {
                "evidence_id": "ev-auth-metric-01",
                "tool_name": "get_service_metrics",
                "service_id": "auth-service",
                "source_ref": "prometheus",
                "observed_at": "2026-11-16T09:59:30Z",
                "data_quality": "complete",
                "error_code": None,
                "records": [
                    {
                        "metric_enum": "latency_p99",
                        "value": 120.0,
                        "unit": "ms",
                    }
                ],
            },
            {
                "evidence_id": "ev-auth-log-01",
                "tool_name": "search_error_logs",
                "service_id": "auth-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:15Z",
                "data_quality": "complete",
                "error_code": None,
                "records": [
                    {
                        "service_id": "auth-service",
                        "status_code": 401,
                        "message": "HTTP 401 Unauthorized: Invalid token signature",
                    }
                ],
            },
        ],
        "runbook_citations": [],
    }


def test_claim_corroborated_with_exact_metric_value(validator, base_context):
    """Klaim latensi/error cocok persis dengan rekaman metrik -> SUPPORTED."""
    claim = validator.validate_claim(
        claim_text="auth-service p99 latency increased to 120ms during peak auth validation",
        evidence_id="ev-auth-metric-01",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.SUPPORTED
    assert claim.reason_code == ValidationReasonCode.CLAIM_CORROBORATED.value
    assert claim.evidence_id == "ev-auth-metric-01"
    assert claim.value_delta is None


def test_claim_value_mismatch_downgrades_to_unsupported(validator, base_context):
    """Model mengklaim lonjakan 500ms padahal metrik hanya 120ms -> VALUE_MISMATCH & UNSUPPORTED."""
    claim = validator.validate_claim(
        claim_text="auth-service p99 latency spiked to 500ms causing timeouts",
        evidence_id="ev-auth-metric-01",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.UNSUPPORTED
    assert claim.reason_code == ValidationReasonCode.VALUE_MISMATCH.value
    assert claim.value_delta is not None
    assert claim.value_delta["claimed"] == 500.0
    assert claim.value_delta["observed"] == 120.0
    assert claim.value_delta["difference"] == 380.0


def test_claim_with_hallucinated_evidence_id_rejected(validator, base_context):
    """Model mencantumkan evidence_id fiktif -> MISSING_EVIDENCE_REF & UNSUPPORTED."""
    claim = validator.validate_claim(
        claim_text="Database pool exhausted on auth-service replica",
        evidence_id="ev-phantom-db-999",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.UNSUPPORTED
    assert claim.reason_code == ValidationReasonCode.MISSING_EVIDENCE_REF.value
    assert "not found" in claim.details.lower()


def test_claim_outside_incident_time_window_rejected_sc14(validator, base_context):
    """Bukti terjadi 30 menit sebelum insiden (SC-14 misleading correlation) -> OUT_OF_WINDOW & UNSUPPORTED."""
    # Add older evidence item (30 minutes prior to query window start)
    base_context["evidence_items"].append({
        "evidence_id": "ev-auth-stale-01",
        "tool_name": "get_service_metrics",
        "service_id": "auth-service",
        "source_ref": "prometheus",
        "observed_at": "2026-11-16T09:25:00Z",  # 30 mins before 09:55:00Z
        "data_quality": "complete",
        "records": [{"metric_enum": "latency_p99", "value": 120.0}],
    })

    claim = validator.validate_claim(
        claim_text="Stale metric correlation shows high latency earlier in the day",
        evidence_id="ev-auth-stale-01",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.UNSUPPORTED
    assert claim.reason_code == ValidationReasonCode.OUT_OF_WINDOW.value
    assert "outside query window" in claim.details.lower()


def test_verified_keyword_or_status_strictly_forbidden_rule007(validator, base_context):
    """Teks atau status bertanda 'VERIFIED' langsung ditolak dan diturunkan ke PARTIAL (RULE-007)."""
    # 1. Claim text with VERIFIED keyword
    claim = validator.validate_claim(
        claim_text="VERIFIED root cause is malformed auth token header",
        evidence_id="ev-auth-log-01",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.PARTIAL
    assert claim.reason_code == ValidationReasonCode.VERIFIED_STATUS_FORBIDDEN.value
    assert "RULE-007" in claim.details

    # 2. Hypothesis claiming confidence == 'VERIFIED'
    hypothesis_with_verified = {
        "hypothesis_id": "hyp-verified-test",
        "title": "Authentication token failure",
        "summary": "Token verification failure",
        "diagnosis": "VERIFIED: Token signature mismatch is the root cause",
        "confidence": "VERIFIED",
        "supporting_evidence_ids": ["ev-auth-log-01"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hypothesis_with_verified, base_context)
    assert report.status != "VERIFIED"
    assert report.status in (HypothesisStatus.PARTIAL, HypothesisStatus.INCONCLUSIVE)
    assert ValidationReasonCode.VERIFIED_STATUS_FORBIDDEN.value in report.reason_codes
    assert report.confidence_score <= 0.40

    # 3. Direct constructor protection: ValidationReport refuses status="VERIFIED"
    with pytest.raises(ValueError, match="RULE-007 Violation"):
        ValidationReport(
            hypothesis_id="hyp-illegal",
            status="VERIFIED",  # type: ignore[arg-type]
            confidence_score=0.99,
        )


def test_claim_within_tolerance_percentage_accepted(validator, base_context):
    """Perbedaan kecil dalam toleransi pembulatan (misal 120ms vs 125ms < 15%) diterima."""
    claim = validator.validate_claim(
        claim_text="auth-service latency reached 125ms",
        evidence_id="ev-auth-metric-01",
        context=base_context,
    )
    assert claim.status == HypothesisStatus.SUPPORTED
    assert claim.reason_code == ValidationReasonCode.CLAIM_CORROBORATED.value
