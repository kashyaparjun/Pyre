"""Pydantic-AI + Pyre: conversation survives a flaky tool crash.

Run with:  uv run --with 'pydantic-ai>=1.0' python examples/pydantic_ai_resilient.py

What it demonstrates:
    1. A pydantic-ai agent is wrapped in a Pyre supervised process with one call:
       `supervise(pyd_agent, system=system, name="chat")`.
    2. A tool raises on one of its invocations.
    3. Without Pyre, the raised exception would kill the run and lose history.
       With Pyre, the bridge process restarts, the *last-committed* message
       history is preserved, and the next call continues the conversation.
"""

from __future__ import annotations

import asyncio
import sys

try:
    from pydantic_ai import Agent as PydanticAgent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel
except ImportError:
    print("This example needs pydantic-ai. Install with: pip install 'pydantic-ai>=1.0'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.pydantic_ai import supervise

_calls = {"n": 0}


def unstable_model(messages: list, info: AgentInfo) -> ModelResponse:
    """A stand-in model that crashes on its second invocation."""
    _calls["n"] += 1
    if _calls["n"] == 2:
        raise RuntimeError("model: transient failure on call 2")
    return ModelResponse(parts=[TextPart(content=f"reply #{_calls['n']}")])


async def main() -> None:
    pyd_agent: PydanticAgent[None, str] = PydanticAgent(FunctionModel(unstable_model))

    system = await Pyre.start()
    try:
        chat = await supervise(pyd_agent, system=system, name="chat")

        r1 = await chat.run("tell me about bees")
        print(f"turn 1: {r1!r}  history={len(await chat.history())}")

        try:
            await chat.run("tell me about ants")
        except Exception as exc:
            print(f"turn 2 crashed as expected: {type(exc).__name__}: {exc}")

        # Pyre restarted the bridge with preserved state. Conversation continues.
        r3 = await chat.run("tell me about wasps")
        history = await chat.history()
        print(
            f"turn 3: {r3!r}  history={len(history)} "
            f"(would be 0 without preserve_state_on_restart)"
        )
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
