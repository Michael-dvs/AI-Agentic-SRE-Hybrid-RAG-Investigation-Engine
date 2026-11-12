"""Pre-ingestion DLP sanitizer and synthetic secret/PII redaction module (SEC-03)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RedactionEvent:
    document_id: str
    pattern_type: str
    line_number: int
    redaction_token: str
    masked_snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RedactionReport:
    documents_scanned: int = 0
    total_redactions: int = 0
    redactions_by_type: dict[str, int] = field(default_factory=dict)
    events: list[RedactionEvent] = field(default_factory=list)

    def record_event(self, event: RedactionEvent) -> None:
        self.total_redactions += 1
        self.redactions_by_type[event.pattern_type] = (
            self.redactions_by_type.get(event.pattern_type, 0) + 1
        )
        self.events.append(event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents_scanned": self.documents_scanned,
            "total_redactions": self.total_redactions,
            "redactions_by_type": dict(sorted(self.redactions_by_type.items())),
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True)
class SanitizerResult:
    document_id: str
    sanitized_text: str
    redaction_count: int
    events: list[RedactionEvent]


# Precompiled regex patterns for synthetic secret / fixture detection
_RE_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_RE_DB_CONN = re.compile(
    r"\b((?:postgres|postgresql|mysql|amqp)://[^:\s]+:)([^@\s]+)(@[^\s]+)\b"
)
_RE_BEARER = re.compile(
    r"\b((?:Bearer|bearer)\s+)([A-Za-z0-9._~+/-]{12,})\b"
)
_RE_API_KEY = re.compile(
    r"\b(?:sim-key-[A-Za-z0-9_-]{6,}|ak_test_[A-Za-z0-9_-]{6,}|sk_test_[A-Za-z0-9_-]{6,}|dummy-secret-[A-Za-z0-9_-]{4,})\b"
)
_RE_CARD_PAN = re.compile(
    r"\b(?:\d{4}[- ]?){3}\d{4}\b"
)
_RE_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b((?:api_key|secret_key|private_key|auth_token|db_password|access_token)\s*[:=]\s*[\"'])([^\"'\r\n]+)([\"'])"
)


def sanitize_document_text(
    text: str,
    document_id: str,
    report: RedactionReport | None = None,
) -> SanitizerResult:
    """Scan and redact synthetic secrets, PII, and credentials before chunking.

    Converts detected sensitive fixtures into neutral redaction tokens (SEC-03).
    """
    lines = text.splitlines(keepends=True)
    sanitized_lines: list[str] = []
    events: list[RedactionEvent] = []

    for line_idx, line in enumerate(lines, start=1):
        modified_line = line

        # 1. Synthetic JWT Token
        def _jwt_sub(match: re.Match[str]) -> str:
            raw_token = match.group(0)
            token_type = "synthetic_jwt"
            snippet = f"{raw_token[:6]}...{raw_token[-4:]}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_JWT_TOKEN]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return "[REDACTED_JWT_TOKEN]"

        modified_line = _RE_JWT.sub(_jwt_sub, modified_line)

        # 2. Database URI password
        def _db_sub(match: re.Match[str]) -> str:
            prefix, raw_pw, suffix = match.groups()
            token_type = "synthetic_db_password"
            snippet = f"{prefix}***{suffix}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_PASSWORD]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return f"{prefix}[REDACTED_PASSWORD]{suffix}"

        modified_line = _RE_DB_CONN.sub(_db_sub, modified_line)

        # 3. Bearer Token
        def _bearer_sub(match: re.Match[str]) -> str:
            prefix, raw_token = match.groups()
            token_type = "synthetic_bearer_token"
            snippet = f"{prefix}{raw_token[:4]}...{raw_token[-4:]}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_BEARER_TOKEN]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return f"{prefix}[REDACTED_BEARER_TOKEN]"

        modified_line = _RE_BEARER.sub(_bearer_sub, modified_line)

        # 4. API Keys
        def _api_key_sub(match: re.Match[str]) -> str:
            raw_key = match.group(0)
            token_type = "synthetic_api_key"
            snippet = f"{raw_key[:8]}...{raw_key[-4:]}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_API_KEY]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return "[REDACTED_API_KEY]"

        modified_line = _RE_API_KEY.sub(_api_key_sub, modified_line)

        # 5. Card PAN
        def _pan_sub(match: re.Match[str]) -> str:
            raw_pan = match.group(0)
            # Exclude short digit groupings or dates like 2026-11-11
            digits = re.sub(r"\D", "", raw_pan)
            if len(digits) not in (15, 16):
                return raw_pan
            token_type = "synthetic_card_pan"
            snippet = f"{digits[:4]}-****-****-{digits[-4:]}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_CARD_PAN]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return "[REDACTED_CARD_PAN]"

        modified_line = _RE_CARD_PAN.sub(_pan_sub, modified_line)

        # 6. Key-Value secrets
        def _kv_secret_sub(match: re.Match[str]) -> str:
            prefix, raw_val, suffix = match.groups()
            token_type = "synthetic_credential_assignment"
            snippet = f"{prefix}***{suffix}"
            event = RedactionEvent(
                document_id=document_id,
                pattern_type=token_type,
                line_number=line_idx,
                redaction_token="[REDACTED_SECRET]",
                masked_snippet=snippet,
            )
            events.append(event)
            if report:
                report.record_event(event)
            return f"{prefix}[REDACTED_SECRET]{suffix}"

        modified_line = _RE_KEY_VALUE_SECRET.sub(_kv_secret_sub, modified_line)

        sanitized_lines.append(modified_line)

    sanitized_text = "".join(sanitized_lines)
    return SanitizerResult(
        document_id=document_id,
        sanitized_text=sanitized_text,
        redaction_count=len(events),
        events=events,
    )

