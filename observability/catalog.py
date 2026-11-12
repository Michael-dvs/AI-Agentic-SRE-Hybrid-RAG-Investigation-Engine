"""Service Catalog and Observed Dependency Graph builder for Chapter C05 (FR-OBS-006, AT-016).

Produces C02-compliant `service-catalog.v1.schema.json` and `dependency-edge.v1.schema.json`
records, dynamically reconciling declared service topology with observed trace spans and
performing downstream-to-upstream cascade attribution.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from services.common.telemetry import utc_now_iso

DECLARED_EDGE_SPECS: list[dict[str, str]] = [
    {
        "edge_id": "edge-gw-auth",
        "from_service_id": "api-gateway",
        "to_service_id": "auth-service",
        "relation_type": "sync_http",
    },
    {
        "edge_id": "edge-gw-tx",
        "from_service_id": "api-gateway",
        "to_service_id": "transaction-service",
        "relation_type": "sync_http",
    },
    {
        "edge_id": "edge-tx-ledger",
        "from_service_id": "transaction-service",
        "to_service_id": "ledger-service",
        "relation_type": "sync_http",
    },
    {
        "edge_id": "edge-ledger-db",
        "from_service_id": "ledger-service",
        "to_service_id": "db-dummy",
        "relation_type": "storage_call",
    },
    {
        "edge_id": "edge-tx-notif",
        "from_service_id": "transaction-service",
        "to_service_id": "notification-service",
        "relation_type": "async_queue",
    },
]


def build_db_dummy_catalog_entry(
    environment: str = "lab",
    application: str = "sre-simulation-poc",
    build_version: str = "0.1.0-sim",
    owner_ref: str = "project-initiator-michael",
) -> dict[str, Any]:
    """Return a service-catalog.v1.schema.json compliant entry for the PostgreSQL storage node."""
    return {
        "schema_version": "1.0",
        "service_id": "db-dummy",
        "service.name": "db-dummy",
        "environment": environment,
        "application": application,
        "component": "storage_dummy",
        "instance_id": "postgres-ledger-lab-01",
        "build_version": build_version,
        "owner_ref": owner_ref,
        "dependency_refs": [],
        "health_endpoints": {
            "liveness_path": "/health/live",
            "readiness_path": "/health/ready",
            "metrics_path": "/metrics",
        },
        "updated_at": utc_now_iso(),
    }


def build_default_service_catalogs(
    environment: str = "lab",
    application: str = "sre-simulation-poc",
    build_version: str = "0.1.0-sim",
    owner_ref: str = "project-initiator-michael",
) -> list[dict[str, Any]]:
    """Build all 6 catalog entries (5 FastAPI microservices + db-dummy storage node)."""
    now = utc_now_iso()
    specs = [
        ("api-gateway", "gateway", ["auth-service", "transaction-service"]),
        ("auth-service", "auth", []),
        ("transaction-service", "transaction", ["ledger-service", "notification-service"]),
        ("ledger-service", "ledger", ["db-dummy"]),
        ("notification-service", "notification_worker", []),
    ]
    entries: list[dict[str, Any]] = []
    for svc_id, comp, deps in specs:
        entries.append(
            {
                "schema_version": "1.0",
                "service_id": svc_id,
                "service.name": svc_id,
                "environment": environment,
                "application": application,
                "component": comp,
                "instance_id": f"{svc_id}-lab-01",
                "build_version": build_version,
                "owner_ref": owner_ref,
                "dependency_refs": deps,
                "health_endpoints": {
                    "liveness_path": "/health/live",
                    "readiness_path": "/health/ready",
                    "metrics_path": "/metrics",
                },
                "updated_at": now,
            }
        )
    entries.append(
        build_db_dummy_catalog_entry(
            environment=environment,
            application=application,
            build_version=build_version,
            owner_ref=owner_ref,
        )
    )
    return entries


def _parse_iso_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        cleaned = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        return datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        return None


def build_observed_dependency_graph(
    spans: list[dict[str, Any]],
    logs: list[dict[str, Any]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    catalogs: list[dict[str, Any]] | None = None,
    environment: str = "lab",
    deployment_version: str = "0.1.0-sim",
    stale_threshold_seconds: float = 300.0,
    reference_time_iso: str | None = None,
) -> dict[str, Any]:
    """Reconcile declared service catalog topology with observed distributed trace spans.

    Returns:
      - `services`: list of valid `service-catalog.v1.schema.json` objects
      - `dependency_edges`: list of valid `dependency-edge.v1.schema.json` objects
      - `edge_telemetry`: per-edge observed call counts, error counts, p95 latency, and error codes
      - `cascade_analysis`: origin dependency vs upstream impact attribution (AT-016)
    """
    now_iso = reference_time_iso or utc_now_iso()
    now_epoch = _parse_iso_epoch(now_iso) or datetime.now(timezone.utc).timestamp()
    service_catalogs = list(catalogs) if catalogs else build_default_service_catalogs(
        environment=environment,
        build_version=deployment_version,
    )
    existing_ids = {c["service_id"] for c in service_catalogs}
    if "db-dummy" not in existing_ids:
        service_catalogs.append(
            build_db_dummy_catalog_entry(
                environment=environment,
                build_version=deployment_version,
            )
        )

    # Index spans by (from_service_id, to_service_id) and also infer parent->child service transitions
    span_by_id: dict[str, dict[str, Any]] = {
        s["span_id"]: s for s in spans if s.get("span_id")
    }
    edge_spans: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for sp in spans:
        from_svc = sp.get("from_service_id")
        to_svc = sp.get("to_service_id") or sp.get("service_id")
        if not from_svc and sp.get("parent_span_id"):
            parent_sp = span_by_id.get(sp["parent_span_id"])
            if parent_sp:
                from_svc = parent_sp.get("service_id")
        if from_svc and to_svc and from_svc != to_svc:
            edge_spans.setdefault((from_svc, to_svc), []).append(sp)

    # Index error logs by service_id
    logs_by_service: dict[str, list[dict[str, Any]]] = {}
    for lg in logs or []:
        sid = lg.get("service_id") or lg.get("service.name")
        if sid:
            logs_by_service.setdefault(sid, []).append(lg)

    # Index RED metrics by (service_id, metric_enum)
    red_by_service: dict[str, dict[str, float]] = {}
    for m in metrics or []:
        sid = m.get("service_id") or m.get("service.name")
        m_enum = m.get("metric_enum")
        if sid and m_enum:
            red_by_service.setdefault(sid, {})[m_enum] = float(m.get("value", 0.0))

    dependency_edges: list[dict[str, Any]] = []
    edge_telemetry: dict[str, dict[str, Any]] = {}

    for spec in DECLARED_EDGE_SPECS:
        edge_id = spec["edge_id"]
        from_svc = spec["from_service_id"]
        to_svc = spec["to_service_id"]
        rel_type = spec["relation_type"]
        matched = edge_spans.get((from_svc, to_svc), [])

        if matched:
            source_kind = "trace_observed"
            latest_ts = max(
                (s.get("end_time") or s.get("start_time") or now_iso) for s in matched
            )
            latest_epoch = _parse_iso_epoch(latest_ts)
            is_fresh = (
                True
                if latest_epoch is None
                else (now_epoch - latest_epoch) <= stale_threshold_seconds
            )
            freshness_status = "fresh" if is_fresh else "stale"
            confidence = round(min(1.0, 0.85 + 0.03 * min(len(matched), 5)), 2)

            durations = sorted(float(s.get("duration_ms", 0.0)) for s in matched)
            p95_idx = max(0, min(len(durations) - 1, math.ceil(0.95 * len(durations)) - 1))
            p95_ms = round(durations[p95_idx], 3)
            err_spans = [
                s
                for s in matched
                if s.get("status") == "error"
                or int(s.get("http_status_code") or 200) >= 500
                or (
                    s.get("error_code")
                    and str(s.get("error_code")).startswith(("ERR_", "WARN_DB_SLOW"))
                )
            ]
            err_codes = sorted(
                {str(s["error_code"]) for s in matched if s.get("error_code")}
            )
            sample_trace_id = matched[-1].get("trace_id")
            source_ref = (
                f"http://tempo:3200/api/traces/{sample_trace_id}"
                if sample_trace_id
                else "http://tempo:3200/api/search"
            )
        else:
            source_kind = "catalog_declared"
            latest_ts = now_iso
            freshness_status = "stale" if spans else "fresh"
            confidence = 0.70 if spans else 0.90
            p95_ms = 0.0
            err_spans = []
            err_codes = []
            source_ref = "http://api-gateway:8000/api/v1/topology"

        # Check whether error or severe latency propagated across this edge
        target_red = red_by_service.get(to_svc, {})
        caller_red = red_by_service.get(from_svc, {})
        target_logs = logs_by_service.get(to_svc, [])
        target_log_errors = [
            lg
            for lg in target_logs
            if lg.get("severity") in ("ERROR", "CRITICAL")
            or lg.get("error_code")
            in (
                "WARN_DB_SLOW_QUERY",
                "WARN_QUEUE_CONSUMER_LAG",
                "ERR_DEPENDENCY_UNAVAILABLE",
                "ERR_CONNECTION_POOL_EXHAUSTED",
            )
        ]

        error_propagation = (
            bool(err_spans)
            or p95_ms >= 250.0
            or (
                (
                    target_red.get("error_rate", 0.0) > 0.0
                    or target_red.get("latency_p95", 0.0) >= 250.0
                    or bool(target_log_errors)
                )
                and (
                    caller_red.get("error_rate", 0.0) > 0.0
                    or caller_red.get("latency_p95", 0.0) >= 250.0
                )
            )
        )
        if to_svc == "db-dummy" and (
            err_spans
            or any(
                lg.get("error_code")
                in (
                    "WARN_DB_SLOW_QUERY",
                    "ERR_DEPENDENCY_UNAVAILABLE",
                    "ERR_CONNECTION_POOL_EXHAUSTED",
                    "ERR_DB_UNAVAILABLE",
                )
                for lg in logs_by_service.get("ledger-service", [])
            )
        ):
            error_propagation = True

        edge_record = {
            "schema_version": "1.0",
            "edge_id": edge_id,
            "from_service_id": from_svc,
            "to_service_id": to_svc,
            "environment": environment,
            "deployment_version": deployment_version,
            "relation_type": rel_type,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "observed_at": latest_ts,
            "freshness_status": freshness_status,
            "confidence": confidence,
            "error_propagation_observed": error_propagation,
        }
        dependency_edges.append(edge_record)
        edge_telemetry[edge_id] = {
            "edge_id": edge_id,
            "from_service_id": from_svc,
            "to_service_id": to_svc,
            "observed_span_count": len(matched),
            "error_span_count": len(err_spans),
            "p95_duration_ms": p95_ms,
            "observed_error_codes": err_codes,
            "error_propagation_observed": error_propagation,
        }

    cascade = analyze_dependency_cascade(
        dependency_edges=dependency_edges,
        edge_telemetry=edge_telemetry,
        red_by_service=red_by_service,
        logs_by_service=logs_by_service,
    )

    return {
        "schema_version": "1.0",
        "observed_at": now_iso,
        "services": service_catalogs,
        "dependency_edges": dependency_edges,
        "edge_telemetry": edge_telemetry,
        "cascade_analysis": cascade,
    }


def analyze_dependency_cascade(
    dependency_edges: list[dict[str, Any]],
    edge_telemetry: dict[str, dict[str, Any]],
    red_by_service: dict[str, dict[str, float]],
    logs_by_service: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Identify downstream root/origin dependency vs upstream impacted callers (AT-016)."""
    propagating_edges = [
        e for e in dependency_edges if e.get("error_propagation_observed") is True
    ]
    if not propagating_edges:
        return {
            "cascade_detected": False,
            "origin_dependency_id": None,
            "primary_fault_service_id": None,
            "upstream_impacted_services": [],
            "propagation_path": [],
            "propagating_edge_ids": [],
        }

    # Build directed adjacency for propagating edges (caller -> callee)
    callees_by_caller: dict[str, list[str]] = {}
    callers_by_callee: dict[str, list[str]] = {}
    affected_nodes: set[str] = set()
    for e in propagating_edges:
        u = e["from_service_id"]
        v = e["to_service_id"]
        callees_by_caller.setdefault(u, []).append(v)
        callers_by_callee.setdefault(v, []).append(u)
        affected_nodes.add(u)
        affected_nodes.add(v)

    # Topological depth from entry point (api-gateway -> transaction-service -> ledger-service -> db-dummy)
    topo_rank = {
        "api-gateway": 0,
        "auth-service": 1,
        "transaction-service": 1,
        "notification-service": 2,
        "ledger-service": 2,
        "db-dummy": 3,
    }
    ordered_affected = sorted(affected_nodes, key=lambda n: topo_rank.get(n, 0))
    origin_node = ordered_affected[-1]
    microservices_only = [n for n in ordered_affected if n != "db-dummy"]
    primary_service = microservices_only[-1] if microservices_only else origin_node
    upstream_impacted = [
        n for n in reversed(microservices_only) if n != primary_service
    ]

    return {
        "cascade_detected": len(ordered_affected) >= 2,
        "origin_dependency_id": origin_node,
        "primary_fault_service_id": primary_service,
        "upstream_impacted_services": upstream_impacted,
        "propagation_path": list(reversed(ordered_affected)),
        "propagating_edge_ids": [e["edge_id"] for e in propagating_edges],
    }
