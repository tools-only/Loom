"""Direct Hand -> Codex app-server channel.

This module deliberately has no dependency on Loom's adapter/provider layer.  It
is the small, testable transport boundary used to prove the Codex channel before
it is registered as a runtime provider.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any


class CodexHandChannelError(RuntimeError):
    """Base error raised by the direct Codex hand channel."""


class CodexHandChannelTimeout(CodexHandChannelError):
    """The app-server lifecycle exceeded the channel deadline."""


class InvalidCodexArtifact(CodexHandChannelError):
    """Codex returned a response that is not a complete Loom artifact."""


@dataclass(frozen=True)
class HandRequest:
    task: str
    hand_id: str
    cwd: str | None = None
    system_prompt: str = ""
    context: dict[str, Any] = field(default_factory=dict)


class CodexHandChannel:
    """Run one Hand request through the official Codex app-server SDK."""

    def __init__(self, *, codex_home: str | None = None, timeout_s: float = 180.0):
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        self._codex_home = codex_home
        self._timeout_s = timeout_s

    async def run(self, request: HandRequest) -> dict[str, Any]:
        """Return the validated artifact body for a Hand request."""
        try:
            return await asyncio.wait_for(self._run(request), timeout=self._timeout_s)
        except asyncio.TimeoutError as exc:
            raise CodexHandChannelTimeout(
                f"Codex app-server exceeded the {self._timeout_s:g}s channel deadline"
            ) from exc

    async def _run(self, request: HandRequest) -> dict[str, Any]:
        try:
            from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox
        except ImportError as exc:
            raise CodexHandChannelError(
                "The direct Codex channel requires the openai-codex package"
            ) from exc

        cwd = os.path.abspath(request.cwd or os.getcwd())
        config = CodexConfig(
            launch_args_override=None,
            cwd=cwd,
            env={"CODEX_HOME": self._codex_home} if self._codex_home else None,
            client_name="loom_hand_channel",
            client_title="Loom Hand Channel",
            client_version="0.1.0",
            experimental_api=True,
        )
        approval_mode = ApprovalMode.deny_all
        sandbox = Sandbox.workspace_write
        completed_messages: list[str] = []
        delta_messages: dict[str, str] = {}
        turn_status = ""

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(
                approval_mode=approval_mode,
                cwd=cwd,
                ephemeral=True,
                sandbox=sandbox,
            )
            turn = await thread.turn(
                self._prompt(request),
                approval_mode=approval_mode,
                cwd=cwd,
                output_schema=complete_artifact_schema(),
                sandbox=sandbox,
            )
            async for notification in turn.stream():
                method = str(getattr(notification, "method", ""))
                params = _notification_params(notification)
                if method == "item/agentMessage/delta":
                    item_id = str(params.get("itemId") or params.get("item_id") or "default")
                    delta = params.get("delta")
                    if isinstance(delta, str):
                        delta_messages[item_id] = delta_messages.get(item_id, "") + delta
                elif method == "item/completed":
                    item = params.get("item") or {}
                    if isinstance(item, dict) and item.get("type") == "agentMessage":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            completed_messages.append(text)
                elif method == "turn/completed":
                    turn_payload = params.get("turn") or {}
                    if isinstance(turn_payload, dict):
                        turn_status = str(turn_payload.get("status") or "").lower()
                elif method in {"error", "turn/error"}:
                    raise CodexHandChannelError(_notification_error(params))

        if turn_status in {"failed", "interrupted", "cancelled"}:
            raise CodexHandChannelError(f"Codex turn ended with status: {turn_status}")

        if completed_messages:
            content = completed_messages[-1]
        else:
            content = "\n".join(delta_messages.values())
        event = _decode_artifact_event(content)
        artifact = event["artifact"]
        violations = validate_complete_artifact(artifact)
        if violations:
            raise InvalidCodexArtifact("Invalid complete artifact: " + "; ".join(violations))
        return artifact

    @staticmethod
    def _prompt(request: HandRequest) -> str:
        envelope = {
            "task": request.task,
            "hand_id": request.hand_id,
            "context": request.context,
        }
        if request.cwd:
            envelope["cwd"] = request.cwd
        if request.system_prompt:
            envelope["system_prompt"] = request.system_prompt
        return (
            f"{request.system_prompt}\n\n" if request.system_prompt else ""
        ) + (
            "You are a Loom Hand running through Codex app-server. Complete the task, then "
            "return exactly one JSON object matching the supplied output schema. Populate every "
            "artifact field. Use empty arrays only when a field truly has no applicable entries. "
            "Every raw_items and raw_sources entry must contain a non-empty URL.\n\n"
            "Task envelope:\n"
            + json.dumps(envelope, ensure_ascii=False, indent=2)
        )


def complete_artifact_schema() -> dict[str, Any]:
    """JSON Schema supplied to Codex structured output."""
    string = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "const": "run.artifact"},
            "artifact": {
                "type": "object",
                "properties": {
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "key_claims": {"type": "array", "items": string},
                            "gaps": {"type": "array", "items": string},
                            "resources_used": {"type": "array", "items": string},
                            "source_notes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source": string,
                                        "tier": string,
                                        "freshness": string,
                                        "note": string,
                                    },
                                    "required": ["source", "tier", "freshness", "note"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "confidence",
                            "key_claims",
                            "gaps",
                            "resources_used",
                            "source_notes",
                        ],
                        "additionalProperties": False,
                    },
                    "narrative": string,
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": string,
                                "title": string,
                                "summary": string,
                                "bullets": {"type": "array", "items": string},
                            },
                            "required": ["id", "title", "summary", "bullets"],
                            "additionalProperties": False,
                        },
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": string,
                                "support": string,
                                "source": string,
                                "source_tier": string,
                                "freshness": string,
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": [
                                "claim",
                                "support",
                                "source",
                                "source_tier",
                                "freshness",
                                "confidence",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "raw_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_type": string,
                                "title": string,
                                "label": string,
                                "value": string,
                                "source": string,
                                "tier": string,
                                "published_at": string,
                                "freshness": string,
                                "summary": string,
                                "relevance": string,
                                "url": string,
                            },
                            "required": [
                                "item_type",
                                "title",
                                "label",
                                "value",
                                "source",
                                "tier",
                                "published_at",
                                "freshness",
                                "summary",
                                "relevance",
                                "url",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "raw_sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "resource_id": string,
                                "fetched_at": string,
                                "content_type": string,
                                "summary": string,
                                "url": string,
                                "query": string,
                            },
                            "required": [
                                "resource_id",
                                "fetched_at",
                                "content_type",
                                "summary",
                                "url",
                                "query",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "metadata",
                    "narrative",
                    "sections",
                    "evidence",
                    "raw_items",
                    "raw_sources",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["type", "artifact"],
        "additionalProperties": False,
    }


def validate_complete_artifact(artifact: Any) -> list[str]:
    """Return semantic contract violations not expressible reliably in schema."""
    if not isinstance(artifact, dict):
        return ["artifact must be an object"]
    required = ("metadata", "narrative", "sections", "evidence", "raw_items", "raw_sources")
    violations = [f"missing {name}" for name in required if name not in artifact]
    if violations:
        return violations
    metadata = artifact["metadata"]
    if not isinstance(metadata, dict):
        violations.append("metadata must be an object")
    else:
        for name in ("key_claims", "gaps", "resources_used", "source_notes"):
            if not isinstance(metadata.get(name), list):
                violations.append(f"metadata.{name} must be an array")
        confidence = metadata.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            violations.append("metadata.confidence must be between 0 and 1")
    if not isinstance(artifact["narrative"], str) or not artifact["narrative"].strip():
        violations.append("narrative must be non-empty")
    for name in ("sections", "evidence", "raw_items", "raw_sources"):
        if not isinstance(artifact[name], list):
            violations.append(f"{name} must be an array")
    for index, item in enumerate(artifact.get("evidence", [])):
        if not isinstance(item, dict):
            violations.append(f"evidence[{index}] must be an object")
            continue
        for field_name in ("claim", "support", "source", "source_tier", "freshness"):
            if not isinstance(item.get(field_name), str) or not item[field_name].strip():
                violations.append(f"evidence[{index}].{field_name} must be non-empty")
        confidence = item.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            violations.append(f"evidence[{index}].confidence must be between 0 and 1")
    for index, item in enumerate(artifact.get("raw_items", [])):
        if not isinstance(item, dict) or not str(item.get("url") or "").strip():
            violations.append(f"raw_items[{index}].url must be non-empty")
    for index, source in enumerate(artifact.get("raw_sources", [])):
        if not isinstance(source, dict) or not str(source.get("url") or "").strip():
            violations.append(f"raw_sources[{index}].url must be non-empty")
    return violations


def _notification_params(notification: Any) -> dict[str, Any]:
    payload = getattr(notification, "payload", None)
    if hasattr(payload, "model_dump"):
        value = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
    else:
        value = payload
    return value if isinstance(value, dict) else {}


def _notification_error(params: dict[str, Any]) -> str:
    error = params.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(params.get("message") or error or "Codex app-server reported an error")


def _decode_artifact_event(content: str) -> dict[str, Any]:
    if not content.strip():
        raise InvalidCodexArtifact("Codex turn completed without a final agent message")
    try:
        value = json.loads(content.strip())
    except json.JSONDecodeError as exc:
        raise InvalidCodexArtifact("Codex final message was not exactly one JSON object") from exc
    if not isinstance(value, dict) or value.get("type") != "run.artifact":
        raise InvalidCodexArtifact("Codex final message must be a run.artifact event")
    if "artifact" not in value:
        raise InvalidCodexArtifact("Codex run.artifact event is missing artifact")
    return value


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run the direct Hand -> Codex channel")
    parser.add_argument("task", help="Hand task to execute")
    parser.add_argument("--hand-id", default="codex-smoke-hand")
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    channel = CodexHandChannel(codex_home=args.codex_home, timeout_s=args.timeout)
    artifact = asyncio.run(
        channel.run(
            HandRequest(
                task=args.task,
                hand_id=args.hand_id,
                cwd=args.cwd,
            )
        )
    )
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
