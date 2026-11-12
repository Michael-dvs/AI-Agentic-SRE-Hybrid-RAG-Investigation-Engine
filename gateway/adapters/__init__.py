"""Gateway telemetry adapters package (C09)."""

from gateway.adapters.apm import ApmAdapter
from gateway.adapters.base import (
    BaseTelemetryAdapter,
    ForbiddenScopeError,
    InvalidTimeRangeError,
    LimitExceededError,
    SchemaInvalidError,
    ServiceNotFoundError,
    SourceUnavailableError,
    TelemetryAdapterError,
    TelemetryResponseEnvelope,
    ToolNotAllowedError,
    UnsupportedSourceError,
    WindowExceededError,
    check_ground_truth_isolation,
    check_mutation_attempt,
    validate_time_window,
)
from gateway.adapters.catalog import CatalogAdapter
from gateway.adapters.logs import LogsAdapter
from gateway.adapters.metrics import MetricsAdapter
from gateway.adapters.traces import TracesAdapter

__all__ = [
    "BaseTelemetryAdapter",
    "TelemetryResponseEnvelope",
    "TelemetryAdapterError",
    "WindowExceededError",
    "InvalidTimeRangeError",
    "LimitExceededError",
    "ServiceNotFoundError",
    "SourceUnavailableError",
    "ToolNotAllowedError",
    "ForbiddenScopeError",
    "SchemaInvalidError",
    "UnsupportedSourceError",
    "validate_time_window",
    "check_ground_truth_isolation",
    "check_mutation_attempt",
    "MetricsAdapter",
    "LogsAdapter",
    "TracesAdapter",
    "CatalogAdapter",
    "ApmAdapter",
]

