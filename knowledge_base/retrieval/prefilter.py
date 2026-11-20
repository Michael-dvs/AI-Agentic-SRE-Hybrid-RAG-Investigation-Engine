"""Strict pre-filtering engine for authorized knowledge retrieval (FR-RAG-004, RULE-005, SEC-01, RAG-01, RAG-02)."""

from __future__ import annotations

import datetime
from typing import Any

from knowledge_base.retrieval.models import RetrievalRequest

_ACTIVE_INDEX_POLICIES = frozenset({"latest", "kb_active_alias", "active_only"})


def parse_iso8601_utc(dt_str: str) -> datetime.datetime:
    """Parse ISO-8601 UTC timestamp ending in Z."""
    clean = dt_str.rstrip("Z")
    if "+" in clean:
        clean = clean.split("+")[0]
    dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


class StrictPreFilter:
    """Pre-filtering engine ensuring zero leakage of obsolete, cross-service,

    or restricted documents prior to scoring, fusion, or reranking.
    """

    @staticmethod
    def is_chunk_applicable(chunk: dict[str, Any], request: RetrievalRequest) -> tuple[bool, str]:
        """Check if chunk satisfies all applicability, boundary, and entitlement constraints.

        Returns (is_allowed, reason_if_rejected).
        """
        # 1. Service boundary check (RAG-02)
        chunk_service = chunk.get("service_id") or chunk.get("service.name")
        if chunk_service != request.service_id:
            return False, f"SERVICE_MISMATCH: chunk {chunk_service} != request {request.service_id}"

        # 2. Environment check
        if chunk.get("environment") != request.environment:
            return False, f"ENV_MISMATCH: chunk {chunk.get('environment')} != request {request.environment}"

        # 3. Status check (RAG-01, SC-10)
        # Only approved documents can be returned as active citations
        if chunk.get("status") != "approved":
            return False, f"STATUS_NOT_APPROVED: status={chunk.get('status')}"

        # 4. Reference time applicability (RAG-01, SC-10, AT-007)
        try:
            ref_dt = parse_iso8601_utc(request.reference_time)
            eff_from = parse_iso8601_utc(chunk["effective_from"])
            if ref_dt < eff_from:
                return False, f"NOT_YET_EFFECTIVE: ref={ref_dt.isoformat()} < from={eff_from.isoformat()}"

            if chunk.get("effective_to") is not None:
                eff_to = parse_iso8601_utc(chunk["effective_to"])
                if ref_dt >= eff_to:
                    return False, f"EXPIRED_OBSOLETE: ref={ref_dt.isoformat()} >= to={eff_to.isoformat()}"
        except Exception as e:
            return False, f"TIMESTAMP_PARSE_ERROR: {e}"

        # 5. Access control & classification check (SEC-01)
        classification = chunk.get("classification", "synthetic-internal")
        if classification == "synthetic-restricted":
            chunk_allowed_groups = set(chunk.get("allowed_groups", []))
            caller_groups = set(request.caller_groups)
            if not chunk_allowed_groups.intersection(caller_groups):
                return False, f"RESTRICTED_ACCESS_DENIED: caller groups {caller_groups} lack allowed {chunk_allowed_groups}"

        # 6. Index version policy check. ``active_only`` remains a safe legacy
        # alias while new callers use the canonical ``kb_active_alias`` value.
        policy = request.index_version_policy
        if not policy:
            return False, "INDEX_VERSION_POLICY_REQUIRED"
        if policy not in _ACTIVE_INDEX_POLICIES:
            chunk_idx_ver = chunk.get("index_version")
            if not chunk_idx_ver or chunk_idx_ver != policy:
                return False, f"INDEX_VERSION_MISMATCH: chunk {chunk_idx_ver} != policy {policy}"

        return True, "APPLICABLE"

    @classmethod
    def filter_chunks(
        cls, chunks: list[dict[str, Any]], request: RetrievalRequest
    ) -> list[tuple[int, dict[str, Any]]]:
        """Apply pre-filters to chunks and return allowed (index, chunk) pairs."""
        applicable: list[tuple[int, dict[str, Any]]] = []
        for idx, chunk in enumerate(chunks):
            allowed, _ = cls.is_chunk_applicable(chunk, request)
            if allowed:
                applicable.append((idx, chunk))
        return applicable

