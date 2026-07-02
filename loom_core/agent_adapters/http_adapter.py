"""Backward-compatible alias for HttpAgentAdapter.

New code should use AgentAdapter(transport="http", protocol="loom", ...) directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_core.agent_adapters.adapter import AgentAdapter


class HttpAgentAdapter(AgentAdapter):
    """Cloud Loom agent adapter: snapshot POST → NDJSON stream + local writeback."""

    def __init__(
        self,
        adapter_id: str,
        endpoint: str,
        runtime: Any,
        hands_root: Path,
        auth_token: str | None = None,
        auth_token_env: str | None = None,
        capabilities: list[str] | None = None,
        timeout_s: float = 120.0,
        _transport: Any = None,
    ) -> None:
        super().__init__(
            adapter_id=adapter_id,
            transport="http",
            protocol="loom",
            endpoint=endpoint,
            auth_token=auth_token,
            auth_token_env=auth_token_env,
            timeout_s=timeout_s,
            runtime=runtime,
            hands_root=hands_root,
            capabilities=capabilities,
            _transport=_transport,
        )
