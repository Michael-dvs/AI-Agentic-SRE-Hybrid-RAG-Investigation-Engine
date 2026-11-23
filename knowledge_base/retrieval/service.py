"""Authorized Knowledge Retrieval Service enforcing Draft 2020-12 contracts and security bounds (C02, C07)."""

from __future__ import annotations

import datetime
import json
import pathlib
import uuid
from dataclasses import replace
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from knowledge_base.retrieval.engine import RetrievalEngine
from knowledge_base.retrieval.models import (
    AppliedFilters,
    Citation,
    RetrievalRequest,
    RetrievalResult,
)

_SCHEMA_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "evidence"
    / "c02-20261109T070500Z"
    / "C02"
    / "contracts"
)

_REQ_SCHEMA_PATH = _SCHEMA_DIR / "retrieval-request.v1.schema.json"
_RES_SCHEMA_PATH = _SCHEMA_DIR / "retrieval-result.v1.schema.json"

_REQ_VALIDATOR = Draft202012Validator(
    json.loads(_REQ_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker()
)
_RES_VALIDATOR = Draft202012Validator(
    json.loads(_RES_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker()
)
_CITATION_VALIDATOR = _RES_VALIDATOR.evolve(schema=_RES_VALIDATOR.schema["properties"]["citations"]["items"])


def has_citation_provenance(citation: dict[str, Any]) -> bool:
    """Check a C02 citation after the internal sanitizer has optionally marked it."""
    payload = {k: v for k, v in citation.items() if k != "sanitized"}
    return (_CITATION_VALIDATOR.is_valid(payload)
            and all(payload[k].strip() for k in ("chunk_id", "document_version", "title", "section_path", "sanitized_excerpt"))
            and all(part not in ("", ".", "..") for part in payload["source_uri"][5:].split("/")))


def get_current_utc_z() -> str:
    """Return current timestamp in ISO-8601 UTC with Z suffix."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def unavailable_result(request: dict[str, Any], caller_scope_ref: str) -> RetrievalResult:
    """C02 response for a validated request when no trustworthy index result exists."""
    req = request if isinstance(request, dict) else {}
    observed_at = get_current_utc_z()
    raw_mode = req.get("retrieval_mode")
    retrieval_mode = (
        raw_mode
        if raw_mode in ("lexical_only", "dense_only", "hybrid_rrf", "hybrid_rerank")
        else "hybrid_rrf"
    )
    raw_service = req.get("service_id")
    service_id = raw_service.strip()[:128] if isinstance(raw_service, str) and raw_service.strip() else "unknown"
    raw_env = req.get("environment")
    environment = raw_env if raw_env in ("lab", "sim-staging", "sim-prod-like") else "lab"
    raw_ref_time = req.get("reference_time")
    reference_time = (
        raw_ref_time
        if isinstance(raw_ref_time, str)
        and raw_ref_time.endswith("Z")
        and FormatChecker().conforms(raw_ref_time, "date-time")
        else observed_at
    )
    scope_ref = caller_scope_ref.strip()[:128] if isinstance(caller_scope_ref, str) and caller_scope_ref.strip() else "sre-core-agent"
    return RetrievalResult(
        request_id=f"req-ret-{uuid.uuid4().hex[:12]}",
        status="unavailable", gap_reason="RETRIEVAL_UNAVAILABLE",
        observed_at=observed_at, index_version=None,
        retrieval_mode_executed=retrieval_mode,
        applied_filters=AppliedFilters(service_id=service_id, environment=environment,
                                       reference_time=reference_time, caller_scope_ref=scope_ref),
    )


class RetrievalService:
    """Service wrapping RetrievalEngine, enforcing validation against C02 JSON schemas,

    security context binding, token budget bounds, and citation provenance.
    """

    def __init__(self, engine: RetrievalEngine) -> None:
        self.engine = engine

    def execute_retrieval(
        self,
        request_data: dict[str, Any],
        caller_scope_ref: str = "sre-core-agent",
        caller_groups: list[str] | None = None,
        request_id: str | None = None,
        *,
        runbooks_only: bool = False,
    ) -> RetrievalResult:
        """Validate request, execute engine retrieval, enforce token limits, and validate response contract."""
        observed_at = get_current_utc_z()
        req_id = request_id or f"req-ret-{uuid.uuid4().hex[:12]}"

        # 1. Validate request schema
        if not _REQ_VALIDATOR.is_valid(request_data) or any(
            not request_data[key].strip() for key in ("query_text", "service_id", "index_version_policy")
        ):
            return RetrievalResult(
                request_id=req_id, status="rejected", gap_reason="SCHEMA_INVALID",
                retrieval_mode_executed=request_data.get("retrieval_mode", "hybrid_rrf"),
                index_version=None, observed_at=observed_at,
                applied_filters=AppliedFilters(
                    service_id=request_data.get("service_id", "unknown"),
                    environment=request_data.get("environment", "lab"),
                    reference_time=request_data.get("reference_time", observed_at),
                    caller_scope_ref=caller_scope_ref,
                ),
            )

        req_obj = RetrievalRequest(
            service_id=request_data["service_id"],
            environment=request_data["environment"],
            query_text=request_data["query_text"],
            reference_time=request_data["reference_time"],
            retrieval_mode=request_data["retrieval_mode"],
            top_k=request_data["top_k"],
            max_context_tokens=request_data["max_context_tokens"],
            index_version_policy=request_data["index_version_policy"],
            caller_scope_ref=caller_scope_ref,
            caller_groups=caller_groups if caller_groups is not None else [],
        )

        # 2. Execute query on engine
        if not req_obj.caller_groups:
            raw_citations, status, gap_reason, latency_ms = [], "rejected", "FORBIDDEN_SCOPE", 0.0
        else:
            try:
                raw_citations, status, gap_reason, latency_ms = self.engine.query(req_obj, runbooks_only=runbooks_only)
            except Exception:
                return replace(unavailable_result(request_data, caller_scope_ref), request_id=req_id)

        # 3. Enforce context token bounding
        bounded_citations: list[Citation] = []
        tokens_accumulated = 0
        truncated = False

        for cit in raw_citations:
            # Estimate tokens: roughly 4 chars per token
            cit_tokens = (len(cit.sanitized_excerpt) + 3) // 4
            if tokens_accumulated + cit_tokens <= req_obj.max_context_tokens:
                bounded_citations.append(cit)
                tokens_accumulated += cit_tokens
            else:
                remaining_tokens = req_obj.max_context_tokens - tokens_accumulated
                if remaining_tokens >= 32:
                    bounded_citations.append(replace(cit, sanitized_excerpt=cit.sanitized_excerpt[:remaining_tokens * 4]))
                    tokens_accumulated += remaining_tokens
                truncated = True
                break

        applied_filters = AppliedFilters(
            service_id=req_obj.service_id,
            environment=req_obj.environment,
            reference_time=req_obj.reference_time,
            status_required="approved",
            caller_scope_ref=caller_scope_ref,
        )

        result = RetrievalResult(
            schema_version="1.0",
            request_id=req_id,
            status=status,
            retrieval_mode_executed=req_obj.retrieval_mode,
            index_version=self.engine.index_version,
            observed_at=observed_at,
            applied_filters=applied_filters,
            citations=bounded_citations,
            truncated=truncated,
            context_tokens_used=tokens_accumulated,
            latency_ms=latency_ms,
            gap_reason=gap_reason,
        )

        # 4. Final contract validation against Draft 2020-12
        if not _RES_VALIDATOR.is_valid(result.to_dict()):
            return replace(unavailable_result(request_data, caller_scope_ref), request_id=req_id)

        return result

