"""CrewAI + Pyre — basic usage.

Run with:  uv run python examples/usage/crewai_basic.py

The adapter wraps a crew *factory* — a zero-arg callable that returns a
fresh crew. Any object whose factory returns ``kickoff(inputs=...)``
works, so a real ``crewai.Crew`` built from real ``Agent`` / ``Task``
objects plugs in unchanged.

A real CrewAI crew executes its tasks via an LLM, so this example uses
a minimal stand-in to keep the run LLM-free. For a crash-isolation demo
with the same stand-in pattern, see ``examples/crewai_resilient.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pyre_agents import Pyre
from pyre_agents.adapters.crewai import supervise


@dataclass
class TinyCrew:
    name: str

    def kickoff(self, inputs: dict[str, object] | None = None) -> dict[str, object]:
        return {"crew": self.name, "inputs": inputs, "summary": f"{self.name} did the work"}


async def main() -> None:
    def research_crew_factory() -> TinyCrew:
        return TinyCrew(name="research")

    system = await Pyre.start()
    try:
        crew = await supervise(research_crew_factory, system=system, name="research")

        out1 = await crew.kickoff({"topic": "pollinators"})
        out2 = await crew.kickoff({"topic": "predators"})

        print(f"kickoff 1: {out1}")
        print(f"kickoff 2: {out2}")
        print(f"total kickoffs: {await crew.kickoffs()}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
