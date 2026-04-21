"""Tests for the openai-agents adapter using a stub Runner (no API calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pyre_agents import AgentInvocationError, Pyre
from pyre_agents.adapters.openai_agents import supervise


@dataclass
class _StubResult:
    final_output: str
    messages: list[dict[str, str]]

    def to_input_list(self) -> list[dict[str, str]]:
        return list(self.messages)


@dataclass
class StubRunner:
    """A Runner stand-in that never hits the network."""

    responses: list[str]
    fail_on_inputs: set[str] = field(default_factory=set)
    calls: int = 0
    last_kwargs: dict[str, Any] = field(default_factory=dict)

    async def run(self, agent: object, input_: Any, **kwargs: Any) -> _StubResult:
        self.calls += 1
        self.last_kwargs = kwargs
        prompt = (
            input_
            if isinstance(input_, str)
            else next((m["content"] for m in reversed(input_) if m.get("role") == "user"), "")
        )
        if prompt in self.fail_on_inputs:
            raise RuntimeError(f"stub runner blew up on input: {prompt!r}")
        reply = self.responses[(self.calls - 1) % len(self.responses)]
        history = input_ if isinstance(input_, list) else [{"role": "user", "content": prompt}]
        history.append({"role": "assistant", "content": reply})
        return _StubResult(final_output=reply, messages=history)


class _StubAgent:
    """Just a placeholder; the adapter hands it through to the Runner."""

    name = "stub"


@pytest.mark.asyncio
async def test_supervised_agent_threads_history_across_calls() -> None:
    system = await Pyre.start()
    runner = StubRunner(responses=["first", "second", "third"])
    supervised = await supervise(_StubAgent(), system=system, name="oa", runner=runner)

    assert await supervised.run("hi") == "first"
    assert await supervised.run("again") == "second"
    history = await supervised.history()
    assert [m["content"] for m in history] == ["hi", "first", "again", "second"]
    await system.stop_system()


@pytest.mark.asyncio
async def test_history_survives_runner_crash_via_supervision() -> None:
    system = await Pyre.start()
    runner = StubRunner(
        responses=["hello", "skipped", "still-here"],
        fail_on_inputs={"CRASH"},
    )
    supervised = await supervise(_StubAgent(), system=system, name="flaky-oa", runner=runner)

    assert await supervised.run("hi") == "hello"
    pre_crash = await supervised.history()

    with pytest.raises(AgentInvocationError):
        await supervised.run("CRASH")

    # Crashed call did not commit history; preserve_state keeps the pre-crash list.
    assert await supervised.history() == pre_crash
    assert await supervised.run("are you alive?") == "still-here"
    history = await supervised.history()
    assert [m["content"] for m in history] == [
        "hi",
        "hello",
        "are you alive?",
        "still-here",
    ]
    await system.stop_system()


@pytest.mark.asyncio
async def test_run_forwards_max_turns_and_context() -> None:
    system = await Pyre.start()
    runner = StubRunner(responses=["ok"])
    supervised = await supervise(_StubAgent(), system=system, name="kwargs", runner=runner)

    await supervised.run("hi", max_turns=3, context={"user_id": 42})
    assert runner.last_kwargs.get("max_turns") == 3
    assert runner.last_kwargs.get("context") == {"user_id": 42}
    await system.stop_system()


@pytest.mark.asyncio
async def test_reset_clears_history() -> None:
    system = await Pyre.start()
    runner = StubRunner(responses=["a", "b"])
    supervised = await supervise(_StubAgent(), system=system, name="reset", runner=runner)

    await supervised.run("first")
    assert len(await supervised.history()) == 2

    await supervised.reset()
    assert await supervised.history() == []
    await system.stop_system()
