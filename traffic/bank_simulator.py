"""Realistic Continuous Banking Traffic & Dynamic Anomaly Simulator for SRE Lab.

Generates time-varying mixed banking traffic (Transfer, QRIS, Notifications,
Transaction Lookup, Health/Topology, and Bad-Request Probes) towards the lab
services or mock ASGI backends. Traffic regimes, customer/merchant entities,
and fault modes evolve dynamically over time to mirror real-world enterprise logs.
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from services.common.fault_control import (
    MAX_FAULT_DURATION_SEC,
    build_harness_headers,
)

# Safety boundary: only allow local lab targets (RULE-009)
ALLOWED_TARGET_HOSTS = {"127.0.0.1", "localhost", "api-gateway", "testserver"}
DEFAULT_HARNESS_TOKEN = "SYNTH-HARNESS-CTRL-KEY-C04"

SYNTHETIC_CUSTOMERS = [
    {"subject": "synth-user-001", "token": "SYNTH-TOKEN-ACTIVE-001", "account": "SYNTH-ACC-001", "name": "Budi Santoso"},
    {"subject": "synth-user-002", "token": "SYNTH-TOKEN-ACTIVE-002", "account": "SYNTH-ACC-002", "name": "Siti Rahma"},
    {"subject": "synth-user-003", "token": "SYNTH-TOKEN-ACTIVE-001", "account": "SYNTH-ACC-003", "name": "Ahmad Dani"},
    {"subject": "synth-user-004", "token": "SYNTH-TOKEN-ACTIVE-002", "account": "SYNTH-ACC-003", "name": "Dewi Lestari"},
    {"subject": "synth-user-005", "token": "SYNTH-TOKEN-ACTIVE-001", "account": "SYNTH-ACC-002", "name": "Rudi Hartono"},
]

SYNTHETIC_COUNTERPARTIES = [
    "SYNTH-ACC-001",
    "SYNTH-ACC-002",
    "SYNTH-ACC-003",
    "SYNTH-BILLER-PLN-101",
    "SYNTH-BILLER-BPJS-202",
    "SYNTH-BILLER-PDAM-303",
    "SYNTH-VA-ECOM-404",
]

# Time-varying traffic regimes so workload & log patterns evolve over time.
TRAFFIC_REGIMES: list[dict[str, Any]] = [
    {
        "name": "MORNING_RUSH",
        "rps_multiplier": 1.3,
        "weights": {
            "BANK_TRANSFER": 0.35,
            "QRIS_PAYMENT": 0.25,
            "CHECK_NOTIFICATIONS": 0.20,
            "CHECK_TX_STATUS": 0.10,
            "SERVICE_STATUS_CHECK": 0.05,
            "BAD_REQUEST_TEST": 0.05,
        },
        "currencies": ["IDR", "IDR", "IDR", "USD", "SGD"],
        "channels": ["mobile-banking", "internet-banking", "atm-network"],
    },
    {
        "name": "LUNCH_QRIS_PEAK",
        "rps_multiplier": 1.5,
        "weights": {
            "BANK_TRANSFER": 0.15,
            "QRIS_PAYMENT": 0.50,
            "CHECK_NOTIFICATIONS": 0.15,
            "CHECK_TX_STATUS": 0.12,
            "SERVICE_STATUS_CHECK": 0.03,
            "BAD_REQUEST_TEST": 0.05,
        },
        "currencies": ["IDR"],
        "channels": ["qris-mobile", "mobile-banking"],
    },
    {
        "name": "EOD_SETTLEMENT",
        "rps_multiplier": 1.1,
        "weights": {
            "BANK_TRANSFER": 0.40,
            "QRIS_PAYMENT": 0.15,
            "CHECK_NOTIFICATIONS": 0.15,
            "CHECK_TX_STATUS": 0.20,
            "SERVICE_STATUS_CHECK": 0.05,
            "BAD_REQUEST_TEST": 0.05,
        },
        "currencies": ["IDR", "USD", "SGD"],
        "channels": ["internet-banking", "api-partner-sim", "mobile-banking"],
    },
    {
        "name": "NIGHT_MAINTENANCE",
        "rps_multiplier": 0.7,
        "weights": {
            "BANK_TRANSFER": 0.20,
            "QRIS_PAYMENT": 0.15,
            "CHECK_NOTIFICATIONS": 0.25,
            "CHECK_TX_STATUS": 0.10,
            "SERVICE_STATUS_CHECK": 0.20,
            "BAD_REQUEST_TEST": 0.10,
        },
        "currencies": ["IDR", "USD"],
        "channels": ["mobile-banking", "backoffice", "atm-network"],
    },
]

# Valid C04 FaultMode catalog for rotating chaos injection
CHAOS_SCENARIOS: list[tuple[str, str, dict[str, Any]]] = [
    ("transaction-service", "http_5xx", {"error_rate": 0.55, "delay_ms": 0, "pool_limit": 1}),
    ("ledger-service", "db_latency", {"delay_ms": 1400, "error_rate": 1.0, "pool_limit": 1}),
    ("ledger-service", "pool_exhausted", {"pool_limit": 1, "delay_ms": 250, "error_rate": 1.0}),
    ("auth-service", "auth_config_mismatch", {"error_rate": 1.0, "delay_ms": 0, "pool_limit": 1}),
    ("transaction-service", "dependency_unavailable", {"error_rate": 1.0, "delay_ms": 0, "pool_limit": 1}),
    ("api-gateway", "trace_context_drop", {"error_rate": 1.0, "delay_ms": 0, "pool_limit": 1}),
    ("transaction-service", "misleading_noise_log", {"error_rate": 1.0, "delay_ms": 0, "pool_limit": 1}),
]


def validate_lab_url(url: str) -> str:
    """Enforce RULE-009: reject any non-local / external target URL."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Rejected target URL '{url}': scheme must be http or https")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_TARGET_HOSTS:
        raise ValueError(
            f"Rejected external target host '{host}' in '{url}'. "
            f"Allowed lab hosts: {sorted(ALLOWED_TARGET_HOSTS)}"
        )
    return url.rstrip("/")


