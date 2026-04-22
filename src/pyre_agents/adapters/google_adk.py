"""Wrap a Google ADK (``google-adk``) agent in a Pyre supervised process.

ADK's ``Runner.run_async`` streams events against a session held by a
``SessionService``. A crash midway through ``run_async`` leaves the run
aborted; Pyre restarts the bridge, and because the session service lives
in the parent process, the ``(user_id, session_id)`` pointer preserved
by ``preserve_state_on_restart`` continues against the same session on
the next call.

Install with ``pip install pyre-agents[google-adk]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from pyre_agents.agent import Agent
from pyre_agents.context import AgentContext
from pyre_agents.ref import AgentRef
from pyre_agents.results import CallResult

if TYPE_CHECKING:
    from google.adk import Agent as ADKAgent  # type: ignore[import-not-found, unused-ignore]

    from pyre_agents.runtime import PyreSystem


# Keyed per supervise() call. Holds (agent, session_service, runner, app_name).
# Non-serializable objects live here; the bridge only carries the key.
_AGENT_REGISTRY: dict[str, tuple[Any, Any, Any, str]] = {}


class _ADKState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_key: str
    user_id: str
    session_id: str


async def _resolve_session_service(explicit: Any | None) -> Any:
    if explicit is not None:
        return explicit
    from google.adk.sessions import (
        InMemorySessionService,  # type: ignore[import-not-found, unused-ignore]
    )

    return InMemorySessionService()  # type: ignore[no-untyped-call, unused-ignore]


async def _resolve_runner(
    explicit: Any | None,
    agent_obj: Any,
    session_service: Any,
    app_name: str,
) -> Any:
    if explicit is not None:
        return explicit
    from google.adk import Runner  # type: ignore[import-not-found, unused-ignore]

    return Runner(app_name=app_name, agent=agent_obj, session_service=session_service)


def _coerce_message(new_message: Any) -> Any:
    """Wrap a plain string into ``google.genai.types.Content`` if possible.

    Already-structured inputs pass through untouched. If ``google.genai`` is
    not importable (e.g. in stub-based tests), we hand the input to the
    runner as-is so duck-typed stubs work.
    """
    if not isinstance(new_message, str):
        return new_message
    try:
        from google.genai import types  # type: ignore[import-not-found, unused-ignore]
    except ImportError:
        return new_message
    return types.Content(role="user", parts=[types.Part(text=new_message)])


async def _drain_final_text(events_iter: Any) -> str:
    final_text = ""
    async for event in events_iter:
        if not hasattr(event, "is_final_response") or not event.is_final_response():
            continue
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            final_text = "".join(getattr(p, "text", "") or "" for p in parts)
    return final_text


class _ADKBridge(Agent[_ADKState]):
    async def init(self, **args: object) -> _ADKState:
        key = str(args["registry_key"])
        if key not in _AGENT_REGISTRY:
            raise RuntimeError(
                f"google-adk agent '{key}' is not registered; "
                "supervise() must run in the same process as .run()"
            )
        return _ADKState(
            registry_key=key,
            user_id=str(args["user_id"]),
            session_id=str(args["session_id"]),
        )

    async def handle_call(
        self,
        state: _ADKState,
        msg: dict[str, Any],
        ctx: AgentContext,
    ) -> CallResult[_ADKState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        agent_obj, session_service, runner_override, app_name = _AGENT_REGISTRY[state.registry_key]

        if msg_type == "run":
            user_input = payload["input"]
            runner = await _resolve_runner(runner_override, agent_obj, session_service, app_name)

            # Ensure the session exists; ADK raises if we run against an
            # unknown session_id and auto_create_session isn't configured.
            if hasattr(session_service, "get_session"):
                existing = session_service.get_session(
                    app_name=app_name,
                    user_id=state.user_id,
                    session_id=state.session_id,
                )
                if hasattr(existing, "__await__"):
                    existing = await existing
                if existing is None and hasattr(session_service, "create_session"):
                    maybe = session_service.create_session(
                        app_name=app_name,
                        user_id=state.user_id,
                        session_id=state.session_id,
                    )
                    if hasattr(maybe, "__await__"):
                        await maybe

            events_iter = runner.run_async(
                user_id=state.user_id,
                session_id=state.session_id,
                new_message=_coerce_message(user_input),
            )
            final_text = await _drain_final_text(events_iter)
            return CallResult(reply=final_text, new_state=state)

        if msg_type == "history":
            events: list[Any] = []
            if hasattr(session_service, "get_session"):
                sess = session_service.get_session(
                    app_name=app_name,
                    user_id=state.user_id,
                    session_id=state.session_id,
                )
                if hasattr(sess, "__await__"):
                    sess = await sess
                if sess is not None:
                    events = list(getattr(sess, "events", []) or [])
            return CallResult(reply=events, new_state=state)

        if msg_type == "reset":
            new_session_id = f"s-{uuid4().hex}"
            return CallResult(
                reply=None,
                new_state=_ADKState(
                    registry_key=state.registry_key,
                    user_id=state.user_id,
                    session_id=new_session_id,
                ),
            )
        raise ValueError(f"unknown call type: {msg_type}")


@dataclass(frozen=True)
class SupervisedADKAgent:
    """Handle for a supervised google-adk Agent."""

    _ref: AgentRef
    _registry_key: str

    @property
    def name(self) -> str:
        return self._ref.name

    async def run(self, input_: Any) -> str:
        return cast(str, await self._ref.call("run", {"input": input_}))

    async def history(self) -> list[Any]:
        return cast(list[Any], await self._ref.call("history", {}))

    async def reset(self) -> None:
        await self._ref.call("reset", {})

    async def stop(self) -> None:
        await self._ref.stop()
        _AGENT_REGISTRY.pop(self._registry_key, None)


async def supervise(
    agent: ADKAgent,
    *,
    system: PyreSystem,
    name: str,
    app_name: str | None = None,
    user_id: str = "default",
    session_id: str | None = None,
    session_service: Any | None = None,
    runner: Any | None = None,
    max_restarts: int = 3,
    within_ms: int = 5000,
    supervisor: str | None = None,
) -> SupervisedADKAgent:
    """Wrap a google-adk ``Agent`` in a Pyre supervised process.

    ``session_service`` defaults to ``InMemorySessionService`` (in-process).
    Swap in ``DatabaseSessionService`` or ``SqliteSessionService`` for
    durable history that survives process restarts, not just handler crashes.

    ``runner`` can be passed to inject a stub for tests. Defaults to the
    library's ``Runner``, built lazily on first ``.run()``.
    """
    resolved_app = app_name or f"pyre-adk-{name}"
    resolved_session = session_id or f"s-{uuid4().hex}"
    resolved_service = await _resolve_session_service(session_service)

    if hasattr(resolved_service, "create_session"):
        maybe = resolved_service.create_session(
            app_name=resolved_app,
            user_id=user_id,
            session_id=resolved_session,
        )
        if hasattr(maybe, "__await__"):
            await maybe

    registry_key = f"{name}:{uuid4().hex}"
    _AGENT_REGISTRY[registry_key] = (agent, resolved_service, runner, resolved_app)

    ref = await system.spawn(
        _ADKBridge,
        name=name,
        args={
            "registry_key": registry_key,
            "user_id": user_id,
            "session_id": resolved_session,
        },
        max_restarts=max_restarts,
        within_ms=within_ms,
        supervisor=supervisor,
        preserve_state_on_restart=True,
    )
    return SupervisedADKAgent(_ref=ref, _registry_key=registry_key)
