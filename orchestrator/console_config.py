"""Configuration helpers for AI Model & Telegram settings in the SRE Console."""

from __future__ import annotations

import os
import pathlib
import re
import time
from typing import Any

import httpx


PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "gemini": {
        "name": "Google Gemini (OpenAI Compat)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "base_url": "http://127.0.0.1:11434/v1",
        "key_env": "LLM_API_KEY",
        "default_model": "llama3.2",
    },
    "custom": {
        "name": "Custom OpenAI-Compatible API",
        "base_url": "",
        "key_env": "LLM_API_KEY",
        "default_model": "",
    },
}


def mask_secret(value: str | None) -> str:
    """Return a safely masked representation of an API key or bot token."""
    raw = (value or "").strip()
    if not raw:
        return "BELUM DIATUR"
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}...{raw[-4:]}"


def _sanitize_env_value(value: str) -> str:
    """Strip newlines and unsafe control chars before writing to .env."""
    cleaned = value.replace("\r", "").replace("\n", "").strip()
    if any(ord(c) < 32 for c in cleaned):
        raise ValueError("Nilai konfigurasi mengandung karakter kontrol tidak valid.")
    return cleaned


class EnvConfigManager:
    """Safe reader and updater for local .env settings (never modifies .env.example)."""

    def __init__(
        self,
        env_path: pathlib.Path | str = ".env",
        example_path: pathlib.Path | str = ".env.example",
    ) -> None:
        self.env_path = pathlib.Path(env_path)
        self.example_path = pathlib.Path(example_path)

    def read_all(self) -> dict[str, str]:
        """Load key-value pairs from .env (if present), overlaid with os.environ."""
        values: dict[str, str] = {}
        if self.env_path.exists():
            pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
            for line in self.env_path.read_text(encoding="utf-8").splitlines():
                match = pattern.match(line)
                if not match:
                    continue
                key = match.group(1)
                raw_val = match.group(2).strip()
                if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ("'", '"'):
                    raw_val = raw_val[1:-1]
                values[key] = raw_val
        for key in (
            "LLM_PROVIDER",
            "LLM_BASE_URL",
            "LLM_MODEL",
            "LLM_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
        ):
            if key in os.environ and os.environ[key]:
                values[key] = os.environ[key]
        return values

    def get(self, key: str, default: str = "") -> str:
        """Read a single setting value from env or .env."""
        if key in os.environ and os.environ[key]:
            return os.environ[key]
        return self.read_all().get(key, default)

    def set_values(self, updates: dict[str, str]) -> None:
        """Persist updates to .env and os.environ without touching .env.example."""
        sanitized = {k: _sanitize_env_value(v) for k, v in updates.items()}
        for k, v in sanitized.items():
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

        if not self.env_path.exists():
            if self.example_path.exists():
                lines = self.example_path.read_text(encoding="utf-8").splitlines()
            else:
                lines = []
        else:
            lines = self.env_path.read_text(encoding="utf-8").splitlines()

        remaining = dict(sanitized)
        new_lines: list[str] = []
        pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=.*$")

        for line in lines:
            match = pattern.match(line)
            if match and match.group(1) in remaining:
                key = match.group(1)
                val = remaining.pop(key)
                new_lines.append(f"{key}={val}")
            else:
                new_lines.append(line)

        for key, val in remaining.items():
            new_lines.append(f"{key}={val}")

        self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class ModelCatalogClient:
    """Fetch available models and verify connectivity against an OpenAI-compatible or Ollama API."""

    def __init__(self, *, client: httpx.Client | None = None, timeout_seconds: float = 8.0) -> None:
        self._client = client
        self.timeout_seconds = timeout_seconds

    def fetch_models(self, base_url: str, api_key: str = "") -> dict[str, Any]:
        """Query GET /models (or Ollama /api/tags fallback) and return model IDs."""
        clean_url = base_url.strip().rstrip("/")
        if not clean_url:
            return {"status": "ERROR", "models": [], "error": "Base URL belum diatur."}

        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        endpoints = [f"{clean_url}/models"]
        if clean_url.endswith("/v1"):
            endpoints.append(f"{clean_url[:-3]}/api/tags")

        start = time.monotonic()
        last_error = "Tidak ada respons dari endpoint."
        for endpoint in endpoints:
            try:
                if self._client is not None:
                    resp = self._client.get(endpoint, headers=headers, timeout=self.timeout_seconds)
                else:
                    with httpx.Client(timeout=self.timeout_seconds) as client:
                        resp = client.get(endpoint, headers=headers)

                latency_ms = round((time.monotonic() - start) * 1000, 1)
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:160]}"
                    continue

                payload = resp.json()
                models: list[str] = []
                if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                    for item in payload["data"]:
                        if isinstance(item, dict) and item.get("id"):
                            models.append(str(item["id"]))
                elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
                    for item in payload["models"]:
                        if isinstance(item, dict) and (item.get("name") or item.get("model")):
                            models.append(str(item.get("name") or item.get("model")))

                if models:
                    unique_sorted = sorted(dict.fromkeys(models))
                    return {
                        "status": "OK",
                        "models": unique_sorted,
                        "count": len(unique_sorted),
                        "latency_ms": latency_ms,
                        "endpoint": endpoint,
                        "error": "",
                    }
                last_error = f"Respons 200 dari {endpoint} namun daftar model kosong."
            except (httpx.HTTPError, ValueError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        return {
            "status": "ERROR",
            "models": [],
            "count": 0,
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "error": last_error,
        }

    def test_connection(self, base_url: str, api_key: str, model_name: str) -> dict[str, Any]:
        """Verify endpoint reachability and whether the selected model appears in the catalog."""
        res = self.fetch_models(base_url, api_key)
        if res["status"] != "OK":
            return res
        models = res["models"]
        model_found = model_name in models if model_name else False
        return {
            "status": "OK",
            "model_found": model_found,
            "count": res["count"],
            "latency_ms": res["latency_ms"],
            "error": "" if model_found else f"Koneksi OK, namun '{model_name}' tidak ditemukan di daftar /models.",
        }


class TelegramConfigHelper:
    """Outbound-only Telegram Bot API validation and chat discovery helper."""

    def __init__(self, *, client: httpx.Client | None = None, timeout_seconds: float = 6.0) -> None:
        self._client = client
        self.timeout_seconds = timeout_seconds

    def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, timeout=self.timeout_seconds)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.get(url)

    def test_bot(self, bot_token: str) -> dict[str, Any]:
        """Call Telegram getMe to verify bot token validity."""
        token = bot_token.strip()
        if not token:
            return {"status": "ERROR", "error": "Telegram Bot Token belum diisi."}
        try:
            resp = self._get(f"https://api.telegram.org/bot{token}/getMe")
            if resp.status_code >= 400:
                return {"status": "ERROR", "error": f"HTTP {resp.status_code}: Token ditolak Telegram."}
            data = resp.json()
            if not data.get("ok"):
                return {"status": "ERROR", "error": str(data.get("description", "Token tidak valid."))}
            bot_info = data.get("result", {})
            return {
                "status": "OK",
                "username": bot_info.get("username", "unknown"),
                "first_name": bot_info.get("first_name", "Bot"),
                "error": "",
            }
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    def discover_chats(self, bot_token: str) -> dict[str, Any]:
        """Inspect recent outbound-only getUpdates payloads to find available Chat IDs."""
        token = bot_token.strip()
        if not token:
            return {"status": "ERROR", "chats": [], "error": "Bot Token belum diisi."}
        try:
            resp = self._get(f"https://api.telegram.org/bot{token}/getUpdates?limit=20")
            if resp.status_code >= 400:
                return {"status": "ERROR", "chats": [], "error": f"HTTP {resp.status_code}"}
            data = resp.json()
            if not data.get("ok"):
                return {"status": "ERROR", "chats": [], "error": str(data.get("description", "Gagal mengambil updates."))}
            chats: dict[str, str] = {}
            for upd in data.get("result", []):
                msg = upd.get("message") or upd.get("my_chat_member", {})
                chat = msg.get("chat") if isinstance(msg, dict) else None
                if isinstance(chat, dict) and chat.get("id") is not None:
                    cid = str(chat["id"])
                    label = chat.get("title") or chat.get("username") or chat.get("first_name") or cid
                    chats[cid] = f"{cid} ({label})"
            return {"status": "OK", "chats": list(chats.items()), "error": ""}
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return {"status": "ERROR", "chats": [], "error": f"{type(exc).__name__}: {exc}"}
