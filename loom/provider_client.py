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
import shutil
import asyncio
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


class LLMConfigurationError(RuntimeError):
    """Raised when the configured provider cannot be called."""


class _MissingMessages:
    def __init__(self, message: str):
        self._message = message

    async def create(self, **_) -> None:
        raise LLMConfigurationError(self._message)


class _MissingLLMClient:
    def __init__(self, message: str):
        self.messages = _MissingMessages(message)


class _TextBlock:
    __slots__ = ("type", "text")

    def __init__(self, text: str):
        self.type = "text"
        self.text = text

    def model_dump(self) -> dict:
        return {"type": "text", "text": self.text}


class _BrainAgentResponse:
    def __init__(self, text: str):
        self.stop_reason = "end_turn"
        self.role = "assistant"
        self.content = [_TextBlock(text)]


class _BrainAgentMessages:
    def __init__(self, command: list[str], timeout_s: float = 180.0):
        self._command = list(command)
        self._timeout_s = timeout_s

    async def create(
        self,
        *,
        model: str = "",
        max_tokens: int = 0,
        system: str = "",
        tools: list | None = None,
        messages: list | None = None,
        timeout_s: float | None = None,
        **_,
    ) -> _BrainAgentResponse:
        prompt = _format_brain_agent_prompt(system=system, messages=messages or [])
        timeout = self._timeout_s if timeout_s is None else max(0.1, float(timeout_s))
        # Strip inherited proxy overrides so claude -p reaches its own API endpoint.
        clean_env = {
            **os.environ,
            "ANTHROPIC_BASE_URL": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        }
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise LLMConfigurationError(
                f"Brain agent command not found: {self._command[0]}"
            ) from exc
        except asyncio.TimeoutError as exc:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise LLMConfigurationError(
                f"Brain agent command timed out after {timeout:g}s"
            ) from exc

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode and not out:
            detail = err[:500] if err else f"exit code {proc.returncode}"
            raise LLMConfigurationError(f"Brain agent command failed: {detail}")
        return _BrainAgentResponse(out)


class _BrainAgentClient:
    def __init__(self, command: list[str]):
        self.messages = _BrainAgentMessages(command)


def _provider_env_key(provider: str) -> str:
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    return _PRESETS.get(provider, {}).get("env_key", "OPENAI_API_KEY")


def _missing_api_key_message(
    provider: str,
    env_key: str,
    *,
    brain_agent_command: list[str] | None = None,
) -> str:
    extra = ""
    if provider == "anthropic":
        extra = " or ANTHROPIC_AUTH_TOKEN"
    prefix = ""
    if brain_agent_command is not None:
        prefix = (
            "No usable Brain agent command was found "
            f"({brain_agent_command[0] if brain_agent_command else 'empty command'}). "
            "Set LOOM_BRAIN_AGENT_COMMAND to your local agent command, or "
        )
    return prefix + (
        f"LLM provider '{provider}' is missing credentials. "
        f"Set {env_key}{extra}, or configure api_key in {CONFIG_PATH}. "
        "Discord bot tokens only authenticate Discord."
    )


def _format_brain_agent_prompt(*, system: str, messages: list) -> str:
    parts: list[str] = []
    if system:
        parts.append(system.strip())
        parts.append("")
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").upper()
        parts.append(f"{role}:")
        parts.append(_message_content_text(msg.get("content", "")))
        parts.append("")
    parts.append("Reply only with the requested output. Do not add commentary.")
    return "\n".join(parts).strip()


def _message_content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        rendered: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    rendered.append(str(block.get("text", "")))
                else:
                    rendered.append(json.dumps(block, ensure_ascii=False))
            else:
                rendered.append(str(block))
        return "\n".join(item for item in rendered if item)
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def _parse_agent_command(raw: str) -> list[str]:
    raw = raw.strip()
    if raw:
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if str(item)]
            except (json.JSONDecodeError, TypeError):
                pass
        return raw.split()
    return []


def _default_claude_agent_command(*, model: str, effort: str) -> list[str]:
    # Loom is an embedded, non-interactive caller. User-level Claude settings can
    # contain unrelated proxy/model overrides and hooks; loading those made the
    # social router depend on a broken local proxy in real deployments.
    return [
        "claude",
        "-p",
        "--setting-sources",
        "project",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--model",
        model,
        "--effort",
        effort,
    ]


def _brain_agent_command() -> list[str]:
    command = _parse_agent_command(
        os.environ.get("LOOM_BRAIN_AGENT_COMMAND")
        or os.environ.get("LOOM_RUNTIME_HAND_COMMAND")
        or ""
    )
    return command or _default_claude_agent_command(model="sonnet", effort="high")


