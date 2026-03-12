"""Agent base class for Phase 2 lifecycle APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from pyre_agents.results import CallResult


class Agent[StateT: BaseModel]:
    """Base class for developer-defined agents."""

    async def init(self, **args: Any) -> StateT:
        """Return initial state for this agent."""
        raise NotImplementedError("Agent.init must be implemented")

    async def handle_call(
        self, state: StateT, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[StateT]:
        """Handle synchronous message and return reply + new state."""
        raise NotImplementedError("Agent.handle_call must be implemented")

    async def handle_cast(self, state: StateT, msg: dict[str, Any], ctx: AgentContext) -> StateT:
        """Handle async fire-and-forget message."""
        return state

    async def handle_info(self, state: StateT, msg: dict[str, Any], ctx: AgentContext) -> StateT:
        """Handle internal/timer messages."""
        return state


if TYPE_CHECKING:
    from pyre_agents.context import AgentContext
