"""Measured DEV-only capacity harness for C20 Stage 2A."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import math
import os
import resource
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from services.alert_intake.dedup import AlertDeduplicator


IncidentProcessor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def utc_now_z() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _rss_mib() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return raw / (1024.0 * 1024.0)
    return raw / 1024.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _snapshot(queue_depth: int) -> dict[str, Any]:
    return {
        "observed_at": utc_now_z(),
        "queue_depth": queue_depth,
        "process_cpu_seconds": round(time.process_time(), 6),
        "process_peak_rss_mib": round(_rss_mib(), 3),
    }


def read_docker_stats() -> dict[str, Any]:
    """Read Docker container CPU/RAM without mutating the lab."""
    try:
        completed = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"status": "UNAVAILABLE", "reason": type(exc).__name__, "containers": []}
    rows = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not rows:
        reason = completed.stderr.strip() or "No running containers returned by docker stats"
        return {"status": "UNAVAILABLE", "reason": reason[:512], "containers": []}
    import json

    containers = []
    for row in rows:
        try:
            containers.append(json.loads(row))
        except json.JSONDecodeError:
            return {"status": "UNAVAILABLE", "reason": "Invalid docker stats JSON", "containers": []}
    return {"status": "MEASURED", "reason": None, "containers": containers}


class CapacityProfiler:
    """Exercise deduplication and bounded concurrent dossier processing with process metrics."""

    def __init__(
        self,
        processor: IncidentProcessor,
        *,
        lab_ram_limit_gib: float = 8.0,
        processing_workers: int = 8,
    ) -> None:
        if processing_workers < 1:
            raise ValueError("processing_workers must be positive")
        self.processor = processor
        self.lab_ram_limit_gib = lab_ram_limit_gib
        self.processing_workers = processing_workers

    @staticmethod
    def _admit_simultaneously(
        deduplicator: AlertDeduplicator,
        alerts: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        barrier = threading.Barrier(len(alerts))

        def admit(alert: Mapping[str, Any]) -> dict[str, Any]:
            barrier.wait(timeout=10)
            return deduplicator.process(alert)

        with ThreadPoolExecutor(max_workers=len(alerts), thread_name_prefix="c20-admit") as pool:
            return list(pool.map(admit, alerts))

    def _process_queue(self, deduplicator: AlertDeduplicator) -> tuple[list[dict[str, Any]], list[float]]:
        incidents = []
        while True:
            incident = deduplicator.dequeue()
            if incident is None:
                break
            incidents.append(incident)

        def process(incident: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
            started = time.perf_counter()
            dossier = dict(self.processor(incident))
            return dossier, (time.perf_counter() - started) * 1000.0

        if not incidents:
            return [], []
        with ThreadPoolExecutor(
            max_workers=min(self.processing_workers, len(incidents)),
            thread_name_prefix="c20-process",
        ) as pool:
            completed = list(pool.map(process, incidents))
        return [item[0] for item in completed], [item[1] for item in completed]

    def run_duplicate_burst(
        self,
        alert: Mapping[str, Any],
        *,
        duplicates: int = 100,
    ) -> dict[str, Any]:
        audit_events: list[dict[str, Any]] = []
        deduplicator = AlertDeduplicator(audit_sink=audit_events.append)
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        rss_before = _rss_mib()
        results = self._admit_simultaneously(deduplicator, [dict(alert) for _ in range(duplicates)])
        samples = [_snapshot(deduplicator.queue_size())]
        dossiers, latencies = self._process_queue(deduplicator)
        samples.append(_snapshot(deduplicator.queue_size()))
        wall_seconds = max(time.perf_counter() - started_wall, 1e-9)
        incident_ids = {
            result["incident"]["incident_id"]
            for result in results
            if result.get("incident") is not None
        }
        return {
            "status": "PASS" if len(incident_ids) == 1 and len(dossiers) == 1 else "FAIL",
            "alerts_submitted": duplicates,
            "unique_incidents": len(incident_ids),
            "dossiers_generated": len(dossiers),
            "final_hit_count": max(result["incident"]["hit_count"] for result in results),
            "action_counts": {
                action: sum(1 for result in results if result["action"] == action)
                for action in ("create", "merge", "split", "backpressure")
            },
            "throughput_alerts_per_second": round(duplicates / wall_seconds, 3),
            "latency_p50_ms": round(_percentile(latencies, 0.50), 3),
            "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
            "process_cpu_seconds": round(time.process_time() - started_cpu, 6),
            "process_peak_rss_mib_before": round(rss_before, 3),
            "process_peak_rss_mib_after": round(_rss_mib(), 3),
            "audit_event_count": len(audit_events),
            "series": samples,
        }

    def run_concurrency_wave(
        self,
        alerts: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        level = len(alerts)
        audit_events: list[dict[str, Any]] = []
        deduplicator = AlertDeduplicator(audit_sink=audit_events.append)
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        rss_before = _rss_mib()
        results = self._admit_simultaneously(deduplicator, alerts)
        peak_depth = deduplicator.queue_size()
        samples = [_snapshot(peak_depth)]
        dossiers, latencies = self._process_queue(deduplicator)
        samples.append(_snapshot(deduplicator.queue_size()))
        wall_seconds = max(time.perf_counter() - started_wall, 1e-9)
        rejected = sum(1 for result in results if result["action"] == "backpressure")
        rss_after = _rss_mib()
        capacity_reached = rss_after > self.lab_ram_limit_gib * 1024.0
        if capacity_reached:
            status = "NOT_RUN (Capacity/Quota Ceiling Reached)"
        else:
            status = "PASS" if len(dossiers) == level and rejected == 0 else "FAIL"
        return {
            "level": level,
            "status": status,
            "accepted_incidents": level - rejected,
            "rejected_incidents": rejected,
            "dossiers_generated": len(dossiers),
            "throughput_incidents_per_second": round(len(dossiers) / wall_seconds, 3),
            "queue_depth_peak": peak_depth,
            "latency_p50_ms": round(_percentile(latencies, 0.50), 3),
            "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
            "process_cpu_seconds": round(time.process_time() - started_cpu, 6),
            "process_cpu_percent_of_one_core": round(
                ((time.process_time() - started_cpu) / wall_seconds) * 100.0,
                3,
            ),
            "process_peak_rss_mib_before": round(rss_before, 3),
            "process_peak_rss_mib_after": round(rss_after, 3),
            "lab_ram_limit_mib": round(self.lab_ram_limit_gib * 1024.0, 3),
            "audit_event_count": len(audit_events),
            "series": samples,
        }
