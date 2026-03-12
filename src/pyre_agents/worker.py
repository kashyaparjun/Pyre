"""Python worker dispatch loop primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from pyre_agents.agent import Agent
from pyre_agents.context import AgentContext
from pyre_agents.results import CallResult


@dataclass(frozen=True)
class WorkerCallOutcome:
    """Outcome of a call handler invocation."""

    reply: Any
    new_state: BaseModel


class Worker:
    """Dispatches lifecycle callbacks for registered agents."""

    async def run_call(
        self,
        agent: Agent[Any],
        state: BaseModel,
        message: dict[str, Any],
        ctx: AgentContext,
    ) -> WorkerCallOutcome:
        result: CallResult[BaseModel] = await agent.handle_call(state, message, ctx)
        self._assert_state_type(type(state), result.new_state)
        return WorkerCallOutcome(reply=result.reply, new_state=result.new_state)

    async def run_cast(
        self,
        agent: Agent[Any],
        state: BaseModel,
        message: dict[str, Any],
        ctx: AgentContext,
    ) -> BaseModel:
        new_state = await agent.handle_cast(state, message, ctx)
        self._assert_state_type(type(state), new_state)
        return cast(BaseModel, new_state)

    async def run_info(
        self,
        agent: Agent[Any],
        state: BaseModel,
        message: dict[str, Any],
        ctx: AgentContext,
    ) -> BaseModel:
        new_state = await agent.handle_info(state, message, ctx)
        self._assert_state_type(type(state), new_state)
        return cast(BaseModel, new_state)

    def _assert_state_type(self, state_type: type[BaseModel], new_state: BaseModel) -> None:
        if not isinstance(new_state, state_type):
            raise TypeError(
                f"Handler returned invalid state type. Expected {state_type.__name__}, "
                f"got {type(new_state).__name__}"
            )
