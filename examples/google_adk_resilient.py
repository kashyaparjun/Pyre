"""Google ADK + Pyre: Runner crashes don't drop the session.

Run with:  uv run --with 'google-adk>=1.0' python examples/google_adk_resilient.py

What it demonstrates:
    1. A real google-adk ``Agent`` is wrapped in a Pyre supervised process
       via ``supervise(agent, system=..., name=..., session_service=...,
       runner=...)``.
    2. The ``Runner`` this example passes to ``supervise(runner=...)`` is a
       stub that mirrors the real ``google.adk.Runner.run_async`` shape —
       deterministic, no network. That lets the example run without a
       ``GOOGLE_API_KEY`` while still exercising the real Agent + adapter.
    3. The stub raises on the second ``.run()``. Without Pyre, that
       exception would kill the run; with Pyre, the bridge restarts,
       ``preserve_state_on_restart`` keeps the ``(user_id, session_id)``
       pointer, and the next call continues against the same session —
       events from turn 1 are still there.

To go live, delete the ``runner=`` / ``session_service=`` overrides and set
``GOOGLE_API_KEY``. The adapter builds a real ``Runner`` and
``InMemorySessionService`` lazily.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from google.adk import Agent as ADKAgent  # type: ignore[import-not-found]
except ImportError:
    print("This example needs google-adk. Install with: pip install 'google-adk>=1.0'")
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
    responses: tuple[str, ...] = ("bees are pollinators", "skipped", "wasps are predators")
    calls: int = 0

    async def run_async(self, *, user_id: str, session_id: str, new_message: Any):
        text = (
            new_message
            if isinstance(new_message, str)
            else "".join(p.text for p in new_message.parts)
        )
        attempt = self.calls
        self.calls += 1
        if attempt == 1:
            raise RuntimeError("stub runner: transient 503 on call 2")
        reply = self.responses[attempt % len(self.responses)]

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
    agent: ADKAgent = ADKAgent(name="assistant", instruction="You are helpful.")
    service = _StubSessionService()
    runner = _StubRunner(session_service=service, app_name="pyre-adk-chat")

    system = await Pyre.start()
    try:
        supervised = await supervise(
            agent,
            system=system,
            name="chat",
            app_name="pyre-adk-chat",
            session_service=service,
            runner=runner,
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
