"""Minimal OpenAI-compatible Chat Completions client (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    provider: str = "openai-compatible"
    temperature: float = 0.2
    timeout_sec: float = 180.0
    max_tokens: int = 4096

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def _read_key_file(path: Path) -> str | None:
    """Read a key from a simple one-line or KEY=value file. Never log contents."""
    if not path.exists() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip().upper() in {
                "DEEPSEEK_API_KEY",
                "OPENAI_API_KEY",
                "VLH_LLM_API_KEY",
                "API_KEY",
            }:
                return v.strip().strip('"').strip("'")
        else:
            return line
    return None


def _try_cockpit_deepseek() -> tuple[str, str] | None:
    """Optional local desktop config (Antigravity Cockpit). Returns (base, key) or None."""
    path = Path.home() / ".antigravity_cockpit" / "codex_model_providers.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        base = str(item.get("baseUrl") or "")
        name = str(item.get("name") or "")
        if "deepseek" not in base.lower() and name.lower() != "deepseek":
            continue
        keys = item.get("apiKeys") or []
        if not keys:
            continue
        key = keys[0].get("apiKey") if isinstance(keys[0], dict) else None
        if key:
            return base.rstrip("/"), str(key)
    return None


def resolve_llm_config(
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    provider: str | None = None,
) -> LLMConfig:
    """Resolve LLM settings from CLI overrides, env, optional local config.

    Key sources (first hit wins for api_key):
      - explicit api_key arg
      - env named by api_key_env / VLH_LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
      - file VLH_LLM_API_KEY_FILE or ~/.config/vlh/llm_api_key
      - Antigravity Cockpit DeepSeek entry (local desktop only)
    """
    env_names = []
    if api_key_env:
        env_names.append(api_key_env)
    # Do NOT auto-pick APIROUTER_API_KEY for DeepSeek — it is often a different gateway.
    env_names += [
        "VLH_LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    ]
    key = api_key or ""
    if not key:
        for n in env_names:
            v = os.environ.get(n)
            if v:
                key = v
                break
    if not key:
        key_file = os.environ.get("VLH_LLM_API_KEY_FILE")
        candidates = []
        if key_file:
            candidates.append(Path(key_file))
        candidates.append(Path.home() / ".config" / "vlh" / "llm_api_key")
        for c in candidates:
            got = _read_key_file(c)
            if got:
                key = got
                break
    base = (
        base_url
        or os.environ.get("VLH_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or ""
    )
    mdl = model or os.environ.get("VLH_LLM_MODEL") or ""
    prov = provider or os.environ.get("VLH_LLM_PROVIDER") or ""

    # Prefer Cockpit DeepSeek when targeting deepseek and no explicit key yet
    want_deepseek = (
        (provider or "").lower() == "deepseek"
        or "deepseek" in (base_url or "").lower()
        or "deepseek" in (base or "").lower()
        or (model or "").lower().startswith("deepseek")
    )
    if want_deepseek and (not key or not base):
        cockpit = _try_cockpit_deepseek()
        if cockpit:
            c_base, c_key = cockpit
            if not base:
                base = c_base
            if not key:
                key = c_key
            if not prov:
                prov = "deepseek"
    elif not key or not base:
        cockpit = _try_cockpit_deepseek()
        if cockpit:
            c_base, c_key = cockpit
            if not base:
                base = c_base
            if not key:
                key = c_key
            if not prov:
                prov = "deepseek"

    if not base:
        # Ollama local fallback
        if not key:
            base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434") + "/v1"
            key = key or "ollama"
            if not mdl:
                mdl = "qwen2.5:14b"
            if not prov:
                prov = "ollama"
        else:
            base = "https://api.deepseek.com"
            if not prov:
                prov = "deepseek"

    if not mdl:
        if "deepseek" in base.lower() or prov == "deepseek":
            mdl = "deepseek-chat"
        elif prov == "ollama" or "11434" in base:
            mdl = "qwen2.5:14b"
        else:
            mdl = "gpt-4o-mini"

    if not prov:
        if "deepseek" in base.lower():
            prov = "deepseek"
        elif "11434" in base or "ollama" in base.lower():
            prov = "ollama"
        else:
            prov = "openai-compatible"

    if not key:
        raise RuntimeError(
            "No LLM API key found. Set VLH_LLM_API_KEY / DEEPSEEK_API_KEY, "
            "or VLH_LLM_BASE_URL to Ollama (http://127.0.0.1:11434/v1)."
        )

    # Normalize DeepSeek root to accept /v1 or bare host
    base = base.rstrip("/")
    return LLMConfig(base_url=base, model=mdl, api_key=key, provider=prov)


def _chat_url(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/v1"):
        return b + "/chat/completions"
    if b.endswith("/chat/completions"):
        return b
    # DeepSeek accepts both /chat/completions and /v1/chat/completions
    return b + "/chat/completions"


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        if json_mode and self.config.provider in {"deepseek", "openai-compatible", "ollama"}:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _chat_url(self.config.base_url),
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Unexpected LLM response shape: {str(body)[:200]}") from e

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                raw = self.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=True,
                )
                return extract_json_object(raw)
            except Exception as e:  # noqa: BLE001
                last_err = e
                # tighten instruction on retry
                messages = list(messages) + [
                    {
                        "role": "user",
                        "content": "上一次输出不是合法 JSON。请只输出一个 JSON 对象，不要 Markdown 代码围栏。",
                    }
                ]
        assert last_err is not None
        raise last_err


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty LLM content")
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    # direct
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # find first {...}
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(text[start : end + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"cannot parse JSON from LLM output: {text[:180]}")
