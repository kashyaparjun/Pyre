"""Agent execution context API."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pyre_agents.supervision import RestartStrategy


class AgentContext:
    """Context object exposed to handlers during invocation."""

    def __init__(self, runtime: PyreSystem, self_name: str) -> None:
        self._runtime = runtime
        self._self_name = self_name

    @property
    def self(self) -> str:
        """Current agent name."""
        return self._self_name

    async def call(self, name: str, type_: str, payload: dict[str, Any]) -> Any:
        """Make a synchronous call to another agent."""
        return await self._runtime.call(name, type_, payload)

    async def cast(self, name: str, type_: str, payload: dict[str, Any]) -> None:
        """Send an async cast to another agent."""
        await self._runtime.cast(name, type_, payload)

    async def spawn(
        self,
        agent_cls: type[Agent[Any]],
        name: str,
        args: dict[str, Any] | None = None,
        *,
        max_restarts: int = 3,
        within_ms: int = 5000,
        strategy: RestartStrategy = RestartStrategy.ONE_FOR_ONE,
        supervisor: str | None = None,
    ) -> AgentRef:
        """Spawn a new agent from within handler execution."""
        return await self._runtime.spawn(
            agent_cls,
            name=name,
            args=args or {},
            max_restarts=max_restarts,
            within_ms=within_ms,
            strategy=strategy,
            supervisor=supervisor,
        )

    async def send_after(
        self, name: str, type_: str, payload: dict[str, Any], delay_ms: int
    ) -> asyncio.Task[None]:
        """Schedule delayed cast delivery."""

        async def _deliver() -> None:
            await asyncio.sleep(delay_ms / 1000)
            await self._runtime.cast(name, type_, payload)

        return asyncio.create_task(_deliver())


if TYPE_CHECKING:
    from pyre_agents.agent import Agent
    from pyre_agents.ref import AgentRef
    from pyre_agents.runtime import PyreSystem