def _social_router_agent_command() -> list[str]:
    command = _parse_agent_command(
        os.environ.get("LOOM_SOCIAL_ROUTER_AGENT_COMMAND") or ""
    )
    return command or _default_claude_agent_command(model="haiku", effort="low")


def _command_exists(command: list[str]) -> bool:
    if not command:
        return False
    executable = command[0]
    if Path(executable).exists():
        return True
    return shutil.which(executable) is not None


def _provider_credentials_available(provider: str, api_key: str | None) -> bool:
    if api_key:
        return True
    env_key = _provider_env_key(provider)
    if os.environ.get(env_key):
        return True
    return provider == "anthropic" and bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ── Config I/O ──────────────────────────────────────────────────────────────

def read_config() -> dict:
    global _config
    if not _config:
        try:
            _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _config = {
                "default": dict(_DEFAULT),
                "hands": {},
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

def _build_client(
    r: dict,
    *,
    prefer_brain_agent: bool = False,
    brain_agent_command: list[str] | None = None,
) -> tuple:
    """Build (client, model) from a resolved config dict."""
    provider = r.get("provider", "anthropic").lower()
    api_key  = r.get("api_key") or None
    base_url = r.get("base_url") or None
    model    = r.get("model") or _DEFAULT["model"]

    selected_agent_command = None
    if prefer_brain_agent and not _provider_credentials_available(provider, api_key):
        selected_agent_command = brain_agent_command or _brain_agent_command()
        if _command_exists(selected_agent_command):
            return (_BrainAgentClient(selected_agent_command), model or "brain-agent")

    if provider == "anthropic":
        env_key = _provider_env_key(provider)
        key = api_key or os.environ.get(env_key, "")
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not key and not auth_token:
            return (
                _MissingLLMClient(
                    _missing_api_key_message(
                        provider,
                        env_key,
                        brain_agent_command=selected_agent_command,
                    )
                ),
                model,
            )
        import anthropic
        kwargs: dict = {}
        if key:
            kwargs["api_key"] = key
        elif auth_token:
            kwargs["auth_token"] = auth_token
        if base_url:
            kwargs["base_url"] = base_url
        client = anthropic.AsyncAnthropic(**kwargs)
    else:
        preset = _PRESETS.get(provider, {})
        env_key = _provider_env_key(provider)
        key = api_key or os.environ.get(env_key, "")
        if not key:
            return (
                _MissingLLMClient(
                    _missing_api_key_message(
                        provider,
                        env_key,
                        brain_agent_command=selected_agent_command,
                    )
                ),
                model,
            )
        try:
            import openai as _oai
        except ImportError as exc:
            raise ImportError(
                "openai package required for non-Anthropic providers: pip install openai"
            ) from exc
        url = base_url or preset.get("base_url", "https://api.openai.com/v1")
        raw = _oai.AsyncOpenAI(api_key=key, base_url=url)
        client = _OAIClient(raw)
    return (client, model)


def get_client_for_hand(hand_id: str) -> tuple:
    """Return (client, model) for the given hand, cached until write_config() clears it."""
    if hand_id not in _client_cache:
        _client_cache[hand_id] = _build_client(_resolve(hand_id))
    return _client_cache[hand_id]


def get_client_for_brain() -> tuple:
    """Return (client, model) for the Brain agent.

    Reads config["brain"] section if present; falls back to config["default"].
    Uses a more capable model than hands by default (sonnet vs haiku).
    """
    cache_key = "__brain__"
    if cache_key not in _client_cache:
        cfg = read_config()
        base = {**_DEFAULT, "model": "claude-sonnet-4-6"}
        base.update({k: v for k, v in cfg.get("default", {}).items() if v})
        base.update({k: v for k, v in cfg.get("brain", {}).items() if v})
        _client_cache[cache_key] = _build_client(base, prefer_brain_agent=True)
    return _client_cache[cache_key]


def get_client_for_social_router() -> tuple:
    """Return a fast client dedicated to social intent routing.

    The router has its own config/cache and command so conversational latency and
    reliability do not inherit the full Brain agent's model, hooks, or proxy.
    """
    cache_key = "__social_router__"
    if cache_key not in _client_cache:
        cfg = read_config()
        base = dict(_DEFAULT)
        base.update({k: v for k, v in cfg.get("default", {}).items() if v})
        base.update({k: v for k, v in cfg.get("router", {}).items() if v})
        _client_cache[cache_key] = _build_client(
            base,
            prefer_brain_agent=True,
            brain_agent_command=_social_router_agent_command(),
        )
    return _client_cache[cache_key]
