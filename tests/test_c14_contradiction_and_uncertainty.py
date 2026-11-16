"""Integration tests for cross-signal contradictions, trace uncertainty, cascade attribution, and multi-fault separation (C14).

Acceptance coverage:
- EV-01: Conflicting signals (metrics normal vs error logs) triggers PARTIAL/INCONCLUSIVE.
- EV-02 & SC-09: Missing trace source results in honest abstention (INCONCLUSIVE, zero phantom spans).
- AT-016 & SC-04: Cascading failures distinguish upstream origin vs downstream symptoms.
- SC-08: Concurrent independent faults are preserved as separate explanations, not collapsed.
- RULE-006: Honest uncertainty disclosure.
"""

from __future__ import annotations

import pytest

from orchestrator.claim_validator_contract import (
    ClaimValidator,
    HypothesisStatus,
    ValidationReasonCode,
)


@pytest.fixture
def validator():
    return ClaimValidator()


def test_ev01_metrics_normal_vs_logs_error_conflict(validator):
    """Log menunjukkan error 500 masif, tetapi metrik menunjukkan error rate 0.00 -> PARTIAL dan kontradiksi tercatat."""
    context = {
        "incident_id": "inc-ev01-conflict",
        "service_id": "transaction-service",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "query_window": {
            "start": "2026-11-16T09:55:00Z",
            "end": "2026-11-16T10:05:00Z",
        },
        "evidence_items": [
            {
                "evidence_id": "ev-tx-log-500",
                "tool_name": "search_error_logs",
                "service_id": "transaction-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [
                    {"status_code": 500, "message": "Internal Server Error: DB connection failed"},
                    {"status_code": 500, "message": "Internal Server Error: Connection reset by peer"},
                ],
            },
            {
                "evidence_id": "ev-tx-metric-zero",
                "tool_name": "get_service_metrics",
                "service_id": "transaction-service",
                "source_ref": "prometheus",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [
                    {"metric_enum": "error_rate", "value": 0.0, "unit": "percent"}
                ],
            },
            {
                "evidence_id": "ev-tx-trace-ok",
                "tool_name": "get_trace_summary",
                "service_id": "transaction-service",
                "source_ref": "tempo",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"span_id": "span-tx-001", "duration_ms": 15.0, "status_code": "OK"}],
            },
        ],
        "runbook_citations": [],
    }

    hypothesis = {
        "hypothesis_id": "hyp-tx-01",
        "title": "Transaction service database connection exhaustion",
        "summary": "Database connectivity loss",
        "diagnosis": "Logs report 500 internal server error due to DB connection failure",
        "confidence": "HIGH",
        "supporting_evidence_ids": ["ev-tx-log-500"],
        "contradicting_evidence_ids": ["ev-tx-metric-zero"],
    }

    report = validator.validate_hypothesis(hypothesis, context)

    # Status must NOT be SUPPORTED; it must be downgraded to PARTIAL due to conflicting signals
    assert report.status == HypothesisStatus.PARTIAL
    assert report.confidence_score <= 0.50
    assert len(report.contradictions) >= 1
    assert "EV-01" in report.contradictions[0]
    assert ValidationReasonCode.CONTRADICTING_SIGNALS.value in report.reason_codes


