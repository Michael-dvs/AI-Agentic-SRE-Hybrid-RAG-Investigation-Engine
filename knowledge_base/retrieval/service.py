"""Authorized Knowledge Retrieval Service enforcing Draft 2020-12 contracts and security bounds (C02, C07)."""

from __future__ import annotations

import datetime
import json
import pathlib
import uuid
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

_REQ_VALIDATOR: Draft202012Validator | None = None
_RES_VALIDATOR: Draft202012Validator | None = None

if _REQ_SCHEMA_PATH.exists():
    _req_schema = json.loads(_REQ_SCHEMA_PATH.read_text(encoding="utf-8"))
    _REQ_VALIDATOR = Draft202012Validator(_req_schema, format_checker=FormatChecker())

if _RES_SCHEMA_PATH.exists():
    _res_schema = json.loads(_RES_SCHEMA_PATH.read_text(encoding="utf-8"))
    _RES_VALIDATOR = Draft202012Validator(_res_schema, format_checker=FormatChecker())


def get_current_utc_z() -> str:
    """Return current timestamp in ISO-8601 UTC with Z suffix."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


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
    ) -> RetrievalResult:
        """Validate request, execute engine retrieval, enforce token limits, and validate response contract."""
        observed_at = get_current_utc_z()
        req_id = request_id or f"req-ret-{uuid.uuid4().hex[:12]}"

        # 1. Validate request schema
        if _REQ_VALIDATOR is not None:
            req_errors = list(_REQ_VALIDATOR.iter_errors(request_data))
            if req_errors:
                err_msg = "; ".join(e.message for e in req_errors)
                return RetrievalResult(
                    schema_version="1.0",
                    request_id=req_id,
                    status="rejected",
                    retrieval_mode_executed=request_data.get("retrieval_mode", "hybrid_rrf"),
                    index_version=self.engine.index_version,
                    observed_at=observed_at,
                    applied_filters=AppliedFilters(
                        service_id=request_data.get("service_id", "unknown"),
                        environment=request_data.get("environment", "lab"),
                        reference_time=request_data.get("reference_time", observed_at),
                        caller_scope_ref=caller_scope_ref,
                    ),
                    citations=[],
                    truncated=False,
                    context_tokens_used=0,
                    latency_ms=0.5,
                    gap_reason="SCHEMA_INVALID",
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
            caller_groups=caller_groups if caller_groups is not None else ["sre-core-l1"],
        )

        # 2. Execute query on engine
        raw_citations, status, gap_reason, latency_ms = self.engine.query(req_obj)

        # 3. Enforce context token bounding
        bounded_citations: list[Citation] = []
        tokens_accumulated = 0
        truncated = False

        for cit in raw_citations:
            # Estimate tokens: roughly 4 chars per token
            cit_tokens = max(1, len(cit.sanitized_excerpt) // 4)
            if tokens_accumulated + cit_tokens <= req_obj.max_context_tokens:
                bounded_citations.append(cit)
                tokens_accumulated += cit_tokens
            else:
                remaining_tokens = req_obj.max_context_tokens - tokens_accumulated
                if remaining_tokens >= 32:
                    # Truncate excerpt to fit remaining budget
                    trimmed_chars = remaining_tokens * 4
                    trimmed_excerpt = cit.sanitized_excerpt[:trimmed_chars] + "... [TRUNCATED]"
                    bounded_citations.append(
                        Citation(
                            chunk_id=cit.chunk_id,
                            document_id=cit.document_id,
                            document_version=cit.document_version,
                            title=cit.title,
                            section_path=cit.section_path,
                            source_uri=cit.source_uri,
                            service_id=cit.service_id,
                            environment=cit.environment,
                            status=cit.status,
                            effective_from=cit.effective_from,
                            effective_to=cit.effective_to,
                            content_hash=cit.content_hash,
                            score=cit.score,
                            score_type=cit.score_type,
                            source_branch=cit.source_branch,
                            sanitized_excerpt=trimmed_excerpt,
                            applicability_verified=True,
                        )
                    )
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
        if _RES_VALIDATOR is not None:
            res_dict = result.to_dict()
            res_errors = list(_RES_VALIDATOR.iter_errors(res_dict))
            if res_errors:
                err_details = "; ".join(f"{e.message} at {list(e.path)}" for e in res_errors)
                raise ValueError(
                    f"Generated RetrievalResult violates retrieval-result.v1 schema: {err_details}"
                )

        return result