@dataclass
class TransactionTelemetry:
    seq_id: int
    operation: str
    channel: str
    status_code: int
    duration_ms: float
    is_error: bool
    error_code: str | None
    account_id: str
    correlation_id: str
    timestamp: str
    regime: str = "MORNING_RUSH"


class BankingTrafficSimulator:
    """Simulates multi-channel banking workloads with evolving regimes and chaos intervals."""

    def __init__(
        self,
        target_url: str = "http://127.0.0.1:18080",
        harness_url: str = "http://127.0.0.1:18080",
        prometheus_url: str | None = "http://127.0.0.1:19090",
        harness_token: str | None = None,
        rps: float = 3.0,
        enable_faults: bool = True,
        fault_interval_sec: float = 45.0,
        fault_duration_sec: float = 15.0,
        regime_duration_sec: float = 30.0,
        client: httpx.AsyncClient | None = None,
        on_event: Callable[[TransactionTelemetry], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_alerts: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> None:
        self.target_url = validate_lab_url(target_url)
        self.harness_url = validate_lab_url(harness_url)
        self.prometheus_url = validate_lab_url(prometheus_url) if prometheus_url else None
        self.harness_token = (
            harness_token
            or os.getenv("HARNESS_CONTROL_TOKEN")
            or DEFAULT_HARNESS_TOKEN
        )
        self.rps = max(0.5, min(rps, 30.0))
        self.enable_faults = enable_faults
        self.fault_interval_sec = max(10.0, fault_interval_sec)
        self.fault_duration_sec = max(1.0, min(fault_duration_sec, MAX_FAULT_DURATION_SEC))
        self.regime_duration_sec = max(5.0, regime_duration_sec)
        self._custom_client = client
        self.on_event = on_event
        self.on_status = on_status
        self.on_alerts = on_alerts

        self._seq = 0
        self._running = False
        self._stop_event = asyncio.Event()
        self._last_fault_time = time.monotonic()
        self._last_regime_time = time.monotonic()
        self._regime_idx = 0
        self._active_fault: str | None = None
        self._last_fault_choice: tuple[str, str] | None = None
        self._alert_checked_for_current_fault = False
        self._recent_tx_ids: collections.deque[str] = collections.deque(maxlen=50)

    @property
    def current_regime(self) -> dict[str, Any]:
        return TRAFFIC_REGIMES[self._regime_idx % len(TRAFFIC_REGIMES)]

    def _emit_status(self, message: str) -> None:
        if self.on_status is not None:
            self.on_status(message)

    def _maybe_advance_regime(self) -> None:
        now = time.monotonic()
        if now - self._last_regime_time >= self.regime_duration_sec:
            self._regime_idx = (self._regime_idx + 1) % len(TRAFFIC_REGIMES)
            self._last_regime_time = now
            regime = self.current_regime
            self._emit_status(
                f"[REGIME SHIFT] Workload evolved to {regime['name']} "
                f"(RPS x{regime['rps_multiplier']})"
            )

    def _pick_operation(self, regime: dict[str, Any]) -> str:
        weights: dict[str, float] = regime["weights"]
        ops = list(weights.keys())
        probs = list(weights.values())
        chosen = random.choices(ops, weights=probs, k=1)[0]
        if chosen == "CHECK_TX_STATUS" and not self._recent_tx_ids:
            return "CHECK_NOTIFICATIONS"
        return chosen

    async def _dispatch_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        url = f"{self.target_url}{path}"
        t0 = time.perf_counter()
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                timeout=5.0,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            data: dict[str, Any] = {}
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                pass
            return resp.status_code, data, elapsed_ms
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return 503, {"error_code": "ERR_CLIENT_TIMEOUT", "message": str(exc)}, elapsed_ms

    async def _execute_step(self, client: httpx.AsyncClient) -> TransactionTelemetry:
        self._seq += 1
        regime = self.current_regime
        user = random.choice(SYNTHETIC_CUSTOMERS)
        counterparty = random.choice(SYNTHETIC_COUNTERPARTIES)
        corr_id = f"sim-bank-{self._seq:06d}-{int(time.time())}"
        now_iso = datetime.now(timezone.utc).isoformat()
        currency = random.choice(regime["currencies"])
        operation = self._pick_operation(regime)

        if operation == "BANK_TRANSFER":
            channel = random.choice(regime["channels"])
            amount = round(
                random.uniform(10_000, 2_500_000) if currency == "IDR" else random.uniform(10, 500),
                2,
            )
            idempotency = f"idem-tx-{self._seq}-{hashlib.md5(corr_id.encode()).hexdigest()[:8]}"
            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="POST",
                path="/api/v1/transactions",
                headers={
                    "Authorization": f"Bearer {user['token']}",
                    "X-Correlation-ID": corr_id,
                },
                json_body={
                    "idempotency_key": idempotency,
                    "account_id": user["account"],
                    "counterparty_id": counterparty,
                    "amount": amount,
                    "currency": currency,
                    "channel": channel,
                },
            )
            if status in (200, 201) and body.get("transaction_id"):
                self._recent_tx_ids.append(str(body["transaction_id"]))

        elif operation == "QRIS_PAYMENT":
            channel = "qris-mobile"
            merchant_id = f"SYNTH-QRIS-MCH-{random.randint(100, 999)}"
            amount = round(random.uniform(5_000, 350_000), 2)
            idempotency = f"idem-qris-{self._seq}-{hashlib.md5(corr_id.encode()).hexdigest()[:8]}"
            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="POST",
                path="/api/v1/transactions",
                headers={
                    "Authorization": f"Bearer {user['token']}",
                    "X-Correlation-ID": corr_id,
                },
                json_body={
                    "idempotency_key": idempotency,
                    "account_id": user["account"],
                    "counterparty_id": merchant_id,
                    "amount": amount,
                    "currency": "IDR",
                    "channel": channel,
                },
            )
            if status in (200, 201) and body.get("transaction_id"):
                self._recent_tx_ids.append(str(body["transaction_id"]))

        elif operation == "CHECK_NOTIFICATIONS":
            channel = random.choice(regime["channels"])
            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="GET",
                path="/api/v1/notifications",
                headers={
                    "Authorization": f"Bearer {user['token']}",
                    "X-Correlation-ID": corr_id,
                },
            )

        elif operation == "CHECK_TX_STATUS":
            channel = "mobile-banking"
            tx_id = random.choice(list(self._recent_tx_ids))
            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="GET",
                path=f"/api/v1/transactions/{tx_id}",
                headers={
                    "Authorization": f"Bearer {user['token']}",
                    "X-Correlation-ID": corr_id,
                },
            )

        elif operation == "SERVICE_STATUS_CHECK":
            channel = "backoffice"
            path = random.choice(["/health/ready", "/api/v1/topology"])
            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="GET",
                path=path,
                headers={"X-Correlation-ID": corr_id},
            )

        else:
            # Varied anomalous/bad client traffic
            operation = "BAD_REQUEST_TEST"
            channel = "adversarial-probe"
            probe_kind = random.choice(["expired_token", "invalid_token", "restricted_acc", "readonly_write"])
            if probe_kind == "expired_token":
                bad_token = "SYNTH-TOKEN-EXPIRED-001"
                acct = user["account"]
            elif probe_kind == "restricted_acc":
                bad_token = "SYNTH-TOKEN-RESTRICTED-ACC"
                acct = "SYNTH-ACC-001"
            elif probe_kind == "readonly_write":
                bad_token = "SYNTH-TOKEN-READONLY-001"
                acct = "SYNTH-ACC-001"
            else:
                bad_token = f"INVALID-KEY-{random.randint(100, 999)}"
                acct = user["account"]

            status, body, duration_ms = await self._dispatch_request(
                client=client,
                method="POST",
                path="/api/v1/transactions",
                headers={
                    "Authorization": f"Bearer {bad_token}",
                    "X-Correlation-ID": corr_id,
                },
                json_body={
                    "idempotency_key": f"bad-{self._seq}-{int(time.time())}",
                    "account_id": acct,
                    "counterparty_id": "SYNTH-ACC-002",
                    "amount": 50_000.0,
                    "currency": "IDR",
                    "channel": channel,
                },
            )

        err_code = body.get("error_code") if isinstance(body, dict) else None
        is_error = status >= 400

        telem = TransactionTelemetry(
            seq_id=self._seq,
            operation=operation,
            channel=channel,
            status_code=status,
            duration_ms=round(duration_ms, 2),
            is_error=is_error,
            error_code=str(err_code) if err_code is not None else None,
            account_id=user["account"],
            correlation_id=corr_id,
            timestamp=now_iso,
            regime=regime["name"],
        )

        if self.on_event:
            self.on_event(telem)

        return telem

    async def _reset_all_faults(self, client: httpx.AsyncClient, reason: str) -> bool:
        payload = {"target_service": "all", "reason": reason}
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = build_harness_headers(self.harness_token, raw_body)
        try:
            resp = await client.post(
                f"{self.harness_url}/_sim/fault/reset",
                headers=headers,
                content=raw_body,
                timeout=3.0,
            )
            return resp.status_code == 200
        except Exception as exc:
            self._emit_status(f"[RECOVERY ERROR] Failed to reset faults: {exc}")
            return False

    async def _check_firing_alerts(self, client: httpx.AsyncClient) -> None:
        if not self.prometheus_url or self._alert_checked_for_current_fault:
            return
        try:
            resp = await client.get(f"{self.prometheus_url}/api/v1/alerts", timeout=2.0)
            if resp.status_code == 200:
                alerts = resp.json().get("alerts", [])
                if alerts:
                    names = ", ".join(
                        f"{a.get('service_id')}:{a.get('alert_type')}"
                        for a in alerts[:3]
                    )
                    self._emit_status(f"[ALERT FIRING] {len(alerts)} alert(s) active -> {names}")
                    self._alert_checked_for_current_fault = True
                    if self.on_alerts is not None:
                        result = self.on_alerts(alerts)
                        if asyncio.iscoroutine(result):
                            await result
        except Exception:
            pass

    async def _manage_periodic_fault(self, client: httpx.AsyncClient) -> None:
        """Inject and automatically clear lab faults using signed C04 fault control."""
        if not self.enable_faults:
            return

        now = time.monotonic()
        if self._active_fault:
            elapsed = now - self._last_fault_time
            if elapsed >= min(5.0, self.fault_duration_sec * 0.4):
                await self._check_firing_alerts(client)
            if elapsed >= self.fault_duration_sec:
                fault_name = self._active_fault
                self._emit_status(f"[RECOVERY] Clearing active chaos fault: {fault_name} ...")
                await self._reset_all_faults(client, reason="simulator_periodic_recovery")
                self._active_fault = None
                self._alert_checked_for_current_fault = False
                self._last_fault_time = now
            return

        if now - self._last_fault_time >= self.fault_interval_sec:
            candidates = [
                c for c in CHAOS_SCENARIOS
                if (c[0], c[1]) != self._last_fault_choice
            ] or CHAOS_SCENARIOS
            target_svc, fault_mode, params = random.choice(candidates)
            fault_id = f"sim-{fault_mode}-{int(time.time())}"
            payload = {
                "fault_id": fault_id,
                "target_service": target_svc,
                "fault_mode": fault_mode,
                "duration_sec": self.fault_duration_sec,
                "delay_ms": int(params.get("delay_ms", 0)),
                "error_rate": float(params.get("error_rate", 1.0)),
                "pool_limit": int(params.get("pool_limit", 1)),
                "seed": random.randint(1000, 999999),
            }
            raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers = build_harness_headers(self.harness_token, raw_body)

            self._emit_status(
                f"[CHAOS INJECTION] Injecting {fault_mode} on {target_svc} "
                f"for {self.fault_duration_sec:.0f}s (fault_id={fault_id}) ..."
            )
            try:
                resp = await client.post(
                    f"{self.harness_url}/_sim/fault/inject",
                    headers=headers,
                    content=raw_body,
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    self._active_fault = f"{target_svc}:{fault_mode}"
                    self._last_fault_choice = (target_svc, fault_mode)
                    self._alert_checked_for_current_fault = False
                    self._last_fault_time = now
                else:
                    self._emit_status(
                        f"[CHAOS REJECTED] HTTP {resp.status_code}: {resp.text[:160]}"
                    )
                    self._last_fault_time = now
            except Exception as exc:
                self._emit_status(f"[CHAOS ERROR] Failed to inject fault: {exc}")
                self._last_fault_time = now

    async def run(
        self,
        count: int | None = None,
        duration_sec: float | None = None,
    ) -> list[TransactionTelemetry]:
        self._running = True
        self._stop_event.clear()
        telemetries: list[TransactionTelemetry] = []
        t_start = time.monotonic()

        client = self._custom_client
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            owns_client = True

        try:
            while self._running:
                if count and self._seq >= count:
                    break
                if duration_sec and (time.monotonic() - t_start) >= duration_sec:
                    break

                self._maybe_advance_regime()
                await self._manage_periodic_fault(client)

                telem = await self._execute_step(client)
                telemetries.append(telem)

                effective_rps = max(0.3, self.rps * float(self.current_regime["rps_multiplier"]))
                jittered_delay = (1.0 / effective_rps) * random.uniform(0.75, 1.25)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=jittered_delay)
                    break  # Stop event triggered
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._active_fault:
                await self._reset_all_faults(client, reason="simulator_shutdown_cleanup")
                self._active_fault = None
            if owns_client:
                await client.aclose()

        return telemetries

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
