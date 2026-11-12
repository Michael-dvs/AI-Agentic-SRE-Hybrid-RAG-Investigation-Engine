"""C10 intake and dependency-correlation contract tests in the synthetic lab."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from starlette.testclient import TestClient
from observability.alerts import build_alert_webhook_headers
from observability.catalog import build_default_service_catalogs
from services.alert_intake import AlertIntakeService
import pytest

from services.alert_intake.correlation import DependencyCorrelator
from services.alert_intake.dedup import AlertDeduplicator


def alert(service: str, incident: str = "inc-test", time: str = "2026-11-12T00:00:00Z") -> dict:
    return {"schema_version": "1.0", "alert_id": "alt-test-01", "source_id": "src-prom-metrics",
            "service_id": service, "environment": "lab", "alert_type": "high_error_rate",
            "severity": "high", "event_time": time, "window_start": "2026-11-11T23:59:00Z",
            "window_end": "2026-11-12T00:00:00Z", "build_version": "0.1.0-sim",
            "error_code": "ERR_TEST", "trace_id": None, "summary": "Synthetic alert",
            "source_ref": "prometheus:lab", "incident_id": incident}


@pytest.fixture
def intake():
    service = AlertIntakeService(webhook_token="synthetic-test-key", catalog=build_default_service_catalogs(),
                                 deduplicator=AlertDeduplicator(), correlator=DependencyCorrelator())
    return service


def post_alert(intake, payload, valid=True):
    body = json.dumps(payload).encode()
    headers = build_alert_webhook_headers(body, webhook_token="synthetic-test-key")
    if not valid:
        headers["X-Alert-Signature"] = "invalid"
    return TestClient(intake.app).post("/alerts", content=body, headers=headers)


def canonical(service="api-gateway"):
    item = alert(service)
    del item["incident_id"]
    return item


def test_alert_intake_signature_valid(intake):
    body = json.dumps(canonical()).encode()
    assert intake.validate_signature(build_alert_webhook_headers(body, "synthetic-test-key"), body)


def test_alert_intake_signature_invalid_rejected(intake):
    response = post_alert(intake, canonical(), valid=False)
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHENTICATED"
    assert intake.deduplicator.dequeue() is None


def test_alert_intake_malformed_schema_rejected(intake):
    item = canonical()
    del item["alert_type"]
    response = post_alert(intake, item)
    assert response.status_code == 400
    assert response.json()["error_code"] == "SCHEMA_INVALID"
    assert intake.deduplicator.dequeue() is None


def test_alert_intake_unmapped_service_triage(intake):
    assert intake.normalize_context(canonical("unknown-service"))["status"] == "MANUAL_TRIAGE_REQUIRED"
    response = post_alert(intake, canonical("unknown-service"))
    assert response.json()["status"] == "MANUAL_TRIAGE_REQUIRED"
    assert intake.deduplicator.dequeue() is None


def test_alert_intake_utc_normalization(intake):
    item = canonical()
    item["event_time"] = "2026-11-12T07:00:00+07:00"
    response = post_alert(intake, item)
    assert response.json()["alert"]["event_time"] == "2026-11-12T00:00:00Z"


def test_end_to_end_intake_to_incident_context(intake):
    response = post_alert(intake, canonical())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["incident"]["incident_id"].startswith("inc-")
    assert data["allowed_services"] == ["api-gateway"]
    assert "transaction-service" in data["dependency_impact"]["downstream_dependencies"]
    assert intake.deduplicator.dequeue()["incident_id"] == data["incident"]["incident_id"]


def test_webhook_correlates_active_incident_lineage(intake):
    first, second = canonical("api-gateway"), canonical("transaction-service")
    first["trace_id"] = second["trace_id"] = "4bf92f3577b34da6a3ce929d0e0e4736"
    first_response = post_alert(intake, first).json()
    second_response = post_alert(intake, second).json()
    assert set(second_response["correlation"]["incident_ids"]) == {
        first_response["incident"]["incident_id"], second_response["incident"]["incident_id"]
    }
    assert second_response["correlation"]["suspected_origins"] == ["transaction-service"]


@pytest.mark.parametrize("failure", ["exception", "missing"])
def test_failure_atomicity_correlation_exception_rolls_back_queue(intake, monkeypatch, failure):
    events = []
    intake.deduplicator._audit_sink = events.append
    def fail(_):
        if failure == "exception":
            raise RuntimeError("correlation unavailable")
        return []
    monkeypatch.setattr(intake.correlator, "correlate_incidents", fail)
    response = post_alert(intake, canonical())
    assert response.status_code == 503
    assert intake.deduplicator.active_alerts() == []
    assert intake.deduplicator.dequeue() is None
    assert events == []


@pytest.mark.parametrize("mode", ["merge", "split"])
def test_failed_correlation_preserves_existing_incident_and_queue(intake, monkeypatch, mode):
    events = []
    d = intake.deduplicator
    d._audit_sink = events.append
    first = post_alert(intake, canonical()).json()["incident"]
    fingerprint = first["fingerprint"]
    if mode == "split":
        incident, seen = d._registry[fingerprint]
        d._registry[fingerprint] = (incident, seen - d.ttl_seconds - 1)
    before = (d._registry[fingerprint][0].copy(), d._registry[fingerprint][1])
    monkeypatch.setattr(intake.correlator, "correlate_incidents",
                        lambda _: (_ for _ in ()).throw(RuntimeError("unavailable")))
    assert post_alert(intake, canonical()).status_code == 503
    assert d._registry[fingerprint] == before
    assert d.dequeue() == first
    assert d.dequeue() is None
    assert [event["action"] for event in events] == ["create"]


def test_failed_admission_is_invisible_to_concurrent_dequeue_and_admission(intake, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    dequeued = threading.Event()
    original = intake.correlator.correlate_incidents
    def correlate(active):
        if any(item["service_id"] == "api-gateway" for item in active):
            entered.set()
            assert release.wait(5)
            raise RuntimeError("unavailable")
        return original(active)
    monkeypatch.setattr(intake.correlator, "correlate_incidents", correlate)
    def dequeue():
        result = intake.deduplicator.dequeue()
        dequeued.set()
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        failed = pool.submit(post_alert, intake, canonical())
        assert entered.wait(5)
        consumer = pool.submit(dequeue)
        successful = pool.submit(post_alert, intake, canonical("transaction-service"))
        try:
            assert not dequeued.wait(0.1)
        finally:
            release.set()
        assert failed.result(timeout=5).status_code == 503
        accepted = successful.result(timeout=5)
        assert accepted.status_code == 200
        removed = consumer.result(timeout=5)
    # The consumer may run before or after the successful admission.
    remaining = intake.deduplicator.dequeue()
    queued = [item for item in (removed, remaining) if item is not None]
    assert [item["incident_id"] for item in queued] == [accepted.json()["incident"]["incident_id"]]
    assert [item["incident_id"] for item in intake.deduplicator.active_alerts()] == [
        accepted.json()["incident"]["incident_id"]
    ]


def test_audit_failure_does_not_commit_admission(intake):
    intake.deduplicator._audit_sink = lambda _: (_ for _ in ()).throw(RuntimeError("audit unavailable"))
    assert post_alert(intake, canonical()).status_code == 503
    assert intake.deduplicator.active_alerts() == []
    assert intake.deduplicator.dequeue() is None


@pytest.mark.parametrize("mode", ["merge", "split"])
def test_audit_failure_preserves_existing_incident(intake, mode):
    d = intake.deduplicator
    first = post_alert(intake, canonical()).json()["incident"]
    fingerprint = first["fingerprint"]
    incident, seen = d._registry[fingerprint]
    if mode == "split":
        d._registry[fingerprint] = (incident, seen - d.ttl_seconds - 1)
    before = (incident.copy(), d._registry[fingerprint][1])
    d._audit_sink = lambda _: (_ for _ in ()).throw(RuntimeError("audit unavailable"))
    assert post_alert(intake, canonical()).status_code == 503
    assert d._registry[fingerprint] == before
    assert d.dequeue() == first
    assert d.dequeue() is None


def test_reject_ground_truth_fields_without_incident(intake):
    item = canonical()
    item["scenario_id"] = "SC-TEST"
    response = post_alert(intake, item)
    assert response.status_code == 400
    assert intake.deduplicator.dequeue() is None


def test_alert_scope_mismatch_requires_manual_triage(intake):
    item = canonical()
    item["environment"] = "staging-sim"
    assert post_alert(intake, item).json()["status"] == "MANUAL_TRIAGE_REQUIRED"
    assert intake.deduplicator.dequeue() is None


def test_zero_ground_truth_leak(intake, monkeypatch):
    import builtins
    from pathlib import Path
    original_open = builtins.open
    original_path_open = Path.open
    attempts = []
    def checked_open(file, *args, **kwargs):
        if "restricted" in str(file):
            attempts.append(str(file))
            raise AssertionError("restricted access")
        return original_open(file, *args, **kwargs)
    def checked_path_open(path, *args, **kwargs):
        if "restricted" in str(path):
            attempts.append(str(path))
            raise AssertionError("restricted access")
        return original_path_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", checked_open)
    monkeypatch.setattr(Path, "open", checked_path_open)
    assert post_alert(intake, canonical()).json()["status"] == "accepted"
    assert attempts == []


def test_zero_mutation_invariance(intake, monkeypatch):
    import socket
    attempts = []
    def deny_connection(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("unexpected network call")
    monkeypatch.setattr(socket.socket, "connect", deny_connection)
    assert post_alert(intake, canonical()).json()["status"] == "accepted"
    assert attempts == []


def test_deduplication_single_alert():
    result = AlertDeduplicator().process(alert("api-gateway"))
    assert result["action"] == "create"
    assert result["incident"]["incident_id"].startswith("inc-")
    assert result["incident"]["hit_count"] == 1
    assert result["incident"]["status"] == "ACTIVE"


def test_deduplication_100_burst_duplicate_alerts():
    d = AlertDeduplicator()
    results = [d.process(alert("api-gateway")) for _ in range(100)]
    assert len({r["incident"]["incident_id"] for r in results}) == 1
    assert results[-1]["incident"]["hit_count"] == 100
    assert d.dequeue()["hit_count"] == 100
    assert d.dequeue() is None


def test_deduplication_ttl_expiration(monkeypatch):
    import services.alert_intake.dedup as dedup
    now = [100.0]
    monkeypatch.setattr(dedup.time, "monotonic", lambda: now[0])
    d = AlertDeduplicator()
    first = d.process(alert("api-gateway"))
    now[0] += 61
    second = d.process(alert("api-gateway"))
    assert second["action"] == "split"
    assert second["incident"]["incident_id"] != first["incident"]["incident_id"]


def test_bounded_queue_backpressure():
    events = []
    d = AlertDeduplicator(max_queue_size=1, audit_sink=events.append)
    first = d.process(alert("api-gateway"))
    rejected = d.process(alert("transaction-service"))
    assert rejected["action"] == "backpressure"
    assert rejected["incident"] is None
    assert d.process(alert("api-gateway"))["incident"]["hit_count"] == 2
    assert d.dequeue()["incident_id"] == first["incident"]["incident_id"]
    assert d.dequeue() is None
    assert any(e["action"] == "backpressure" for e in events)


def test_deduplication_audits_create_merge_and_ttl_split(monkeypatch):
    import services.alert_intake.dedup as dedup
    now = [10.0]
    monkeypatch.setattr(dedup.time, "monotonic", lambda: now[0])
    events = []
    d = AlertDeduplicator(audit_sink=events.append)
    d.process(alert("api-gateway"))
    d.process(alert("api-gateway"))
    now[0] += 61
    d.process(alert("api-gateway"))
    assert [e["action"] for e in events] == ["create", "merge", "split"]
    assert all(e["incident_id"] and e["at"].endswith("Z") for e in events)


def test_cascade_correlation_origin_vs_downstream():
    correlator = DependencyCorrelator()
    gateway, transaction = alert("api-gateway", "inc-1"), alert("transaction-service", "inc-2")
    gateway["trace_id"] = transaction["trace_id"] = "4bf92f3577b34da6a3ce929d0e0e4736"
    groups = correlator.correlate_incidents([gateway, transaction])
    assert len(groups) == 1
    assert groups[0]["suspected_origins"] == ["transaction-service"]
    assert groups[0]["downstream_symptoms"] == ["api-gateway"]
    assert "db-dummy" in groups[0]["impact_graph"]["downstream_dependencies"]
    assert groups[0]["status"] == "INCONCLUSIVE"


def test_unobserved_topology_alone_does_not_merge():
    groups = DependencyCorrelator().correlate_incidents(
        [alert("api-gateway", "inc-1"), alert("transaction-service", "inc-2")]
    )
    assert len(groups) == 2


def test_concurrent_independent_faults_split():
    groups = DependencyCorrelator().correlate_incidents([alert("auth-service", "inc-1"), alert("notification-service", "inc-2")])
    assert len(groups) == 2
    assert {tuple(g["incident_ids"]) for g in groups} == {("inc-1",), ("inc-2",)}


def test_correlation_time_and_environment_boundaries():
    correlator = DependencyCorrelator(correlation_window_seconds=60)
    first = alert("api-gateway", "inc-1")
    second = alert("transaction-service", "inc-2", "2026-11-12T00:01:01Z")
    assert len(correlator.correlate_incidents([first, second])) == 2
    second["event_time"] = first["event_time"]
    second["environment"] = "staging-sim"
    assert len(correlator.correlate_incidents([first, second])) == 2


def test_dependency_freshness_is_not_fabricated():
    c = DependencyCorrelator()
    graph = c.build_impact_graph("transaction-service", "2026-11-12T00:00:00Z")
    assert "api-gateway" in graph["upstream_callers"]
    assert "ledger-service" in graph["downstream_dependencies"]
    assert all(edge["edge_freshness"] == "stale" for edge in graph["edges"])
    with pytest.raises(ValueError):
        c.build_impact_graph("transaction-service", "2026-11-12T00:00:00Z", 4)


def test_merge_split_audit_logging():
    events = []
    c = DependencyCorrelator(audit=events.append)
    c.correlate_incidents([alert("auth-service", "inc-1"), alert("notification-service", "inc-2")])
    assert events[0]["event"] == "correlation_split"
    assert events[0]["incident_id"] == "inc-2"
    assert events[0]["timestamp"].endswith("Z")
