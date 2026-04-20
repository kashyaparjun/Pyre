"""Same flaky-agent scenario, run twice: raw asyncio vs Pyre supervision.

Run with:  uv run python examples/without_vs_with_pyre.py

Scenario:
    A tiny chat agent keeps a message history. A tool it calls is transient:
    it succeeds on calls 1 and 3 but raises on call 2. The caller runs three
    turns — ``bees``, ``ants``, ``wasps`` — in order.

The point of the demo:
    In the raw-asyncio version, the agent mutates history as it goes. When the
    ``ants`` turn's tool call raises, the user message has already been
    appended — but the assistant message never is. History is now
    inconsistent (one dangling user turn with no reply) and the next turn
    continues from that corrupted state.

    In the Pyre version, the handler constructs a new history and only
    *returns* it on success. Pyre only commits ``state`` after a handler
    returns, so the ``ants`` crash never touches state. With
    ``preserve_state_on_restart=True``, the restart keeps the clean
    post-``bees`` state, and the ``wasps`` turn appends to it cleanly.

    Result: raw asyncio ends with 3 user messages + 2 assistant messages
    (corrupt). Pyre ends with 2 user + 2 assistant (clean).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from pyre_agents import Agent, AgentContext, AgentInvocationError, CallResult, Pyre

_tool_calls = {"n": 0}


def reset_tool_counter() -> None:
    _tool_calls["n"] = 0


def flaky_tool(topic: str) -> str:
    """Succeeds on calls 1 and 3, raises on call 2."""
    _tool_calls["n"] += 1
    if _tool_calls["n"] == 2:
        raise RuntimeError(f"transient failure on call 2 (topic={topic!r})")
    return f"facts about {topic}"


# --- Variant A: raw asyncio, naive in-place mutation --------------------------


@dataclass
class RawAsyncioChatAgent:
    history: list[dict[str, str]] = field(default_factory=list)

    async def turn(self, topic: str) -> str:
        self.history.append({"role": "user", "content": topic})
        fact = flaky_tool(topic)
        self.history.append({"role": "assistant", "content": fact})
        return fact


async def run_without_pyre() -> list[dict[str, str]]:
    reset_tool_counter()
    agent = RawAsyncioChatAgent()
    for topic in ("bees", "ants", "wasps"):
        try:
            await agent.turn(topic)
        except Exception as exc:
            print(f"  [raw] turn {topic!r} crashed: {exc}")
    return agent.history


# --- Variant B: Pyre-supervised, state committed atomically on success --------


class ChatState(BaseModel):
    history: list[dict[str, str]] = []


class PyreChatAgent(Agent[ChatState]):
    async def init(self, **args: Any) -> ChatState:
        return ChatState()

    async def handle_call(
        self, state: ChatState, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[ChatState]:
        msg_type = str(msg["type"])
        if msg_type == "get_history":
            return CallResult(reply=list(state.history), new_state=state)
        if msg_type == "turn":
            topic = str(msg["payload"]["topic"])
            fact = flaky_tool(topic)  # raises on call 2; state not yet reassigned
            new_history = [
                *state.history,
                {"role": "user", "content": topic},
                {"role": "assistant", "content": fact},
            ]
            return CallResult(reply=fact, new_state=ChatState(history=new_history))
        raise ValueError(f"unknown type: {msg_type}")


async def run_with_pyre() -> list[dict[str, str]]:
    reset_tool_counter()
    system = await Pyre.start()
    try:
        ref = await system.spawn(
            PyreChatAgent,
            name="chat",
            preserve_state_on_restart=True,
        )
        for topic in ("bees", "ants", "wasps"):
            try:
                await ref.call("turn", {"topic": topic})
            except AgentInvocationError as exc:
                print(f"  [pyre] turn {topic!r} crashed: {exc}")
        history: list[dict[str, str]] = await ref.call("get_history", {})
        return history
    finally:
        await system.stop_system()


# --- Side-by-side -------------------------------------------------------------


def format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "    (empty)"
    return "\n".join(f"    {m['role']:9s}: {m['content']}" for m in history)


def is_consistent(history: list[dict[str, str]]) -> bool:
    """A consistent conversation alternates user/assistant and ends on assistant."""
    if len(history) % 2 != 0:
        return False
    for i, msg in enumerate(history):
        expected = "user" if i % 2 == 0 else "assistant"
        if msg["role"] != expected:
            return False
    return True


async def main() -> None:
    print("Without Pyre (raw asyncio with in-place mutation):")
    raw = await run_without_pyre()
    print(format_history(raw))
    print(f"  consistent conversation? {is_consistent(raw)}\n")

    print("With Pyre (preserve_state_on_restart=True, atomic commit):")
    pyred = await run_with_pyre()
    print(format_history(pyred))
    print(f"  consistent conversation? {is_consistent(pyred)}\n")

    print("Punchline:")
    print(
        f"  Raw asyncio: {len(raw)} messages, "
        f"{'clean' if is_consistent(raw) else 'CORRUPT (dangling user turn)'}."
    )
    print(
        f"  Pyre:        {len(pyred)} messages, "
        f"{'clean' if is_consistent(pyred) else 'corrupt'} — "
        f"the crashed turn never touched committed state."
    )


if __name__ == "__main__":
    asyncio.run(main())
