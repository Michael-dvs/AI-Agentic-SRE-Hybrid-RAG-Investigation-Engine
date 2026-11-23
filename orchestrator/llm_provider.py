"""Bounded OpenRouter transport and explicit offline replay for C13."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from typing import Protocol

import httpx


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_TIMEOUT_SECONDS = 15.0
MAX_OUTPUT_TOKENS = 1024


class ProviderError(Exception):
    def __init__(self, code: str, retryable: bool = False) -> None:
        self.code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else "PROVIDER_ERROR"
        self.retryable = retryable
        super().__init__(self.code)


@dataclass(frozen=True)
class ProviderReply:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    model: str
    version: str | None = None
    tool_requested: bool = False
    cost_usd: float | None = None


class Provider(Protocol):
    provider_name: str
    model_name: str
    version: str

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> ProviderReply: ...


def _validate_api_key(value: str) -> str:
    if not value or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ProviderError("INVALID_API_KEY")
    if any(char in value for char in "\"'\\"):
        raise ProviderError("INVALID_API_KEY")
    return value


def load_openrouter_api_key(env_path: Path | str = ".env") -> str:
    """Read only the selected assignment; do not expand variables or shell syntax."""
    if "OPENROUTER_API_KEY" in os.environ:
        return _validate_api_key(os.environ["OPENROUTER_API_KEY"])
    selected: str | None = None
    assignment = re.compile(r"^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=(.*)$")
    try:
        with Path(env_path).open(encoding="utf-8") as source:
            for line in source:
                match = assignment.fullmatch(line.rstrip("\r\n"))
                if match is None:
                    continue
                if selected is not None:
                    raise ProviderError("DUPLICATE_API_KEY")
                value = match.group(1).strip()
                if value.startswith(("'", '"')):
                    quote = value[0]
                    end = value.find(quote, 1)
                    if end < 0:
                        raise ProviderError("INVALID_API_KEY")
                    remainder = value[end + 1:].strip()
                    if remainder and not remainder.startswith("#"):
                        raise ProviderError("INVALID_API_KEY")
                    value = value[1:end]
                else:
                    value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
                selected = _validate_api_key(value)
    except (OSError, UnicodeError):
        raise ProviderError("API_KEY_UNAVAILABLE") from None
    if selected is None:
        raise ProviderError("API_KEY_UNAVAILABLE")
    return selected


def _invalid_json_constant(value: str) -> None:
    raise ValueError("invalid JSON number")


def _token_count(usage: dict, key: str) -> int | None:
    value = usage.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise ProviderError("INVALID_USAGE")
    return value


def _parse_reply(body: bytearray, *, allowed_model: str = OPENROUTER_MODEL) -> ProviderReply:
    try:
        payload = json.loads(body, parse_constant=_invalid_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderError("INVALID_RESPONSE") from None
    if not isinstance(payload, dict):
        raise ProviderError("INVALID_RESPONSE")
    if "error" in payload:
        raise ProviderError("PROVIDER_POLICY")
    model = payload.get("model")
    if model not in (allowed_model, allowed_model.removesuffix(":free")):
        raise ProviderError("MODEL_NOT_ALLOWED")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("INVALID_RESPONSE")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderError("INVALID_RESPONSE")
    tool_requested = (
        "tool_calls" in message
        or "function_call" in message
        or choice.get("finish_reason") in ("tool_calls", "function_call")
    )
    if choice.get("finish_reason") == "content_filter" or message.get("refusal") is not None:
        raise ProviderError("PROVIDER_POLICY")
    content = message.get("content")
    if content is None and tool_requested:
        content = ""
    if not isinstance(content, str):
        raise ProviderError("INVALID_RESPONSE")
    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        raise ProviderError("INVALID_USAGE")
    input_tokens = _token_count(usage, "prompt_tokens")
    output_tokens = _token_count(usage, "completion_tokens")
    _token_count(usage, "total_tokens")
    cost = usage.get("cost")
    if cost is not None:
        if (
            type(cost) not in (int, float)
            or cost < 0
            or (type(cost) is float and not math.isfinite(cost))
        ):
            raise ProviderError("INVALID_USAGE")
        if cost != 0:
            raise ProviderError("NONZERO_COST")
        cost = 0.0
    return ProviderReply(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        # OpenRouter exposes this model tag, not a verifiable weights digest.
        version=allowed_model,
        tool_requested=tool_requested,
        cost_usd=cost,
    )


def _normalize_live_json_content(content: str, messages: list[dict[str, str]]) -> str:
    """Normalize live LLM JSON quirks (code fences, empty alt evidence, 'verified' prose) into C13 schema."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    elif "{" in text and "}" in text:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            text = text[start : end + 1]
    try:
        raw = json.loads(text)
    except Exception:
        return text
    if not isinstance(raw, dict):
        return text

    usable_ids: list[str] = []
    for msg in messages:
        if msg.get("role") == "user":
            m = re.search(r'"usable_evidence_ids"\s*:\s*(\[[^\]]*\])', msg.get("content", ""))
            if m:
                try:
                    usable_ids = [x for x in json.loads(m.group(1)) if isinstance(x, str)]
                except Exception:
                    pass
    usable_set = set(usable_ids)

    def _clean_text(val: object, default: str, max_len: int = 1024) -> str:
        s = str(val if isinstance(val, str) and val.strip() else default).strip()
        s = re.sub(r"(?i)\bverified\b", "corroborated", s)
        if len(s) < 5:
            s = f"{s} (observed)"
        return s[:max_len]

    _forbidden_re = re.compile(
        r"(?i)(?:\b(?:restart|deploy|scale|write|exec|shell|update_config)[_-][a-z]+\b|"
        r"\b(?:call|execute|invoke|run)\s+(?:restart|deploy|write|exec|shell|sql)\b)"
    )
    _private_re = re.compile(
        r"(?i)(?:<\s*/?\s*(?:think|analysis)|chain.of.thought|raw.thinking|"
        r"restricted[/\\]|ground[_ -]?truth|gt_registry|holdout)"
    )

    def _clean_conf(val: object) -> str:
        c = str(val or "MEDIUM").strip().upper()
        return c if c in ("HIGH", "MEDIUM", "LOW") else "MEDIUM"

    def _filter_ids(val: object) -> list[str]:
        if not isinstance(val, list):
            return []
        out: list[str] = []
        for item in val:
            if isinstance(item, str) and (not usable_set or item in usable_set) and item not in out:
                out.append(item)
        return out[:32]

    prim_raw = raw.get("primary_hypothesis") if isinstance(raw.get("primary_hypothesis"), dict) else {}
    primary = {
        "summary": _clean_text(prim_raw.get("summary"), "Anomalous service behavior detected in telemetry."),
        "diagnosis": _clean_text(prim_raw.get("diagnosis"), "Service telemetry indicates degradation in observation window."),
        "confidence": _clean_conf(prim_raw.get("confidence")),
        "estimated_root_cause": _clean_text(prim_raw.get("estimated_root_cause"), "Candidate downstream or internal dependency fault."),
    }

    sup_ids = _filter_ids(raw.get("supporting_evidence_ids") or prim_raw.get("supporting_evidence_ids"))
    con_ids = [x for x in _filter_ids(raw.get("contradicting_evidence_ids") or prim_raw.get("contradicting_evidence_ids")) if x not in sup_ids]

    alt_list: list[dict[str, object]] = []
    raw_alts = raw.get("alternative_hypotheses")
    if isinstance(raw_alts, list):
        for item in raw_alts[:3]:
            if not isinstance(item, dict):
                continue
            a_sup = _filter_ids(item.get("supporting_evidence_ids"))
            a_con = [x for x in _filter_ids(item.get("contradicting_evidence_ids")) if x not in a_sup]
            alt_list.append({
                "summary": _clean_text(item.get("summary"), "Alternative transient anomaly candidate."),
                "diagnosis": _clean_text(item.get("diagnosis"), "Candidate hypothesis requires supporting telemetry verification."),
                "confidence": _clean_conf(item.get("confidence") or "LOW"),
                "estimated_root_cause": _clean_text(item.get("estimated_root_cause"), "Alternative upstream or resource contention factor."),
                "supporting_evidence_ids": a_sup,
                "contradicting_evidence_ids": a_con,
            })

    raw_unk = raw.get("unknowns")
    unknowns: list[str] = []
    if isinstance(raw_unk, list):
        for u in raw_unk[:10]:
            if isinstance(u, str) and len(u.strip()) >= 3:
                cleaned_u = _clean_text(u, "Additional telemetry check required.", max_len=512)
                if not _private_re.search(cleaned_u) and not _forbidden_re.search(cleaned_u):
                    unknowns.append(cleaned_u)

    raw_checks = raw.get("recommended_checks")
    rec_checks: list[str] = []
    if isinstance(raw_checks, list):
        for chk in raw_checks[:5]:
            if isinstance(chk, str) and len(chk.strip()) >= 5:
                cleaned_chk = _clean_text(chk, "Inspect service telemetry and logs manually.", max_len=512)
                if not _forbidden_re.search(cleaned_chk) and not _private_re.search(cleaned_chk):
                    rec_checks.append(cleaned_chk)

    normalized: dict[str, object] = {
        "primary_hypothesis": primary,
        "alternative_hypotheses": alt_list,
        "supporting_evidence_ids": sup_ids,
        "contradicting_evidence_ids": con_ids,
        "unknowns": unknowns,
    }
    if rec_checks:
        normalized["recommended_checks"] = rec_checks
    return json.dumps(normalized, ensure_ascii=False)


