"""Resource, Latency, Token Accounting, and Shadow Unit Cost Tracker (AT-015, KPI-07, KPI-14, NFR-007, NFR-008, NFR-013, C15)."""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import resource
import time
from typing import Any, Dict, List, Optional

_LOG = logging.getLogger(__name__)

# Standard simulation reference pricing (USD per unit) for shadow cost accounting (AT-015, KPI-14)
# In lab simulation actual spending is $0.00, but shadow rates quantify enterprise run-rate.
DEFAULT_RATES = {
    "prompt_token_per_1k": 0.00015,      # $0.15 / 1M input tokens
    "completion_token_per_1k": 0.00060,  # $0.60 / 1M output tokens
    "embedding_token_per_1k": 0.00002,   # $0.02 / 1M embedding tokens
    "tool_call_unit_cost": 0.00005,      # $0.05 / 1k tool calls
}


def get_process_resource_usage() -> Dict[str, float]:
    """Capture current process RSS memory in MiB and CPU time in seconds."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        rss_mb = mem_info.rss / (1024 * 1024)
        cpu_times = proc.cpu_times()
        cpu_sec = cpu_times.user + cpu_times.system
        return {"rss_memory_mb": round(rss_mb, 2), "cpu_time_seconds": round(cpu_sec, 3)}
    except Exception:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        # On macOS, ru_maxrss is in bytes; on Linux, in KiB
        rss_bytes = usage.ru_maxrss if sys_is_macos() else usage.ru_maxrss * 1024
        rss_mb = rss_bytes / (1024 * 1024)
        cpu_sec = usage.ru_utime + usage.ru_stime
        return {"rss_memory_mb": round(rss_mb, 2), "cpu_time_seconds": round(cpu_sec, 3)}


def sys_is_macos() -> bool:
    import platform
    return platform.system() == "Darwin"


class IncidentCostProfile:
    """Detailed latency, token, and cost profile for an individual investigation."""

    def __init__(self, incident_id: str, rates: Optional[Dict[str, float]] = None) -> None:
        self.incident_id = incident_id
        self.rates = rates or DEFAULT_RATES
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.completed_at: Optional[str] = None
        self._start_perf = time.perf_counter()

        self.state_durations_ms: Dict[str, float] = {}
        self.retrieval_latency_ms: float = 0.0
        self.total_intake_to_dossier_ms: float = 0.0

        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.embedding_tokens: int = 0
        self.tool_calls_count: int = 0

        self.outcome: str = "IN_PROGRESS"
        self.start_resources = get_process_resource_usage()
        self.end_resources: Dict[str, float] = {}

    def record_state_duration(self, state: str, duration_ms: float) -> None:
        self.state_durations_ms[state] = round(duration_ms, 3)

    def record_retrieval_latency(self, latency_ms: float) -> None:
        self.retrieval_latency_ms = round(latency_ms, 3)

    def record_tokens(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += max(0, prompt)
        self.completion_tokens += max(0, completion)

    def record_embedding_tokens(self, count: int) -> None:
        self.embedding_tokens += max(0, count)

    def record_tool_call(self, count: int = 1) -> None:
        self.tool_calls_count += max(0, count)

    def finish(self, outcome: str = "COMPLETED") -> Dict[str, Any]:
        self.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.outcome = outcome
        elapsed_sec = time.perf_counter() - self._start_perf
        self.total_intake_to_dossier_ms = round(elapsed_sec * 1000.0, 3)
        self.end_resources = get_process_resource_usage()
        return self.to_dict()

    def compute_shadow_cost_usd(self) -> float:
        """Compute transparent shadow unit cost in USD (AT-015, KPI-14)."""
        prompt_cost = (self.prompt_tokens / 1000.0) * self.rates.get("prompt_token_per_1k", 0.00015)
        completion_cost = (self.completion_tokens / 1000.0) * self.rates.get("completion_token_per_1k", 0.00060)
        embedding_cost = (self.embedding_tokens / 1000.0) * self.rates.get("embedding_token_per_1k", 0.00002)
        tool_cost = self.tool_calls_count * self.rates.get("tool_call_unit_cost", 0.00005)

        total = prompt_cost + completion_cost + embedding_cost + tool_cost
        return round(total, 6)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "outcome": self.outcome,
            "latency": {
                "intake_to_dossier_duration_ms": self.total_intake_to_dossier_ms,
                "retrieval_latency_ms": self.retrieval_latency_ms,
                "state_durations_ms": self.state_durations_ms,
                "kpi_07_under_120s": (self.total_intake_to_dossier_ms <= 120000.0),
            },
            "tokens": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "embedding_tokens": self.embedding_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens + self.embedding_tokens,
            },
            "calls": {
                "tool_calls_count": self.tool_calls_count,
            },
            "shadow_cost": {
                "currency": "USD",
                "estimated_unit_cost_usd": self.compute_shadow_cost_usd(),
                "actual_billed_lab_cost_usd": 0.00,
                "applied_rates": self.rates,
            },
            "resource_usage": {
                "initial_rss_mb": self.start_resources.get("rss_memory_mb", 0.0),
                "final_rss_mb": self.end_resources.get("rss_memory_mb", 0.0),
                "peak_rss_mb": max(
                    self.start_resources.get("rss_memory_mb", 0.0),
                    self.end_resources.get("rss_memory_mb", 0.0),
                ),
                "memory_ceiling_8gib_ok": max(
                    self.start_resources.get("rss_memory_mb", 0.0),
                    self.end_resources.get("rss_memory_mb", 0.0),
                ) <= 8192.0,
            },
        }


class CostAndResourceTracker:
    """Collector and manager for investigation cost, latency, and resource metrics across all runs."""

    def __init__(self, rates: Optional[Dict[str, float]] = None) -> None:
        self.rates = rates or DEFAULT_RATES
        self.profiles: Dict[str, IncidentCostProfile] = {}

    def start_incident(self, incident_id: str) -> IncidentCostProfile:
        profile = IncidentCostProfile(incident_id, rates=self.rates)
        self.profiles[incident_id] = profile
        return profile

    def get_profile(self, incident_id: str) -> Optional[IncidentCostProfile]:
        return self.profiles.get(incident_id)

    def record_state_duration(self, incident_id: str, state: str, duration_ms: float) -> None:
        prof = self.profiles.get(incident_id)
        if prof:
            prof.record_state_duration(state, duration_ms)

    def record_retrieval(self, incident_id: str, latency_ms: float, embedding_tokens: int = 0) -> None:
        prof = self.profiles.get(incident_id)
        if prof:
            prof.record_retrieval_latency(latency_ms)
            if embedding_tokens > 0:
                prof.record_embedding_tokens(embedding_tokens)

    def record_tokens(self, incident_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        prof = self.profiles.get(incident_id)
        if prof:
            prof.record_tokens(prompt_tokens, completion_tokens)

    def record_embedding_tokens(self, incident_id: str, count: int) -> None:
        prof = self.profiles.get(incident_id)
        if prof:
            prof.record_embedding_tokens(count)

    def record_tool_call(self, incident_id: str, count: int = 1) -> None:
        prof = self.profiles.get(incident_id)
        if prof:
            prof.record_tool_call(count)

    def finish_incident(self, incident_id: str, outcome: str = "COMPLETED") -> Dict[str, Any]:
        prof = self.profiles.get(incident_id)
        if not prof:
            prof = self.start_incident(incident_id)
        return prof.finish(outcome)

    def export_summary(self) -> Dict[str, Any]:
        """Produce an aggregated summary of cost and latency telemetry across all runs."""
        all_metrics = [p.to_dict() for p in self.profiles.values()]
        total_runs = len(all_metrics)

        total_tokens = sum(m["tokens"]["total_tokens"] for m in all_metrics)
        total_shadow_cost = sum(m["shadow_cost"]["estimated_unit_cost_usd"] for m in all_metrics)
        latencies = [m["latency"]["intake_to_dossier_duration_ms"] for m in all_metrics if m["latency"]["intake_to_dossier_duration_ms"] > 0]

        p95_latency = 0.0
        if latencies:
            sorted_lat = sorted(latencies)
            idx = int(len(sorted_lat) * 0.95)
            p95_latency = sorted_lat[min(idx, len(sorted_lat) - 1)]

        return {
            "total_incidents_tracked": total_runs,
            "total_tokens_consumed": total_tokens,
            "total_shadow_cost_usd": round(total_shadow_cost, 6),
            "actual_billed_lab_cost_usd": 0.00,
            "p95_intake_to_dossier_ms": round(p95_latency, 3),
            "kpi_07_p95_met": p95_latency <= 120000.0 if latencies else True,
            "incident_runs": all_metrics,
        }
