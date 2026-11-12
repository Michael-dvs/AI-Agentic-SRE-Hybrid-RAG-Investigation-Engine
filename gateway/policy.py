"""Authenticated Read-Only Policy Gateway implementing the 8-Step Deterministic Enforcement Pipeline (MCP-01, MCP-02, SEC-01, SEC-03, AT-005, AT-008, C08)."""

from __future__ import annotations

import datetime
import json
import pathlib
import uuid
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from gateway.auth import AuthenticatedContext, AuthenticationError, Authenticator
from gateway.audit import SecurityAuditLogger
from gateway.config import GatewayPolicyConfig
from gateway.dispatcher import ToolDispatcher
from gateway.sanitizer import DeterministicSanitizer, SanitizerFailureError

_CONTRACT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)

# Load JSON schema validators
_SCHEMAS: dict[str, Any] = {}
_VALIDATORS: dict[str, Draft202012Validator] = {}

_SCHEMA_FILES = {
    "tool_result": "tool-result.v1.schema.json",
    "get_service_metrics": "metrics-request.v1.schema.json",
    "search_error_logs": "logs-request.v1.schema.json",
    "get_trace_summary": "trace-request.v1.schema.json",
    "get_service_dependencies": "dependencies-request.v1.schema.json",
    "retrieve_runbooks": "retrieval-request.v1.schema.json",
}

for name, fname in _SCHEMA_FILES.items():
    p = _CONTRACT_DIR / fname
    if p.exists():
        s = json.loads(p.read_text(encoding="utf-8"))
        _SCHEMAS[name] = s
        _VALIDATORS[name] = Draft202012Validator(s, format_checker=FormatChecker())


def parse_iso8601_utc(dt_str: str) -> datetime.datetime:
    """Parse ISO-8601 UTC timestamp ending in Z."""
    clean = dt_str.rstrip("Z")
    if "+" in clean:
        clean = clean.split("+")[0]
    dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


