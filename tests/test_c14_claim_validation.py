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


@pytest.fixture
def gateway_dependency_context():
    return {
        "incident_id": "inc-p0-01-gateway",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-23T03:44:14Z",
        "query_window": {
            "start": "2026-11-23T03:39:14Z",
            "end": "2026-11-23T03:45:14Z",
        },
        "evidence_items": [
            {
                "evidence_id": "ev-gw-rate-01",
                "tool_name": "get_service_metrics",
                "service_id": "api-gateway",
                "source_ref": "prometheus",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "records": [
                    {"service_id": "api-gateway", "metric_enum": "request_rate", "value": 0.4833},
                    {"service_id": "api-gateway", "metric_enum": "request_rate", "value": 0.4833},
                ],
            },
            {
                "evidence_id": "ev-gw-log-503",
                "tool_name": "search_error_logs",
                "service_id": "api-gateway",
                "source_ref": "loki",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "records": [
                    {
                        "service_id": "api-gateway",
                        "status_code": 503,
                        "error_code": "ERR_DEPENDENCY_UNAVAILABLE",
                        "message": "ERR_DEPENDENCY_UNAVAILABLE: Downstream dependency on transaction-service refused connection",
                    }
                ],
            },
            {
                "evidence_id": "ev-gw-trace-ok",
                "tool_name": "get_trace_summary",
                "service_id": "api-gateway",
                "source_ref": "tempo",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "records": [
                    {"service_id": "api-gateway", "span_id": "4d6de2bc32063db7", "duration_ms": 17.281, "status_code": "OK"}
                ],
            },
            {
                "evidence_id": "ev-notif-empty",
                "tool_name": "search_error_logs",
                "service_id": "notification-service",
                "source_ref": "loki",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "records": [],
            },
            {
                "evidence_id": "ev-notif-err",
                "tool_name": "search_error_logs",
                "service_id": "notification-service",
                "source_ref": "loki",
                "observed_at": "2026-11-23T03:44:28Z",
                "data_quality": "complete",
                "records": [
                    {"service_id": "notification-service", "status_code": 500, "message": "SMTP relay timeout"}
                ],
            },
        ],
        "runbook_citations": [],
    }


