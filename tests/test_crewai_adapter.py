"""Tests for the CrewAI adapter using a stub crew (no LLM calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pyre_agents import AgentInvocationError, Pyre
from pyre_agents.adapters.crewai import supervise


@dataclass
class StubCrew:
    """Minimal CrewAI-shaped crew for tests — no agents, no LLM."""

    output: Any = "done"
    fail_once: bool = False
    state: dict[str, int] = field(default_factory=lambda: {"calls": 0})

    def kickoff(self, inputs: dict[str, Any] | None = None) -> Any:
        self.state["calls"] += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("first run blew up")
        if inputs is None:
            return self.output
        return {"inputs": inputs, "output": self.output}


@pytest.mark.asyncio
async def test_supervised_crew_runs_kickoff_and_tracks_count() -> None:
    system = await Pyre.start()
    supervised = await supervise(lambda: StubCrew(output="hello"), system=system, name="c1")

    assert await supervised.kickoff() == "hello"
    assert await supervised.kickoff({"topic": "pyre"}) == {
        "inputs": {"topic": "pyre"},
        "output": "hello",
    }
    assert await supervised.kickoffs() == 2
    await system.stop_system()


@pytest.mark.asyncio
async def test_crash_does_not_kill_the_system_and_retry_succeeds() -> None:
    system = await Pyre.start()

    def factory() -> StubCrew:
        # Each crash-then-retry gets a fresh crew. The first factory call returns a
        # crew that will blow up on first kickoff; subsequent crews are healthy.
        factory.calls += 1  # type: ignore[attr-defined]
        return StubCrew(output="survived", fail_once=factory.calls == 1)  # type: ignore[attr-defined]

    factory.calls = 0  # type: ignore[attr-defined]

    supervised = await supervise(factory, system=system, name="flaky")

    with pytest.raises(AgentInvocationError):
        await supervised.kickoff()

    # kickoffs counter preserved across restart (still 0 because the first one crashed
    # before committing new state), and the next call runs on a fresh crew instance.
    assert await supervised.kickoffs() == 0
    assert await supervised.kickoff() == "survived"
    assert await supervised.kickoffs() == 1
    await system.stop_system()


@dataclass
class AsyncStubCrew:
    """Stub crew that exposes kickoff_async, matching real CrewAI's async API."""

    output: Any = "async-done"
    async_calls: int = 0
    sync_calls: int = 0

    async def kickoff_async(self, inputs: dict[str, Any] | None = None) -> Any:
        self.async_calls += 1
        return {"async": True, "inputs": inputs, "output": self.output}

    def kickoff(self, inputs: dict[str, Any] | None = None) -> Any:
        # Should NOT be called when kickoff_async exists.
        self.sync_calls += 1
        return "wrong-path"


@pytest.mark.asyncio
async def test_adapter_prefers_kickoff_async_when_available() -> None:
    system = await Pyre.start()
    crew = AsyncStubCrew()
    supervised = await supervise(lambda: crew, system=system, name="async-crew")

    result = await supervised.kickoff({"topic": "x"})

    assert result == {"async": True, "inputs": {"topic": "x"}, "output": "async-done"}
    assert crew.async_calls == 1
    assert crew.sync_calls == 0
    await system.stop_system()


@pytest.mark.asyncio
async def test_concurrent_crews_are_isolated() -> None:
    system = await Pyre.start()
    healthy = await supervise(lambda: StubCrew(output="ok"), system=system, name="healthy")
    flaky = await supervise(
        lambda: StubCrew(output="nope", fail_once=True), system=system, name="flaky"
    )

    with pytest.raises(AgentInvocationError):
        await flaky.kickoff()
    # The flaky crew's crash does not affect the healthy one.
    assert await healthy.kickoff() == "ok"
    assert await healthy.kickoffs() == 1
    await system.stop_system()
