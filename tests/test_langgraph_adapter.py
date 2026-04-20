"""Tests for the LangGraph adapter using a stub graph (no LangGraph import)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pyre_agents import AgentInvocationError, Pyre
from pyre_agents.adapters.langgraph import supervise


@dataclass
class SyncStubGraph:
    """Stub CompiledStateGraph exposing only sync .invoke()."""

    output: Any = "done"
    fail_first: bool = False
    calls: int = 0

    def invoke(self, input_: Any, config: dict[str, Any] | None = None) -> Any:
        self.calls += 1
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("first invoke failed")
        return {"input": input_, "config": config, "output": self.output}


@dataclass
class AsyncStubGraph:
    """Stub graph that exposes ainvoke; adapter should prefer the async path."""

    output: Any = "async-done"
    async_calls: int = 0
    sync_calls: int = 0
    last_config: dict[str, Any] | None = field(default=None)

    async def ainvoke(self, input_: Any, config: dict[str, Any] | None = None) -> Any:
        self.async_calls += 1
        self.last_config = config
        return {"input": input_, "output": self.output}

    def invoke(self, input_: Any, config: dict[str, Any] | None = None) -> Any:
        self.sync_calls += 1
        return "should-not-be-called"


@pytest.mark.asyncio
async def test_sync_invoke_runs_and_counts() -> None:
    system = await Pyre.start()
    supervised = await supervise(lambda: SyncStubGraph(output="ok"), system=system, name="g1")

    result = await supervised.invoke({"messages": ["hi"]})

    assert result == {"input": {"messages": ["hi"]}, "config": None, "output": "ok"}
    assert await supervised.invocations() == 1
    await system.stop_system()


@pytest.mark.asyncio
async def test_adapter_prefers_ainvoke_when_available() -> None:
    system = await Pyre.start()
    graph = AsyncStubGraph()
    supervised = await supervise(lambda: graph, system=system, name="async-graph")

    await supervised.invoke({"messages": ["hi"]}, config={"configurable": {"thread_id": "t1"}})

    assert graph.async_calls == 1
    assert graph.sync_calls == 0
    assert graph.last_config == {"configurable": {"thread_id": "t1"}}
    await system.stop_system()


@pytest.mark.asyncio
async def test_concurrent_graphs_are_isolated() -> None:
    system = await Pyre.start()
    healthy = await supervise(
        lambda: SyncStubGraph(output="ok"), system=system, name="healthy-graph"
    )
    flaky = await supervise(
        lambda: SyncStubGraph(output="nope", fail_first=True),
        system=system,
        name="flaky-graph",
    )

    with pytest.raises(AgentInvocationError):
        await flaky.invoke({"messages": []})

    # Flaky graph's crash is invisible to the healthy one.
    result = await healthy.invoke({"messages": []})
    assert result["output"] == "ok"
    await system.stop_system()


@pytest.mark.asyncio
async def test_crash_restarts_and_retry_uses_fresh_graph() -> None:
    system = await Pyre.start()
    call_counter = {"n": 0}

    def factory() -> SyncStubGraph:
        call_counter["n"] += 1
        return SyncStubGraph(output="survived", fail_first=call_counter["n"] == 1)

    supervised = await supervise(factory, system=system, name="flaky")

    with pytest.raises(AgentInvocationError):
        await supervised.invoke({"messages": ["first"]})

    # Default (no preserve flag): invocations counter resets on restart.
    assert await supervised.invocations() == 0
    result = await supervised.invoke({"messages": ["second"]})
    assert result["output"] == "survived"
    assert await supervised.invocations() == 1
    await system.stop_system()
