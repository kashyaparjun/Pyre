"""OpenAI Agents SDK + Pyre: Runner crashes don't drop the conversation.

Run with:  uv run --with 'openai-agents>=0.2' python examples/openai_agents_resilient.py

What it demonstrates:
    1. A real openai-agents ``Agent`` is wrapped in a Pyre supervised process
       via ``supervise(agent, system=..., name=...)``.
    2. The ``Runner`` this example passes to ``supervise(runner=...)`` is a
       stub — same shape as the real ``agents.Runner``, but deterministic
       and no network. That lets the example run without an OpenAI key
       while still exercising the real Agent + Pyre adapter flow.
    3. The stub raises on the second ``.run()``. Without Pyre, that
       exception would kill the run and the first turn's messages would
       be lost. With Pyre, the bridge restarts, ``preserve_state_on_restart``
       keeps the committed input-list from turn 1 intact, and the next
       call continues the conversation.

To go live, delete the ``runner=_StubRunner()`` argument to ``supervise``.
The adapter falls back to the real ``agents.Runner`` and hits OpenAI with
whatever ``OPENAI_API_KEY`` you have configured.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from agents import Agent as OpenAIAgent  # type: ignore[import-not-found]
except ImportError:
    print("This example needs openai-agents. Install with: pip install 'openai-agents>=0.2'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.openai_agents import supervise


@dataclass
class _StubResult:
    final_output: str
    messages: list[Any]

    def to_input_list(self) -> list[Any]:
        return list(self.messages)


@dataclass
class _StubRunner:
    """Same shape as agents.Runner but deterministic — no network."""

    responses: tuple[str, ...] = ("hello", "skipped", "after-crash")
    calls: int = 0
    last_kwargs: dict[str, Any] = field(default_factory=dict)

    async def run(self, agent: OpenAIAgent[Any], input_: Any, **kwargs: Any) -> _StubResult:
        self.calls += 1
        self.last_kwargs = kwargs
        if self.calls == 2:
            raise RuntimeError("stub runner: transient 503 on call 2")
        prompt = (
            input_
            if isinstance(input_, str)
            else next((m["content"] for m in reversed(input_) if m.get("role") == "user"), "")
        )
        reply = self.responses[(self.calls - 1) % len(self.responses)]
        history = input_ if isinstance(input_, list) else [{"role": "user", "content": prompt}]
        history.append({"role": "assistant", "content": reply})
        return _StubResult(final_output=reply, messages=history)


async def main() -> None:
    # A real openai-agents Agent — instructions, tools, handoffs, the works.
    # (Here we just set a name and instructions, no tools, since the stub
    # runner doesn't execute them.)
    agent: OpenAIAgent[Any] = OpenAIAgent(
        name="assistant",
        instructions="You are a helpful assistant.",
    )

    system = await Pyre.start()
    try:
        supervised = await supervise(
            agent,
            system=system,
            name="chat",
            runner=_StubRunner(),  # remove this arg to go live
        )

        r1 = await supervised.run("tell me about bees")
        print(f"turn 1: {r1!r}  history={len(await supervised.history())}")

        try:
            await supervised.run("tell me about ants")
        except Exception as exc:
            print(f"turn 2 crashed as expected: {type(exc).__name__}: {exc}")

        r3 = await supervised.run("tell me about wasps")
        history = await supervised.history()
        print(
            f"turn 3: {r3!r}  history={len(history)} "
            f"(would be 0 without preserve_state_on_restart)"
        )
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
