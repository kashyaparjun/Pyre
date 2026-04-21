"""A multi-perspective research assistant built on Pyre + pydantic-ai.

Run with:  uv run --with 'pydantic-ai>=1.0' python examples/research_assistant.py

This is Pyre eating its own dog food. It's the kind of product an agent
developer actually ships: a user poses a topic, three perspective agents
(technical, business, risk) each produce a short analysis in parallel, and
a synthesizer agent combines their answers.

What makes it non-trivial:
    - All four agents are pydantic-ai ``Agent`` instances wrapped via
      ``pyre_agents.adapters.pydantic_ai.supervise``.
    - The perspective agents run concurrently — they're independent, so
      there is no reason to wait for one before starting the next.
    - The "risk" agent has a flaky dependency that raises on its first
      invocation. Without Pyre, that exception would kill the run and the
      two other perspectives' work would be wasted. With Pyre, the crash
      is isolated to the risk agent's supervised process, Pyre restarts
      it, conversation history is preserved (we did a prior "warm up"
      turn), and a retry succeeds.
    - The synthesizer then runs with all three outputs.

The agents are backed by pydantic-ai's ``FunctionModel`` so the demo runs
deterministically without any API key. Swap a real model in
``build_agent`` — ``PydanticAgent("openai:gpt-4o", ...)`` — to run with
a real provider; the rest of the code is unchanged.
"""

from __future__ import annotations

import asyncio
import sys

try:
    from pydantic_ai import Agent as PydanticAgent  # type: ignore[import-not-found]
    from pydantic_ai.messages import (  # type: ignore[import-not-found]
        ModelResponse,
        TextPart,
    )
    from pydantic_ai.models.function import (  # type: ignore[import-not-found]
        AgentInfo,
        FunctionModel,
    )
except ImportError:
    print("This example needs pydantic-ai. Install with: pip install 'pydantic-ai>=1.0'")
    sys.exit(1)

from pyre_agents import Pyre
from pyre_agents.adapters.pydantic_ai import SupervisedPydanticAIAgent, supervise

# --- The "model" — deterministic, keyed by the perspective's role ------------

_RESPONSES: dict[str, list[str]] = {
    "technical": [
        "warming up",
        "Technically: the architecture pushes concurrency into the BEAM "
        "scheduler, avoiding Python GIL contention for agent dispatch.",
    ],
    "business": [
        "warming up",
        "Commercially: fault isolation lowers MTTR on production agent "
        "pipelines, which is the #1 reliability concern cited by ops teams.",
    ],
    "risk": [
        "warming up",
        "Risks: the dual-runtime architecture adds operational surface "
        "(two BEAM + Python processes to monitor, one bridge protocol).",
    ],
    "synthesizer": [
        "Consolidated view: Pyre trades deployment complexity for stronger "
        "fault isolation — the right call for teams running many concurrent "
        "agents, probably overkill for a single-agent prototype.",
    ],
}

# A module-level counter the risk agent's flaky tool consults.
_risk_tool_calls = {"n": 0}


def _make_model(role: str) -> FunctionModel:
    responses = iter(_RESPONSES[role])

    def fn(messages: list[object], info: AgentInfo) -> ModelResponse:
        if role == "risk":
            _risk_tool_calls["n"] += 1
            # Flaky: first real answer turn (the second model call overall)
            # raises, simulating a provider hiccup.
            if _risk_tool_calls["n"] == 2:
                raise RuntimeError("risk provider: transient 503")
        return ModelResponse(parts=[TextPart(content=next(responses))])

    return FunctionModel(fn)


def build_agent(role: str) -> PydanticAgent[None, str]:
    """Return a pydantic-ai Agent for a given role. Swap the model to go live."""
    return PydanticAgent(_make_model(role), system_prompt=f"You are the {role} perspective.")


# --- Orchestration -----------------------------------------------------------


async def _warm_up(agent: SupervisedPydanticAIAgent) -> None:
    """One cheap turn so preserve_state_on_restart has something to keep."""
    await agent.run("You will analyze a topic. Acknowledge.")


async def _perspective(agent: SupervisedPydanticAIAgent, topic: str) -> tuple[str, str]:
    """Ask a perspective agent about the topic. Retries once on crash."""
    try:
        answer = await agent.run(f"Analyze this topic from your perspective: {topic}")
    except Exception as exc:
        print(f"  [{agent.name}] crashed ({exc}); Pyre restarted the bridge. retrying...")
        answer = await agent.run(f"Analyze this topic from your perspective: {topic}")
    return agent.name, str(answer)


async def main() -> None:
    topic = "Does Pyre make sense for a team running 200 concurrent LLM agents?"

    system = await Pyre.start()
    try:
        # Wrap each pydantic-ai agent once. One-liner per adapter call.
        technical = await supervise(build_agent("technical"), system=system, name="technical")
        business = await supervise(build_agent("business"), system=system, name="business")
        risk = await supervise(build_agent("risk"), system=system, name="risk")
        synthesizer = await supervise(build_agent("synthesizer"), system=system, name="synth")

        # Warm-up turn threads a message into each perspective agent's history
        # so the preserve_state_on_restart promise has a visible payoff when
        # the risk agent crashes below.
        await asyncio.gather(_warm_up(technical), _warm_up(business), _warm_up(risk))

        # Run all three perspectives concurrently. The risk agent will crash
        # on its first real run; Pyre isolates it and the retry succeeds.
        print(f"Topic: {topic}\n")
        print("Perspectives (running concurrently):")
        results = await asyncio.gather(
            _perspective(technical, topic),
            _perspective(business, topic),
            _perspective(risk, topic),
        )
        for name, answer in results:
            print(f"  [{name}]  {answer}")

        # Verify history was preserved across the risk agent's crash.
        risk_history = await risk.history()
        print(f"\n[risk agent] history length = {len(risk_history)} (pre-crash warm-up preserved)")

        # Hand everything to the synthesizer.
        perspectives_text = "\n".join(f"{name}: {answer}" for name, answer in results)
        summary = await synthesizer.run(
            f"Synthesize these perspectives into a single recommendation:\n{perspectives_text}"
        )
        print(f"\nSynthesis:\n  {summary}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
