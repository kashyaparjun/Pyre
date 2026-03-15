from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from pyre_agents import (
    Agent,
    AgentContext,
    AgentInvocationError,
    CallResult,
    PerformanceConfig,
    Pyre,
)


class SlowState(BaseModel):
    count: int = 0


class SlowAgent(Agent[SlowState]):
    async def init(self, **args: object) -> SlowState:
        return SlowState()

    async def handle_call(
        self,
        state: SlowState,
        msg: dict[str, object],
        ctx: AgentContext,
    ) -> CallResult[SlowState]:
        if msg.get("type") == "slow":
            await asyncio.sleep(0.05)
            return CallResult(reply=state.count, new_state=state)
        return CallResult(reply=state.count, new_state=state)


@pytest.mark.asyncio
async def test_runtime_backpressure_rejects_call_when_mailbox_saturated() -> None:
    runtime = await Pyre.start(
        performance=PerformanceConfig(max_mailbox_depth=1, handler_worker_count=1)
    )
    try:
        ref = await runtime.spawn(SlowAgent, name="slow")

        first = asyncio.create_task(ref.call("slow", {}))
        await asyncio.sleep(0.005)
        with pytest.raises(AgentInvocationError, match="mailbox saturated"):
            await ref.call("slow", {})
        _ = await first

        metrics = runtime.metrics()
        assert metrics.backpressure_rejections >= 1
    finally:
        await runtime.stop_system()
