"""OpenAI Agents SDK + Pyre — basic usage.

Run with:  uv run --with 'openai-agents>=0.2' python examples/usage/openai_agents.py

A real ``agents.Agent`` paired with a stub ``Runner`` so the example runs
without ``OPENAI_API_KEY``. Delete ``runner=_StubRunner()`` to go live
against OpenAI.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from agents import Agent  # type: ignore[import-not-found]
except ImportError:
    print("Install with: pip install 'openai-agents>=0.2'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.openai_agents import supervise


@dataclass
class _StubResult:
    final_output: str
    messages: list[Any] = field(default_factory=list)

    def to_input_list(self) -> list[Any]:
        return list(self.messages)


@dataclass
class _StubRunner:
    responses: tuple[str, ...] = ("Hi, I'm your agent.", "Yes — turn 1 is in history.")
    calls: int = 0

    async def run(self, agent: Any, input_: Any, **kwargs: Any) -> _StubResult:
        reply = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        prompt = (
            input_
            if isinstance(input_, str)
            else next((m["content"] for m in reversed(input_) if m.get("role") == "user"), "")
        )
        history = input_ if isinstance(input_, list) else [{"role": "user", "content": prompt}]
        history.append({"role": "assistant", "content": reply})
        return _StubResult(final_output=reply, messages=history)


async def main() -> None:
    agent: Agent[Any] = Agent(name="assistant", instructions="Be concise.")

    system = await Pyre.start()
    try:
        supervised = await supervise(
            agent, system=system, name="assistant", runner=_StubRunner()
        )

        r1 = await supervised.run("Who are you?")
        r2 = await supervised.run("Do you remember our first turn?")

        print(f"turn 1: {r1}")
        print(f"turn 2: {r2}")
        print(f"history length: {len(await supervised.history())}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
