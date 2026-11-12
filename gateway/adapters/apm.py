"""Read-only APM Stub Adapter returning honest unsupported disposition under ADR-S07 (C09, ADR-S07)."""

from __future__ import annotations

from typing import Any, Optional

from gateway.adapters.base import (
    BaseTelemetryAdapter,
    ForbiddenScopeError,
    TelemetryResponseEnvelope,
    ToolNotAllowedError,
    check_ground_truth_isolation,
    check_mutation_attempt,
)
from services.common.telemetry import utc_now_iso


class ApmAdapter(BaseTelemetryAdapter):
    """Read-only APM adapter returning explicit UNSUPPORTED_SOURCE disposition under ADR-S07."""

    tool_name = "get_apm_health"
    default_source_ref = "apm:unsupported"

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: Any = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            client=client,
            sanitizer=sanitizer,
            max_window_seconds=max_window_seconds,
            timeout_seconds=timeout_seconds,
        )

    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute APM query returning honest UNSUPPORTED_SOURCE status (ADR-S07, RULE-006)."""
        now_z = utc_now_iso()

        # Step A: Mutation & Ground Truth check
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

        start = arguments.get("start") or now_z
        end = arguments.get("end") or now_z

        # Step B: Return Honest Unsupported Envelope (No Fabricated Metrics / Spans)
        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self.default_source_ref,
            observed_at=now_z,
            query_window={
                "start": start,
                "end": end,
                "duration_seconds": 0.0,
            },
            data_quality="unavailable",
            truncated=False,
            sanitized=True,
            error_code="UNSUPPORTED_SOURCE",
            data=None,  # No synthetic fabricated APM data allowed
            status="unavailable",
        )
