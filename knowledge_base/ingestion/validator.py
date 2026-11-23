"""Strict metadata validation module for knowledge base ingestion (RULE-005, SEC-01)."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: str
    document_version: str
    title: str
    service_id: str
    service_name: str
    environment: str
    application: str
    component: str
    status: str
    effective_from: str
    effective_to: str | None
    classification: str
    allowed_groups: list[str]
    owner_ref: str
    language: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_version": self.document_version,
            "title": self.title,
            "service_id": self.service_id,
            "service.name": self.service_name,
            "environment": self.environment,
            "application": self.application,
            "component": self.component,
            "status": self.status,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "classification": self.classification,
            "allowed_groups": list(self.allowed_groups),
            "owner_ref": self.owner_ref,
            "language": self.language,
            "updated_at": self.updated_at,
        }


_RE_DOC_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_VALID_ENVIRONMENTS = {"lab", "sim-staging", "sim-prod-like"}
_VALID_STATUSES = {"approved", "draft", "obsolete", "withdrawn"}
_VALID_CLASSIFICATIONS = {
    "synthetic-internal",
    "synthetic-restricted",
    "synthetic-confidential",
}
_VALID_LANGUAGES = {"id", "en", "id-en"}


def _parse_iso_z(val: Any, field_name: str) -> str:
    if not isinstance(val, str):
        raise ValueError(f"{field_name} must be a string ISO datetime ending in 'Z', got {type(val).__name__}")
    if not val.endswith("Z"):
        raise ValueError(f"{field_name} must be an ISO datetime ending in 'Z': {val}")
    try:
        # validate parseability
        datetime.datetime.fromisoformat(val[:-1] + "+00:00")
    except Exception as exc:
        raise ValueError(f"Invalid ISO datetime for {field_name}: {val}") from exc
    return val


def validate_document_metadata(raw_meta: dict[str, Any], file_path: str = "") -> DocumentMetadata:
    """Strictly validate and normalize raw document metadata. Fail-fast on any anomaly."""
    context_prefix = f"In document [{file_path}]: " if file_path else ""

    def required_text(key: str) -> str:
        value = raw_meta.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{context_prefix}Missing or invalid '{key}'")
        return value.strip()

    # 1. document_id
    doc_id = required_text("document_id")
    if not doc_id or not _RE_DOC_ID.match(doc_id):
        raise ValueError(f"{context_prefix}Invalid or missing 'document_id': '{doc_id}'")

    # 2. document_version
    version = required_text("document_version")

    # 3. title
    title = required_text("title")
    if len(title) < 3 or len(title) > 256:
        raise ValueError(f"{context_prefix}'title' length must be between 3 and 256 characters")

    # 4. service_id & service.name
    service_id = required_text("service_id")

    service_name = required_text("service.name" if "service.name" in raw_meta else "service_name")

    # 5. environment
    environment = required_text("environment")
    if environment not in _VALID_ENVIRONMENTS:
        raise ValueError(f"{context_prefix}Invalid environment '{environment}'. Expected one of {_VALID_ENVIRONMENTS}")

    # 6. application & component
    application = str(raw_meta.get("application", "sre-simulation-poc")).strip()
    component = str(raw_meta.get("component", "core")).strip()

    # 7. status normalization
    raw_status = str(raw_meta.get("status", "")).strip().lower()
    if raw_status in ("active", "current"):
        status = "approved"
    elif raw_status in _VALID_STATUSES:
        status = raw_status
    else:
        raise ValueError(f"{context_prefix}Invalid status '{raw_status}'. Must be one of {_VALID_STATUSES} (or 'active'/'current')")

    # 8. effective_from & effective_to
    effective_from_raw = raw_meta.get("effective_from")
    if not effective_from_raw:
        raise ValueError(f"{context_prefix}Missing 'effective_from'")
    effective_from = _parse_iso_z(str(effective_from_raw), "effective_from")

    if "effective_to" not in raw_meta:
        raise ValueError(f"{context_prefix}Missing 'effective_to'")
    effective_to_raw = raw_meta["effective_to"]
    effective_to: str | None = None
    if effective_to_raw is not None:
        effective_to = _parse_iso_z(effective_to_raw, "effective_to")
        # Validate order
        dt_from = datetime.datetime.fromisoformat(effective_from[:-1] + "+00:00")
        dt_to = datetime.datetime.fromisoformat(effective_to[:-1] + "+00:00")
        if dt_from > dt_to:
            raise ValueError(f"{context_prefix}effective_from ({effective_from}) cannot be after effective_to ({effective_to})")

    # 9. classification
    raw_classification = str(raw_meta.get("classification", "")).strip().lower()
    if raw_classification in ("internal", "synthetic-internal"):
        classification = "synthetic-internal"
    elif raw_classification in ("restricted", "synthetic-restricted"):
        classification = "synthetic-restricted"
    elif raw_classification in ("confidential", "synthetic-confidential"):
        classification = "synthetic-confidential"
    else:
        raise ValueError(
            f"{context_prefix}Invalid classification '{raw_classification}'. Expected one of {_VALID_CLASSIFICATIONS}"
        )

    # 10. allowed_groups
    allowed_groups_raw = raw_meta.get("allowed_groups")
    if not isinstance(allowed_groups_raw, list) or len(allowed_groups_raw) == 0:
        raise ValueError(f"{context_prefix}'allowed_groups' must be a non-empty list of group identifiers")
    if not all(isinstance(g, str) and g.strip() for g in allowed_groups_raw):
        raise ValueError(f"{context_prefix}'allowed_groups' contains an invalid identifier")
    allowed_groups = [g.strip() for g in allowed_groups_raw]

    # 11. owner_ref
    owner_ref = str(raw_meta.get("owner_ref", "")).strip()
    if not owner_ref:
        raise ValueError(f"{context_prefix}Missing 'owner_ref'")

    # 12. language
    language = str(raw_meta.get("language", "id")).strip().lower()
    if language not in _VALID_LANGUAGES:
        raise ValueError(f"{context_prefix}Invalid language '{language}'. Expected one of {_VALID_LANGUAGES}")

    # 13. updated_at
    updated_at_raw = raw_meta.get("updated_at")
    if not updated_at_raw:
        updated_at = effective_from
    else:
        updated_at = _parse_iso_z(str(updated_at_raw), "updated_at")

    return DocumentMetadata(
        document_id=doc_id,
        document_version=version,
        title=title,
        service_id=service_id,
        service_name=service_name,
        environment=environment,
        application=application,
        component=component,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        classification=classification,
        allowed_groups=allowed_groups,
        owner_ref=owner_ref,
        language=language,
        updated_at=updated_at,
    )

