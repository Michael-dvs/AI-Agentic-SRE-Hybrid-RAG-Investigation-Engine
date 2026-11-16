"""Offline transport and credential boundaries for C13 (OPS-02, SEC-03, MCP-01)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from pathlib import Path

import httpx
import pytest

from orchestrator.llm_provider import (
    MAX_RESPONSE_BYTES,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OpenRouterProvider,
    ProviderError,
    ProviderReply,
    ReplayProvider,
    load_openrouter_api_key,
)


MESSAGES = [{"role": "user", "content": "Summarize synthetic evidence E1."}]
SYNTHETIC_KEY = "synthetic-provider-test-key"


def response_payload() -> dict:
    return {
        "model": OPENROUTER_MODEL,
        "choices": [{"message": {"content": '{"summary":"synthetic"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 25, "completion_tokens": 8, "total_tokens": 33, "cost": 0},
    }


def complete(provider, *, max_output_tokens=1024, timeout_seconds=15):
    return asyncio.run(provider.complete(
        MESSAGES, max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds
    ))


def provider_with_payload(payload):
    return OpenRouterProvider(
        SYNTHETIC_KEY,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )


def test_request_uses_only_approved_route_and_zero_cost_policy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload())

    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(handler))
    reply = complete(provider, timeout_seconds=99)
    assert provider.provider_name == "openrouter"
    assert provider.model_name == provider.version == OPENROUTER_MODEL
    assert reply == ProviderReply('{"summary":"synthetic"}', 25, 8, OPENROUTER_MODEL, OPENROUTER_MODEL, False, 0.0)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"{OPENROUTER_BASE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {SYNTHETIC_KEY}"
    assert request.headers["accept-encoding"] == "identity"
    assert set(request.extensions["timeout"].values()) == {15.0}
    assert json.loads(request.content) == {
        "model": OPENROUTER_MODEL,
        "messages": MESSAGES,
        "stream": False,
        "temperature": 0,
        "max_tokens": 1024,
        "provider": {
            "max_price": {"prompt": 0, "completion": 0},
            "allow_fallbacks": False,
            "data_collection": "allow",
        },
        "reasoning": {"exclude": True},
    }


def test_client_disables_environment_and_redirects(monkeypatch):
    actual_client = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return actual_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    complete(provider_with_payload(response_payload()))
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False


def test_reasoning_and_other_response_fields_never_escape():
    payload = response_payload()
    payload["choices"][0]["message"].update({
        "reasoning": "synthetic-hidden-reasoning-marker",
        "reasoning_details": [{"text": "synthetic-hidden-reasoning-marker"}],
    })
    payload["provider"] = "untrusted-provider-identity"
    payload["system_fingerprint"] = "untrusted-weights-claim"
    reply = complete(provider_with_payload(payload))
    assert "reasoning" not in json.dumps(asdict(reply))
    assert "untrusted" not in json.dumps(asdict(reply))
    assert reply.version == OPENROUTER_MODEL


@pytest.mark.parametrize("model", [OPENROUTER_MODEL, OPENROUTER_MODEL.removesuffix(":free")])
def test_response_model_accepts_only_exact_free_or_base_tag(model):
    payload = response_payload()
    payload["model"] = model
    assert complete(provider_with_payload(payload)).model == model


@pytest.mark.parametrize("model", [None, "other/model:free", OPENROUTER_MODEL + ":extended", [], 42])
def test_mismatched_model_is_not_allowed(model):
    payload = response_payload()
    payload["model"] = model
    with pytest.raises(ProviderError, match="^MODEL_NOT_ALLOWED$") as error:
        complete(provider_with_payload(payload))
    assert not error.value.retryable


@pytest.mark.parametrize("field", ["tool_calls", "function_call", "finish_reason"])
@pytest.mark.parametrize("content", [None, ""])
def test_tool_request_is_preserved_without_content(field, content):
    payload = response_payload()
    choice = payload["choices"][0]
    choice["message"]["content"] = content
    if field == "finish_reason":
        choice["finish_reason"] = "tool_calls"
    else:
        choice["message"][field] = {"name": "forbidden_synthetic_action"}
    reply = complete(provider_with_payload(payload))
    assert reply.tool_requested is True
    assert reply.content == ""
    assert "forbidden_synthetic_action" not in json.dumps(asdict(reply))


def test_missing_content_with_tool_call_is_preserved():
    payload = response_payload()
    payload["choices"][0]["message"] = {"tool_calls": []}
    assert complete(provider_with_payload(payload)).tool_requested


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens", "total_tokens"])
@pytest.mark.parametrize("value", [True, False, -1, 1.5, "12", [], {}])
def test_invalid_token_usage_is_not_retryable(field, value):
    payload = response_payload()
    payload["usage"][field] = value
    with pytest.raises(ProviderError, match="^INVALID_USAGE$") as error:
        complete(provider_with_payload(payload))
    assert not error.value.retryable


@pytest.mark.parametrize("usage", [True, [], "untrusted", 12, None])
def test_malformed_usage_is_rejected(usage):
    payload = response_payload()
    payload["usage"] = usage
    with pytest.raises(ProviderError, match="^INVALID_USAGE$"):
        complete(provider_with_payload(payload))


def test_absent_usage_is_unknown_not_fabricated_zero():
    payload = response_payload()
    del payload["usage"]
    reply = complete(provider_with_payload(payload))
    assert reply.input_tokens is None
    assert reply.output_tokens is None
    assert reply.cost_usd is None


@pytest.mark.parametrize("cost,code", [(0.01, "NONZERO_COST"), (1, "NONZERO_COST"), (-1, "INVALID_USAGE"), (True, "INVALID_USAGE"), ("0", "INVALID_USAGE")])
def test_only_numeric_zero_cost_is_accepted(cost, code):
    payload = response_payload()
    payload["usage"]["cost"] = cost
    with pytest.raises(ProviderError, match=f"^{code}$") as error:
        complete(provider_with_payload(payload))
    assert not error.value.retryable


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_usage_is_rejected(number):
    body = json.dumps(response_payload()).replace('"cost": 0', f'"cost": {number}')
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=body)
    ))
    with pytest.raises(ProviderError) as error:
        complete(provider)
    assert error.value.code in {"INVALID_USAGE", "INVALID_RESPONSE"}
    assert not error.value.retryable


@pytest.mark.parametrize("status,retryable", [(301, False), (400, False), (401, False), (402, False), (403, False), (404, False), (408, False), (429, True), (500, True), (502, True), (503, True)])
def test_http_errors_are_safe_and_do_not_retry_inside_provider(status, retryable, caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="synthetic-untrusted-error-marker", headers={"Location": "https://unapproved.invalid"})

    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as error:
        complete(provider)
    assert error.value.code == f"HTTP_{status}"
    assert str(error.value) == error.value.code
    assert error.value.retryable is retryable
    assert len(requests) == 1
    assert "synthetic-untrusted-error-marker" not in caplog.text
    assert SYNTHETIC_KEY not in caplog.text


@pytest.mark.parametrize("exception,code,retryable", [
    (httpx.ConnectError, "PROVIDER_OFFLINE", True),
    (httpx.ReadError, "PROVIDER_OFFLINE", True),
    (httpx.ReadTimeout, "PROVIDER_TIMEOUT", True),
    (httpx.RemoteProtocolError, "INVALID_HTTP", False),
])
def test_transport_errors_are_safe(exception, code, retryable):
    def handler(request):
        raise exception("synthetic-untrusted-error-marker", request=request)

    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as error:
        complete(provider)
    assert str(error.value) == code
    assert error.value.retryable is retryable
    assert error.value.__suppress_context__


@pytest.mark.parametrize("body", [b"not-json", b"\xff", b"[]", b"{}", b'{"model":'])
def test_malformed_response_is_not_retryable(body):
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=body)
    ))
    with pytest.raises(ProviderError) as error:
        complete(provider)
    assert not error.value.retryable
    assert str(error.value) in {"INVALID_RESPONSE", "MODEL_NOT_ALLOWED"}


@pytest.mark.parametrize("mutation", ["missing_message", "missing_content", "content_list", "choices_empty", "choices_multiple", "policy", "refusal", "error"])
def test_invalid_or_policy_response_has_no_output(mutation):
    payload = response_payload()
    choice = payload["choices"][0]
    if mutation == "missing_message":
        del choice["message"]
    elif mutation == "missing_content":
        del choice["message"]["content"]
    elif mutation == "content_list":
        choice["message"]["content"] = []
    elif mutation == "choices_empty":
        payload["choices"] = []
    elif mutation == "choices_multiple":
        payload["choices"] *= 2
    elif mutation == "policy":
        choice["finish_reason"] = "content_filter"
    elif mutation == "refusal":
        choice["message"]["refusal"] = "synthetic-refusal"
    else:
        payload["error"] = {"message": "synthetic-error"}
    with pytest.raises(ProviderError) as error:
        complete(provider_with_payload(payload))
    assert not error.value.retryable
    assert str(error.value) in {"INVALID_RESPONSE", "PROVIDER_POLICY"}


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def test_response_limit_stops_receiving_at_first_excess_chunk():
    stream = ChunkStream([b"x" * (MAX_RESPONSE_BYTES // 2), b"x" * (MAX_RESPONSE_BYTES // 2), b"x", b"not-read"])
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    ))
    with pytest.raises(ProviderError, match="^RESPONSE_TOO_LARGE$"):
        complete(provider)
    assert stream.read_count == 3
    assert stream.closed


def test_response_exactly_at_size_limit_is_accepted():
    body = json.dumps(response_payload()).encode()
    body += b" " * (MAX_RESPONSE_BYTES - len(body))
    stream = ChunkStream([body[:100], body[100:]])
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    ))
    assert complete(provider).input_tokens == 25
    assert stream.closed


def test_compressed_response_is_refused_before_reading():
    stream = ChunkStream([b"unread"])
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream, headers={"Content-Encoding": "gzip"})
    ))
    with pytest.raises(ProviderError, match="^INVALID_RESPONSE$"):
        complete(provider)
    assert stream.read_count == 0
    assert stream.closed


def test_hard_wall_timeout_covers_receiving_body():
    stream = ChunkStream([b"{"], delay=60)
    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)
    ))
    with pytest.raises(ProviderError, match="^PROVIDER_TIMEOUT$") as error:
        complete(provider, timeout_seconds=0.01)
    assert error.value.retryable
    assert stream.closed


def test_hard_wall_timeout_covers_waiting_for_headers():
    async def handler(request):
        await asyncio.sleep(60)
        return httpx.Response(200, json=response_payload())

    provider = OpenRouterProvider(SYNTHETIC_KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="^PROVIDER_TIMEOUT$"):
        complete(provider, timeout_seconds=0.01)


@pytest.mark.parametrize("value", [0, -1, True, 1025, 1.5])
def test_output_limit_rejected_without_network(value):
    with pytest.raises(ProviderError, match="^INVALID_TOKEN_LIMIT$"):
        complete(OpenRouterProvider(SYNTHETIC_KEY), max_output_tokens=value)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), "15"])
def test_invalid_timeout_rejected_without_network(value):
    with pytest.raises(ProviderError, match="^INVALID_TIMEOUT$"):
        complete(OpenRouterProvider(SYNTHETIC_KEY), timeout_seconds=value)


@pytest.mark.parametrize("messages", [[], [{"role": "tool", "content": "x"}], [{"role": "user", "content": "x", "tool_calls": []}], [{"role": "user", "content": []}]])
def test_message_fields_cannot_enable_tools(messages):
    with pytest.raises(ProviderError, match="^INVALID_MESSAGES$"):
        asyncio.run(OpenRouterProvider(SYNTHETIC_KEY).complete(messages, max_output_tokens=1, timeout_seconds=1))


def test_replay_order_errors_and_detached_call_records():
    reply = ProviderReply("synthetic", 2, 1, "c13-replay", "1")
    provider = ReplayProvider([ProviderError("PROVIDER_TIMEOUT", True), reply])
    messages = [{"role": "user", "content": "synthetic"}]
    with pytest.raises(ProviderError, match="PROVIDER_TIMEOUT"):
        complete(provider)
    assert asyncio.run(provider.complete(messages, max_output_tokens=10, timeout_seconds=2)) == reply
    messages[0]["content"] = "changed"
    assert provider.calls[1] == {"messages": [{"role": "user", "content": "synthetic"}], "max_output_tokens": 10, "timeout_seconds": 2}
    assert (provider.provider_name, provider.model_name, provider.version) == ("replay", "c13-replay", "1")
    with pytest.raises(ProviderError, match="^REPLAY_EXHAUSTED$"):
        complete(provider)
    assert len(provider.calls) == 3


def test_error_text_is_only_a_safe_code():
    error = ProviderError("untrusted response: synthetic secret")
    assert str(error) == error.code == "PROVIDER_ERROR"
    assert not error.retryable


def test_environment_key_takes_precedence_without_opening_file(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", SYNTHETIC_KEY)
    assert load_openrouter_api_key(tmp_path / "absent") == SYNTHETIC_KEY


@pytest.mark.parametrize("assignment", [
    "OPENROUTER_API_KEY=synthetic-provider-test-key",
    " export OPENROUTER_API_KEY = 'synthetic-provider-test-key' # synthetic comment",
    'OPENROUTER_API_KEY="synthetic-provider-test-key"',
    "OPENROUTER_API_KEY=synthetic-provider-test-key # synthetic comment",
])
def test_dotenv_selects_only_key_assignment(monkeypatch, tmp_path, assignment, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("UNRELATED_SYNTHETIC_SECRET=do-not-output\n# OPENROUTER_API_KEY=ignored\n" + assignment + "\n", encoding="utf-8")
    assert load_openrouter_api_key(path) == SYNTHETIC_KEY
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("assignment", [
    "OPENROUTER_API_KEY=",
    'OPENROUTER_API_KEY=""',
    'OPENROUTER_API_KEY="synthetic\nmultiline"',
    "OPENROUTER_API_KEY=synthetic\\\ncontinued",
    "OPENROUTER_API_KEY=two words",
    'OPENROUTER_API_KEY="synthetic" trailing',
    "OPENROUTER_API_KEY='unclosed",
])
def test_dotenv_rejects_empty_or_multiline_key(monkeypatch, tmp_path, assignment):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text(assignment, encoding="utf-8")
    with pytest.raises(ProviderError, match="^INVALID_API_KEY$"):
        load_openrouter_api_key(path)


def test_dotenv_rejects_duplicate_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("OPENROUTER_API_KEY=synthetic-one\nexport OPENROUTER_API_KEY=synthetic-two\n", encoding="utf-8")
    with pytest.raises(ProviderError, match="^DUPLICATE_API_KEY$"):
        load_openrouter_api_key(path)


@pytest.mark.parametrize("key", ["", "synthetic\nmultiline", "synthetic\rnewline", "synthetic key"])
def test_invalid_environment_key_does_not_fall_back(monkeypatch, tmp_path, key):
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    path = tmp_path / ".env"
    path.write_text("OPENROUTER_API_KEY=synthetic-valid", encoding="utf-8")
    with pytest.raises(ProviderError, match="^INVALID_API_KEY$"):
        load_openrouter_api_key(path)


def test_dotenv_never_executes_shell(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    marker = tmp_path / "must-not-exist"
    path = tmp_path / ".env"
    path.write_text(f"OPENROUTER_API_KEY=$(touch {marker})\n", encoding="utf-8")
    with pytest.raises(ProviderError, match="^INVALID_API_KEY$"):
        load_openrouter_api_key(path)
    assert not marker.exists()


def test_missing_dotenv_or_assignment_has_safe_error(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path: Path = tmp_path / ".env"
    with pytest.raises(ProviderError, match="^API_KEY_UNAVAILABLE$"):
        load_openrouter_api_key(path)
    path.write_text("UNRELATED_SYNTHETIC_SECRET=do-not-output\n", encoding="utf-8")
    with pytest.raises(ProviderError, match="^API_KEY_UNAVAILABLE$"):
        load_openrouter_api_key(path)
