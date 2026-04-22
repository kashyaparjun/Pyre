"""pydantic-ai + Pyre — basic usage (no API key required).

Run with:  uv run --with 'pydantic-ai>=1.0' python examples/usage/pydantic_ai.py

Shows the shortest path from a native ``pydantic_ai.Agent`` to a
Pyre-supervised one. The agent is backed by a deterministic
``FunctionModel`` so no key is needed; swap the model argument for e.g.
``"openai:gpt-4o-mini"`` to go live.
"""

from __future__ import annotations

import asyncio
import sys

try:
    from pydantic_ai import Agent  # type: ignore[import-not-found]
    from pydantic_ai.messages import ModelResponse, TextPart  # type: ignore[import-not-found]
    from pydantic_ai.models.function import (  # type: ignore[import-not-found]
        AgentInfo,
        FunctionModel,
    )
except ImportError:
    print("Install with: pip install 'pydantic-ai>=1.0'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.pydantic_ai import supervise


def _deterministic_model() -> FunctionModel:
    replies = iter(["Hello! I'm a deterministic agent.", "I remember our last turn."])

    def fn(messages: list[object], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=next(replies))])

    return FunctionModel(fn)


async def main() -> None:
    # A real pydantic-ai Agent. For live use, replace _deterministic_model()
    # with "openai:gpt-4o-mini" (or another provider string).
    agent = Agent(_deterministic_model(), system_prompt="Be helpful.")

    system = await Pyre.start()
    try:
        supervised = await supervise(agent, system=system, name="assistant")

        r1 = await supervised.run("Hi, who are you?")
        r2 = await supervised.run("What do you remember?")

        print(f"turn 1: {r1}")
        print(f"turn 2: {r2}")
        print(f"history length: {len(await supervised.history())}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
