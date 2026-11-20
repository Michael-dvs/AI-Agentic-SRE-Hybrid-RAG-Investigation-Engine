"""Bounded, in-process alert deduplication for the synthetic lab.

The registry TTL is measured from the most recent accepted hit using a monotonic
clock; event timestamps determine fingerprint buckets, not registry expiry.
The queue retains accepted work until it is dequeued, even if its registry entry
expires. This component does not infer a common root cause from a fingerprint.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Mapping


_LOG = logging.getLogger(__name__)


def _audit_to_log(event: dict[str, Any]) -> None:
    _LOG.warning("%s", json.dumps(event, sort_keys=True))


def _event_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event_time must include a timezone")
    return parsed.astimezone(timezone.utc)


def compute_fingerprint(alert: Mapping[str, Any], window_bucket_seconds: int = 60) -> str:
    """Return SHA-256 of service:environment:alert_type:error_code:UTC bucket.

    Input must already have passed intake validation and time normalization.
    A null error_code is represented as an empty field.
    """
    if not isinstance(window_bucket_seconds, int) or isinstance(window_bucket_seconds, bool) or window_bucket_seconds <= 0:
        raise ValueError("window_bucket_seconds must be a positive integer")
    bucket = int(_event_time(alert["event_time"]).timestamp() // window_bucket_seconds)
    parts = (alert["service_id"], alert["environment"], alert["alert_type"], alert.get("error_code") or "", str(bucket))
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


class AlertDeduplicator:
    """Thread-safe, bounded dedup registry and FIFO work queue.

    ``process(alert)`` returns ``{"action": ..., "incident": ...}``: action is
    ``create``, ``merge``, ``split`` (same fingerprint after TTL expiry), or
    ``backpressure``. The incident is a detached snapshot, or None when rejected.
    Only newly created/split incidents enter the queue; duplicates merge even when
    the queue is full. ``dequeue()`` returns the next snapshot or None if empty.

    The audit sink is a callable accepting one structured dictionary; it must not
    call back into this instance. Sink errors propagate before the decision mutates
    internal state. A rejected admission changes no registry or queue state.
    """

    compute_fingerprint = staticmethod(compute_fingerprint)

    def __init__(
        self,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        ttl_seconds: float = 60,
        max_queue_size: int = 500,
        max_registry_size: int = 500,
        window_bucket_seconds: int = 60,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not isinstance(max_queue_size, int) or isinstance(max_queue_size, bool) or not 1 <= max_queue_size <= 500:
            raise ValueError("max_queue_size must be between 1 and 500")
        if not isinstance(max_registry_size, int) or isinstance(max_registry_size, bool) or max_registry_size < 1:
            raise ValueError("max_registry_size must be positive")
        if not isinstance(window_bucket_seconds, int) or isinstance(window_bucket_seconds, bool) or window_bucket_seconds <= 0:
            raise ValueError("window_bucket_seconds must be a positive integer")
        self._audit_sink = audit_sink if audit_sink is not None else _audit_to_log
        self.ttl_seconds = ttl_seconds
        self.max_queue_size = max_queue_size
        self.max_registry_size = max_registry_size
        self.window_bucket_seconds = window_bucket_seconds
        self._registry: dict[str, tuple[dict[str, Any], float]] = {}
        self._queue: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()

    def process(self, alert: Mapping[str, Any]) -> dict[str, Any]:
        result, _ = self.admit(alert, lambda incident, active: None)
        return result

    def admit(
        self,
        alert: Mapping[str, Any],
        correlate: Callable[[dict[str, Any], list[dict[str, Any]]], Any],
    ) -> tuple[dict[str, Any], Any]:
        """Correlate a proposed admission under the lock before committing it.

        The callback receives detached snapshots and must not call this registry.
        A callback or audit exception leaves the registry and queue unchanged.
        """
        fingerprint = compute_fingerprint(alert, self.window_bucket_seconds)
        with self._lock:
            now = time.monotonic()
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            entry = self._registry.get(fingerprint)
            if entry is not None and now - entry[1] < self.ttl_seconds:
                incident = entry[0].copy()
                incident["last_seen_at"] = timestamp
                incident["hit_count"] += 1
                active = [item.copy() for key, (item, seen) in self._registry.items()
                          if key != fingerprint and now - seen < self.ttl_seconds]
                active.append(incident.copy())
                correlation = correlate(incident.copy(), active)
                now = time.monotonic()
                self._audit_sink({"action": "merge", "incident_id": incident["incident_id"], "fingerprint": fingerprint, "at": timestamp, "reason": "matching_fingerprint"})
                entry[0].update(incident)
                self._registry[fingerprint] = (entry[0], now)
                return {"action": "merge", "incident": incident.copy()}, correlation

            expired = [key for key, (_, seen) in self._registry.items() if now - seen >= self.ttl_seconds]
            if len(self._queue) >= self.max_queue_size or len(self._registry) - len(expired) >= self.max_registry_size:
                self._audit_sink({"action": "backpressure", "incident_id": None, "fingerprint": fingerprint, "at": timestamp, "reason": "capacity_exhausted"})
                return {"action": "backpressure", "incident": None}, None

            action = "split" if entry is not None else "create"
            incident = {
                "incident_id": f"inc-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}",
                "fingerprint": fingerprint,
                "service_id": alert["service_id"],
                "environment": alert["environment"],
                "alert_type": alert["alert_type"],
                "error_code": alert.get("error_code"),
                "trace_id": alert.get("trace_id"),
                "event_time": alert["event_time"],
                "window_start": alert["window_start"],
                "window_end": alert["window_end"],
                "first_seen_at": timestamp,
                "last_seen_at": timestamp,
                "hit_count": 1,
                "status": "ACTIVE",
            }
            active = [item.copy() for item, seen in self._registry.values()
                      if now - seen < self.ttl_seconds]
            active.append(incident.copy())
            correlation = correlate(incident.copy(), active)
            now = time.monotonic()
            self._audit_sink({"action": action, "incident_id": incident["incident_id"], "fingerprint": fingerprint, "at": timestamp, "reason": "ttl_expired" if action == "split" else "new_fingerprint"})
            for key in expired:
                del self._registry[key]
            self._registry[fingerprint] = (incident, now)
            self._queue.append(incident)
            return {"action": action, "incident": incident.copy()}, correlation

    def active_alerts(self) -> list[dict[str, Any]]:
        """Return bounded active incident snapshots for correlation."""
        with self._lock:
            now = time.monotonic()
            return [incident.copy() for incident, seen in self._registry.values()
                    if now - seen < self.ttl_seconds]

    def dequeue(self) -> dict[str, Any] | None:
        """Remove and return the oldest pending incident snapshot, or None."""
        with self._lock:
            return self._queue.popleft().copy() if self._queue else None

    def queue_size(self) -> int:
        """Return the current bounded work queue depth."""
        with self._lock:
            return len(self._queue)
