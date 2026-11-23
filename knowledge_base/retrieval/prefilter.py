"""Strict pre-filtering engine for authorized knowledge retrieval (FR-RAG-004, RULE-005, SEC-01, RAG-01, RAG-02)."""

from __future__ import annotations

import datetime
from typing import Any

from knowledge_base.retrieval.models import RetrievalRequest

_ACTIVE_INDEX_POLICIES = frozenset({"latest", "kb_active_alias", "active_only"})


def is_runbook_id(value: object) -> bool:
    """The published corpus uses SOP- identifiers for operational runbooks."""
    return isinstance(value, str) and value.startswith("SOP-") and len(value) > 4


def matches_index(policy: str, version: str) -> bool:
    return bool(version and version.strip()) and version not in _ACTIVE_INDEX_POLICIES and (
        policy in _ACTIVE_INDEX_POLICIES or policy == version
    )


def parse_iso8601_utc(dt_str: str) -> datetime.datetime:
    """Parse ISO-8601 UTC timestamp ending in Z."""
    if not isinstance(dt_str, str) or not dt_str.endswith("Z"):
        raise ValueError("Missing UTC timestamp")
    return datetime.datetime.fromisoformat(dt_str[:-1] + "+00:00")


class StrictPreFilter:
    """Pre-filtering engine ensuring zero leakage of obsolete, cross-service,

    or restricted documents prior to scoring, fusion, or reranking.
    """

    @staticmethod
    def is_chunk_applicable(chunk: dict[str, Any], request: RetrievalRequest) -> tuple[bool, str]:
        """Check if chunk satisfies all applicability, boundary, and entitlement constraints.

        Returns (is_allowed, reason_if_rejected).
        """
        if not request.service_id or chunk.get("service_id") != request.service_id:
            return False, "SERVICE_MISMATCH"
        if not request.environment or chunk.get("environment") != request.environment:
            return False, "ENV_MISMATCH"

        # 3. Status check (RAG-01, SC-10)
        # Only approved documents can be returned as active citations
        if chunk.get("status") != "approved":
            return False, "STATUS_NOT_APPROVED"

        # 4. Reference time applicability (RAG-01, SC-10, AT-007)
        try:
            ref_dt = parse_iso8601_utc(request.reference_time)
            eff_from = parse_iso8601_utc(chunk["effective_from"])
            if ref_dt < eff_from:
                return False, "NOT_YET_EFFECTIVE"

            if chunk["effective_to"] is not None:
                eff_to = parse_iso8601_utc(chunk["effective_to"])
                if ref_dt >= eff_to:
                    return False, "EXPIRED_OBSOLETE"
        except (KeyError, ValueError, TypeError):
            return False, "TIMESTAMP_PARSE_ERROR"

        groups = chunk.get("allowed_groups")
        if (chunk.get("classification") not in ("synthetic-internal", "synthetic-confidential", "synthetic-restricted")
                or not isinstance(groups, list)
                or not all(isinstance(group, str) and group.strip() for group in groups)
                or not isinstance(request.caller_groups, list)
                or not any(group in request.caller_groups for group in groups)):
            return False, "RESTRICTED_ACCESS_DENIED"

        # 6. Index version policy check. ``active_only`` remains a safe legacy
        # alias while new callers use the canonical ``kb_active_alias`` value.
        policy = request.index_version_policy
        if not policy:
            return False, "INDEX_VERSION_POLICY_REQUIRED"
        if not matches_index(policy, chunk.get("index_version", "")):
            return False, "INDEX_VERSION_MISMATCH"

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

