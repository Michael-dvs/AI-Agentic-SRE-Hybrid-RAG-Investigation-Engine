"""Pre-sink deterministic redactor and fail-closed sanitizer module (SEC-03, NFR-003, C08)."""

from __future__ import annotations

import copy
import re
from typing import Any


class SanitizerFailureError(Exception):
    """Raised when sanitizer encounters an unexpected failure, triggering FAIL_CLOSED policy."""
    def __init__(self, message: str = "Deterministic sanitizer execution failed") -> None:
        super().__init__(message)
        self.code = "REDACTION_FAILED"


# Redaction regular expressions
_PATTERNS = [
    # JWT tokens
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED:SEC-03:JWT]"),
    # Bearer tokens or API keys
    (re.compile(r"(?i)\b(bearer\s+[A-Za-z0-9_\-\.]{12,}|api[_-]?key\s*[:=]\s*[A-Za-z0-9_\-]{12,})"), "[REDACTED:SEC-03:API_KEY]"),
    # Passwords and credentials
    (re.compile(r"(?i)\b(password|secret|pwd)\s*[:=]\s*['\"]?[^\s,'\"]{4,}['\"]?"), "[REDACTED:SEC-03:CREDENTIAL]"),
    # Synthetic credit card PANs (13-19 digits with optional spaces/hyphens)
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{16}\b"), "[REDACTED:SEC-03:CARD_PAN]"),
]


class DeterministicSanitizer:
    """Pre-sink redactor that recursively masks synthetic PII, credentials, and secrets.

    Implements a strict FAIL_CLOSED security policy: any unexpected error immediately
    halts response delivery and prevents raw data leakage (SEC-03).
    """

    def __init__(self) -> None:
        self.patterns = _PATTERNS

    def sanitize_text(self, text: str) -> tuple[str, int]:
        """Apply all redaction rules to text and return sanitized string and count of redactions."""
        sanitized = text
        count = 0
        for pattern, replacement in self.patterns:
            matches = len(pattern.findall(sanitized))
            if matches > 0:
                sanitized = pattern.sub(replacement, sanitized)
                count += matches
        return sanitized, count

    def sanitize_object(self, obj: Any, force_failure: bool = False) -> tuple[Any, int]:
        """Recursively sanitize dict, list, or scalar values.

        If force_failure is True, raises SanitizerFailureError to test fail-closed behavior.
        """
        if force_failure:
            raise SanitizerFailureError("Simulated unexpected failure inside deterministic sanitizer (SEC-03)")

        try:
            return self._sanitize_recursive(obj)
        except Exception as e:
            if isinstance(e, SanitizerFailureError):
                raise
            raise SanitizerFailureError(f"Unexpected sanitizer exception: {e}") from e

    def _sanitize_recursive(self, obj: Any) -> tuple[Any, int]:
        total_redactions = 0

        if isinstance(obj, str):
            clean_str, cnt = self.sanitize_text(obj)
            return clean_str, cnt

        elif isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                # Also sanitize key if it happens to contain a sensitive substring
                clean_k, k_cnt = self.sanitize_text(str(k))
                clean_v, v_cnt = self._sanitize_recursive(v)
                new_dict[clean_k] = clean_v
                total_redactions += (k_cnt + v_cnt)
            return new_dict, total_redactions

        elif isinstance(obj, (list, tuple)):
            new_list = []
            for item in obj:
                clean_item, cnt = self._sanitize_recursive(item)
                new_list.append(clean_item)
                total_redactions += cnt
            return new_list, total_redactions

        else:
            return obj, 0

