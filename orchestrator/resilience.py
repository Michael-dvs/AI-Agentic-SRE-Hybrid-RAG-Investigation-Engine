"""Resilience Controller, Circuit Breaker, Budgets, Deadlines, and Cancellation (C11, FR-AGT-004, FR-AGT-006, FR-AGT-009, ADR-S05)."""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

_LOG = logging.getLogger(__name__)


class ResilienceError(Exception):
    """Base exception for resilience enforcement."""

    def __init__(self, message: str, code: str = "RESILIENCE_ERROR") -> None:
        super().__init__(message)
        self.code = code


class DeadlineExceededError(ResilienceError):
    """Raised when total incident investigation time exceeds the global deadline (FR-AGT-006, ADR-S05)."""

    def __init__(self, message: str = "Global incident investigation deadline exceeded") -> None:
        super().__init__(message, code="DEADLINE_EXCEEDED")


class BudgetExhaustedError(ResilienceError):
    """Raised when total tool calls for an incident exceed the allocated budget (FR-AGT-004, ADR-S05)."""

    def __init__(self, message: str = "Incident tool call budget exhausted") -> None:
        super().__init__(message, code="BUDGET_EXHAUSTED")


class IncidentCancelledError(ResilienceError):
    """Raised when an active incident investigation is cancelled via kill switch (FR-AGT-009)."""

    def __init__(self, message: str = "Investigation cancelled by operator kill switch") -> None:
        super().__init__(message, code="CANCELLED")


class CircuitOpenError(ResilienceError):
    """Raised when a tool backend is unavailable and circuit breaker is open (NFR-014)."""

    def __init__(self, target: str, message: str = "Circuit breaker open for target") -> None:
        super().__init__(f"{message}: {target}", code="SOURCE_UNAVAILABLE")
        self.target = target


