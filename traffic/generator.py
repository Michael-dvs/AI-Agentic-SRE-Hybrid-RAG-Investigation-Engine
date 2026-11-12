"""Deterministic Synthetic Traffic Generator for C03 Lab (SC-01).

Supports normal and spike profiles, fixed PRNG seed, bounded rate/duration/concurrency,
strict external target rejection (RULE-009), and reproducible JSON summary output.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

ALLOWED_TARGET_HOSTS = {"127.0.0.1", "localhost", "api-gateway", "testserver"}
MAX_CONCURRENCY_CAP = 16
MAX_RATE_RPS = 50.0
MAX_DURATION_SEC = 300.0

PROFILES: dict[str, dict[str, Any]] = {
    "normal": {
        "rate_rps": 4.0,
        "duration_sec": 3.0,
        "concurrency_cap": 2,
        "channels": ["mobile-sim", "web-sim", "atm-sim"],
        "currencies": ["IDR", "USD", "SGD"],
    },
    "spike": {
        "rate_rps": 12.0,
        "duration_sec": 3.0,
        "concurrency_cap": 6,
        "channels": ["mobile-sim", "web-sim", "qr-burst-sim"],
        "currencies": ["IDR", "USD"],
    },
}


@dataclass(frozen=True)
class PlannedRequest:
    seq_index: int
    idempotency_key: str
    correlation_id: str
    traceparent: str
    account_id: str
    counterparty_id: str
    amount: float
    currency: str
    channel: str
    token: str


def validate_target_url(target_url: str) -> str:
    """Enforce RULE-009: reject any non-local / external traffic generator target."""
    parsed = urlparse(target_url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Rejected target URL '{target_url}': scheme must be http or https"
        )
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_TARGET_HOSTS:
        raise ValueError(
            f"Rejected external target host '{host}' in '{target_url}'. "
            f"Allowed lab hosts: {sorted(ALLOWED_TARGET_HOSTS)}"
        )
    return target_url.rstrip("/")


def build_deterministic_schedule(
    profile: str,
    seed: int,
    rate_rps: float | None = None,
    duration_sec: float | None = None,
    count_override: int | None = None,
) -> tuple[list[PlannedRequest], str]:
    """Generate a deterministic request schedule for a given seed and profile."""
    if profile not in PROFILES:
        raise ValueError(f"Unsupported profile '{profile}'. Expected one of {list(PROFILES)}")

    prof = PROFILES[profile]
    eff_rate = float(rate_rps if rate_rps is not None else prof["rate_rps"])
    eff_dur = float(duration_sec if duration_sec is not None else prof["duration_sec"])
    if eff_rate <= 0 or eff_rate > MAX_RATE_RPS:
        raise ValueError(f"rate_rps must be in (0, {MAX_RATE_RPS}]")
    if eff_dur <= 0 or eff_dur > MAX_DURATION_SEC:
        raise ValueError(f"duration_sec must be in (0, {MAX_DURATION_SEC}]")

    total_requests = (
        int(count_override)
        if count_override is not None
        else max(1, int(round(eff_rate * eff_dur)))
    )

    rng = random.Random(seed)
    accounts = ["SYNTH-ACC-001", "SYNTH-ACC-002", "SYNTH-ACC-003"]
    channels = prof["channels"]
    currencies = prof["currencies"]

    schedule: list[PlannedRequest] = []
    for idx in range(total_requests):
        src_acc = rng.choice(accounts)
        other_accounts = [a for a in accounts if a != src_acc]
        dst_acc = rng.choice(other_accounts)
        currency = rng.choice(currencies)
        channel = rng.choice(channels)
        raw_amount = rng.uniform(10.0, 5000.0) if currency != "IDR" else rng.uniform(10000.0, 2500000.0)
        amount = round(raw_amount, 2)

        key_material = f"{profile}:{seed}:{idx}:{src_acc}:{dst_acc}:{amount}"
        digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        idempotency_key = f"idem-{profile}-{seed}-{idx:04d}-{digest[:8]}"
        correlation_id = f"corr-{profile}-{seed}-{idx:04d}-{digest[8:16]}"
        trace_id = digest[:32]
        span_id = digest[32:48]
        traceparent = f"00-{trace_id}-{span_id}-01"

        schedule.append(
            PlannedRequest(
                seq_index=idx,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                traceparent=traceparent,
                account_id=src_acc,
                counterparty_id=dst_acc,
                amount=amount,
                currency=currency,
                channel=channel,
                token="SYNTH-TOKEN-ACTIVE-001",
            )
        )

    schedule_json = json.dumps([asdict(r) for r in schedule], sort_keys=True)
    schedule_hash = hashlib.sha256(schedule_json.encode("utf-8")).hexdigest()
    return schedule, schedule_hash


async def run_traffic_profile(
    target_url: str = "http://127.0.0.1:18080",
    profile: str = "normal",
    seed: int = 20261109,
    rate_rps: float | None = None,
    duration_sec: float | None = None,
    concurrency_cap: int | None = None,
    count_override: int | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Execute the deterministic synthetic traffic schedule and return summary telemetry."""
    base_url = validate_target_url(target_url)
    prof = PROFILES[profile]
    eff_rate = float(rate_rps if rate_rps is not None else prof["rate_rps"])
    eff_dur = float(duration_sec if duration_sec is not None else prof["duration_sec"])
    eff_conc = int(concurrency_cap if concurrency_cap is not None else prof["concurrency_cap"])
    if eff_conc < 1 or eff_conc > MAX_CONCURRENCY_CAP:
        raise ValueError(f"concurrency_cap must be between 1 and {MAX_CONCURRENCY_CAP}")

    schedule, schedule_hash = build_deterministic_schedule(
        profile=profile,
        seed=seed,
        rate_rps=eff_rate,
        duration_sec=eff_dur,
        count_override=count_override,
    )

    sem = asyncio.Semaphore(eff_conc)
    interval_sec = 1.0 / eff_rate
    latencies_ms: list[float] = []
    status_counts: dict[str, int] = {}
    sample_tx_ids: list[str] = []

    async def _send_one(client: httpx.AsyncClient, item: PlannedRequest) -> None:
        if item.seq_index > 0 and http_client is None:
            await asyncio.sleep(min(item.seq_index * interval_sec, eff_dur))
        async with sem:
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/transactions",
                    headers={
                        "Authorization": f"Bearer {item.token}",
                        "X-Correlation-ID": item.correlation_id,
                        "traceparent": item.traceparent,
                    },
                    json={
                        "idempotency_key": item.idempotency_key,
                        "account_id": item.account_id,
                        "counterparty_id": item.counterparty_id,
                        "amount": item.amount,
                        "currency": item.currency,
                        "channel": item.channel,
                    },
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(elapsed_ms)
                code_str = str(resp.status_code)
                status_counts[code_str] = status_counts.get(code_str, 0) + 1
                if resp.status_code in (200, 201):
                    tx_id = resp.json().get("transaction_id")
                    if tx_id and len(sample_tx_ids) < 5:
                        sample_tx_ids.append(tx_id)
            except Exception:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(elapsed_ms)
                status_counts["network_error"] = status_counts.get("network_error", 0) + 1

    start_wall = time.perf_counter()
    if http_client is not None:
        await asyncio.gather(*(_send_one(http_client, item) for item in schedule))
    else:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await asyncio.gather(*(_send_one(client, item) for item in schedule))
    wall_elapsed_sec = round(time.perf_counter() - start_wall, 3)

    sorted_lat = sorted(latencies_ms)
    if sorted_lat:
        p50_idx = max(0, min(len(sorted_lat) - 1, math.ceil(0.50 * len(sorted_lat)) - 1))
        p95_idx = max(0, min(len(sorted_lat) - 1, math.ceil(0.95 * len(sorted_lat)) - 1))
        p50_ms = round(sorted_lat[p50_idx], 2)
        p95_ms = round(sorted_lat[p95_idx], 2)
    else:
        p50_ms = 0.0
        p95_ms = 0.0

    success_count = status_counts.get("200", 0) + status_counts.get("201", 0)
    error_count = len(schedule) - success_count

    return {
        "scenario_id": "SC-01",
        "profile": profile,
        "seed": seed,
        "target_url": base_url,
        "rate_rps": eff_rate,
        "duration_sec": eff_dur,
        "concurrency_cap": eff_conc,
        "planned_requests": len(schedule),
        "completed_requests": len(latencies_ms),
        "success_count": success_count,
        "error_count": error_count,
        "status_counts": status_counts,
        "p50_latency_ms": p50_ms,
        "p95_latency_ms": p95_ms,
        "wall_elapsed_sec": wall_elapsed_sec,
        "schedule_sha256": schedule_hash,
        "first_request": asdict(schedule[0]),
        "sample_transaction_ids": sample_tx_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic synthetic traffic generator for C03 lab."
    )
    parser.add_argument(
        "--target-url",
        default="http://127.0.0.1:18080",
        help="Gateway base URL (must be localhost/127.0.0.1/api-gateway)",
    )
    parser.add_argument(
        "--profile",
        choices=["normal", "spike"],
        default="normal",
        help="Traffic profile",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261109,
        help="Fixed PRNG seed for deterministic traffic generation",
    )
    parser.add_argument("--rate", type=float, default=None, help="Requests per second")
    parser.add_argument("--duration", type=float, default=None, help="Duration in seconds")
    parser.add_argument(
        "--concurrency", type=int, default=None, help="Max concurrent requests (<=16)"
    )
    parser.add_argument(
        "--count", type=int, default=None, help="Optional exact request count override"
    )
    args = parser.parse_args(argv)

    summary = asyncio.run(
        run_traffic_profile(
            target_url=args.target_url,
            profile=args.profile,
            seed=args.seed,
            rate_rps=args.rate,
            duration_sec=args.duration,
            concurrency_cap=args.concurrency,
            count_override=args.count,
        )
    )
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

