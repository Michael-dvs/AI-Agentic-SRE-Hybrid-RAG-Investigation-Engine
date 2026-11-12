"""Bounded dependency correlation; topology suggests candidates, never proves causality."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable

from observability.catalog import DECLARED_EDGE_SPECS, build_default_service_catalogs


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


class DependencyCorrelator:
    """Correlate only directed dependency paths within a bounded time window.

    Declared edges have no observation timestamp and are marked stale, rather
    than presenting static topology as an observed fresh dependency.
    """

    def __init__(self, edges: list[dict[str, Any]] | None = None,
                 correlation_window_seconds: float = 60.0,
                 audit: Callable[[dict[str, Any]], None] | None = None) -> None:
        if correlation_window_seconds <= 0:
            raise ValueError("correlation window must be positive")
        self.window = correlation_window_seconds
        self.audit = audit if audit is not None else lambda event: logging.getLogger(__name__).warning("%s", json.dumps(event, sort_keys=True))
        self.edges = [dict(e) for e in (DECLARED_EDGE_SPECS if edges is None else edges)]
        self.services = {s["service_id"] for s in build_default_service_catalogs()}

    def _edge(self, edge: dict[str, Any], reference_time: str) -> dict[str, Any]:
        observed = edge.get("observed_at")
        fresh = False
        if observed:
            age = (_time(reference_time) - _time(observed)).total_seconds()
            fresh = 0 <= age <= 300
        return {"edge_id": edge.get("edge_id"),
                "from_service_id": edge["from_service_id"],
                "to_service_id": edge["to_service_id"],
                "relation_type": edge.get("relation_type"),
                "source_kind": edge.get("source_kind", "catalog_declared"),
                "observed_at": observed,
                "edge_freshness": "fresh" if fresh else "stale"}

    def build_impact_graph(self, primary_service: str, reference_time: str,
                           max_depth: int = 2) -> dict[str, Any]:
        _time(reference_time)
        if primary_service not in self.services:
            raise ValueError("SERVICE_UNMAPPED")
        if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 1 <= max_depth <= 3:
            raise ValueError("LIMIT_EXCEEDED")
        edges = [self._edge(e, reference_time) for e in self.edges]
        selected: dict[str, dict[str, Any]] = {}
        def traverse(reverse: bool) -> list[str]:
            seen = {primary_service}
            queue = deque([(primary_service, 0)])
            while queue:
                current, depth = queue.popleft()
                if depth >= max_depth:
                    continue
                for edge in edges:
                    source, target = edge["from_service_id"], edge["to_service_id"]
                    if (target if reverse else source) != current:
                        continue
                    neighbor = source if reverse else target
                    selected[str(edge["edge_id"])] = edge
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append((neighbor, depth + 1))
            return sorted(seen - {primary_service})
        upstream = traverse(True)
        downstream = traverse(False)
        return {"primary_service": primary_service, "reference_time": reference_time,
                "max_depth": max_depth, "upstream_callers": upstream,
                "downstream_dependencies": downstream,
                "edges": sorted(selected.values(), key=lambda e: str(e["edge_id"])),
                "uncertainty": "Topology alone does not establish causality; stale edges are unconfirmed."}

    def _path(self, source: str, target: str, reference_time: str | None = None) -> bool:
        queue = deque([(source, 0)])
        visited = {source}
        while queue:
            current, depth = queue.popleft()
            if current == target and depth:
                return True
            if depth == 3:
                continue
            for edge in self.edges:
                if reference_time is not None and self._edge(edge, reference_time)["edge_freshness"] != "fresh":
                    continue
                if edge["from_service_id"] == current and edge["to_service_id"] not in visited:
                    neighbor = edge["to_service_id"]
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return False

    def correlate_incidents(self, active_alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Require pairwise direction, environment and time compatibility: no
        # transitive bridge can silently merge independent incidents.
        alerts = sorted(active_alerts, key=lambda a: (a["event_time"], a["service_id"], a.get("incident_id", "")))
        groups: list[list[dict[str, Any]]] = []
        for alert in alerts:
            if alert["service_id"] not in self.services:
                raise ValueError("SERVICE_UNMAPPED")
            timestamp = _time(alert["event_time"])
            def compatible(other: dict[str, Any]) -> bool:
                a, b = alert["service_id"], other["service_id"]
                related = self._path(a, b) or self._path(b, a)
                shared_trace = bool(alert.get("trace_id")) and alert.get("trace_id") == other.get("trace_id")
                reference = max(alert["event_time"], other["event_time"])
                observed_path = self._path(a, b, reference) or self._path(b, a, reference)
                return (alert["environment"] == other["environment"]
                        and abs((timestamp - _time(other["event_time"])).total_seconds()) <= self.window
                        and (a == b or (related and (shared_trace or observed_path))))
            group = next((g for g in groups if all(compatible(item) for item in g)), None)
            if group is None:
                groups.append([alert])
                if len(groups) > 1 and self.audit:
                    self.audit({"event": "correlation_split", "incident_id": alert.get("incident_id"),
                                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
            else:
                group.append(alert)
        results = []
        for group in groups:
            services = sorted({a["service_id"] for a in group})
            origins = [s for s in services if not any(self._path(s, other) for other in services if other != s)]
            reference = max(a["event_time"] for a in group)
            results.append({"incident_ids": [a.get("incident_id") for a in group],
                            "services": services, "suspected_origins": origins,
                            "downstream_symptoms": sorted(set(services) - set(origins)),
                            "impact_graph": self.build_impact_graph((origins or services)[0], reference, 3),
                            "status": "INCONCLUSIVE"})
        return results