class CircuitBreaker:
    """Thread-safe circuit breaker preventing cascading failures and backend hammering (NFR-014).

    Trips to OPEN when consecutive failures reach failure_threshold.
    Remains OPEN during cooldown_seconds, then transitions to HALF_OPEN to test.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 10.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        # target -> {"failures": int, "state": str, "last_failure_time": float}
        self._state: Dict[str, Dict[str, Any]] = {}

    def is_open(self, target: str) -> bool:
        """Return True if circuit is currently OPEN (blocking requests)."""
        with self._lock:
            info = self._state.get(target)
            if not info:
                return False
            if info["state"] == "OPEN":
                now = self._clock()
                if now - info["last_failure_time"] >= self.cooldown_seconds:
                    # Transition to HALF_OPEN to allow trial request
                    info["state"] = "HALF_OPEN"
                    return False
                return True
            return False

    def record_success(self, target: str) -> None:
        """Record successful call to target, resetting failure counter."""
        with self._lock:
            if target in self._state:
                self._state[target] = {
                    "failures": 0,
                    "state": "CLOSED",
                    "last_failure_time": 0.0,
                }

    def record_failure(self, target: str) -> bool:
        """Record failure. Returns True if circuit tripped to OPEN."""
        with self._lock:
            now = self._clock()
            info = self._state.setdefault(
                target, {"failures": 0, "state": "CLOSED", "last_failure_time": 0.0}
            )
            info["failures"] += 1
            info["last_failure_time"] = now

            if info["failures"] >= self.failure_threshold:
                tripped = info["state"] != "OPEN"
                info["state"] = "OPEN"
                if tripped:
                    _LOG.warning("Circuit breaker tripped to OPEN for target %s (failures: %d)", target, info["failures"])
                return tripped
            return False

    def get_state(self, target: str) -> str:
        with self._lock:
            info = self._state.get(target)
            if not info:
                return "CLOSED"
            if info["state"] == "OPEN":
                if self._clock() - info["last_failure_time"] >= self.cooldown_seconds:
                    return "HALF_OPEN"
            return str(info["state"])

    def reset(self, target: str | None = None) -> None:
        with self._lock:
            if target:
                self._state.pop(target, None)
            else:
                self._state.clear()


class DeadLetterQueue:
    """In-memory Dead Letter Queue (DLQ) storing unprocessable or aborted incidents for offline audit (NFR-006)."""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def enqueue(
        self,
        incident_id: str,
        reason_code: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        entry = {
            "incident_id": incident_id,
            "reason_code": reason_code,
            "error_message": error_message,
            "enqueued_at": now_z,
            "context": context or {},
        }
        with self._lock:
            if len(self._queue) >= self.max_size:
                self._queue.pop(0)  # FIFO eviction on cap
            self._queue.append(entry)

    def get_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._queue)

    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()


class ResilienceController:
    """Supervises deadlines, tool quotas, circuit breakers, and kill switch per incident (FR-AGT-004, FR-AGT-006, FR-AGT-009)."""

    def __init__(
        self,
        default_deadline_seconds: float = 120.0,
        max_tool_calls: int = 30,
        circuit_breaker: CircuitBreaker | None = None,
        dlq: DeadLetterQueue | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.default_deadline_seconds = default_deadline_seconds
        self.max_tool_calls = max_tool_calls
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.dlq = dlq or DeadLetterQueue()
        self._clock = clock or time.monotonic

        # incident_id -> start_time_monotonic
        self._incident_start_times: Dict[str, float] = {}
        # incident_id -> tool_call_count
        self._tool_call_counts: Dict[str, int] = {}
        self._cancelled_incidents: Set[str] = set()
        self._cancellation_reasons: Dict[str, str] = {}
        self._kill_switch_engaged = False
        self._kill_switch_reason = "Emergency kill switch engaged"
        self._lock = threading.Lock()

        # Audit events for E11 packaging
        self._resilience_events: List[Dict[str, Any]] = []

    def start_incident(self, incident_id: str) -> bool:
        """Register an incident, or reject it when the global kill switch is engaged."""
        with self._lock:
            if self._kill_switch_engaged:
                self._cancelled_incidents.add(incident_id)
                self._cancellation_reasons[incident_id] = self._kill_switch_reason
                self._resilience_events.append({
                    "event_type": "INTAKE_REJECTED_KILL_SWITCH",
                    "incident_id": incident_id,
                    "reason": self._kill_switch_reason,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                })
                return False
            if incident_id not in self._incident_start_times:
                self._incident_start_times[incident_id] = self._clock()
            self._tool_call_counts.setdefault(incident_id, 0)
            return True

    def check_deadline(self, incident_id: str, deadline_seconds: float | None = None) -> float:
        """Check if global deadline exceeded. Returns elapsed seconds or raises DeadlineExceededError."""
        limit = deadline_seconds if deadline_seconds is not None else self.default_deadline_seconds
        with self._lock:
            start = self._incident_start_times.get(incident_id)
            if start is None:
                start = self._clock()
                self._incident_start_times[incident_id] = start

            elapsed = self._clock() - start
            if elapsed > limit:
                event = {
                    "event_type": "DEADLINE_EXCEEDED",
                    "incident_id": incident_id,
                    "elapsed_seconds": elapsed,
                    "limit_seconds": limit,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                self._resilience_events.append(event)
                raise DeadlineExceededError(
                    f"Investigation for {incident_id} exceeded global deadline ({elapsed:.2f}s > {limit:.2f}s)"
                )
            return elapsed

    def check_and_increment_budget(self, incident_id: str) -> int:
        """Check tool call quota and increment counter. Raises BudgetExhaustedError if exceeded."""
        with self._lock:
            count = self._tool_call_counts.get(incident_id, 0)
            if count >= self.max_tool_calls:
                event = {
                    "event_type": "BUDGET_EXHAUSTED",
                    "incident_id": incident_id,
                    "current_count": count,
                    "limit": self.max_tool_calls,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                self._resilience_events.append(event)
                raise BudgetExhaustedError(
                    f"Tool call budget exhausted for {incident_id} ({count}/{self.max_tool_calls})"
                )
            self._tool_call_counts[incident_id] = count + 1
            return self._tool_call_counts[incident_id]

    def get_tool_call_count(self, incident_id: str) -> int:
        with self._lock:
            return self._tool_call_counts.get(incident_id, 0)

    def cancel_incident(self, incident_id: str, reason: str = "Operator cancellation kill switch") -> None:
        """Emergency kill switch cancelling active incident investigation."""
        with self._lock:
            self._cancelled_incidents.add(incident_id)
            self._cancellation_reasons[incident_id] = reason
            event = {
                "event_type": "INCIDENT_CANCELLED",
                "incident_id": incident_id,
                "reason": reason,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self._resilience_events.append(event)
            _LOG.warning("Kill switch engaged: incident %s cancelled (%s)", incident_id, reason)

    def engage_kill_switch(self, reason: str = "Emergency operator kill switch") -> list[str]:
        """Reject new intake and cooperatively cancel every registered investigation."""
        with self._lock:
            self._kill_switch_engaged = True
            self._kill_switch_reason = reason
            active = sorted(self._incident_start_times)
            self._cancelled_incidents.update(active)
            for incident_id in active:
                self._cancellation_reasons[incident_id] = reason
            self._resilience_events.append({
                "event_type": "GLOBAL_KILL_SWITCH_ENGAGED",
                "incident_ids": active,
                "reason": reason,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            })
            return active

    @property
    def kill_switch_engaged(self) -> bool:
        with self._lock:
            return self._kill_switch_engaged

    def is_cancelled(self, incident_id: str) -> bool:
        with self._lock:
            return incident_id in self._cancelled_incidents

    def check_cancellation(self, incident_id: str) -> None:
        """Check if incident was cancelled via kill switch. Raises IncidentCancelledError if so."""
        with self._lock:
            if incident_id in self._cancelled_incidents:
                reason = self._cancellation_reasons.get(incident_id, "Cancelled by operator")
                raise IncidentCancelledError(f"Incident {incident_id} cancelled: {reason}")

    def check_preflight(self, incident_id: str, target_tool: str) -> None:
        """Perform comprehensive pre-flight check before executing a tool call."""
        self.check_cancellation(incident_id)
        self.check_deadline(incident_id)
        if self.circuit_breaker.is_open(target_tool):
            event = {
                "event_type": "CIRCUIT_BREAKER_BLOCKED",
                "incident_id": incident_id,
                "target_tool": target_tool,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            with self._lock:
                self._resilience_events.append(event)
            raise CircuitOpenError(target_tool, f"Circuit breaker open for {target_tool}")
        self.check_and_increment_budget(incident_id)

    def record_tool_result(self, target_tool: str, status: str) -> None:
        """Record outcome of tool execution to adjust circuit breaker."""
        if status in ("ok", "partial"):
            self.circuit_breaker.record_success(target_tool)
        elif status in ("unavailable", "timeout", "error"):
            tripped = self.circuit_breaker.record_failure(target_tool)
            if tripped:
                event = {
                    "event_type": "CIRCUIT_BREAKER_TRIPPED",
                    "target_tool": target_tool,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                }
                with self._lock:
                    self._resilience_events.append(event)

    def record_dlq_event(
        self,
        incident_id: str,
        reason_code: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Enqueue incident into DLQ and record audit event."""
        self.dlq.enqueue(incident_id, reason_code, error_message, context)
        event = {
            "event_type": "DLQ_ENQUEUED",
            "incident_id": incident_id,
            "reason_code": reason_code,
            "error_message": error_message,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        with self._lock:
            self._resilience_events.append(event)

    def get_events(self) -> List[Dict[str, Any]]:
        """Return all resilience events (deadlines, budgets, circuit trips, DLQ) for evidence packaging."""
        with self._lock:
            return list(self._resilience_events)
