"""BudgetGovernor — per-episode resource budget enforcement.

Debits are called by the orchestrator at phase boundaries. When a cap is
exceeded, BudgetExceeded is raised and the orchestrator transitions the
episode to early Synthesizing with a quality_gap — it does NOT abort,
because partial synthesis is better than nothing.

Caps of 0 mean "unlimited" (no enforcement for that dimension).
"""
from __future__ import annotations

import time
from typing import Any


class BudgetExceeded(Exception):
    """Raised when a resource cap is exceeded.

    Attributes
    ----------
    resource : str
        "tokens" | "cost_usd" | "wall_clock_ms"
    used : int | float
    cap  : int | float
    """

    def __init__(self, resource: str, used: Any, cap: Any) -> None:
        super().__init__(f"Budget exceeded [{resource}]: used={used} cap={cap}")
        self.resource = resource
        self.used = used
        self.cap = cap


class BudgetGovernor:
    """Track and enforce token, cost, and wall-clock budgets for one episode.

    Parameters
    ----------
    token_total : int
        Maximum tokens across all hands combined. 0 = unlimited.
    cost_cap_usd : float
        Maximum USD spend. 0.0 = unlimited.
    wall_clock_ms : int
        Maximum elapsed wall-clock time in milliseconds. 0 = unlimited.
    """

    def __init__(
        self,
        token_total: int = 0,
        cost_cap_usd: float = 0.0,
        wall_clock_ms: int = 0,
    ) -> None:
        self.token_total = token_total
        self.cost_cap_usd = cost_cap_usd
        self.wall_clock_ms = wall_clock_ms
        self.token_used: int = 0
        self.cost_used_usd: float = 0.0
        self._started_at: float = time.time()

    def debit_tokens(self, n: int) -> None:
        self.token_used += n
        if self.token_total > 0 and self.token_used > self.token_total:
            raise BudgetExceeded("tokens", self.token_used, self.token_total)

    def debit_cost(self, usd: float) -> None:
        self.cost_used_usd += usd
        if self.cost_cap_usd > 0 and self.cost_used_usd > self.cost_cap_usd:
            raise BudgetExceeded("cost_usd", self.cost_used_usd, self.cost_cap_usd)

    def check_wall_clock(self) -> None:
        """Raise BudgetExceeded if wall-clock budget is set and elapsed."""
        if self.wall_clock_ms <= 0:
            return
        elapsed_ms = (time.time() - self._started_at) * 1000
        if elapsed_ms > self.wall_clock_ms:
            raise BudgetExceeded("wall_clock_ms", int(elapsed_ms), self.wall_clock_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_total": self.token_total,
            "token_used": self.token_used,
            "cost_cap_usd": self.cost_cap_usd,
            "cost_used_usd": self.cost_used_usd,
            "wall_clock_ms": self.wall_clock_ms,
            "elapsed_ms": round((time.time() - self._started_at) * 1000),
        }