def test_ev02_sc09_trace_source_unavailable_honest_abstention(validator):
    """Sinyal trace berstatus SOURCE_UNAVAILABLE -> INCONCLUSIVE, confidence <= 0.40, dicatat di unknowns."""
    context = {
        "incident_id": "inc-ev02-trace-outage",
        "service_id": "ledger-service",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "query_window": {
            "start": "2026-11-16T09:55:00Z",
            "end": "2026-11-16T10:05:00Z",
        },
        "evidence_items": [
            {
                "evidence_id": "ev-ledger-logs",
                "tool_name": "search_error_logs",
                "service_id": "ledger-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"status_code": 503, "message": "Database lock timeout"}],
            },
            {
                "evidence_id": "ev-ledger-trace-outage",
                "tool_name": "get_trace_summary",
                "service_id": "ledger-service",
                "source_ref": "tempo",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "unavailable",
                "error_code": "SOURCE_UNAVAILABLE",
                "records": [],
            },
        ],
        "runbook_citations": [],
    }

    hypothesis = {
        "hypothesis_id": "hyp-ledger-01",
        "title": "Ledger database contention",
        "summary": "Database lock timeout observed",
        "diagnosis": "Ledger service experiencing 503 lock timeout",
        "confidence": "HIGH",
        "supporting_evidence_ids": ["ev-ledger-logs"],
        "contradicting_evidence_ids": [],
    }

    report = validator.validate_hypothesis(hypothesis, context)

    # Must abstain honestly: status INCONCLUSIVE, confidence <= 0.40, zero imaginary spans
    assert report.status == HypothesisStatus.INCONCLUSIVE
    assert report.confidence_score <= 0.40
    assert len(report.unknowns) >= 1
    assert "EV-02" in report.unknowns[0]
    assert ValidationReasonCode.SOURCE_UNAVAILABLE.value in report.reason_codes


def test_at016_sc04_cascading_failure_distinguishes_origin_vs_downstream(validator):
    """Layanan hulu (ledger-service) mati memicu cascade ke api-gateway. Validator memastikan origin diidentifikasi."""
    context = {
        "incident_id": "inc-cascade-sc04",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "evidence_items": [
            {
                "evidence_id": "ev-gw-logs",
                "tool_name": "search_error_logs",
                "service_id": "api-gateway",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"service_id": "api-gateway", "status_code": 502, "message": "Bad Gateway: upstream failed"}],
            },
            {
                "evidence_id": "ev-ledger-logs",
                "tool_name": "search_error_logs",
                "service_id": "ledger-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"service_id": "ledger-service", "status_code": 500, "message": "PostgreSQL connection refused"}],
            },
            {
                "evidence_id": "ev-gw-trace",
                "tool_name": "get_trace_summary",
                "service_id": "api-gateway",
                "source_ref": "tempo",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"span_id": "span-gw-01", "duration_ms": 250.0, "status_code": "ERROR"}],
            },
        ],
    }

    hypothesis = {
        "hypothesis_id": "hyp-cascade-01",
        "title": "Cascading failure propagating to api-gateway",
        "summary": "Gateway 502 caused by upstream failure",
        "diagnosis": "Upstream ledger-service is unreachable causing downstream 502 on api-gateway",
        "confidence": "HIGH",
        "supporting_evidence_ids": ["ev-gw-logs", "ev-ledger-logs"],
        "contradicting_evidence_ids": [],
    }

    report = validator.validate_hypothesis(hypothesis, context)

    assert report.is_cascade is True
    assert report.origin_service == "ledger-service"
    assert ValidationReasonCode.DOWNSTREAM_SYMPTOM_CASCADE.value in report.reason_codes


def test_sc08_concurrent_independent_faults_not_collapsed(validator):
    """Dua error independen (Auth token error + Ledger DB lock) terjadi bersamaan. Validator mencegah penggabungan palsu."""
    context = {
        "incident_id": "inc-sc08-multifault",
        "service_id": "api-gateway",
        "environment": "lab",
        "event_time": "2026-11-16T10:00:00Z",
        "evidence_items": [
            {
                "evidence_id": "ev-auth-401",
                "tool_name": "search_error_logs",
                "service_id": "auth-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"service_id": "auth-service", "status_code": 401, "message": "Invalid Bearer Token"}],
            },
            {
                "evidence_id": "ev-ledger-500",
                "tool_name": "search_error_logs",
                "service_id": "ledger-service",
                "source_ref": "loki",
                "observed_at": "2026-11-16T10:00:00Z",
                "data_quality": "complete",
                "records": [{"service_id": "ledger-service", "status_code": 500, "message": "Database deadlock detected"}],
            },
        ],
    }

    cascade_info = validator.evaluate_cascade_and_multifault([], context)
    assert cascade_info["is_multi_fault"] is True
    assert "401" in cascade_info["error_types"]
    assert "500" in cascade_info["error_types"]
    assert len(cascade_info["error_services"]) >= 2
