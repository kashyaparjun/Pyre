"""Tests for the pydantic-ai adapter using a stub agent (no LLM calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pyre_agents import AgentInvocationError, Pyre
from pyre_agents.adapters.pydantic_ai import supervise


@dataclass
class _StubResult:
    output: str
    messages: list[dict[str, str]]

    def all_messages(self) -> list[dict[str, str]]:
        return list(self.messages)


@dataclass
class StubAgent:
    """Minimal pydantic-ai-shaped agent for tests — no LLM, no network."""

    responses: list[str]
    fail_on_prompts: set[str] = field(default_factory=set)
    call_count: int = 0
    last_kwargs: dict[str, Any] = field(default_factory=dict)

    async def run(
        self,
        prompt: str,
        *,
        message_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> _StubResult:
        self.call_count += 1
        self.last_kwargs = {"message_history": message_history, **kwargs}
        if prompt in self.fail_on_prompts:
            raise RuntimeError(f"stub agent blew up on prompt: {prompt!r}")
        reply = self.responses[(self.call_count - 1) % len(self.responses)]
        history = list(message_history or [])
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": reply})
        return _StubResult(output=reply, messages=history)


@pytest.mark.asyncio
async def test_supervised_agent_threads_history_across_calls() -> None:
    system = await Pyre.start()
    stub = StubAgent(responses=["first", "second", "third"])
    supervised = await supervise(stub, system=system, name="helper")

    first = await supervised.run("hi")
    second = await supervised.run("again")

    assert first == "first"
    assert second == "second"
    history = await supervised.history()
    assert [m["content"] for m in history] == ["hi", "first", "again", "second"]
    await system.stop_system()


@pytest.mark.asyncio
async def test_history_survives_tool_crash_via_supervision() -> None:
    system = await Pyre.start()
    stub = StubAgent(
        responses=["hello", "skipped", "still-here"],
        fail_on_prompts={"CRASH"},
    )
    supervised = await supervise(stub, system=system, name="resilient")

    assert await supervised.run("hi") == "hello"
    history_before_crash = await supervised.history()

    with pytest.raises(AgentInvocationError):
        await supervised.run("CRASH")

    # The crashed handler did not commit state, so history is unchanged; and because
    # preserve_state_on_restart is on, the restart does not wipe it either.
    assert await supervised.history() == history_before_crash
    assert await supervised.run("are you alive?") == "still-here"
    history_after = await supervised.history()
    assert [m["content"] for m in history_after] == [
        "hi",
        "hello",
        "are you alive?",
        "still-here",
    ]
    await system.stop_system()


@pytest.mark.asyncio
async def test_reset_clears_message_history() -> None:
    system = await Pyre.start()
    stub = StubAgent(responses=["a", "b"])
    supervised = await supervise(stub, system=system, name="resetme")

    await supervised.run("first")
    assert len(await supervised.history()) == 2

    await supervised.reset()
    assert await supervised.history() == []
    await system.stop_system()


@pytest.mark.asyncio
async def test_deps_and_model_settings_are_forwarded() -> None:
    system = await Pyre.start()
    stub = StubAgent(responses=["ok"])
    supervised = await supervise(stub, system=system, name="kwargs")

    await supervised.run(
        "hi",
        deps={"user_id": 42},
        model_settings={"temperature": 0.1},
    )
    assert stub.last_kwargs.get("deps") == {"user_id": 42}
    assert stub.last_kwargs.get("model_settings") == {"temperature": 0.1}
    await system.stop_system()


@pytest.mark.asyncio
async def test_non_string_prompt_is_rejected() -> None:
    from pyre_agents import AgentInvocationError

    system = await Pyre.start()
    stub = StubAgent(responses=["ok"])
    supervised = await supervise(stub, system=system, name="strict")

    with pytest.raises(AgentInvocationError):
        await supervised.run(123)  # type: ignore[arg-type]
    await system.stop_system()
