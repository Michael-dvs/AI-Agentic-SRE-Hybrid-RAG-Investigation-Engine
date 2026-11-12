"""Bounded Fault Execution, Recovery, and Leakage Verification Runner (C04).

Workflow: validate -> baseline_check -> inject -> observe -> stop -> recover -> verify -> record.
Guarantees automatic cleanup on interruption and verifies C03 baseline recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict
from typing import Any

import httpx

from fault_harness.gt_registry import RestrictedGroundTruthRegistry
from fault_harness.scenarios import (
    SCENARIO_CATALOG,
    get_public_scenario_manifest,
)
from services.common.fault_control import (
    ALLOWLISTED_SERVICES,
    AUTHORIZED_HARNESS_PRINCIPAL,
    MAX_CONCURRENT_FAULTS_PER_SERVICE,
    MAX_FAULT_DURATION_SEC,
    build_harness_headers,
)
from services.common.telemetry import utc_now_iso
from traffic.generator import validate_target_url

_FORBIDDEN_LEAK_RE = re.compile(
    r"\b(SC-0[1-9]|SC-1[0-4]|ground_truth|expected_root_cause|actual_root_cause|"
    r"split_freeze_hash|SYNTH-HARNESS-CTRL-KEY)\b",
    re.IGNORECASE,
)


def scan_for_gt_leakage(samples: list[Any]) -> dict[str, Any]:
    """Scan HTTP responses, headers, and log lines for any leaked scenario ID or GT token."""
    leaks: list[dict[str, str]] = []
    for idx, item in enumerate(samples):
        serialized = item if isinstance(item, str) else json.dumps(item, sort_keys=True)
        matches = _FORBIDDEN_LEAK_RE.findall(serialized)
        if matches:
            leaks.append(
                {
                    "sample_index": str(idx),
                    "matched_terms": ",".join(sorted(set(matches))),
                    "snippet": serialized[:200],
                }
            )
    return {
        "scanned_count": len(samples),
        "leakage_detected": len(leaks) > 0,
        "leaks": leaks,
    }


async def _send_signed_harness_post(
    client: httpx.AsyncClient,
    gateway_url: str,
    path: str,
    payload: dict[str, Any],
    harness_token: str,
    principal_id: str = AUTHORIZED_HARNESS_PRINCIPAL,
) -> tuple[int, dict[str, Any]]:
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = build_harness_headers(
        secret_token=harness_token,
        body_bytes=raw_body,
        principal_id=principal_id,
    )
    resp = await client.post(
        f"{gateway_url.rstrip('/')}{path}",
        content=raw_body,
        headers=headers,
        timeout=5.0,
    )
    return resp.status_code, resp.json()


async def verify_c03_baseline_smoke(
    client: httpx.AsyncClient,
    gateway_url: str,
    tag: str,
) -> dict[str, Any]:
    """Run C03 synchronous + asynchronous smoke test and verify healthy recovery."""
    base = validate_target_url(gateway_url)
    r_ready = await client.get(f"{base}/health/ready", timeout=5.0)
    if r_ready.status_code != 200:
        return {
            "passed": False,
            "reason": f"Gateway /health/ready returned {r_ready.status_code}",
            "ready_status": r_ready.status_code,
        }

    idem_key = f"idem-c04-smoke-{tag}-{uuid.uuid4().hex[:8]}"
    corr_id = f"corr-c04-smoke-{tag}"
    trace_id = hashlib.sha256(idem_key.encode("utf-8")).hexdigest()[:32]
    traceparent = f"00-{trace_id}-0102030405060708-01"

    t0 = time.perf_counter()
    r_tx = await client.post(
        f"{base}/api/v1/transactions",
        headers={
            "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
            "X-Correlation-ID": corr_id,
            "traceparent": traceparent,
        },
        json={
            "idempotency_key": idem_key,
            "account_id": "SYNTH-ACC-001",
            "counterparty_id": "SYNTH-ACC-002",
            "amount": 125000.0,
            "currency": "IDR",
            "channel": "mobile-sim",
        },
        timeout=5.0,
    )
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    if r_tx.status_code not in (200, 201):
        return {
            "passed": False,
            "reason": f"POST /api/v1/transactions returned {r_tx.status_code}",
            "response": r_tx.json(),
        }

    tx_id = r_tx.json()["transaction_id"]
    notif_delivered = False
    for _ in range(15):
        r_get = await client.get(
            f"{base}/api/v1/transactions/{tx_id}",
            headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
            timeout=5.0,
        )
        if r_get.status_code == 200:
            ntf = r_get.json().get("notification")
            if ntf and ntf.get("delivery_status") == "DELIVERED_ACKED":
                notif_delivered = True
                break
        await asyncio.sleep(0.1)

    return {
        "passed": notif_delivered,
        "transaction_id": tx_id,
        "status_code": r_tx.status_code,
        "latency_ms": latency_ms,
        "async_notification_delivered": notif_delivered,
        "checked_at": utc_now_iso(),
    }


async def emergency_stop_all(
    gateway_url: str = "http://127.0.0.1:18080",
    harness_token: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Unconditionally reset all faults across all 5 lab services and verify recovery."""
    base = validate_target_url(gateway_url)
    token = harness_token or os.getenv(
        "HARNESS_CONTROL_TOKEN", "SYNTH-HARNESS-CTRL-KEY-C04"
    )

    async def _do_stop(client: httpx.AsyncClient) -> dict[str, Any]:
        code, reset_resp = await _send_signed_harness_post(
            client,
            base,
            "/_sim/fault/reset",
            {"target_service": "all", "reason": "emergency_or_scheduled_reset"},
            token,
        )
        smoke = await verify_c03_baseline_smoke(client, base, tag="post-reset")
        return {
            "reset_http_status": code,
            "reset_response": reset_resp,
            "post_reset_smoke": smoke,
            "recovered_cleanly": code == 200 and smoke["passed"],
        }

    if http_client is not None:
        return await _do_stop(http_client)
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await _do_stop(client)