class PolicyGateway:
    """Deterministic, authenticated, read-only policy gateway protecting simulation telemetry and knowledge tools."""

    def __init__(
        self,
        policy: GatewayPolicyConfig | None = None,
        audit_logger: SecurityAuditLogger | None = None,
        sanitizer: DeterministicSanitizer | None = None,
        dispatcher: ToolDispatcher | None = None,
    ) -> None:
        self.policy = policy or GatewayPolicyConfig()
        self.authenticator = Authenticator(self.policy)
        self.audit_logger = audit_logger or SecurityAuditLogger()
        self.sanitizer = sanitizer or DeterministicSanitizer()
        self.dispatcher = dispatcher or ToolDispatcher()
        self.tool_call_counters: dict[str, int] = {}  # incident_id -> call count

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        token: str | None,
        incident_id: str | None = None,
        correlation_id: str | None = None,
        override_groups: list[str] | None = None,
        override_services: set[str] | None = None,
        force_sanitizer_failure: bool = False,
    ) -> dict[str, Any]:
        """Execute 8-step deterministic enforcement pipeline for tool invocation."""
        req_id = f"req-{uuid.uuid4().hex[:12]}"
        now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        default_window = {
            "start": arguments.get("start", now_z),
            "end": arguments.get("end", now_z),
        }

        # Helper to construct and validate tool-result envelope
        def _make_tool_envelope(
            status: str,
            error_code: str | None,
            records: list[dict[str, Any]],
            source_ref: str | None = None,
            query_window: dict[str, str] | None = None,
            truncated: bool = False,
            data_quality: str = "complete",
        ) -> dict[str, Any]:
            envelope = {
                "schema_version": "1.0",
                "tool_name": tool_name if tool_name in self.policy.allowed_tools and tool_name != "retrieve_runbooks" else "get_service_metrics",
                "request_id": req_id,
                "status": status,
                "source_ref": source_ref,
                "observed_at": now_z,
                "query_window": query_window or default_window,
                "sampling": {
                    "applied": False,
                    "method": None,
                    "returned_count": len(records),
                    "source_count": len(records),
                },
                "truncated": truncated,
                "data_quality": data_quality,
                "sanitized": True,
                "records": records,
                "error_code": error_code,
            }
            if "tool_result" in _VALIDATORS and tool_name in (
                "get_service_metrics", "search_error_logs", "get_trace_summary", "get_service_dependencies"
            ) and error_code not in ("UNSUPPORTED_SOURCE", "SERVICE_NOT_FOUND", "TIMEOUT"):
                errors = list(_VALIDATORS["tool_result"].iter_errors(envelope))
                if errors:
                    err_msg = "; ".join(e.message for e in errors)
                    raise ValueError(f"Gateway generated invalid tool-result envelope: {err_msg}")
            return envelope

        # -------------------------------------------------------------
        # Step 1 — Authenticate Caller & Bind Trusted Scope
        # -------------------------------------------------------------
        try:
            context = self.authenticator.authenticate(
                token=token,
                incident_id=incident_id,
                override_groups=override_groups,
                override_services=override_services,
            )
        except AuthenticationError as e:
            self.audit_logger.record_event(
                actor_ref="principal_investigator",
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="UNAUTHENTICATED",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="UNAUTHENTICATED", records=[])

        # -------------------------------------------------------------
        # Step 2 — Tool Allowlist & Mutation Check (MCP-01, AT-005)
        # -------------------------------------------------------------
        if tool_name in self.policy.prohibited_tools or tool_name not in self.policy.allowed_tools:
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="TOOL_NOT_ALLOWED",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="TOOL_NOT_ALLOWED", records=[])

        # -------------------------------------------------------------
        # Step 3 — Strict JSON Schema & Format Validation (SEC-02)
        # -------------------------------------------------------------
        validator = _VALIDATORS.get(tool_name)
        if validator is not None:
            schema_errors = list(validator.iter_errors(arguments))
            if schema_errors:
                self.audit_logger.record_event(
                    actor_ref=context.actor_ref,
                    action="TOOL_DENIAL",
                    target_ref=tool_name,
                    result_code="DENY",
                    reason_code="SCHEMA_INVALID",
                    request_payload=arguments,
                    incident_id=incident_id,
                    correlation_id=correlation_id,
                )
                return _make_tool_envelope(status="rejected", error_code="SCHEMA_INVALID", records=[])

        # -------------------------------------------------------------
        # Step 4 — Authorization & Ground Truth Blockade (AT-008, SEC-01)
        # -------------------------------------------------------------
        # A. Ground truth isolation check
        raw_args_str = json.dumps(arguments).lower()
        if any(gt_target in raw_args_str for gt_target in self.policy.blocked_gt_targets):
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="FORBIDDEN_SCOPE",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="FORBIDDEN_SCOPE", records=[])

        # B. Service and environment scope check
        service_id = arguments.get("service_id")
        if service_id and not context.is_service_allowed(service_id):
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="FORBIDDEN_SCOPE",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="FORBIDDEN_SCOPE", records=[])

        env = arguments.get("environment")
        if env and not context.is_environment_allowed(env):
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="FORBIDDEN_SCOPE",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="FORBIDDEN_SCOPE", records=[])

        # -------------------------------------------------------------
        # Step 5 — Semantic Window, Count, Quota & Limits (MCP-02)
        # -------------------------------------------------------------
        # A. Time window check
        if "start" in arguments and "end" in arguments:
            try:
                dt_start = parse_iso8601_utc(arguments["start"])
                dt_end = parse_iso8601_utc(arguments["end"])
                if dt_start >= dt_end:
                    self.audit_logger.record_event(
                        actor_ref=context.actor_ref,
                        action="TOOL_DENIAL",
                        target_ref=tool_name,
                        result_code="DENY",
                        reason_code="INVALID_TIME_RANGE",
                        request_payload=arguments,
                        incident_id=incident_id,
                        correlation_id=correlation_id,
                    )
                    return _make_tool_envelope(status="rejected", error_code="INVALID_TIME_RANGE", records=[])

                window_duration = (dt_end - dt_start).total_seconds()
                # STRICT MCP-02: DO NOT SILENTLY CLAMP. MUST REJECT WITH WINDOW_EXCEEDED
                if window_duration > self.policy.max_window_seconds:
                    self.audit_logger.record_event(
                        actor_ref=context.actor_ref,
                        action="TOOL_DENIAL",
                        target_ref=tool_name,
                        result_code="DENY",
                        reason_code="WINDOW_EXCEEDED",
                        request_payload=arguments,
                        incident_id=incident_id,
                        correlation_id=correlation_id,
                    )
                    return _make_tool_envelope(status="rejected", error_code="WINDOW_EXCEEDED", records=[])
            except Exception:
                return _make_tool_envelope(status="rejected", error_code="SCHEMA_INVALID", records=[])

        # B. Count and depth limits
        if arguments.get("max_points", 0) > self.policy.max_points or \
           arguments.get("max_hits", 0) > self.policy.max_hits or \
           arguments.get("max_depth", 0) > self.policy.max_dependency_depth:
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code="LIMIT_EXCEEDED",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(status="rejected", error_code="LIMIT_EXCEEDED", records=[])

        # C. Incident quota
        if incident_id:
            count = self.tool_call_counters.get(incident_id, 0)
            if count >= self.policy.max_tool_calls_per_incident:
                self.audit_logger.record_event(
                    actor_ref=context.actor_ref,
                    action="TOOL_DENIAL",
                    target_ref=tool_name,
                    result_code="DENY",
                    reason_code="BUDGET_EXHAUSTED",
                    request_payload=arguments,
                    incident_id=incident_id,
                    correlation_id=correlation_id,
                )
                return _make_tool_envelope(status="rejected", error_code="BUDGET_EXHAUSTED", records=[])
            self.tool_call_counters[incident_id] = count + 1

        # -------------------------------------------------------------
        # Step 6 — Parameterized Read-Only Dispatch
        # -------------------------------------------------------------
        dispatch_data, status, error_code, source_ref = self.dispatcher.dispatch(
            tool_name=tool_name,
            arguments=arguments,
            caller_groups=context.allowed_groups,
            caller_scope_ref=context.principal_id,
        )

        if tool_name == "retrieve_runbooks":
            # For retrieval, response is already RetrievalResult dict
            action_code = "KB_RETRIEVAL"
        else:
            action_code = "TOOL_INVOCATION"

        if status == "unavailable":
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action=action_code,
                target_ref=tool_name,
                result_code="ERROR",
                reason_code=error_code or "SOURCE_UNAVAILABLE",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            if tool_name == "retrieve_runbooks":
                return dispatch_data
            return _make_tool_envelope(
                status="unavailable",
                error_code=error_code or "SOURCE_UNAVAILABLE",
                records=[],
                source_ref=source_ref,
                data_quality="unavailable",
            )

        if status == "rejected":
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="TOOL_DENIAL",
                target_ref=tool_name,
                result_code="DENY",
                reason_code=error_code or "TOOL_NOT_ALLOWED",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(
                status="rejected",
                error_code=error_code or "TOOL_NOT_ALLOWED",
                records=[],
                source_ref=source_ref,
                data_quality="unavailable",
            )

        # -------------------------------------------------------------
        # Step 7 — Mandatory SEC-03 Redaction & FAIL_CLOSED Bounding
        # -------------------------------------------------------------
        try:
            sanitized_data, redactions = self.sanitizer.sanitize_object(
                dispatch_data, force_failure=force_sanitizer_failure
            )
        except (SanitizerFailureError, Exception):
            # FAIL-CLOSED: NEVER RETURN UNSANITIZED RAW PAYLOAD
            self.audit_logger.record_event(
                actor_ref=context.actor_ref,
                action="REDACTION_GATE",
                target_ref=tool_name,
                result_code="ERROR",
                reason_code="REDACTION_FAILED",
                request_payload=arguments,
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return _make_tool_envelope(
                status="rejected",
                error_code="REDACTION_FAILED",
                records=[],
                source_ref=source_ref,
            )

        # -------------------------------------------------------------
        # Step 8 — Synchronous Audit Logging & Envelope Return
        # -------------------------------------------------------------
        self.audit_logger.record_event(
            actor_ref=context.actor_ref,
            action=action_code,
            target_ref=tool_name,
            result_code="ALLOW",
            reason_code="OK",
            request_payload=arguments,
            incident_id=incident_id,
            correlation_id=correlation_id,
        )

        if tool_name == "retrieve_runbooks":
            return sanitized_data

        records = sanitized_data.get("records")
        if records is None and isinstance(sanitized_data.get("data"), list):
            records = sanitized_data.get("data")
        records = records or []
        truncated = bool(sanitized_data.get("truncated", False))
        data_quality = str(sanitized_data.get("data_quality", "complete"))
        return _make_tool_envelope(
            status="ok",
            error_code=None,
            records=records,
            source_ref=source_ref,
            query_window={
                "start": arguments.get("start", now_z),
                "end": arguments.get("end", now_z),
            },
            data_quality=data_quality,
            truncated=truncated,
        )

