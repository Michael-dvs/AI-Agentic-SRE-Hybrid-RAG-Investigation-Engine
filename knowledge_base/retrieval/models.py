"""Data models for Authorized Knowledge Retrieval Contract v1 (C02, C07)."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RetrievalMode = Literal["lexical_only", "dense_only", "hybrid_rrf", "hybrid_rerank"]
RetrievalStatus = Literal["ok", "no_match", "unavailable", "rejected"]
ScoreType = Literal["bm25_sparse", "cosine_dense", "rrf_fusion", "cross_encoder_rerank"]
SourceBranch = Literal["sparse", "dense", "hybrid", "reranked"]
GapReason = Literal[
    "NO_APPLICABLE_RUNBOOK",
    "RETRIEVAL_UNAVAILABLE",
    "FORBIDDEN_SCOPE",
    "SCHEMA_INVALID",
    "BUDGET_EXHAUSTED",
]


@dataclass(frozen=True)
class RetrievalRequest:
    service_id: str
    environment: str
    query_text: str
    reference_time: str
    retrieval_mode: RetrievalMode
    top_k: int
    max_context_tokens: int
    index_version_policy: str
    # Server-side injected security context
    caller_scope_ref: str = "sre-core-agent"
    caller_groups: list[str] = field(default_factory=lambda: ["sre-core-l1"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "environment": self.environment,
            "query_text": self.query_text,
            "reference_time": self.reference_time,
            "retrieval_mode": self.retrieval_mode,
            "top_k": self.top_k,
            "max_context_tokens": self.max_context_tokens,
            "index_version_policy": self.index_version_policy,
        }


@dataclass(frozen=True)
class AppliedFilters:
    service_id: str
    environment: str
    reference_time: str
    status_required: str = "approved"
    caller_scope_ref: str = "sre-core-agent"

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "environment": self.environment,
            "reference_time": self.reference_time,
            "status_required": self.status_required,
            "caller_scope_ref": self.caller_scope_ref,
        }


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    document_id: str
    document_version: str
    title: str
    section_path: str
    source_uri: str
    service_id: str
    environment: str
    status: str
    effective_from: str
    effective_to: str | None
    content_hash: str
    score: float
    score_type: ScoreType
    source_branch: SourceBranch
    sanitized_excerpt: str
    applicability_verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_version": self.document_version,
            "title": self.title,
            "section_path": self.section_path,
            "source_uri": self.source_uri,
            "service_id": self.service_id,
            "environment": self.environment,
            "status": self.status,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "content_hash": self.content_hash,
            "score": round(self.score, 6),
            "score_type": self.score_type,
            "source_branch": self.source_branch,
            "sanitized_excerpt": self.sanitized_excerpt,
            "applicability_verified": self.applicability_verified,
        }


@dataclass
class RetrievalResult:
    schema_version: str = "1.0"
    request_id: str = ""
    status: RetrievalStatus = "ok"
    retrieval_mode_executed: RetrievalMode = "hybrid_rrf"
    index_version: str | None = None
    observed_at: str = ""
    applied_filters: AppliedFilters = field(
        default_factory=lambda: AppliedFilters(
            service_id="unknown", environment="lab", reference_time="2026-01-01T00:00:00Z"
        )
    )
    citations: list[Citation] = field(default_factory=list)
    truncated: bool = False
    context_tokens_used: int = 0
    latency_ms: float = 0.0
    gap_reason: GapReason | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "status": self.status,
            "retrieval_mode_executed": self.retrieval_mode_executed,
            "index_version": self.index_version,
            "observed_at": self.observed_at,
            "applied_filters": self.applied_filters.to_dict(),
            "citations": [c.to_dict() for c in self.citations],
            "truncated": self.truncated,
            "context_tokens_used": self.context_tokens_used,
            "latency_ms": round(self.latency_ms, 2),
            "gap_reason": self.gap_reason,
        }

