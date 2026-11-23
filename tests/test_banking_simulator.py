import subprocess
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from services.api_gateway.app import create_app
from traffic.bank_simulator import (
    TRAFFIC_REGIMES,
    BankingTrafficSimulator,
)


@pytest.mark.anyio
async def test_banking_traffic_simulator_mock_app():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        simulator = BankingTrafficSimulator(
            target_url="http://testserver",
            harness_url="http://testserver",
            prometheus_url=None,
            rps=20.0,
            enable_faults=False,
            client=client,
        )
        telemetries = await simulator.run(count=15)
        assert len(telemetries) == 15
        for t in telemetries:
            assert t.seq_id > 0
            assert t.operation in (
                "BANK_TRANSFER",
                "QRIS_PAYMENT",
                "CHECK_NOTIFICATIONS",
                "CHECK_TX_STATUS",
                "SERVICE_STATUS_CHECK",
                "BAD_REQUEST_TEST",
            )
            assert t.regime in [r["name"] for r in TRAFFIC_REGIMES]
            assert t.status_code > 0


@pytest.mark.anyio
async def test_banking_simulator_regime_evolves_over_time():
    app = create_app()
    transport = ASGITransport(app=app)
    statuses: list[str] = []
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        simulator = BankingTrafficSimulator(
            target_url="http://testserver",
            harness_url="http://testserver",
            prometheus_url=None,
            rps=10.0,
            enable_faults=False,
            regime_duration_sec=5.0,
            client=client,
            on_status=statuses.append,
        )
        # Simulate elapsed time past regime_duration_sec
        simulator._last_regime_time -= 10.0
        initial_regime = simulator.current_regime["name"]
        telemetries = await simulator.run(count=3)
        assert len(telemetries) == 3
        assert simulator.current_regime["name"] != initial_regime
        assert any("[REGIME SHIFT]" in s for s in statuses)


@pytest.mark.anyio
async def test_banking_simulator_signed_fault_inject_and_reset():
    app = create_app()
    transport = ASGITransport(app=app)
    statuses: list[str] = []
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        simulator = BankingTrafficSimulator(
            target_url="http://testserver",
            harness_url="http://testserver",
            prometheus_url=None,
            rps=20.0,
            enable_faults=True,
            fault_interval_sec=10.0,
            fault_duration_sec=5.0,
            client=client,
            on_status=statuses.append,
        )
        # Force fault injection to trigger on api-gateway (in-process app)
        simulator._last_fault_time -= 20.0
        # Temporarily restrict CHAOS_SCENARIOS target check via direct _manage_periodic_fault
        # Run 2 steps; if chosen target is api-gateway it succeeds 200, otherwise proxy returns 503
        # Either way it must NOT raise any unhandled exception!
        telemetries = await simulator.run(count=4)
        assert len(telemetries) == 4
        assert any("[CHAOS INJECTION]" in s for s in statuses)


def test_banking_simulator_rejects_external_url():
    with pytest.raises(ValueError, match="Rejected external target host"):
        BankingTrafficSimulator(target_url="https://example.com")


def test_run_banking_simulator_cli_help():
    res = subprocess.run(
        [sys.executable, "scripts/run_banking_simulator.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "--regime-duration" in res.stdout
    assert "--skip-preflight" in res.stdout


def test_run_banking_simulator_cli_skip_preflight_smoke():
    res = subprocess.run(
        [
            sys.executable,
            "scripts/run_banking_simulator.py",
            "--skip-preflight",
            "--count",
            "2",
            "--rps",
            "20",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "Traffic Run Summary" in res.stdout
