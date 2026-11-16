"""Unit & Integration tests for Cryptographic Hash-Chained Audit Ledger (C15, audit-event.v1, BRD §12.2, ADR-S06)."""

import json
import pathlib
import pytest
from unittest.mock import patch, mock_open

from observability.audit_chain import (
    AuditWriteError,
    HashChainedAuditStore,
    compute_chain_hash,
    compute_request_fingerprint,
    verify_chain_integrity,
)


def test_audit_event_generation_and_schema_conformance(tmp_path):
    log_file = tmp_path / "security_audit.jsonl"
    store = HashChainedAuditStore(log_path=log_file)

    event = store.record_event(
        actor_ref="principal_investigator",
        action="ALERT_ADMISSION",
        target_ref="api-gateway",
        result_code="ALLOW",
        reason_code="OK",
        request_payload={"alert_id": "alt-001"},
        incident_id="inc-test-001",
    )

    assert event["schema_version"] == "1.0"
    assert event["actor_ref"] == "principal_investigator"
    assert event["action"] == "ALERT_ADMISSION"
    assert event["result_code"] == "ALLOW"
    assert event["reason_code"] == "OK"
    assert event["sanitized"] is True
    assert event["prev_event_hash"] is None  # Genesis event
    assert len(event["event_hash"]) == 64
    assert store.last_event_hash == event["event_hash"]

    # Verify written to disk
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    disk_event = json.loads(lines[0])
    assert disk_event["audit_event_id"] == event["audit_event_id"]


def test_audit_chain_sequential_linking_and_integrity_verification(tmp_path):
    log_file = tmp_path / "chain.jsonl"
    store = HashChainedAuditStore(log_path=log_file)

    ev1 = store.record_event(
        actor_ref="principal_intake",
        action="ALERT_ADMISSION",
        target_ref="api-gateway",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )

    ev2 = store.record_event(
        actor_ref="principal_tool_gateway",
        action="TOOL_INVOCATION",
        target_ref="search_error_logs",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )

    ev3 = store.record_event(
        actor_ref="principal_reviewer",
        action="HUMAN_REVIEW_DECISION",
        target_ref="dossier-001",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )

    assert ev1["prev_event_hash"] is None
    assert ev2["prev_event_hash"] == ev1["event_hash"]
    assert ev3["prev_event_hash"] == ev2["event_hash"]

    # Verify integrity of untampered chain
    is_valid, violations = verify_chain_integrity(store.events)
    assert is_valid is True
    assert len(violations) == 0


def test_audit_chain_tamper_detection(tmp_path):
    store = HashChainedAuditStore()

    store.record_event(
        actor_ref="principal_intake",
        action="ALERT_ADMISSION",
        target_ref="api-gateway",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )
    store.record_event(
        actor_ref="principal_tool_gateway",
        action="TOOL_INVOCATION",
        target_ref="search_error_logs",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )
    store.record_event(
        actor_ref="principal_reviewer",
        action="HUMAN_REVIEW_DECISION",
        target_ref="dossier-001",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )

    # Tamper 1: modify a field in event 1
    tampered_events = [dict(ev) for ev in store.events]
    tampered_events[1]["result_code"] = "DENY"

    is_valid, violations = verify_chain_integrity(tampered_events)
    assert is_valid is False
    assert any("Hash mismatch" in v for v in violations)

    # Tamper 2: break prev_event_hash linkage
    tampered_linkage = [dict(ev) for ev in store.events]
    tampered_linkage[2]["prev_event_hash"] = "0" * 64
    is_valid_link, link_violations = verify_chain_integrity(tampered_linkage)
    assert is_valid_link is False
    assert any("Chain break" in v for v in link_violations)


def test_audit_store_fail_closed_on_io_failure(tmp_path):
    log_file = tmp_path / "fail_closed_audit.jsonl"
    store = HashChainedAuditStore(log_path=log_file)

    # Record first event successfully
    store.record_event(
        actor_ref="principal_intake",
        action="ALERT_ADMISSION",
        target_ref="api-gateway",
        result_code="ALLOW",
        reason_code="OK",
        incident_id="inc-001",
    )
    last_valid_hash = store.last_event_hash
    initial_event_count = len(store.events)

    # Simulate disk failure on subsequent write
    with patch("builtins.open", side_effect=IOError("Simulated disk full or permission denied")):
        with pytest.raises(AuditWriteError) as exc_info:
            store.record_event(
                actor_ref="principal_tool_gateway",
                action="TOOL_INVOCATION",
                target_ref="search_error_logs",
                result_code="ALLOW",
                reason_code="OK",
                incident_id="inc-001",
            )
        assert "FAIL_CLOSED" in str(exc_info.value)

    # Enforce that memory state did not advance when write failed
    assert store.last_event_hash == last_valid_hash
    assert len(store.events) == initial_event_count
