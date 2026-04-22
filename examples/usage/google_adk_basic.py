"""Google ADK + Pyre — basic usage.

Run with:  uv run --with 'google-adk>=1.0' python examples/usage/google_adk.py

A real ``google.adk.Agent`` paired with stub ``Runner`` + ``SessionService``
so the example runs without ``GOOGLE_API_KEY``. Drop the ``runner=`` and
``session_service=`` overrides to let the adapter build the real
``Runner`` and ``InMemorySessionService`` lazily.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from google.adk import Agent  # type: ignore[import-not-found]
except ImportError:
    print("Install with: pip install 'google-adk>=1.0'")
    sys.exit(1)

from pyre_agents import Pyre
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

    def is_final_response(self) -> bool:
        return True


@dataclass
class _StubSession:
    events: list[_StubEvent] = field(default_factory=list)


class _StubSessionService:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str, str], _StubSession] = {}

    def create_session(self, *, app_name: str, user_id: str, session_id: str) -> _StubSession:
        self.sessions.setdefault((app_name, user_id, session_id), _StubSession())
        return self.sessions[(app_name, user_id, session_id)]

    def get_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> _StubSession | None:
        return self.sessions.get((app_name, user_id, session_id))


@dataclass
class _StubRunner:
    session_service: _StubSessionService
    app_name: str
    responses: tuple[str, ...] = ("Hi, I'm your ADK agent.", "Yes — the session continues.")
    calls: int = 0

    async def run_async(self, *, user_id: str, session_id: str, new_message: Any):
        reply = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        text = (
            new_message
            if isinstance(new_message, str)
            else "".join(p.text for p in new_message.parts)
        )
        sess = self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        ) or self.session_service.create_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        sess.events.append(_StubEvent(content=_StubContent(role="user", parts=[_StubPart(text)])))
        event = _StubEvent(content=_StubContent(role="model", parts=[_StubPart(reply)]))
        sess.events.append(event)
        yield event


async def main() -> None:
    agent: Agent = Agent(name="assistant", instruction="Be concise.")
    service = _StubSessionService()
    runner = _StubRunner(session_service=service, app_name="pyre-adk-usage")

    system = await Pyre.start()
    try:
        supervised = await supervise(
            agent,
            system=system,
            name="assistant",
            app_name="pyre-adk-usage",
            session_service=service,
            runner=runner,
        )

        r1 = await supervised.run("Who are you?")
        r2 = await supervised.run("Do you remember our first turn?")

        print(f"turn 1: {r1}")
        print(f"turn 2: {r2}")
        print(f"session events: {len(await supervised.history())}")
    finally:
        await system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
