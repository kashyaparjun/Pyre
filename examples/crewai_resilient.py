"""CrewAI + Pyre: one crew's crash cannot kill another.

Run with:  uv run --with 'crewai>=0.70' python examples/crewai_resilient.py

What it demonstrates:
    1. Two crews are each wrapped in their own Pyre supervised process with:
       `supervise(crew_factory, system=system, name=...)`.
    2. The flaky crew's first kickoff raises, but Pyre isolates the crash —
       the healthy crew continues working in parallel.
    3. A retry on the flaky wrapper invokes a fresh crew instance (via the
       factory) and succeeds.

The demo uses tiny stand-in classes that mimic the CrewAI interface so it can run
without an LLM API key. The adapter itself works with any object exposing
`kickoff(inputs=...)` or `kickoff_async(inputs=...)`, so a real Crew plugs in as-is.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class TinyCrew:
    """Stand-in for a CrewAI Crew; swap in a real one in production."""

    name: str
    fail_first_kickoff: bool = False
    state: dict[str, int] = field(default_factory=lambda: {"calls": 0})

    def kickoff(self, inputs: dict[str, object] | None = None) -> dict[str, object]:
        self.state["calls"] += 1
        if self.fail_first_kickoff:
            self.fail_first_kickoff = False
            raise RuntimeError(f"{self.name}: first kickoff failed")
        return {"crew": self.name, "inputs": inputs, "call": self.state["calls"]}


async def main() -> None:
    from pyre_agents import Pyre
    from pyre_agents.adapters.crewai import supervise

    flaky_calls = {"n": 0}

    def flaky_factory() -> TinyCrew:
        flaky_calls["n"] += 1
        return TinyCrew(name="flaky", fail_first_kickoff=flaky_calls["n"] == 1)

    system = await Pyre.start()
    try:
        flaky = await supervise(flaky_factory, system=system, name="flaky")
        healthy = await supervise(lambda: TinyCrew(name="healthy"), system=system, name="healthy")

        try:
            await flaky.kickoff({"task": "research"})
        except Exception as exc:
            print(f"flaky crew crashed as expected: {type(exc).__name__}: {exc}")

        # Healthy crew is untouched by flaky's crash.
        out = await healthy.kickoff({"task": "summarize"})
        print(f"healthy crew still working: {out}")

        # Retry the flaky wrapper — factory returns a fresh crew this time.
        out = await flaky.kickoff({"task": "research"})
        print(f"flaky crew recovered on retry: {out}")
        print(f"flaky kickoffs recorded: {await flaky.kickoffs()}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
