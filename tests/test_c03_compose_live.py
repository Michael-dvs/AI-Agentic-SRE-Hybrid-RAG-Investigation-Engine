"""Live Docker Compose end-to-end tests against http://127.0.0.1:18080."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import time
import uuid

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from traffic.generator import run_traffic_profile

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:18080")
CONTRACTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)


def _gateway_reachable() -> bool:
    try:
        r = httpx.get(f"{GATEWAY_URL}/health/live", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _gateway_reachable(),
    reason=f"Live Docker Compose stack is not running at {GATEWAY_URL}",
)


def test_live_compose_readiness_and_topology_contracts() -> None:
    """Verify live Gateway readiness and C02 contract validity for all 5 running services."""
    r_ready = httpx.get(f"{GATEWAY_URL}/health/ready", timeout=5.0)
    assert r_ready.status_code == 200
    ready_data = r_ready.json()
    assert ready_data["status"] == "ready"
    assert ready_data["details"] == {"auth-service": True, "transaction-service": True}

    r_topo = httpx.get(f"{GATEWAY_URL}/api/v1/topology", timeout=5.0)
    assert r_topo.status_code == 200
    topo = r_topo.json()
    assert len(topo["services"]) == 5

    cat_schema = json.loads((CONTRACTS_DIR / "service-catalog.v1.schema.json").read_text())
    cat_val = Draft202012Validator(cat_schema, format_checker=FormatChecker())
    for svc in topo["services"]:
        cat_val.validate(svc)


def test_live_sync_postgres_and_async_rabbitmq_notification_chain() -> None:
    """Verify full sync (Gateway->Auth->Transaction->Ledger->PostgreSQL) and async (RabbitMQ->Notification) flow."""
    suffix = uuid.uuid4().hex[:10]
    idem_key = f"idem-live-e2e-{suffix}"
    corr_id = f"corr-live-e2e-{suffix}"
    trace_id = f"99887766554433221100aabb{suffix[:8]}"
    traceparent = f"00-{trace_id}-0102030405060708-01"

    payload = {
        "idempotency_key": idem_key,
        "account_id": "SYNTH-ACC-001",
        "counterparty_id": "SYNTH-ACC-002",
        "amount": 325000.0,
        "currency": "IDR",
        "channel": "mobile-sim",
    }
    headers = {
        "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
        "X-Correlation-ID": corr_id,
        "traceparent": traceparent,
    }

    r1 = httpx.post(
        f"{GATEWAY_URL}/api/v1/transactions",
        headers=headers,
        json=payload,
        timeout=5.0,
    )
    assert r1.status_code == 201
    body1 = r1.json()
    assert body1["idempotent_replay"] is False
    assert body1["notification_dispatch"] == "PUBLISHED_RABBITMQ"
    assert body1["correlation_id"] == corr_id
    assert body1["trace_id"] == trace_id
    tx_id = body1["transaction_id"]

    # Idempotent replay against PostgreSQL
    r2 = httpx.post(
        f"{GATEWAY_URL}/api/v1/transactions",
        headers=headers,
        json=payload,
        timeout=5.0,
    )
    assert r2.status_code == 200
    assert r2.json()["idempotent_replay"] is True
    assert r2.json()["transaction_id"] == tx_id

    # Poll for asynchronous RabbitMQ consumption by notification-service
    delivered = None
    deadline = time.time() + 5.0
    while time.time() < deadline:
        r_get = httpx.get(
            f"{GATEWAY_URL}/api/v1/transactions/{tx_id}",
            headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
            timeout=5.0,
        )
        assert r_get.status_code == 200
        tx_state = r_get.json()
        if tx_state.get("notification") is not None:
            delivered = tx_state["notification"]
            break
        time.sleep(0.15)

    assert delivered is not None, "RabbitMQ notification was not consumed within 5s"
    assert delivered["delivery_status"] == "DELIVERED_ACKED"
    assert delivered["transaction_id"] == tx_id
    assert delivered["correlation_id"] == corr_id
    assert delivered["trace_id"] == trace_id


def test_live_traffic_generator_normal_and_spike_profiles() -> None:
    """Verify deterministic normal and spike profiles against live Docker Compose stack."""
    normal_res = asyncio.run(
        run_traffic_profile(
            target_url=GATEWAY_URL,
            profile="normal",
            seed=20261109,
            count_override=8,
        )
    )
    assert normal_res["error_count"] == 0
    assert normal_res["success_count"] == 8

    spike_res = asyncio.run(
        run_traffic_profile(
            target_url=GATEWAY_URL,
            profile="spike",
            seed=20261109,
            count_override=12,
        )
    )
    assert spike_res["error_count"] == 0
    assert spike_res["success_count"] == 12


def test_live_compose_restart_and_postgres_data_persistence() -> None:
    """Verify PostgreSQL data persistence and idempotency after restarting postgres & ledger-service."""
    suffix = uuid.uuid4().hex[:10]
    idem_key = f"idem-persist-restart-{suffix}"
    payload = {
        "idempotency_key": idem_key,
        "account_id": "SYNTH-ACC-002",
        "counterparty_id": "SYNTH-ACC-003",
        "amount": 888000.0,
        "currency": "IDR",
        "channel": "mobile-sim",
    }
    headers = {"Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001"}

    r_create = httpx.post(
        f"{GATEWAY_URL}/api/v1/transactions",
        headers=headers,
        json=payload,
        timeout=5.0,
    )
    assert r_create.status_code == 201
    tx_id = r_create.json()["transaction_id"]

    subprocess.run(
        ["docker", "compose", "restart", "postgres", "ledger-service"],
        check=True,
        capture_output=True,
        text=True,
    )

    ready = False
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            r_rdy = httpx.get(f"{GATEWAY_URL}/health/ready", timeout=2.0)
            if r_rdy.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.5)
    assert ready, "Gateway did not recover readiness after postgres & ledger-service restart"

    r_get = httpx.get(
        f"{GATEWAY_URL}/api/v1/transactions/{tx_id}",
        headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
        timeout=5.0,
    )
    assert r_get.status_code == 200
    assert r_get.json()["transaction_id"] == tx_id
    assert r_get.json()["amount"] == 888000.0

    r_replay = httpx.post(
        f"{GATEWAY_URL}/api/v1/transactions",
        headers=headers,
        json=payload,
        timeout=5.0,
    )
    assert r_replay.status_code == 200
    assert r_replay.json()["idempotent_replay"] is True
    assert r_replay.json()["transaction_id"] == tx_id