def test_irrelevant_downstream_503_rejected_for_rate_limit_hypothesis(validator, gateway_dependency_context):
    """Rate-limiting hypothesis citing 503 ERR_DEPENDENCY_UNAVAILABLE must be UNSUPPORTED, not PARTIAL/SUPPORTED."""
    hyp = {
        "hypothesis_id": "hyp-rate-limit",
        "title": "api-gateway rate limiting or configuration change causing reduced request acceptance.",
        "summary": "api-gateway rate limiting or configuration change",
        "diagnosis": "Alternative degradation pathway in observation window.",
        "estimated_root_cause": "api-gateway internal rate limiting or misconfigured thresholds blocking traffic.",
        "supporting_evidence_ids": ["ev-gw-log-503"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.UNSUPPORTED
    assert ValidationReasonCode.IRRELEVANT_EVIDENCE.value in report.reason_codes
    assert report.supporting_evidence_ids == []
    assert any("ev-gw-log-503" in u for u in report.unknowns)


def test_irrelevant_downstream_503_rejected_for_traffic_surge_hypothesis(validator, gateway_dependency_context):
    """Traffic-surge hypothesis citing downstream 503 connection refusal must be UNSUPPORTED."""
    hyp = {
        "hypothesis_id": "hyp-traffic-surge",
        "title": "upstream client traffic surge overwhelming api-gateway capacity.",
        "summary": "upstream client traffic surge",
        "diagnosis": "Sudden increase in client request rate exceeding api-gateway capacity.",
        "supporting_evidence_ids": ["ev-gw-log-503"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.UNSUPPORTED
    assert ValidationReasonCode.IRRELEVANT_EVIDENCE.value in report.reason_codes
    assert report.supporting_evidence_ids == []


def test_flat_low_request_rate_contradicts_traffic_surge(validator, gateway_dependency_context):
    """Flat low request_rate (0.4833 req/s) directly contradicts a traffic-surge claim -> CONTRADICTED."""
    hyp = {
        "hypothesis_id": "hyp-surge-contradicted",
        "title": "upstream client traffic surge",
        "diagnosis": "Sudden increase in client request rate overwhelming api-gateway.",
        "supporting_evidence_ids": ["ev-gw-rate-01"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.CONTRADICTED
    assert ValidationReasonCode.CLAIM_CONTRADICTED.value in report.reason_codes
    assert report.supporting_evidence_ids == []
    assert "ev-gw-rate-01" in report.contradicting_evidence_ids


def test_empty_records_and_service_mismatch_rejected(validator, gateway_dependency_context):
    """Zero-record evidence and unrelated-service evidence cannot substantiate a failure claim."""
    empty_claim = validator.validate_claim(
        claim_text="transaction-service error spike",
        evidence_id="ev-notif-empty",
        context=gateway_dependency_context,
    )
    assert empty_claim.status == HypothesisStatus.UNSUPPORTED
    assert empty_claim.reason_code == ValidationReasonCode.IRRELEVANT_EVIDENCE.value

    wrong_svc = validator.validate_claim(
        claim_text="transaction-service database connection failed",
        evidence_id="ev-notif-err",
        context=gateway_dependency_context,
    )
    assert wrong_svc.status == HypothesisStatus.UNSUPPORTED
    assert wrong_svc.reason_code == ValidationReasonCode.IRRELEVANT_EVIDENCE.value


def test_missing_supporting_evidence_preserves_uncertainty(validator, gateway_dependency_context):
    """Hypothesis without supporting_evidence_ids stays UNSUPPORTED/INCONCLUSIVE with explicit unknowns."""
    hyp = {
        "hypothesis_id": "hyp-missing-ev",
        "title": "api-gateway rate limiting configuration change",
        "diagnosis": "Rate limit thresholds may have changed without configuration telemetry.",
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.UNSUPPORTED
    assert ValidationReasonCode.MISSING_SUPPORTING_EVIDENCE.value in report.reason_codes
    assert report.supporting_evidence_ids == []
    assert any("no supporting evidence" in u.lower() for u in report.unknowns)


def test_valid_downstream_dependency_evidence_corroborated_without_verified(validator, gateway_dependency_context):
    """Valid downstream 503 ERR_DEPENDENCY_UNAVAILABLE evidence supports downstream dependency hypothesis, never VERIFIED."""
    hyp = {
        "hypothesis_id": "hyp-valid-dep",
        "title": "api-gateway degraded due to downstream transaction-service connection refusal",
        "diagnosis": "Downstream dependency on transaction-service refused connection causing 503 ERR_DEPENDENCY_UNAVAILABLE.",
        "supporting_evidence_ids": ["ev-gw-log-503"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.SUPPORTED
    assert report.status != "VERIFIED"
    assert report.supporting_evidence_ids == ["ev-gw-log-503"]
    assert ValidationReasonCode.CLAIM_CORROBORATED.value in report.reason_codes


def test_mixed_valid_and_irrelevant_evidence_yields_partial_pruned(validator, gateway_dependency_context):
    """When valid and irrelevant evidence are both cited, irrelevant ID is pruned and status is PARTIAL."""
    hyp = {
        "hypothesis_id": "hyp-mixed",
        "title": "api-gateway downstream transaction-service failure",
        "diagnosis": "Downstream transaction-service refused connection causing 503 ERR_DEPENDENCY_UNAVAILABLE.",
        "supporting_evidence_ids": ["ev-gw-log-503", "ev-notif-empty"],
        "contradicting_evidence_ids": [],
    }
    report = validator.validate_hypothesis(hyp, gateway_dependency_context)
    assert report.status == HypothesisStatus.PARTIAL
    assert report.supporting_evidence_ids == ["ev-gw-log-503"]
    assert ValidationReasonCode.IRRELEVANT_EVIDENCE.value in report.reason_codes
