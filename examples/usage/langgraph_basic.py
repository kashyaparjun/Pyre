"""LangGraph + Pyre — basic usage.

Run with:  uv run python examples/usage/langgraph.py

The adapter wraps a graph *factory* — a zero-arg callable returning a
compiled graph. Any object exposing ``.invoke(input, config=...)`` works,
so a real ``CompiledStateGraph`` plugs in unchanged. The stand-in below
lets the example run without ``langgraph`` installed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pyre_agents import Pyre
from pyre_agents.adapters.langgraph import supervise


@dataclass
class TinyGraph:
    name: str

    def invoke(
        self, input_: dict[str, object], config: dict[str, object] | None = None
    ) -> dict[str, object]:
        return {"graph": self.name, "input": input_, "output": "done"}


async def main() -> None:
    def build_graph() -> TinyGraph:
        return TinyGraph(name="summarizer")

    system = await Pyre.start()
    try:
        graph = await supervise(build_graph, system=system, name="summarizer")

        r1 = await graph.invoke({"messages": ["ingest article"]})
        r2 = await graph.invoke({"messages": ["ingest follow-up"]})

        print(f"invoke 1: {r1}")
        print(f"invoke 2: {r2}")
        print(f"total invocations: {await graph.invocations()}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
