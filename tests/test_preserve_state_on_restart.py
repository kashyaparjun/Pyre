from __future__ import annotations

import pytest
from pydantic import BaseModel

from pyre_agents import (
    Agent,
    AgentContext,
    AgentInvocationError,
    CallResult,
    Pyre,
    RestartStrategy,
)


class CounterState(BaseModel):
    count: int


class CounterAgent(Agent[CounterState]):
    async def init(self, **args: object) -> CounterState:
        initial_obj = args.get("initial", 0)
        initial = initial_obj if isinstance(initial_obj, int) else int(str(initial_obj))
        return CounterState(count=initial)

    async def handle_call(
        self, state: CounterState, msg: dict[str, object], ctx: AgentContext
    ) -> CallResult[CounterState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        assert isinstance(payload, dict)

        if msg_type == "increment":
            amount = int(payload.get("amount", 1))
            next_state = CounterState(count=state.count + amount)
            return CallResult(reply=next_state.count, new_state=next_state)
        if msg_type == "get":
            return CallResult(reply=state.count, new_state=state)
        if msg_type == "boom":
            raise RuntimeError("forced crash")
        raise ValueError(f"unknown call type: {msg_type}")


@pytest.mark.asyncio
async def test_preserve_state_restores_last_committed_state_after_crash() -> None:
    system = await Pyre.start()
    agent = await system.spawn(
        CounterAgent,
        name="counter",
        args={"initial": 0},
        preserve_state_on_restart=True,
    )
    await agent.call("increment", {"amount": 7})
    await agent.call("increment", {"amount": 3})

    with pytest.raises(AgentInvocationError):
        await agent.call("boom", {})

    assert await agent.call("get", {}) == 10
    await system.stop_system()


@pytest.mark.asyncio
async def test_default_behavior_still_reinitializes_state_on_restart() -> None:
    system = await Pyre.start()
    agent = await system.spawn(CounterAgent, name="counter", args={"initial": 5})
    await agent.call("increment", {"amount": 4})
    assert await agent.call("get", {}) == 9

    with pytest.raises(AgentInvocationError):
        await agent.call("boom", {})

    assert await agent.call("get", {}) == 5
    await system.stop_system()


@pytest.mark.asyncio
async def test_preserve_is_per_agent_under_one_for_all_supervision() -> None:
    """Each sibling's preserve flag is honored independently: when a crash under
    one_for_all triggers a group restart, preserving siblings keep their state,
    non-preserving siblings get reinitialized."""
    system = await Pyre.start()
    await system.create_supervisor(name="group", strategy=RestartStrategy.ONE_FOR_ALL)

    keeps_state = await system.spawn(
        CounterAgent,
        name="keeps",
        args={"initial": 0},
        supervisor="group",
        preserve_state_on_restart=True,
    )
    resets_state = await system.spawn(
        CounterAgent,
        name="resets",
        args={"initial": 100},
        supervisor="group",
    )

    await keeps_state.call("increment", {"amount": 7})
    await resets_state.call("increment", {"amount": 7})
    assert await keeps_state.call("get", {}) == 7
    assert await resets_state.call("get", {}) == 107

    with pytest.raises(AgentInvocationError):
        await keeps_state.call("boom", {})

    assert await keeps_state.call("get", {}) == 7
    assert await resets_state.call("get", {}) == 100
    await system.stop_system()
