"""Authenticated C10 alert intake for the synthetic lab.

The caller supplies the C05 webhook token, a catalog snapshot, a deduplicator
and a correlator. No default credentials or downstream workflow are installed.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator, FormatChecker

from observability.alerts import verify_alert_webhook_headers


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "evidence/c02-20261109T070500Z/C02/contracts/alert-event.v1.schema.json"
)
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_TIME_FIELDS = ("event_time", "window_start", "window_end")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


class AlertIntakeService:
    """Validate signed alerts and expose a C11 incident context at POST /alerts.

    ``catalog`` is a sequence of C05 catalog records. The deduplicator's
    ``admit`` method runs correlation against detached candidate snapshots
    under its lock before committing. The correlator builds the impact graph
    and correlates active incidents. No investigation worker is dispatched.
    """

    def __init__(
        self,
        *,
        webhook_token: str,
        catalog: Sequence[Mapping[str, Any]],
        deduplicator: Any,
        correlator: Any,
    ) -> None:
        if not isinstance(webhook_token, str) or not webhook_token.strip():
            raise ValueError("an explicit non-empty webhook token is required")
        if deduplicator is None or correlator is None:
            raise ValueError("deduplicator and correlator are required")
        if not isinstance(catalog, (list, tuple)):
            raise ValueError("catalog must be a sequence of catalog records")
        self.webhook_token = webhook_token
        self.catalog: list[dict[str, Any]] = []
        for entry in catalog:
            if not isinstance(entry, Mapping) or any(
                not isinstance(entry.get(key), str) or not entry[key].strip()
                for key in ("service_id", "service.name", "environment")
            ):
                raise ValueError("invalid catalog identity")
            self.catalog.append(dict(entry))
        self.deduplicator = deduplicator
        self.correlator = correlator
        with _SCHEMA_PATH.open(encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())
        # Unmapped identities need manual triage even when outside C02's enum,
        # but every other constraint remains identical to the canonical schema.
        manual_schema = copy.deepcopy(schema)
        for key in ("service_id", "environment"):
            manual_schema["properties"][key].pop("enum", None)
            manual_schema["properties"][key].update(minLength=1, maxLength=128)
        self._manual_validator = Draft202012Validator(
            manual_schema, format_checker=FormatChecker()
        )
        self.app = FastAPI()
        self.app.add_api_route("/alerts", self.receive_alert, methods=["POST"])

    def validate_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        try:
            return verify_alert_webhook_headers(dict(headers), raw_body, self.webhook_token)
        except (TypeError, ValueError, AttributeError):
            return False

    def validate_schema(self, payload: Any) -> tuple[bool, str | None]:
        if next(self._validator.iter_errors(payload), None) is not None:
            return False, "SCHEMA_INVALID"
        start = datetime.fromisoformat(payload["window_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(payload["window_end"].replace("Z", "+00:00"))
        if start >= end:
            return False, "SCHEMA_INVALID"
        return True, None

    def normalize_context(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("alert must be an object")
        normalized = dict(payload)
        for field in _TIME_FIELDS:
            value = normalized.get(field)
            if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
                raise ValueError("invalid timestamp")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            normalized[field] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        matches = self._matches(normalized)
        if len(matches) != 1 or matches[0]["service.name"] != normalized.get("service_id"):
            return {"status": "MANUAL_TRIAGE_REQUIRED", "alert": normalized}
        return normalized

    def _matches(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [entry for entry in self.catalog if
                entry["service_id"] == payload.get("service_id") and
                entry["environment"] == payload.get("environment")]

    def process(self, payload: Any) -> dict[str, Any]:
        """Process an already authenticated JSON payload; never dispatch a workflow."""
        try:
            normalized = self.normalize_context(payload)
        except (ValueError, TypeError, OverflowError):
            return {"status": "rejected", "error_code": "SCHEMA_INVALID"}

        if normalized.get("status") == "MANUAL_TRIAGE_REQUIRED" and isinstance(normalized.get("alert"), dict):
            normalized = normalized["alert"]
            if next(self._manual_validator.iter_errors(normalized), None) is not None:
                return {"status": "rejected", "error_code": "SCHEMA_INVALID"}
            start = datetime.fromisoformat(normalized["window_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(normalized["window_end"].replace("Z", "+00:00"))
            if start >= end:
                return {"status": "rejected", "error_code": "SCHEMA_INVALID"}
            return {"status": "MANUAL_TRIAGE_REQUIRED", "error_code": "SERVICE_UNMAPPED"}

        valid, error = self.validate_schema(normalized)
        if not valid:
            return {"status": "rejected", "error_code": error}
        graph = self.correlator.build_impact_graph(
            primary_service=normalized["service_id"],
            reference_time=normalized["event_time"],
            max_depth=2,
        )
        if not isinstance(graph, dict):
            raise ValueError("invalid correlation result")
        def correlate(incident: dict[str, Any], active: list[dict[str, Any]]) -> dict[str, Any]:
            groups = self.correlator.correlate_incidents(active)
            related = next((group for group in groups if incident["incident_id"] in group["incident_ids"]), None)
            if related is None:
                raise ValueError("incident missing from correlation result")
            return related

        result, related = self.deduplicator.admit(normalized, correlate)
        if not isinstance(result, dict) or result.get("action") not in {"create", "merge", "split", "backpressure"}:
            raise ValueError("invalid deduplicator result")
        if result["action"] == "backpressure":
            return {"status": "backpressure", "error_code": "SOURCE_UNAVAILABLE"}
        incident = result.get("incident")
        if not isinstance(incident, dict) or not incident.get("incident_id"):
            raise ValueError("deduplicator did not return an incident")
        return {
            "status": "accepted",
            "action": result["action"],
            "incident": incident,
            "alert": normalized,
            "allowed_services": [normalized["service_id"]],
            "environment": normalized["environment"],
            "window_start": normalized["window_start"],
            "window_end": normalized["window_end"],
            "correlation": related,
            "dependency_impact": graph,
        }

    async def receive_alert(self, request: Request) -> JSONResponse:
        raw_body = await request.body()
        if not self.validate_signature(request.headers, raw_body):
            return JSONResponse({"status": "rejected", "error_code": "UNAUTHENTICATED"}, status_code=401)
        try:
            payload = json.loads(raw_body, object_pairs_hook=_unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant")))
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"status": "rejected", "error_code": "SCHEMA_INVALID"}, status_code=400)
        try:
            result = self.process(payload)
        except Exception:
            return JSONResponse({"status": "failed_safe", "error_code": "SOURCE_UNAVAILABLE"}, status_code=503)
        status_code = {"rejected": 400, "backpressure": 503}.get(result["status"], 200)
        return JSONResponse(result, status_code=status_code)
