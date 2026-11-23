"""Gateway configuration, token registries, and semantic policy limits (ADR-S03, ADR-S05, C08)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set


@dataclass
class GatewayPolicyConfig:
    policy_version: str = "1.0.0"
    max_window_seconds: int = 3600  # Strict cap: queries > 3600s rejected (MCP-02)
    max_points: int = 1000          # Maximum data points in metrics query (ADR-S05)
    max_hits: int = 500             # Maximum log hits (ADR-S05)
    max_dependency_depth: int = 3   # Maximum BFS/DFS depth in service catalog (ADR-S05)
    max_tool_calls_per_incident: int = 30
    
    # Authorized read-only tools
    allowed_tools: Set[str] = field(default_factory=lambda: {
        "get_service_metrics",
        "search_error_logs",
        "get_trace_summary",
        "get_service_dependencies",
        "retrieve_runbooks",
        "get_apm_health",
    })

    # Mutation / prohibited tools strictly rejected (MCP-01, AT-005)
    prohibited_tools: Set[str] = field(default_factory=lambda: {
        "restart_service",
        "deploy_service",
        "deploy_patch",
        "scale_deployment",
        "execute_shell",
        "run_shell",
        "run_sql",
        "execute_sql",
        "raw_promql_query",
        "read_ground_truth",
        "write_file",
        "remediate_incident",
    })

    # Recognized lab environments
    allowed_environments: Set[str] = field(default_factory=lambda: {
        "lab",
        "sim-staging",
        "sim-prod-like",
    })

    # Known lab microservices
    allowed_services: Set[str] = field(default_factory=lambda: {
        "api-gateway",
        "auth-service",
        "transaction-service",
        "ledger-service",
        "notification-service",
        "db-dummy",
        "rabbitmq-dummy",
    })

    # Blocked paths and keywords for Ground Truth isolation (AT-008, RULE-002)
    blocked_gt_targets: Set[str] = field(default_factory=lambda: {
        "restricted",
        "gt_registry",
        "ground_truth",
        "holdout",
        "fault_harness",
        "scenario_id",
        "injected_fault",
    })


# Synthetic credential store for local simulation (ADR-S03)
SYNTHETIC_BEARER_TOKENS = {
    "sre-sim-coord-token-secret-2026": {
        "principal_id": "principal:investigator-coord",
        "actor_ref": "principal_investigator",
        "default_groups": ["sre-core-l1", "l1-operator"],
        "description": "Agent coordinator and investigator principal",
    },
    "sre-sim-reviewer-token-secret-2026": {
        "principal_id": "principal:human-reviewer",
        "actor_ref": "principal_reviewer",
        "default_groups": ["sre-core-l2", "l2-investigator", "security-admin"],
        "description": "L1/L2 Human Reviewer principal",
    },
    "sre-sim-harness-token-secret-2026": {
        "principal_id": "principal:operator-harness",
        "actor_ref": "principal_fault_harness",
        "default_groups": ["sre-infra-admin"],
        "description": "Fault injection harness operator (isolated from tools)",
    },
    "sre-sim-gateway-token-secret-2026": {
        "principal_id": "principal:mcp-policy-gateway",
        "actor_ref": "principal_tool_gateway",
        "default_groups": ["system"],
        "description": "Internal gateway component principal",
    },
    "sre-sim-evaluator-token-secret-2026": {
        "principal_id": "principal:offline-evaluator",
        "actor_ref": "principal_evaluator",
        "default_groups": ["eval-admin"],
        "description": "Offline evaluator principal",
    },
}

