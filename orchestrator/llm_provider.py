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


def _parse_reply(body: bytearray) -> ProviderReply:
    try:
        payload = json.loads(body, parse_constant=_invalid_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderError("INVALID_RESPONSE") from None
    if not isinstance(payload, dict):
        raise ProviderError("INVALID_RESPONSE")
    if "error" in payload:
        raise ProviderError("PROVIDER_POLICY")
    model = payload.get("model")
    if model not in (OPENROUTER_MODEL, OPENROUTER_MODEL.removesuffix(":free")):
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
        version=OPENROUTER_MODEL,
        tool_requested=tool_requested,
        cost_usd=cost,
    )


class OpenRouterProvider:
    provider_name = "openrouter"
    model_name = OPENROUTER_MODEL
    version = OPENROUTER_MODEL

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = _validate_api_key(api_key)
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
        request = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "provider": {
                "max_price": {"prompt": 0, "completion": 0},
                "allow_fallbacks": False,
                "data_collection": "allow",
            },
            "reasoning": {"exclude": True},
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
                        f"{OPENROUTER_BASE_URL}/chat/completions",
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
                        return _parse_reply(body)
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
