"""LangGraph + Pyre — basic usage with a real agent graph (no LLM).

Run with:  uv run --with 'langgraph>=0.2' python examples/usage/langgraph_basic.py

Builds a real ``StateGraph`` with three nodes wired together by edges —
no LLM calls, just plain Python functions playing the role of "agents"
in the graph. The compiled graph is then wrapped by Pyre via
``supervise(graph_factory, ...)``, which isolates each invocation in its
own supervised process.

Swap any node's body for a real LLM agent (e.g. a pydantic-ai or
openai-agents call) to go live — the graph structure stays the same.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TypedDict

try:
    from langgraph.graph import END, START, StateGraph  # type: ignore[import-not-found]
except ImportError:
    print("Install with: pip install 'langgraph>=0.2'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.langgraph import supervise


class ResearchState(TypedDict):
    topic: str
    outline: list[str]
    draft: str
    review: str


def planner(state: ResearchState) -> dict:
    """First 'agent' — decides what sections to cover."""
    return {"outline": [f"intro to {state['topic']}", "key points", "conclusion"]}


def writer(state: ResearchState) -> dict:
    """Second 'agent' — turns the outline into a draft."""
    sections = " / ".join(state["outline"])
    return {"draft": f"Draft on {state['topic']}: {sections}"}


def reviewer(state: ResearchState) -> dict:
    """Third 'agent' — reviews the draft."""
    word_count = len(state["draft"].split())
    return {"review": f"Reviewed: {word_count} words, looks good."}


def build_research_graph():
    """Factory: build + compile the real StateGraph on each supervise call."""
    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner)
    graph.add_node("writer", writer)
    graph.add_node("reviewer", reviewer)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_edge("reviewer", END)
    return graph.compile()


async def main() -> None:
    system = await Pyre.start()
    try:
        supervised = await supervise(build_research_graph, system=system, name="research")

        r1 = await supervised.invoke(
            {"topic": "bees", "outline": [], "draft": "", "review": ""}
        )
        r2 = await supervised.invoke(
            {"topic": "ants", "outline": [], "draft": "", "review": ""}
        )

        print(f"run 1 topic: {r1['topic']}")
        print(f"  outline: {r1['outline']}")
        print(f"  draft:   {r1['draft']}")
        print(f"  review:  {r1['review']}")
        print(f"run 2 topic: {r2['topic']}")
        print(f"  review:  {r2['review']}")
        print(f"total graph invocations: {await supervised.invocations()}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
