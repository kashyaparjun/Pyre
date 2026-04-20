"""LangGraph + Pyre: concurrent graphs don't take each other down.

Run with:  uv run python examples/langgraph_resilient.py

What it demonstrates:
    LangGraph already has durable execution via Checkpointer — that's
    orthogonal to this adapter. The adapter's contribution is isolation
    between independent graph runs. Two supervised graphs run side by side;
    one blows up, the other keeps working; retry on the flaky wrapper
    invokes a fresh compiled graph.

The demo uses a tiny stand-in that exposes invoke() the way a real
CompiledStateGraph does, so it runs without needing the langgraph package
installed. A real graph plugs in unchanged via `pyre.supervise(lambda: build_graph())`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class TinyGraph:
    """Stand-in for a LangGraph CompiledStateGraph."""

    name: str
    fail_first: bool = False
    calls: int = 0

    def invoke(self, input_: dict, config: dict | None = None) -> dict:
        self.calls += 1
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError(f"{self.name}: first invoke crashed")
        return {"graph": self.name, "input": input_, "call": self.calls}


async def main() -> None:
    from pyre_agents import Pyre
    from pyre_agents.adapters.langgraph import supervise

    flaky_calls = {"n": 0}

    def flaky_factory() -> TinyGraph:
        flaky_calls["n"] += 1
        return TinyGraph(name="flaky", fail_first=flaky_calls["n"] == 1)

    system = await Pyre.start()
    try:
        flaky = await supervise(flaky_factory, system=system, name="flaky")
        healthy = await supervise(lambda: TinyGraph(name="healthy"), system=system, name="healthy")

        try:
            await flaky.invoke({"messages": ["start"]})
        except Exception as exc:
            print(f"flaky graph crashed as expected: {type(exc).__name__}: {exc}")

        # Healthy graph is untouched.
        out = await healthy.invoke({"messages": ["summarize"]})
        print(f"healthy graph still working: {out}")

        # Retry flaky — factory returns a fresh graph that succeeds.
        out = await flaky.invoke({"messages": ["start"]})
        print(f"flaky graph recovered on retry: {out}")
        print(f"flaky invocations recorded: {await flaky.invocations()}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