async def run_scenario_workflow(
    scenario_id: str,
    gateway_url: str = "http://127.0.0.1:18080",
    duration_override_sec: float | None = None,
    seed_override: int | None = None,
    registry: RestrictedGroundTruthRegistry | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Execute the 8-step bounded C04 lifecycle:
    validate -> baseline_check -> inject -> observe -> stop -> recover -> verify -> record.
    """
    # Step 1: validate
    base_url = validate_target_url(gateway_url)
    if scenario_id not in SCENARIO_CATALOG:
        raise ValueError(f"Unsupported scenario_id '{scenario_id}'")

    spec = SCENARIO_CATALOG[scenario_id]
    for target in spec.target_services:
        if target not in ALLOWLISTED_SERVICES:
            raise ValueError(f"Unauthorized fault target '{target}'")

    duration_sec = float(
        duration_override_sec
        if duration_override_sec is not None
        else spec.default_duration_sec
    )
    if duration_sec <= 0 or duration_sec > MAX_FAULT_DURATION_SEC:
        raise ValueError(
            f"duration_sec {duration_sec} exceeds bounds (0, {MAX_FAULT_DURATION_SEC}]"
        )
    if len(spec.fault_actions) > MAX_CONCURRENT_FAULTS_PER_SERVICE:
        raise ValueError(
            f"Scenario '{scenario_id}' exceeds max concurrent faults ({MAX_CONCURRENT_FAULTS_PER_SERVICE})"
        )

    seed = int(seed_override if seed_override is not None else spec.default_seed)
    gt_reg = registry or RestrictedGroundTruthRegistry()
    harness_token = gt_reg.harness_token

    run_suffix = uuid.uuid4().hex[:10]
    run_id = f"run-{seed}-{run_suffix}"
    incident_id = f"inc-{seed}-{run_suffix}"

    planned_params = [
        {
            "fault_id": f"flt-{run_suffix}-{act.fault_id_suffix}",
            "target_service": act.target_service,
            "fault_mode": act.fault_mode,
            "duration_sec": duration_sec,
            "delay_ms": act.delay_ms,
            "error_rate": act.error_rate,
            "pool_limit": act.pool_limit,
            "seed": seed,
        }
        for act in spec.fault_actions
    ]

    async def _execute(client: httpx.AsyncClient) -> dict[str, Any]:
        # Step 2: baseline_check
        pre_smoke = await verify_c03_baseline_smoke(client, base_url, tag="pre-inject")
        if not pre_smoke["passed"]:
            raise RuntimeError(
                f"Pre-injection C03 baseline check failed: {pre_smoke}"
            )

        # Freeze GT record BEFORE fault onset (RULE-002 / BRD §13.3)
        frozen_record = gt_reg.freeze_ground_truth(
            run_id=run_id,
            incident_id=incident_id,
            scenario_id=scenario_id,
            fault_seed=seed,
            injected_parameters=planned_params,
            caller_principal=AUTHORIZED_HARNESS_PRINCIPAL,
            caller_token=harness_token,
        )

        fault_onset_at = utc_now_iso()
        fault_end_at = fault_onset_at
        injection_results: list[dict[str, Any]] = []
        observed_probes: list[dict[str, Any]] = []
        leak_scan: dict[str, Any] = {"scanned_count": 0, "leakage_detected": False, "leaks": []}
        recovery_result: dict[str, Any] = {}

        try:
            # Step 3: inject
            for param in planned_params:
                code, resp_json = await _send_signed_harness_post(
                    client, base_url, "/_sim/fault/inject", param, harness_token
                )
                if code != 200:
                    raise RuntimeError(
                        f"Fault injection failed with status {code}: {resp_json}"
                    )
                injection_results.append(resp_json)

            # Step 4: observe
            samples_to_scan: list[Any] = []
            for probe_idx in range(2):
                idem_key = f"idem-probe-{run_suffix}-{probe_idx}"
                corr_id = f"corr-probe-{run_suffix}-{probe_idx}"
                t_start = time.perf_counter()
                r_probe = await client.post(
                    f"{base_url}/api/v1/transactions",
                    headers={
                        "Authorization": "Bearer SYNTH-TOKEN-ACTIVE-001",
                        "X-Correlation-ID": corr_id,
                    },
                    json={
                        "idempotency_key": idem_key,
                        "account_id": "SYNTH-ACC-001",
                        "counterparty_id": "SYNTH-ACC-002",
                        "amount": 210000.0 + probe_idx * 1000.0,
                        "currency": "IDR",
                        "channel": "mobile-sim",
                    },
                    timeout=5.0,
                )
                elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
                probe_body = r_probe.json()
                samples_to_scan.append(dict(r_probe.headers))
                samples_to_scan.append(probe_body)

                observed_probes.append(
                    {
                        "probe_index": probe_idx,
                        "status_code": r_probe.status_code,
                        "latency_ms": elapsed_ms,
                        "error_code": probe_body.get("error_code"),
                        "transaction_id": probe_body.get("transaction_id"),
                    }
                )

            # Check notification queue stats during observation
            r_ntf = await client.get(
                f"{base_url}/api/v1/notifications",
                headers={"Authorization": "Bearer SYNTH-TOKEN-READONLY-001"},
                timeout=5.0,
            )
            ntf_stats = r_ntf.json() if r_ntf.status_code == 200 else {}
            samples_to_scan.append(ntf_stats)
            leak_scan = scan_for_gt_leakage(samples_to_scan)

        finally:
            # Step 5, 6, 7: stop -> recover -> verify (guaranteed even on exception)
            recovery_result = await emergency_stop_all(
                gateway_url=base_url,
                harness_token=harness_token,
                http_client=client,
            )
            fault_end_at = utc_now_iso()

        if not recovery_result.get("recovered_cleanly"):
            raise RuntimeError(
                f"Post-fault recovery verification failed for run {run_id}: {recovery_result}"
            )

        # Step 8: record
        gt_reg.record_execution_outcome(
            run_id=run_id,
            fault_onset_at=fault_onset_at,
            fault_end_at=fault_end_at,
            injection_outcome="INJECTED_AND_OBSERVED",
            recovery_outcome="RECOVERED_VERIFIED",
            leakage_detected=leak_scan["leakage_detected"],
            evidence_refs=[f"evidence/c04/{run_id}"],
            caller_principal=AUTHORIZED_HARNESS_PRINCIPAL,
            caller_token=harness_token,
        )

        # Return sanitized run summary (never includes scenario_id/root-cause answer in runtime telemetry)
        return {
            "run_id": run_id,
            "incident_id": incident_id,
            "workflow_steps_completed": [
                "validate",
                "baseline_check",
                "inject",
                "observe",
                "stop",
                "recover",
                "verify",
                "record",
            ],
            "pre_injection_baseline": pre_smoke,
            "fault_onset_at": fault_onset_at,
            "fault_end_at": fault_end_at,
            "label_frozen_at": frozen_record["label_frozen_at"],
            "frozen_record_sha256": frozen_record["record_sha256"],
            "active_faults_injected": len(injection_results),
            "observed_probes": observed_probes,
            "observed_notification_queue": {
                "consumer_lag_active": ntf_stats.get("consumer_lag_active"),
                "backlog_depth": ntf_stats.get("backlog_depth"),
            },
            "leakage_scan": leak_scan,
            "post_recovery_verification": recovery_result["post_reset_smoke"],
            "recovered_cleanly": recovery_result["recovered_cleanly"],
        }

    if http_client is not None:
        return await _execute(http_client)
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await _execute(client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="C04 Fault Injection & Recovery Harness CLI (Operator Only)."
    )
    parser.add_argument(
        "--gateway-url",
        default="http://127.0.0.1:18080",
        help="Local lab API Gateway URL",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CATALOG.keys()),
        default=None,
        help="Scenario ID to execute through the 8-step bounded workflow",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="Fault duration in seconds (<= 120s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261109,
        help="Deterministic seed",
    )
    parser.add_argument(
        "--emergency-stop",
        action="store_true",
        help="Immediately reset all faults on all 5 services and run recovery smoke test",
    )
    parser.add_argument(
        "--export-manifest",
        action="store_true",
        help="Print sanitized public scenario catalog JSON",
    )
    args = parser.parse_args(argv)

    if args.export_manifest:
        sys.stdout.write(json.dumps(get_public_scenario_manifest(), indent=2) + "\n")
        return 0

    if args.emergency_stop:
        res = asyncio.run(emergency_stop_all(gateway_url=args.gateway_url))
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
        return 0 if res["recovered_cleanly"] else 1

    if args.scenario:
        summary = asyncio.run(
            run_scenario_workflow(
                scenario_id=args.scenario,
                gateway_url=args.gateway_url,
                duration_override_sec=args.duration,
                seed_override=args.seed,
            )
        )
        sys.stdout.write(json.dumps(summary, indent=2) + "\n")
        return (
            0
            if summary["recovered_cleanly"]
            and not summary["leakage_scan"]["leakage_detected"]
            else 1
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

