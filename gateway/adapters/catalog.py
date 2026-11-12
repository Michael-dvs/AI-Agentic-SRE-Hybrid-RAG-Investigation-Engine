"""Read-only Service Dependencies Adapter querying Service Catalog (C09, MCP-01, MCP-02, ADR-S05)."""

from __future__ import annotations

import collections
from typing import Any, Optional

from gateway.adapters.base import (
    BaseTelemetryAdapter,
    ForbiddenScopeError,
    LimitExceededError,
    SchemaInvalidError,
    ServiceNotFoundError,
    TelemetryResponseEnvelope,
    ToolNotAllowedError,
    check_ground_truth_isolation,
    check_mutation_attempt,
)
from gateway.adapters.metrics import KNOWN_SERVICES
from observability.catalog import (
    DECLARED_EDGE_SPECS,
    build_default_service_catalogs,
)
from services.common.telemetry import utc_now_iso


class CatalogAdapter(BaseTelemetryAdapter):
    """Read-only telemetry adapter for Service Dependencies and Topology Graph."""

    tool_name = "get_service_dependencies"
    default_source_ref = "catalog:in-memory"
    max_depth_cap = 3

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: Any = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
        max_depth_cap: int = 3,
    ) -> None:
        super().__init__(
            base_url=base_url,
            client=client,
            sanitizer=sanitizer,
            max_window_seconds=max_window_seconds,
            timeout_seconds=timeout_seconds,
        )
        self.max_depth_cap = max_depth_cap

    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute parameterized read-only dependency graph traversal."""
        now_z = utc_now_iso()

        # Step A: Mutation & Ground Truth check (MCP-01, AT-005, AT-008)
        try:
            check_mutation_attempt(arguments)
            check_ground_truth_isolation(arguments)
        except ToolNotAllowedError:
            return self._error_envelope(
                error_code="TOOL_NOT_ALLOWED",
                message="Mutation actions are prohibited",
                status="rejected",
            )
        except ForbiddenScopeError:
            return self._error_envelope(
                error_code="FORBIDDEN_SCOPE",
                message="Access to ground truth is forbidden",
                status="rejected",
            )

        # Step B: Parameter extraction
        service_id = arguments.get("service_id")
        raw_max_depth = arguments.get("max_depth", 2)
        reference_time = arguments.get("reference_time", now_z)

        # Step C: Validate Service ID
        if not service_id or service_id not in KNOWN_SERVICES:
            return self._error_envelope(
                error_code="SERVICE_NOT_FOUND",
                message=f"Service {service_id!r} not registered in service catalog",
                status="rejected",
            )

        # Step D: Validate max_depth limits (ADR-S05: hard cap = 3)
        try:
            max_depth = int(raw_max_depth)
        except (ValueError, TypeError):
            return self._error_envelope(
                error_code="SCHEMA_INVALID",
                message=f"Invalid max_depth value: {raw_max_depth!r}",
                status="rejected",
            )

        if max_depth < 1:
            return self._error_envelope(
                error_code="SCHEMA_INVALID",
                message=f"max_depth must be at least 1, got {max_depth}",
                status="rejected",
            )

        if max_depth > self.max_depth_cap:
            return self._error_envelope(
                error_code="LIMIT_EXCEEDED",
                message=f"max_depth {max_depth} exceeds policy cap of {self.max_depth_cap} (ADR-S05)",
                status="rejected",
            )

        # Step E: Graph Traversal (Downstream and Upstream BFS up to max_depth)
        downstream_deps: set[str] = set()
        upstream_deps: set[str] = set()
        collected_edges: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()

        # Downstream BFS (who does this service call?)
        queue = collections.deque([(service_id, 0)])
        visited_down = {service_id}
        while queue:
            curr_svc, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in DECLARED_EDGE_SPECS:
                if edge["from_service_id"] == curr_svc:
                    target = edge["to_service_id"]
                    downstream_deps.add(target)
                    if edge["edge_id"] not in seen_edge_ids:
                        seen_edge_ids.add(edge["edge_id"])
                        collected_edges.append({
                            "edge_id": edge["edge_id"],
                            "source": edge["from_service_id"],
                            "target": edge["to_service_id"],
                            "kind": "catalog_declared",
                            "relation_type": edge.get("relation_type", "sync_http"),
                            "status": "fresh",
                            "depth": depth + 1,
                        })
                    if target not in visited_down:
                        visited_down.add(target)
                        queue.append((target, depth + 1))

        # Upstream BFS (who calls this service?)
        queue = collections.deque([(service_id, 0)])
        visited_up = {service_id}
        while queue:
            curr_svc, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in DECLARED_EDGE_SPECS:
                if edge["to_service_id"] == curr_svc:
                    source = edge["from_service_id"]
                    upstream_deps.add(source)
                    if edge["edge_id"] not in seen_edge_ids:
                        seen_edge_ids.add(edge["edge_id"])
                        collected_edges.append({
                            "edge_id": edge["edge_id"],
                            "source": edge["from_service_id"],
                            "target": edge["to_service_id"],
                            "kind": "catalog_declared",
                            "relation_type": edge.get("relation_type", "sync_http"),
                            "status": "fresh",
                            "depth": depth + 1,
                        })
                    if source not in visited_up:
                        visited_up.add(source)
                        queue.append((source, depth + 1))

        # Sort edges deterministically
        collected_edges.sort(key=lambda e: e["edge_id"])

        payload = {
            "service_id": service_id,
            "max_depth": max_depth,
            "upstream_dependencies": sorted(upstream_deps),
            "downstream_dependencies": sorted(downstream_deps),
            "records": collected_edges,
            "edges": collected_edges,
        }

        # Step F: Pre-sink SEC-03 Sanitization
        sanitized_payload, _ = self.sanitizer.sanitize_object(payload)

        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self._get_source_ref(),
            observed_at=now_z,
            query_window={
                "start": reference_time,
                "end": reference_time,
                "duration_seconds": 0.0,
            },
            data_quality="complete",
            truncated=False,
            sanitized=True,
            error_code=None,
            data=sanitized_payload.get("records", []),
            status="ok",
        )
