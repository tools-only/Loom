"""SynthesisGuard — prevents unsafe state usage in final synthesis.

Ensures contested, stale, and verifying states are not used as uncaveated
facts, and appends appropriate constraints to the synthesis prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .environment_state import EnvironmentStateFrame


@dataclass
class SynthesisConstraint:
    state_id: str
    constraint_type: str  # exclude, caveat, refresh_required, pending
    message: str


@dataclass
class SynthesisGuardResult:
    allowed_state_ids: list[str] = field(default_factory=list)
    constraints: list[SynthesisConstraint] = field(default_factory=list)
    prompt_additions: list[str] = field(default_factory=list)


class SynthesisGuard:
    """Builds safety constraints for synthesis based on environment state frame."""

    @staticmethod
    def build_constraints(
        frame: EnvironmentStateFrame,
        review_result: dict | None = None,
    ) -> SynthesisGuardResult:
        result = SynthesisGuardResult()

        for state in frame.states:
            if state.status == "contested":
                result.constraints.append(SynthesisConstraint(
                    state_id=state.state_id,
                    constraint_type="caveat",
                    message=f"State {state.state_id} ({state.summary[:80]}) is contested. Use with caveat.",
                ))
                result.prompt_additions.append(
                    f"Include caveat for: {state.summary[:120]}. Mark as contested."
                )

            elif state.status == "stale":
                result.constraints.append(SynthesisConstraint(
                    state_id=state.state_id,
                    constraint_type="refresh_required",
                    message=f"State {state.state_id} ({state.summary[:80]}) is stale. Refresh or exclude.",
                ))
                result.prompt_additions.append(
                    f"State may be stale: {state.summary[:120]}. Exclude or note staleness."
                )

            elif state.status == "verifying":
                result.constraints.append(SynthesisConstraint(
                    state_id=state.state_id,
                    constraint_type="pending",
                    message=f"State {state.state_id} is still being verified. Note as pending.",
                ))
                result.prompt_additions.append(
                    f"Verification pending for: {state.summary[:120]}. Note this in the answer."
                )

            elif state.status == "resolved":
                result.allowed_state_ids.append(state.state_id)

            elif state.status == "active":
                result.allowed_state_ids.append(state.state_id)

        if review_result and isinstance(review_result, dict):
            gaps = review_result.get("confidence_gaps", []) or []
            for g in gaps:
                result.prompt_additions.append(
                    f"Review gap: {str(g.get('gap', str(g)))[:200]}. Address if possible."
                )

        return result

    @staticmethod
    def guard_prompt(result: SynthesisGuardResult) -> str:
        if not result.prompt_additions:
            return ""
        lines = ["", "### Synthesis Constraints", ""]
        for constraint in result.constraints:
            lines.append(f"- [{constraint.constraint_type}] {constraint.message}")
        lines.append("")
        return "\n".join(lines)
