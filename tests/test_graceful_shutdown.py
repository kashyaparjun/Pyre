"""Tests for stop_system's graceful in-flight-drain behavior."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from pyre_agents import (
    Agent,
    AgentContext,
    AgentNotFoundError,
    CallResult,
    Pyre,
    SystemStoppedError,
)


class _NullState(BaseModel):
    pass


class _SlowAgent(Agent[_NullState]):
    async def init(self, **args: object) -> _NullState:
        return _NullState()

    async def handle_call(
        self, state: _NullState, msg: dict[str, object], ctx: AgentContext
    ) -> CallResult[_NullState]:
        delay_ms = int(msg["payload"]["delay_ms"])  # type: ignore[index]
        await asyncio.sleep(delay_ms / 1000)
        return CallResult(reply="done", new_state=state)


@pytest.mark.asyncio
async def test_new_calls_rejected_while_stop_system_is_running() -> None:
    system = await Pyre.start()
    ref = await system.spawn(_SlowAgent, name="slow")
    in_flight = asyncio.create_task(ref.call("work", {"delay_ms": 100}))
    await asyncio.sleep(0.01)  # let the call enter in-flight

    stopper = asyncio.create_task(system.stop_system(drain_timeout_s=2.0))
    await asyncio.sleep(0.01)  # let stop_system set the shutting-down flag

    with pytest.raises(SystemStoppedError):
        await ref.call("work", {"delay_ms": 10})

    await stopper  # drain completes
    assert await in_flight == "done"


@pytest.mark.asyncio
async def test_stop_system_returns_within_timeout_when_handler_is_slow() -> None:
    system = await Pyre.start()
    ref = await system.spawn(_SlowAgent, name="slow")
    # 2-second handler, 0.1-second drain budget — stop returns early.
    long_running = asyncio.create_task(ref.call("work", {"delay_ms": 2_000}))
    await asyncio.sleep(0.01)

    started = asyncio.get_event_loop().time()
    await system.stop_system(drain_timeout_s=0.1)
    elapsed = asyncio.get_event_loop().time() - started

    assert elapsed < 1.0, f"stop_system waited {elapsed}s, should have given up at 0.1s"

    # Clean up the orphaned task so the test doesn't leak it.
    try:
        await long_running
    except AgentNotFoundError:
        # Agent tables were cleared during stop; the task may surface that.
        pass


@pytest.mark.asyncio
async def test_stop_system_waits_for_in_flight_when_budget_is_generous() -> None:
    system = await Pyre.start()
    ref = await system.spawn(_SlowAgent, name="slow")
    in_flight = asyncio.create_task(ref.call("work", {"delay_ms": 100}))
    await asyncio.sleep(0.01)

    started = asyncio.get_event_loop().time()
    await system.stop_system(drain_timeout_s=5.0)
    elapsed = asyncio.get_event_loop().time() - started

    # Drain should have waited for the ~100ms handler, not given up immediately.
    assert elapsed >= 0.05
    assert await in_flight == "done"