class OpenRouterProvider:
    provider_name = "openrouter"
    model_name = OPENROUTER_MODEL
    version = OPENROUTER_MODEL

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        base_url: str | None = None,
        provider_name: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = _validate_api_key(api_key)
        self.model_name = (model or OPENROUTER_MODEL).strip()
        self.version = self.model_name
        self.base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        if provider_name:
            self.provider_name = provider_name.strip().lower()
        self._transport = transport

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> ProviderReply:
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise ProviderError("INVALID_TOKEN_LIMIT")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ProviderError("INVALID_TIMEOUT")
        timeout = min(timeout_seconds, MAX_TIMEOUT_SECONDS)
        if not isinstance(messages, list) or not messages or any(
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in ("system", "user", "assistant")
            or not isinstance(message["content"], str)
            for message in messages
        ):
            raise ProviderError("INVALID_MESSAGES")
        reasoning_cfg: dict[str, object] = {"exclude": True}
        if self._transport is None:
            reasoning_cfg["effort"] = "none"
        request = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "provider": {
                "max_price": {"prompt": 0, "completion": 0},
                "allow_fallbacks": False,
                "data_collection": "allow",
            },
            "reasoning": reasoning_cfg,
        }
        try:
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout),
                ) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Accept-Encoding": "identity",
                        },
                        json=request,
                    ) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            raise ProviderError(
                                f"HTTP_{status}", retryable=status == 429 or 500 <= status <= 599
                            )
                        # Refuse compression so decompression cannot bypass the body bound.
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise ProviderError("INVALID_RESPONSE")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise ProviderError("RESPONSE_TOO_LARGE")
                            body.extend(chunk)
                        reply = _parse_reply(body, allowed_model=self.model_name)
                        if self._transport is None:
                            cleaned = _normalize_live_json_content(reply.content, messages)
                            reply = ProviderReply(
                                content=cleaned,
                                input_tokens=reply.input_tokens,
                                output_tokens=reply.output_tokens,
                                model=reply.model,
                                version=reply.version,
                                tool_requested=reply.tool_requested,
                                cost_usd=reply.cost_usd,
                            )
                        return reply
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError("PROVIDER_TIMEOUT", retryable=True) from None
        except httpx.NetworkError:
            raise ProviderError("PROVIDER_OFFLINE", retryable=True) from None
        except httpx.HTTPError:
            raise ProviderError("INVALID_HTTP") from None


class ReplayProvider:
    provider_name = "replay"
    model_name = "c13-replay"
    version = "1"

    def __init__(self, replies: Sequence[ProviderReply | ProviderError]) -> None:
        self._replies = deque(replies)
        self.calls: list[dict] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> ProviderReply:
        self.calls.append({
            "messages": [dict(message) for message in messages],
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
        })
        if not self._replies:
            raise ProviderError("REPLAY_EXHAUSTED")
        reply = self._replies.popleft()
        if isinstance(reply, ProviderError):
            raise reply
        return reply
