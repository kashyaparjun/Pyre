"""End-to-end integration: real LangGraph graph supervised by Pyre.

Stub tests in test_langgraph_adapter.py prove the adapter's shape. This
file proves the adapter actually works against the real library — a real
StateGraph, compiled, with MemorySaver checkpointing, invoked through
Pyre.supervise and surviving a node-level crash.
"""

from __future__ import annotations

from typing import TypedDict

import pytest

pytest.importorskip("langgraph", reason="langgraph extra not installed")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from pyre_agents import AgentInvocationError, Pyre  # noqa: E402
from pyre_agents.adapters.langgraph import supervise  # noqa: E402


class _GraphState(TypedDict, total=False):
    x: int
    seen: list[str]


def _build_healthy_graph() -> object:
    def step_a(state: _GraphState) -> _GraphState:
        return {"x": state.get("x", 0) + 1, "seen": [*state.get("seen", []), "a"]}

    def step_b(state: _GraphState) -> _GraphState:
        return {"x": state.get("x", 0) * 10, "seen": [*state.get("seen", []), "b"]}

    graph = StateGraph(_GraphState)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    return graph.compile(checkpointer=MemorySaver())


def _build_flaky_graph(fail_once: list[bool]) -> object:
    def step(state: _GraphState) -> _GraphState:
        if fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("flaky node: first invocation raises")
        return {"x": 42}

    graph = StateGraph(_GraphState)
    graph.add_node("only", step)
    graph.add_edge(START, "only")
    graph.add_edge("only", END)
    return graph.compile()


@pytest.mark.asyncio
async def test_real_langgraph_graph_runs_through_supervisor() -> None:
    system = await Pyre.start()
    try:
        supervised = await supervise(_build_healthy_graph, system=system, name="real-lg")
        result = await supervised.invoke(
            {"x": 0, "seen": []},
            config={"configurable": {"thread_id": "t1"}},
        )
        assert result["x"] == 10
        assert result["seen"] == ["a", "b"]
        assert await supervised.invocations() == 1
    finally:
        await system.stop_system()


@pytest.mark.asyncio
async def test_real_langgraph_node_crash_is_isolated_and_retryable() -> None:
    system = await Pyre.start()
    fail_once_state = [True]

    def factory() -> object:
        return _build_flaky_graph(fail_once_state)

    try:
        supervised = await supervise(factory, system=system, name="flaky-lg")

        with pytest.raises(AgentInvocationError):
            await supervised.invoke({})

        # Fresh graph instance on retry; fail_once_state has been reset by
        # the first (failed) invocation's side effect.
        result = await supervised.invoke({})
        assert result["x"] == 42
    finally:
        await system.stop_system()
