"""provider_client.py — multi-provider async LLM client factory for Loom Hands.

Supported providers:
  anthropic (default) — native Anthropic SDK
  openai              — openai SDK
  groq                — OpenAI-compat, auto-fills base_url
  deepseek            — OpenAI-compat, auto-fills base_url
  gemini              — OpenAI-compat, auto-fills base_url

Config is read from loom-config.json. Call write_config() to hot-reload without restart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "loom-config.json"

_DEFAULT: dict = {
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "api_key": "",
    "base_url": "",
}

_PRESETS: dict = {
    "xai":      {"base_url": "https://api.x.ai/v1",                                      "env_key": "XAI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1",                              "env_key": "DEEPSEEK_API_KEY"},
    "gemini":   {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "env_key": "GEMINI_API_KEY"},
    "openai":   {"base_url": "https://api.openai.com/v1",                                "env_key": "OPENAI_API_KEY"},
}

_STOP_MAP: dict = {
    "tool_calls":     "tool_use",
    "stop":           "end_turn",
    "length":         "max_tokens",
    "content_filter": "end_turn",
}

_config: dict = {}
_client_cache: dict[str, tuple] = {}


# ── Config I/O ──────────────────────────────────────────────────────────────

def read_config() -> dict:
    global _config
    if not _config:
        try:
            _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _config = {
                "default": dict(_DEFAULT),
                "hands": {h: {} for h in ("market", "sentiment", "target", "position")},
            }
    return _config


def write_config(cfg: dict) -> None:
    """Persist config to disk and invalidate client cache."""
    global _config, _client_cache
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    _config = cfg
    _client_cache.clear()


def _resolve(hand_id: str) -> dict:
    cfg = read_config()
    merged = {**_DEFAULT, **cfg.get("default", {})}
    for k, v in cfg.get("hands", {}).get(hand_id, {}).items():
        if v:  # skip empty strings — they mean "inherit default"
            merged[k] = v
    return merged


# ── OpenAI-compat message/tool adapters ─────────────────────────────────────

def _tools_to_oai(tools: list | None) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in (tools or [])
    ]


def _msgs_to_oai(messages: list) -> list:
    out: list = []
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
            else:
                texts: list[str] = []
                results: list[dict] = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        results.append({
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": b.get("content", ""),
                        })
                    elif b.get("type") == "text":
                        texts.append(b["text"])
                if texts:
                    out.append({"role": "user", "content": "\n".join(texts)})
                out.extend(results)
        elif role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
            else:
                texts = []
                tool_calls: list[dict] = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        texts.append(b["text"])
                    elif b.get("type") == "tool_use":
                        tool_calls.append({
                            "id": b["id"],
                            "type": "function",
                            "function": {
                                "name": b["name"],
                                "arguments": json.dumps(b.get("input", {})),
                            },
                        })
                obj: dict = {"role": "assistant"}
                if texts:
                    obj["content"] = "\n".join(texts)
                if tool_calls:
                    obj["tool_calls"] = tool_calls
                out.append(obj)
    return out


# ── Lightweight Anthropic-compatible response wrappers ───────────────────────

class _Block:
    """Drop-in for Anthropic SDK TextBlock / ToolUseBlock."""
    __slots__ = ("type", "text", "id", "name", "input")

    def __init__(self, d: dict):
        self.type  = d.get("type", "text")
        self.text  = d.get("text", "")
        self.id    = d.get("id", "")
        self.name  = d.get("name", "")
        self.input = d.get("input", {})

    def model_dump(self) -> dict:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class _OAIResponse:
    """Wraps an OpenAI chat completion choice as an Anthropic-compatible response."""
    def __init__(self, choice):
        msg = choice.message
        self.stop_reason = _STOP_MAP.get(choice.finish_reason or "stop", "end_turn")
        self.role = "assistant"
        self._blocks: list[dict] = []
        if msg.content:
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            if text:
                self._blocks.append({"type": "text", "text": text})
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                inp = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                inp = {}
            self._blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": inp,
            })

    @property
    def content(self) -> list[_Block]:
        return [_Block(b) for b in self._blocks]


class _OAIMessages:
    def __init__(self, raw):
        self._raw = raw

    async def create(self, *, model: str, max_tokens: int, system: str,
                     tools: list, messages: list, **_) -> _OAIResponse:
        oai: list = []
        if system:
            oai.append({"role": "system", "content": system})
        oai.extend(_msgs_to_oai(messages))
        params: dict = {"model": model, "max_completion_tokens": max_tokens, "messages": oai}
        oai_tools = _tools_to_oai(tools)
        if oai_tools:
            params["tools"] = oai_tools
        resp = await self._raw.chat.completions.create(**params)
        return _OAIResponse(resp.choices[0])


class _OAIClient:
    def __init__(self, raw):
        self.messages = _OAIMessages(raw)


# ── Factory ──────────────────────────────────────────────────────────────────

def get_client_for_hand(hand_id: str) -> tuple:
    """Return (client, model) for the given hand, cached until write_config() clears it."""
    if hand_id not in _client_cache:
        r = _resolve(hand_id)
        provider = r.get("provider", "anthropic").lower()
        api_key  = r.get("api_key") or None
        base_url = r.get("base_url") or None
        model    = r.get("model") or _DEFAULT["model"]

        if provider == "anthropic":
            import anthropic
            kwargs: dict = {}
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["base_url"] = base_url
            client = anthropic.AsyncAnthropic(**kwargs)
        else:
            try:
                import openai as _oai
            except ImportError as exc:
                raise ImportError(
                    "openai package required for non-Anthropic providers: pip install openai"
                ) from exc
            preset = _PRESETS.get(provider, {})
            key = api_key or os.environ.get(preset.get("env_key", "OPENAI_API_KEY"), "")
            url = base_url or preset.get("base_url", "https://api.openai.com/v1")
            raw = _oai.AsyncOpenAI(api_key=key, base_url=url)
            client = _OAIClient(raw)

        _client_cache[hand_id] = (client, model)
    return _client_cache[hand_id]
