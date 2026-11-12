"""Base telemetry adapter interface and standard response envelope (C09, ADR-S05, ADR-S07, MCP-01, MCP-02)."""

from __future__ import annotations

import abc
import datetime
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import httpx

from gateway.sanitizer import DeterministicSanitizer
from services.common.telemetry import utc_now_iso


# ---------------------------------------------------------------------------
# Exception Hierarchy
# ---------------------------------------------------------------------------

class TelemetryAdapterError(Exception):
    """Base exception for all telemetry adapter failures."""

    def __init__(self, message: str, error_code: str = "SOURCE_UNAVAILABLE") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class WindowExceededError(TelemetryAdapterError):
    """Raised when query duration exceeds hard cap (MCP-02, ADR-S05)."""

    def __init__(self, message: str = "Query window exceeds policy limit") -> None:
        super().__init__(message, error_code="WINDOW_EXCEEDED")


class InvalidTimeRangeError(TelemetryAdapterError):
    """Raised when start time is equal to or after end time."""

    def __init__(self, message: str = "Start time must be strictly before end time") -> None:
        super().__init__(message, error_code="INVALID_TIME_RANGE")


class LimitExceededError(TelemetryAdapterError):
    """Raised when max_points, max_hits, or max_depth exceeds policy limit."""

    def __init__(self, message: str = "Query limits exceeded policy cap") -> None:
        super().__init__(message, error_code="LIMIT_EXCEEDED")


class ServiceNotFoundError(TelemetryAdapterError):
    """Raised when queried service_id is not registered in Service Catalog."""

    def __init__(self, message: str = "Service ID not found in service catalog") -> None:
        super().__init__(message, error_code="SERVICE_NOT_FOUND")


class SourceUnavailableError(TelemetryAdapterError):
    """Raised when telemetry backend is down, times out, or unreachable (SC-09, EV-02)."""

    def __init__(self, message: str = "Telemetry source backend is unreachable") -> None:
        super().__init__(message, error_code="SOURCE_UNAVAILABLE")


class BackendTimeoutError(TelemetryAdapterError):
    """Raised when backend call exceeds per-call deadline (ADR-S05)."""

    def __init__(self, message: str = "Telemetry query timed out") -> None:
        super().__init__(message, error_code="BACKEND_TIMEOUT")


class ToolNotAllowedError(TelemetryAdapterError):
    """Raised when mutation or unapproved operations are attempted (MCP-01, AT-005)."""

    def __init__(self, message: str = "Mutation operations are strictly prohibited") -> None:
        super().__init__(message, error_code="TOOL_NOT_ALLOWED")


class ForbiddenScopeError(TelemetryAdapterError):
    """Raised when caller attempts to access restricted ground truth or unauthorized scope (AT-008)."""

    def __init__(self, message: str = "Access to forbidden scope or ground truth blocked") -> None:
        super().__init__(message, error_code="FORBIDDEN_SCOPE")


class SchemaInvalidError(TelemetryAdapterError):
    """Raised when input parameters violate contract formats or contain injected syntax."""

    def __init__(self, message: str = "Invalid query parameter schema or format") -> None:
        super().__init__(message, error_code="SCHEMA_INVALID")


class UnsupportedSourceError(TelemetryAdapterError):
    """Raised when tool source is intentionally disabled under architecture decision (ADR-S07)."""

    def __init__(self, message: str = "Telemetry source is unsupported under ADR-S07") -> None:
        super().__init__(message, error_code="UNSUPPORTED_SOURCE")


# ---------------------------------------------------------------------------
# Strict Validation Helpers (No Silent Clamping)
# ---------------------------------------------------------------------------

_ISO8601_UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_BLOCKED_GT_SUBSTRINGS = (
    "restricted",
    "ground_truth",
    "gt_registry",
    "scenario_id",
    "injected_fault",
    "split_freeze_hash",
    "expected_root_cause",
)
_PROHIBITED_MUTATION_KEYWORDS = (
    "write",
    "restart",
    "deploy",
    "scale",
    "exec",
    "shell",
    "sql",
    "drop",
    "delete",
    "update",
    "remediate",
    "kill",
)


