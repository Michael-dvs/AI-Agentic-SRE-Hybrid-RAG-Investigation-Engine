"""Sanitized AI Observability Tracer and OpenInference-compatible Local Sink (ADR-S06, BR-014, NFR-005, NFR-018, SEC-03)."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import pathlib
import re
import uuid
from typing import Any, Dict, List, Optional

from gateway.sanitizer import DeterministicSanitizer, SanitizerFailureError

_LOG = logging.getLogger(__name__)

# Regular expressions to strictly block raw thinking and hidden CoT
_COT_PATTERNS = [
    re.compile(r"(?is)<\s*think\b[^>]*>.*?<\s*/\s*think\s*>"),
    re.compile(r"(?is)<\s*analysis\b[^>]*>.*?<\s*/\s*analysis\s*>"),
]
_COT_ATTR_KEYS = {"think", "thinking", "raw_thinking", "chain_of_thought", "internal_reasoning"}


def strip_hidden_cot(obj: Any) -> Any:
    """Recursively strip or block any raw thinking tags or hidden chain-of-thought keys."""
    if isinstance(obj, str):
        cleaned = obj
        for pattern in _COT_PATTERNS:
            cleaned = pattern.sub("[REDACTED:COT]", cleaned)
        return cleaned
    elif isinstance(obj, dict):
        cleaned_dict = {}
        for k, v in obj.items():
            if str(k).lower() in _COT_ATTR_KEYS:
                continue
            cleaned_dict[k] = strip_hidden_cot(v)
        return cleaned_dict
    elif isinstance(obj, list):
        return [strip_hidden_cot(item) for item in obj]
    return obj


class TraceSpan:
    """Represents a discrete span in the AI investigation lifecycle."""

    def __init__(
        self,
        name: str,
        span_id: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.start_time = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.end_time: Optional[str] = None
        self.duration_ms: float = 0.0
        self.status: str = "OK"
        self.attributes: Dict[str, Any] = attributes or {}

    def finish(self, status: str = "OK", extra_attrs: Optional[Dict[str, Any]] = None) -> None:
        self.end_time = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.status = status
        if extra_attrs:
            self.attributes.update(extra_attrs)
        try:
            start_dt = datetime.datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end_dt = datetime.datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            self.duration_ms = max(0.0, (end_dt - start_dt).total_seconds() * 1000.0)
        except Exception:
            self.duration_ms = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "attributes": self.attributes,
        }


class SanitizedAITracer:
    """Lightweight, sanitized local AI trace sink implementing fail-open resilience (ADR-S06).

    Decoupled from the independent security audit sink:
    If this tracer experiences an outage, exception, or file error, it logs a warning
    and drops or buffers spans safely without interrupting the primary investigation pipeline.
    """

    def __init__(
        self,
        sink_path: Optional[pathlib.Path | str] = None,
        max_buffered_spans: int = 1000,
        simulate_outage: bool = False,
    ) -> None:
        self.sink_path = pathlib.Path(sink_path) if sink_path else None
        if self.sink_path:
            self.sink_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_buffered_spans = max_buffered_spans
        self.simulate_outage = simulate_outage
        self.sanitizer = DeterministicSanitizer()
        self.traces: Dict[str, Dict[str, Any]] = {}
        self.spans: List[Dict[str, Any]] = []
        self.dropped_spans_count = 0

    def start_trace(
        self,
        incident_id: str,
        correlation_id: str,
        trace_id: Optional[str] = None,
        version_manifest: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Initialize an AI trace session for an incident."""
        if self.simulate_outage:
            _LOG.warning("AI Observability Sink outage simulated; tracer start_trace safely degraded.")
            return f"trace-dropped-{uuid.uuid4().hex[:8]}"

        tid = trace_id or f"ai-trace-{uuid.uuid4().hex[:16]}"
        manifest, _ = self.sanitizer.sanitize_object(version_manifest or {})

        self.traces[incident_id] = {
            "trace_id": tid,
            "incident_id": incident_id,
            "correlation_id": correlation_id,
            "version_manifest": strip_hidden_cot(manifest),
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "completed_at": None,
            "outcome": "IN_PROGRESS",
            "spans": [],
        }
        return tid

    def record_span(
        self,
        incident_id: str,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent_span_id: Optional[str] = None,
        status: str = "OK",
        duration_ms: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a completed, sanitized span in the AI trace sink."""
        if self.simulate_outage:
            self.dropped_spans_count += 1
            _LOG.warning(
                "AI Observability Sink outage simulated; dropped span %s for %s without interrupting investigation.",
                name,
                incident_id,
            )
            return None

        try:
            # 1. Strip raw thinking and CoT
            clean_attrs = strip_hidden_cot(attributes or {})

            # 2. Enforce pre-sink fail-closed sanitization on attributes
            sanitized_attrs, redaction_count = self.sanitizer.sanitize_object(clean_attrs)
            sanitized_attrs["redaction_count"] = redaction_count

            now_z = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            span_id = f"span-{uuid.uuid4().hex[:12]}"

            span_data: Dict[str, Any] = {
                "span_id": span_id,
                "incident_id": incident_id,
                "name": name,
                "parent_span_id": parent_span_id,
                "timestamp": now_z,
                "duration_ms": round(duration_ms or 0.0, 3),
                "status": status,
                "sanitized": True,
                "attributes": sanitized_attrs,
            }

            if incident_id in self.traces:
                self.traces[incident_id]["spans"].append(span_data)

            if len(self.spans) < self.max_buffered_spans:
                self.spans.append(span_data)
            else:
                self.dropped_spans_count += 1

            # Persist to JSONL if path configured (fail-open if disk write fails)
            if self.sink_path:
                try:
                    with open(self.sink_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(span_data) + "\n")
                except Exception as disk_err:
                    _LOG.warning("AI Observability Sink disk write failed: %s; buffered in memory.", disk_err)

            return span_data

        except SanitizerFailureError:
            # Re-raise sanitizer failures if forced (SEC-03 fail-closed)
            raise
        except Exception as exc:
            _LOG.warning("Non-fatal AI Observability Sink error: %s; investigation continues unimpeded.", exc)
            return None

    def end_trace(
        self,
        incident_id: str,
        outcome: str = "COMPLETED",
        final_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Conclude an AI trace session."""
        if self.simulate_outage:
            _LOG.warning("AI Observability Sink outage simulated; end_trace safely degraded.")
            return None

        trace = self.traces.get(incident_id)
        if not trace:
            return None

        trace["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        trace["outcome"] = outcome
        if final_summary:
            clean_summary = strip_hidden_cot(final_summary)
            sanitized_summary, _ = self.sanitizer.sanitize_object(clean_summary)
            trace["final_summary"] = sanitized_summary

        return trace

    def export_traces(self) -> List[Dict[str, Any]]:
        """Export all recorded trace objects."""
        return list(self.traces.values())

    def export_jsonl(self, output_path: pathlib.Path | str) -> int:
        """Export all recorded spans to a JSONL file."""
        target = pathlib.Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(target, "w", encoding="utf-8") as f:
            for span in self.spans:
                f.write(json.dumps(span) + "\n")
                count += 1
        return count
