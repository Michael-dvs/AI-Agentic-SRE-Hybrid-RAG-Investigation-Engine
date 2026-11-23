"""C13: bounded model synthesis; policy and workflow remain outside the model."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from gateway.audit import SecurityAuditLogger
from gateway.sanitizer import DeterministicSanitizer
from orchestrator.context_builder import ContextRejected, SanitizedContextBuilder, prompt_template_hash
from orchestrator.llm_provider import ProviderError
from orchestrator.resilience import ResilienceController
from orchestrator.state_machine import utc_now_z

_TEXT = {"type": "string", "minLength": 5, "maxLength": 1024}
_IDS = {"type": "array", "maxItems": 32, "uniqueItems": True,
        "items": {"type": "string", "pattern": "^ev-[A-Za-z0-9._-]+$"}}
_HYPOTHESIS = {
    "type": "object",
    "required": ["summary", "diagnosis", "confidence", "estimated_root_cause"],
    "properties": {"summary": {"$ref": "#/$defs/text"}, "diagnosis": {"$ref": "#/$defs/text"},
                   "confidence": {"enum": ["HIGH", "MEDIUM", "LOW"]},
                   "estimated_root_cause": {"$ref": "#/$defs/text"}},
}
_RETRIEVAL_SCHEMA = Path(__file__).resolve().parent.parent / "evidence/c02-20261109T070500Z/C02/contracts/retrieval-result.v1.schema.json"
_RETRIEVAL_VALIDATOR = Draft202012Validator(
    json.loads(_RETRIEVAL_SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
)


def sanitized_citations(retrieval_result: dict) -> list[dict]:
    """Adapt validated C02 citations to the internal C13 sanitization envelope."""
    if not _RETRIEVAL_VALIDATOR.is_valid(retrieval_result):
        raise ContextRejected("CONTEXT_SCHEMA_INVALID")
    citations, _ = DeterministicSanitizer().sanitize_object(retrieval_result["citations"])
    return [{**citation, "sanitized": True} for citation in citations]

HYPOTHESIS_SCHEMA = {
    "$defs": {"text": _TEXT, "ids": _IDS, "hypothesis": _HYPOTHESIS},
    "type": "object", "additionalProperties": False,
    "required": ["primary_hypothesis", "alternative_hypotheses", "supporting_evidence_ids",
                 "contradicting_evidence_ids", "unknowns"],
    "properties": {
        "primary_hypothesis": {"$ref": "#/$defs/hypothesis", "unevaluatedProperties": False},
        "alternative_hypotheses": {
            "type": "array", "maxItems": 3,
            "items": {
                "$ref": "#/$defs/hypothesis", "unevaluatedProperties": False,
                "required": ["supporting_evidence_ids", "contradicting_evidence_ids"],
                "properties": {"supporting_evidence_ids": {"$ref": "#/$defs/ids"},
                               "contradicting_evidence_ids": {"$ref": "#/$defs/ids"}},
            },
        },
        "supporting_evidence_ids": {"$ref": "#/$defs/ids"},
        "contradicting_evidence_ids": {"$ref": "#/$defs/ids"},
        "unknowns": {"type": "array", "maxItems": 10,
                     "items": {"type": "string", "minLength": 3, "maxLength": 512}},
        "recommended_checks": {
            "type": "array", "maxItems": 5,
            "items": {"type": "string", "minLength": 5, "maxLength": 512},
        },
    },
}
_VALIDATOR = Draft202012Validator(HYPOTHESIS_SCHEMA)
_TOOL_KEYS = {"tool", "tools", "tool_calls", "function_call", "function", "action", "command"}
_FORBIDDEN_TEXT = re.compile(
    r"(?i)(?:\b(?:restart|deploy|scale|write|exec|shell|update_config)[_-][a-z]+\b|"
    r"\b(?:call|execute|invoke|run)\s+(?:restart|deploy|write|exec|shell|sql)\b)"
)
_PRIVATE_TEXT = re.compile(r"(?i)(?:<\s*/?\s*(?:think|analysis)|chain.of.thought|raw.thinking|"
                           r"restricted[/\\]|ground[_ -]?truth|gt_registry|holdout)")


class OutputRejected(Exception):
    def __init__(self, code: str = "SCHEMA_INVALID") -> None:
        super().__init__(code)
        self.code = code


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise OutputRejected()
        result[key] = value
    return result


def validate_candidates(content: str, evidence_ids: frozenset[str]) -> dict[str, Any]:
    """Only accepted, re-sanitized JSON may leave this boundary; rejected text is never logged."""
    if len(content.encode("utf-8")) > 32768:
        raise OutputRejected("LIMIT_EXCEEDED")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(OutputRejected()))
    except (ValueError, RecursionError) as exc:
        raise OutputRejected() from None

    def check(node: Any) -> None:
        if isinstance(node, dict):
            if any(k.lower() in _TOOL_KEYS for k in node):
                raise OutputRejected("TOOL_NOT_ALLOWED")
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
        elif isinstance(node, str):
            if _FORBIDDEN_TEXT.search(node):
                raise OutputRejected("TOOL_NOT_ALLOWED")
            if _PRIVATE_TEXT.search(node) or re.search(r"\bVERIFIED\b", node, re.I):
                raise OutputRejected()
    check(value)
    if not _VALIDATOR.is_valid(value):
        raise OutputRejected()
    for hypothesis in [value, *value["alternative_hypotheses"]]:
        supporting = set(hypothesis["supporting_evidence_ids"])
        contradicting = set(hypothesis["contradicting_evidence_ids"])
        if not supporting or supporting & contradicting or not (supporting | contradicting) <= evidence_ids:
            raise OutputRejected("EVIDENCE_REFERENCE_INVALID")
    clean, _ = DeterministicSanitizer().sanitize_object(value)
    if not _VALIDATOR.is_valid(clean):
        raise OutputRejected()
    return clean


@dataclass(frozen=True)
class LLMLimits:
    max_input_tokens: int = 4096
    max_output_tokens: int = 1024
    timeout_seconds: float = 15.0
    max_retries: int = 2
    incident_input_tokens: int = 12288
    incident_output_tokens: int = 3072

    def __post_init__(self) -> None:
        for name, cap in (("max_input_tokens", 4096), ("max_output_tokens", 1024),
                          ("incident_input_tokens", 12288), ("incident_output_tokens", 3072)):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= cap:
                raise ValueError(f"Invalid {name}")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 2:
            raise ValueError("Invalid max_retries")
        if isinstance(self.timeout_seconds, bool) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 15:
            raise ValueError("Invalid timeout_seconds")


class LLMRunLedger:
    """Reserve before dispatch. A crash with an unknown outcome never triggers a second dispatch."""
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.connection:
            self.connection.execute("""CREATE TABLE IF NOT EXISTS c13_llm_runs (
                incident_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL,
                result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                input_reserved INTEGER NOT NULL DEFAULT 0, output_reserved INTEGER NOT NULL DEFAULT 0,
                input_reported INTEGER NOT NULL DEFAULT 0, output_reported INTEGER NOT NULL DEFAULT 0,
                usage_missing INTEGER NOT NULL DEFAULT 0)""")

    def begin(self, incident_id: str, context_hash: str) -> tuple[bool, dict | None]:
        with self.lock, self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO c13_llm_runs (incident_id,context_hash) VALUES (?,?)",
                (incident_id, context_hash))
            if cursor.rowcount:
                return True, None
            row = self.connection.execute(
                "SELECT context_hash,result FROM c13_llm_runs WHERE incident_id=?", (incident_id,)).fetchone()
            if row[0] != context_hash:
                return False, {"status": "fallback", "reason_code": "VERSION_CONFLICT"}
            return False, json.loads(row[1]) if row[1] else {"status": "fallback", "reason_code": "OUTCOME_UNKNOWN"}

    def reserve(self, incident_id: str, input_tokens: int, limits: LLMLimits) -> bool:
        with self.lock, self.connection:
            cursor = self.connection.execute("""UPDATE c13_llm_runs SET attempts=attempts+1,
                input_reserved=input_reserved+?,output_reserved=output_reserved+?
                WHERE incident_id=? AND attempts<? AND input_reserved+?<=? AND output_reserved+?<=?""",
                (input_tokens, limits.max_output_tokens, incident_id, 1 + limits.max_retries,
                 input_tokens, limits.incident_input_tokens, limits.max_output_tokens, limits.incident_output_tokens))
            return bool(cursor.rowcount)

    def record_usage(self, incident_id: str, input_tokens: int | None, output_tokens: int | None) -> None:
        with self.lock, self.connection:
            self.connection.execute("""UPDATE c13_llm_runs SET input_reported=input_reported+?,
                output_reported=output_reported+?,usage_missing=usage_missing+? WHERE incident_id=?""",
                (input_tokens or 0, output_tokens or 0, int(input_tokens is None or output_tokens is None), incident_id))

    def usage(self, incident_id: str) -> dict[str, int]:
        with self.lock:
            row = self.connection.execute("""SELECT attempts,input_reserved,output_reserved,
                input_reported,output_reported,usage_missing FROM c13_llm_runs WHERE incident_id=?""",
                (incident_id,)).fetchone()
        return dict(zip(("attempts", "input_reserved", "output_reserved", "input_reported",
                         "output_reported", "usage_missing"), row or (0,) * 6))

    def finish(self, incident_id: str, result: dict) -> None:
        with self.lock, self.connection:
            self.connection.execute("UPDATE c13_llm_runs SET result=? WHERE incident_id=?",
                                    (json.dumps(result), incident_id))

    def close(self) -> None:
        self.connection.close()


class LLMInvestigator:
    def __init__(self, provider: Any, ledger: LLMRunLedger, audit: SecurityAuditLogger,
                 *, limits: LLMLimits | None = None, artifact_dir: str | Path | None = None) -> None:
        self.provider = provider
        self.ledger = ledger
        self.audit = audit
        self.limits = limits or LLMLimits()
        self.builder = SanitizedContextBuilder()
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.file_lock = threading.Lock()
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            (self.artifact_dir / "model-version-manifest.json").write_text(
                json.dumps(self.manifest(), indent=2) + "\n", encoding="utf-8")

    def manifest(self) -> dict:
        return {"provider": self.provider.provider_name, "model_name": self.provider.model_name,
                "version": self.provider.version, "weights_digest": None,
                "version_limitation": "Provider model tag; immutable weight digest not exposed",
                "decoding": {"temperature": 0, "max_output_tokens": self.limits.max_output_tokens},
                "prompt_sha256": prompt_template_hash(HYPOTHESIS_SCHEMA),
                "limits": asdict(self.limits), "input_accounting": "utf8_byte_upper_bound_plus_framing_reserve",
                "cash_budget_usd": 0, "ollama_enabled": False}

    def _append(self, filename: str, event: dict) -> None:
        if self.artifact_dir:
            with self.file_lock, (self.artifact_dir / filename).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def _audit(self, incident_id: str, reason: str, *, dispatch: bool = False) -> None:
        allowed = {"TOOL_NOT_ALLOWED", "SCHEMA_INVALID", "REDACTION_FAILED", "LIMIT_EXCEEDED",
                   "BUDGET_EXHAUSTED", "BACKEND_TIMEOUT", "VERSION_CONFLICT", "FORBIDDEN_SCOPE"}
        context_codes = {
            "CONTEXT_UNSANITIZED": "REDACTION_FAILED", "CONTEXT_REDACTION_FAILED": "REDACTION_FAILED",
            "CONTEXT_RESTRICTED": "FORBIDDEN_SCOPE", "CONTEXT_TOO_LARGE": "LIMIT_EXCEEDED",
            "CONTEXT_SCHEMA_INVALID": "SCHEMA_INVALID", "CONTEXT_CITATION_INVALID": "SCHEMA_INVALID",
            "CONTEXT_EVIDENCE_INVALID": "SCHEMA_INVALID", "CONTEXT_INVALID": "SCHEMA_INVALID",
        }
        code = "OK" if dispatch else context_codes.get(reason, reason if reason in allowed else "SOURCE_UNAVAILABLE")
        self.audit.record_event(
            actor_ref="principal_investigator", action="LLM_DISPATCH" if dispatch else "LLM_FALLBACK",
            target_ref="controlled_llm", result_code="ALLOW" if dispatch else "FALLBACK",
            reason_code=code, incident_id=incident_id, request_payload={"reason_code": reason})

    def _fallback(self, incident_id: str, code: str) -> dict:
        self._audit(incident_id, code)
        event = {"incident_id": incident_id, "observed_at": utc_now_z(), "reason_code": code,
                 "status": "INCONCLUSIVE", "investigation_mode": "manual_fallback",
                 "sanitized": True, "usage": self.ledger.usage(incident_id)}
        self._append("llm-outage-fallback-audit.jsonl", event)
        return {"status": "fallback", "reason_code": code, "usage": event["usage"], "manifest": self.manifest()}

    def generate(self, context: dict, resilience: ResilienceController) -> dict:
        incident_id = context["incident_id"]
        resilience.check_cancellation(incident_id)
        if context.get("llm_context_error"):
            return self._fallback(incident_id, "SCHEMA_INVALID")
        try:
            prepared = self.builder.build(context, HYPOTHESIS_SCHEMA)
        except ContextRejected as exc:
            return self._fallback(incident_id, exc.code)
        if prepared.input_tokens_upper_bound > self.limits.max_input_tokens:
            return self._fallback(incident_id, "LIMIT_EXCEEDED")
        identity = {"messages": prepared.messages, "manifest": self.manifest()}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        owner, previous = self.ledger.begin(incident_id, fingerprint)
        if not owner:
            if previous.get("manifest"):
                return previous
            return self._fallback(incident_id, previous["reason_code"])
        result = asyncio.run(self._generate(context, prepared, resilience))
        self.ledger.finish(incident_id, result)
        return result

    async def _generate(self, context: dict, prepared: Any, resilience: ResilienceController) -> dict:
        incident_id = context["incident_id"]
        last_error = "SOURCE_UNAVAILABLE"
        for attempt in range(1 + self.limits.max_retries):
            resilience.check_cancellation(incident_id)
            elapsed = resilience.check_deadline(incident_id)
            remaining = resilience.default_deadline_seconds - elapsed - 1.0
            if remaining <= 0:
                return self._fallback(incident_id, "DEADLINE_EXCEEDED")
            timeout = min(self.limits.timeout_seconds, remaining)
            if not self.ledger.reserve(incident_id, prepared.input_tokens_upper_bound, self.limits):
                return self._fallback(incident_id, "BUDGET_EXHAUSTED")
            self._audit(incident_id, "OK", dispatch=True)
            self._append("sanitized-model-io.jsonl", {"incident_id": incident_id, "attempt": attempt + 1,
                         "direction": "input", "sanitized": True, "messages": prepared.messages,
                         "prompt_sha256": prepared.prompt_hash})
            try:
                reply = await asyncio.wait_for(self.provider.complete(
                    prepared.messages, max_output_tokens=self.limits.max_output_tokens,
                    timeout_seconds=timeout), timeout=timeout)
                resilience.check_cancellation(incident_id)
                self.ledger.record_usage(incident_id, reply.input_tokens, reply.output_tokens)
                if reply.tool_requested:
                    raise OutputRejected("TOOL_NOT_ALLOWED")
                if (reply.input_tokens is None or reply.output_tokens is None):
                    raise OutputRejected("USAGE_UNAVAILABLE")
                if reply.input_tokens > self.limits.max_input_tokens or reply.output_tokens > self.limits.max_output_tokens:
                    raise OutputRejected("LIMIT_EXCEEDED")
                candidates = validate_candidates(reply.content, prepared.evidence_ids)
                self._append("sanitized-model-io.jsonl", {"incident_id": incident_id, "attempt": attempt + 1,
                             "direction": "output", "sanitized": True, "candidates": candidates,
                             "usage": self.ledger.usage(incident_id)})
                self._append("hypothesis-candidates.jsonl", {
                    "incident_id": incident_id,
                    "observed_at": utc_now_z(),
                    "sanitized": True,
                    "candidates": candidates,
                })
                return {"status": "accepted", "reason_code": "OK", "candidates": candidates,
                        "usage": self.ledger.usage(incident_id), "manifest": self.manifest()}
            except OutputRejected as exc:
                self._append("sanitized-model-io.jsonl", {
                    "incident_id": incident_id, "attempt": attempt + 1, "direction": "output",
                    "sanitized": True, "content_retained": False, "reason_code": exc.code,
                })
                return self._fallback(incident_id, exc.code)
            except (ProviderError, TimeoutError) as exc:
                last_error = exc.code if isinstance(exc, ProviderError) else "BACKEND_TIMEOUT"
                self.ledger.record_usage(incident_id, None, None)
                self._append("llm-outage-fallback-audit.jsonl", {
                    "incident_id": incident_id, "observed_at": utc_now_z(), "attempt": attempt + 1,
                    "reason_code": last_error, "status": "ATTEMPT_FAILED", "sanitized": True})
                if isinstance(exc, ProviderError) and not exc.retryable:
                    break
                if attempt < self.limits.max_retries:
                    delay = 0.1 * (2 ** attempt) + random.uniform(0, 0.05)
                    await asyncio.sleep(min(delay, max(0, remaining - timeout)))
        return self._fallback(incident_id, last_error)