def parse_iso8601_utc(dt_str: str) -> datetime.datetime:
    """Parse strict ISO 8601 UTC timestamp ending with Z."""
    if not isinstance(dt_str, str) or not _ISO8601_UTC_PATTERN.match(dt_str):
        raise SchemaInvalidError(f"Timestamp must be ISO 8601 UTC ending in 'Z': {dt_str!r}")
    clean = dt_str[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(clean)


def validate_time_window(
    start: str,
    end: str,
    max_window_seconds: int = 3600,
) -> tuple[datetime.datetime, datetime.datetime, float]:
    """Validate query time window strictly without silent clamping (MCP-02, ADR-S05).

    Returns:
        tuple of (start_dt, end_dt, duration_seconds)
    Raises:
        SchemaInvalidError: If timestamp is malformed.
        InvalidTimeRangeError: If start >= end.
        WindowExceededError: If duration > max_window_seconds.
    """
    dt_start = parse_iso8601_utc(start)
    dt_end = parse_iso8601_utc(end)

    if dt_start >= dt_end:
        raise InvalidTimeRangeError(
            f"Start time ({start}) must be strictly earlier than end time ({end})"
        )

    duration = (dt_end - dt_start).total_seconds()
    if duration > max_window_seconds:
        raise WindowExceededError(
            f"Requested time window of {duration:.1f}s exceeds hard limit of {max_window_seconds}s (MCP-02)"
        )

    return dt_start, dt_end, duration


def check_ground_truth_isolation(data: Any) -> None:
    """Verify input arguments contain zero ground truth path references (AT-008, RULE-002)."""
    serialized = json.dumps(data, default=str).lower()
    for token in _BLOCKED_GT_SUBSTRINGS:
        if token in serialized:
            raise ForbiddenScopeError(
                f"Ground truth token or path reference {token!r} detected in parameters"
            )


def check_mutation_attempt(action_or_args: Any) -> None:
    """Strictly reject mutation keywords in action names or query arguments (MCP-01, AT-005)."""
    serialized = json.dumps(action_or_args, default=str).lower()
    for kw in _PROHIBITED_MUTATION_KEYWORDS:
        # Match whole word or command pattern
        if re.search(rf"\b{re.escape(kw)}\b", serialized):
            raise ToolNotAllowedError(
                f"Mutation keyword {kw!r} is strictly forbidden in read-only telemetry adapter"
            )


# ---------------------------------------------------------------------------
# Standard Response Envelope
# ---------------------------------------------------------------------------

@dataclass
class TelemetryResponseEnvelope:
    """Canonical read-only telemetry response envelope (C02, C09, ADR-DC02)."""

    tool_name: str
    source_ref: str
    observed_at: str
    query_window: dict[str, Any]
    data_quality: str
    truncated: bool
    sanitized: bool
    error_code: Optional[str]
    data: Any
    status: str = "ok"

    def __post_init__(self) -> None:
        if self.data_quality not in ("complete", "partial", "unavailable"):
            raise ValueError(f"Invalid data_quality: {self.data_quality}")
        if self.status not in ("ok", "partial", "unavailable", "rejected"):
            raise ValueError(f"Invalid status: {self.status}")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        """Convert envelope to serializable dictionary."""
        return {
            "tool_name": self.tool_name,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "query_window": dict(self.query_window),
            "data_quality": self.data_quality,
            "truncated": self.truncated,
            "sanitized": self.sanitized,
            "error_code": self.error_code,
            "status": self.status,
            "data": self.data,
        }

    def to_contract_envelope(self, request_id: str | None = None) -> dict[str, Any]:
        """Convert to strict tool-result.v1.schema.json format."""
        import uuid

        records: list[dict[str, Any]] = []
        if isinstance(self.data, list):
            records = [r for r in self.data if isinstance(r, dict)]
        elif isinstance(self.data, dict) and "records" in self.data:
            records = self.data["records"]

        return {
            "schema_version": "1.0",
            "tool_name": self.tool_name if self.tool_name in (
                "get_service_metrics", "search_error_logs", "get_trace_summary", "get_service_dependencies"
            ) else "get_service_metrics",
            "request_id": request_id or f"req-{uuid.uuid4().hex[:12]}",
            "status": self.status,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "query_window": {
                "start": self.query_window.get("start", self.observed_at),
                "end": self.query_window.get("end", self.observed_at),
            },
            "sampling": {
                "applied": False,
                "method": None,
                "returned_count": len(records),
                "source_count": len(records),
            },
            "truncated": self.truncated,
            "data_quality": self.data_quality,
            "sanitized": True,
            "records": records,
            "error_code": self.error_code,
        }


# ---------------------------------------------------------------------------
# Base Telemetry Adapter Abstract Class
# ---------------------------------------------------------------------------

class BaseTelemetryAdapter(abc.ABC):
    """Abstract base class for all read-only telemetry adapters."""

    tool_name: str
    default_source_ref: str
    max_window_seconds: int = 3600
    timeout_seconds: float = 5.0

    def __init__(
        self,
        base_url: str | None = None,
        client: Any = None,
        sanitizer: DeterministicSanitizer | None = None,
        max_window_seconds: int = 3600,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.client = client
        self.sanitizer = sanitizer or DeterministicSanitizer()
        self.max_window_seconds = max_window_seconds
        self.timeout_seconds = timeout_seconds

    def _get_source_ref(self) -> str:
        if self.base_url:
            return f"{self.default_source_ref.split(':')[0]}:{self.base_url}"
        return self.default_source_ref

    def _error_envelope(
        self,
        error_code: str,
        message: str | None = None,
        status: str = "rejected",
        data_quality: str = "unavailable",
        query_window: dict[str, Any] | None = None,
    ) -> TelemetryResponseEnvelope:
        now_z = utc_now_iso()
        return TelemetryResponseEnvelope(
            tool_name=self.tool_name,
            source_ref=self._get_source_ref(),
            observed_at=now_z,
            query_window=query_window or {"start": now_z, "end": now_z, "duration_seconds": 0.0},
            data_quality=data_quality,
            truncated=False,
            sanitized=True,
            error_code=error_code,
            data=None,
            status=status,
        )

    @abc.abstractmethod
    def execute(self, arguments: dict[str, Any]) -> TelemetryResponseEnvelope:
        """Execute read-only query and return standardized TelemetryResponseEnvelope."""
        ...

