from __future__ import annotations

import pytest
from pydantic import BaseModel

from pyre_agents import (
    Agent,
    AgentContext,
    AgentInvocationError,
    AgentTerminatedError,
    CallResult,
    Pyre,
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

    async def handle_cast(
        self, state: CounterState, msg: dict[str, object], ctx: AgentContext
    ) -> CounterState:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        assert isinstance(payload, dict)
        if msg_type == "increment":
            amount = int(payload.get("amount", 1))
            return CounterState(count=state.count + amount)
        return state


class RelayState(BaseModel):
    seen: int = 0


class RelayAgent(Agent[RelayState]):
    async def init(self, **args: object) -> RelayState:
        return RelayState()

    async def handle_call(
        self, state: RelayState, msg: dict[str, object], ctx: AgentContext
    ) -> CallResult[RelayState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        assert isinstance(payload, dict)
        if msg_type == "bounce":
            value = await ctx.call("counter", "increment", {"amount": int(payload["amount"])})
            return CallResult(reply=value, new_state=RelayState(seen=state.seen + 1))
        raise ValueError(msg_type)


@pytest.mark.asyncio
async def test_spawn_call_and_cast() -> None:
    system = await Pyre.start()
    ref = await system.spawn(CounterAgent, name="counter", args={"initial": 2})

    assert await ref.call("get", {}) == 2
    assert await ref.call("increment", {"amount": 3}) == 5

    await ref.cast("increment", {"amount": 4})
    assert await ref.call("get", {}) == 9
    await system.stop_system()


@pytest.mark.asyncio
async def test_ctx_call_between_agents() -> None:
    system = await Pyre.start()
    await system.spawn(CounterAgent, name="counter", args={"initial": 1})
    relay = await system.spawn(RelayAgent, name="relay")
    assert await relay.call("bounce", {"amount": 2}) == 3
    await system.stop_system()


@pytest.mark.asyncio
async def test_crash_triggers_restart_with_initial_state() -> None:
    system = await Pyre.start()
    ref = await system.spawn(CounterAgent, name="counter", args={"initial": 10})

    with pytest.raises(AgentInvocationError):
        await ref.call("boom", {})

    assert await ref.call("get", {}) == 10
    await system.stop_system()


@pytest.mark.asyncio
async def test_restart_intensity_terminates_agent() -> None:
    system = await Pyre.start()
    ref = await system.spawn(
        CounterAgent,
        name="counter",
        args={"initial": 0},
        max_restarts=1,
        within_ms=60_000,
    )

    with pytest.raises(AgentInvocationError):
        await ref.call("boom", {})
    with pytest.raises(AgentTerminatedError):
        await ref.call("boom", {})
    with pytest.raises(AgentTerminatedError):
        await ref.call("get", {})

    await system.stop_system()
