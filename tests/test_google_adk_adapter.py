"""Tests for the google-adk adapter using stub Runner + SessionService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pyre_agents import AgentInvocationError, Pyre
from pyre_agents.adapters.google_adk import supervise


@dataclass
class _StubPart:
    text: str


@dataclass
class _StubContent:
    role: str
    parts: list[_StubPart]


@dataclass
class _StubEvent:
    content: _StubContent
    final: bool = True

    def is_final_response(self) -> bool:
        return self.final


@dataclass
class _StubSession:
    events: list[_StubEvent] = field(default_factory=list)


class _StubSessionService:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str, str], _StubSession] = {}

    def create_session(self, *, app_name: str, user_id: str, session_id: str) -> _StubSession:
        key = (app_name, user_id, session_id)
        self.sessions.setdefault(key, _StubSession())
        return self.sessions[key]

    def get_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> _StubSession | None:
        return self.sessions.get((app_name, user_id, session_id))


@dataclass
class _StubRunner:
    """Mirrors ADK's Runner.run_async shape; no network."""

    responses: list[str]
    session_service: _StubSessionService
    app_name: str
    fail_on_inputs: set[str] = field(default_factory=set)
    calls: int = 0

    async def run_async(
        self, *, user_id: str, session_id: str, new_message: Any
    ):
        text = (
            new_message
            if isinstance(new_message, str)
            else "".join(p.text for p in new_message.parts)
        )
        if text in self.fail_on_inputs:
            raise RuntimeError(f"stub runner blew up on input: {text!r}")
        reply = self.responses[self.calls % len(self.responses)]
        self.calls += 1

        sess = self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if sess is None:
            sess = self.session_service.create_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
        sess.events.append(_StubEvent(content=_StubContent(role="user", parts=[_StubPart(text)])))
        event = _StubEvent(content=_StubContent(role="model", parts=[_StubPart(reply)]))
        sess.events.append(event)
        yield event


class _StubAgent:
    name = "stub"


@pytest.mark.asyncio
async def test_supervised_adk_returns_final_text_and_tracks_history() -> None:
    system = await Pyre.start()
    service = _StubSessionService()
    runner = _StubRunner(
        responses=["first", "second"], session_service=service, app_name="pyre-adk-adk"
    )
    supervised = await supervise(
        _StubAgent(), system=system, name="adk", session_service=service, runner=runner
    )

    assert await supervised.run("hi") == "first"
    assert await supervised.run("again") == "second"
    events = await supervised.history()
    assert [e.content.parts[0].text for e in events] == ["hi", "first", "again", "second"]
    await system.stop_system()


@pytest.mark.asyncio
async def test_session_survives_runner_crash_via_supervision() -> None:
    system = await Pyre.start()
    service = _StubSessionService()
    runner = _StubRunner(
        responses=["hello", "after"],
        session_service=service,
        app_name="pyre-adk-flaky",
        fail_on_inputs={"CRASH"},
    )
    supervised = await supervise(
        _StubAgent(), system=system, name="flaky", session_service=service, runner=runner
    )

    assert await supervised.run("hi") == "hello"
    pre = await supervised.history()

    with pytest.raises(AgentInvocationError):
        await supervised.run("CRASH")

    # Session events from turn 1 survive; session_id pointer preserved.
    post = await supervised.history()
    assert [e.content.parts[0].text for e in post][:2] == ["hi", "hello"]
    assert len(post) >= len(pre)

    assert await supervised.run("still there?") == "after"
    final = await supervised.history()
    assert [e.content.parts[0].text for e in final][-2:] == ["still there?", "after"]
    await system.stop_system()


@pytest.mark.asyncio
async def test_reset_rotates_session_id() -> None:
    system = await Pyre.start()
    service = _StubSessionService()
    runner = _StubRunner(
        responses=["a", "b"], session_service=service, app_name="pyre-adk-reset"
    )
    supervised = await supervise(
        _StubAgent(), system=system, name="reset", session_service=service, runner=runner
    )

    await supervised.run("first")
    assert len(await supervised.history()) == 2

    await supervised.reset()
    assert await supervised.history() == []
    await system.stop_system()
