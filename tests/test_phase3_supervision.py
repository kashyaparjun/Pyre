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
async def test_one_for_one_restarts_only_crashed_child() -> None:
    system = await Pyre.start()
    await system.create_supervisor(name="group", strategy=RestartStrategy.ONE_FOR_ONE)

    first = await system.spawn(CounterAgent, name="first", args={"initial": 1}, supervisor="group")
    second = await system.spawn(
        CounterAgent, name="second", args={"initial": 10}, supervisor="group"
    )
    await first.call("increment", {"amount": 4})
    await second.call("increment", {"amount": 2})

    with pytest.raises(AgentInvocationError):
        await first.call("boom", {})

    assert await first.call("get", {}) == 1
    assert await second.call("get", {}) == 12
    await system.stop_system()


@pytest.mark.asyncio
async def test_one_for_all_restarts_all_children() -> None:
    system = await Pyre.start()
    await system.create_supervisor(name="group", strategy=RestartStrategy.ONE_FOR_ALL)

    first = await system.spawn(CounterAgent, name="first", args={"initial": 1}, supervisor="group")
    second = await system.spawn(
        CounterAgent, name="second", args={"initial": 10}, supervisor="group"
    )
    await first.call("increment", {"amount": 4})
    await second.call("increment", {"amount": 2})

    with pytest.raises(AgentInvocationError):
        await first.call("boom", {})

    assert await first.call("get", {}) == 1
    assert await second.call("get", {}) == 10
    await system.stop_system()


@pytest.mark.asyncio
async def test_rest_for_one_restarts_crashed_child_and_younger_siblings() -> None:
    system = await Pyre.start()
    await system.create_supervisor(name="group", strategy=RestartStrategy.REST_FOR_ONE)

    first = await system.spawn(CounterAgent, name="first", args={"initial": 1}, supervisor="group")
    second = await system.spawn(
        CounterAgent, name="second", args={"initial": 10}, supervisor="group"
    )
    third = await system.spawn(
        CounterAgent, name="third", args={"initial": 100}, supervisor="group"
    )
    await first.call("increment", {"amount": 5})
    await second.call("increment", {"amount": 5})
    await third.call("increment", {"amount": 5})

    with pytest.raises(AgentInvocationError):
        await second.call("boom", {})

    assert await first.call("get", {}) == 6
    assert await second.call("get", {}) == 10
    assert await third.call("get", {}) == 100
    await system.stop_system()


@pytest.mark.asyncio
async def test_nested_supervisor_restarts_do_not_escape_to_parent_group() -> None:
    system = await Pyre.start()
    await system.create_supervisor(name="parent", strategy=RestartStrategy.ONE_FOR_ALL)
    await system.create_supervisor(
        name="child",
        strategy=RestartStrategy.REST_FOR_ONE,
        parent="parent",
    )

    parent_agent = await system.spawn(
        CounterAgent, name="parent-agent", args={"initial": 50}, supervisor="parent"
    )
    child_one = await system.spawn(
        CounterAgent, name="child-one", args={"initial": 1}, supervisor="child"
    )
    child_two = await system.spawn(
        CounterAgent, name="child-two", args={"initial": 10}, supervisor="child"
    )
    await parent_agent.call("increment", {"amount": 2})
    await child_one.call("increment", {"amount": 3})
    await child_two.call("increment", {"amount": 4})

    with pytest.raises(AgentInvocationError):
        await child_one.call("boom", {})

    assert await parent_agent.call("get", {}) == 52
    assert await child_one.call("get", {}) == 1
    assert await child_two.call("get", {}) == 10
    await system.stop_system()


@pytest.mark.asyncio
async def test_supervisor_restart_intensity_terminates_entire_group() -> None:
    system = await Pyre.start()
    await system.create_supervisor(
        name="group",
        strategy=RestartStrategy.ONE_FOR_ALL,
        max_restarts=1,
        within_ms=60_000,
    )
    first = await system.spawn(CounterAgent, name="first", args={"initial": 1}, supervisor="group")
    second = await system.spawn(
        CounterAgent, name="second", args={"initial": 10}, supervisor="group"
    )

    with pytest.raises(AgentInvocationError):
        await first.call("boom", {})
    with pytest.raises(AgentTerminatedError):
        await first.call("boom", {})
    with pytest.raises(AgentTerminatedError):
        await second.call("get", {})

    await system.stop_system()
