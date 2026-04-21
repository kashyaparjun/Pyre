"""Wrap a pydantic-ai Agent in a Pyre supervised process.

What this adapter does — and does not — catch:
    pydantic-ai already has its own error-handling layer. Tool exceptions are
    typically caught by the framework and fed back to the model as retries
    (via `ModelRetry` or the default tool-error handler). Those crashes never
    reach this adapter because they never escape `agent.run()`.

    Pyre sits one layer out: it restarts the bridge when an exception *does*
    escape `agent.run()`. In practice that's provider outages, unhandled
    exceptions inside custom model code, `FallbackModel` exhaustion, or bugs in
    tools that don't convert to `ModelRetry`. When those happen, Pyre's
    `preserve_state_on_restart` keeps the last-committed `message_history`
    intact, so the next `run()` continues the conversation instead of starting
    over.

Install with `pip install pyre-agents[pydantic-ai]`.
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
    # Ignore is needed when the optional extra is not installed; unused-ignore
    # prevents mypy from complaining when it IS installed.
    from pydantic_ai import (  # type: ignore[import-not-found, unused-ignore]
        Agent as PydanticAIAgent,
    )

    from pyre_agents.runtime import PyreSystem


# Keyed by a UUID generated per supervise() call. We route calls through this
# registry because pydantic-ai Agent instances are not serializable through
# Pyre's args dict; the Pyre bridge stores only the key and looks up the live
# agent here. Entries are removed when the SupervisedPydanticAIAgent is stopped.
_AGENT_REGISTRY: dict[str, Any] = {}


class _PydanticAIState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_key: str
    messages: list[Any] = []


class _PydanticAIBridge(Agent[_PydanticAIState]):
    async def init(self, **args: object) -> _PydanticAIState:
        key = str(args["registry_key"])
        if key not in _AGENT_REGISTRY:
            raise RuntimeError(
                f"pydantic-ai agent '{key}' is not registered; "
                "supervise() must run in the same process as .run()"
            )
        return _PydanticAIState(registry_key=key)

    async def handle_call(
        self,
        state: _PydanticAIState,
        msg: dict[str, Any],
        ctx: AgentContext,
    ) -> CallResult[_PydanticAIState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        if msg_type == "run":
            prompt = payload["prompt"]
            if not isinstance(prompt, str):
                raise TypeError(f"prompt must be str, got {type(prompt).__name__}")
            deps = payload.get("deps")
            model_settings = payload.get("model_settings")
            pyd_agent = _AGENT_REGISTRY[state.registry_key]
            kwargs: dict[str, Any] = {
                "message_history": list(state.messages) if state.messages else None,
            }
            if deps is not None:
                kwargs["deps"] = deps
            if model_settings is not None:
                kwargs["model_settings"] = model_settings
            result = await pyd_agent.run(prompt, **kwargs)
            if not hasattr(result, "output"):
                raise RuntimeError(
                    "pydantic-ai RunResult has no .output attribute; "
                    "this adapter requires pydantic-ai>=1.0"
                )
            new_state = _PydanticAIState(
                registry_key=state.registry_key,
                messages=list(result.all_messages()),
            )
            return CallResult(reply=result.output, new_state=new_state)
        if msg_type == "history":
            return CallResult(reply=list(state.messages), new_state=state)
        if msg_type == "reset":
            return CallResult(
                reply=None,
                new_state=_PydanticAIState(registry_key=state.registry_key),
            )
        raise ValueError(f"unknown call type: {msg_type}")


@dataclass(frozen=True)
class SupervisedPydanticAIAgent:
    """Handle returned by ``supervise`` — drop-in replacement for ``.run``."""

    _ref: AgentRef
    _registry_key: str

    @property
    def name(self) -> str:
        return self._ref.name

    async def run(
        self,
        prompt: str,
        *,
        deps: Any = None,
        model_settings: dict[str, Any] | None = None,
    ) -> Any:
        return await self._ref.call(
            "run",
            {"prompt": prompt, "deps": deps, "model_settings": model_settings},
        )

    async def history(self) -> list[Any]:
        return cast(list[Any], await self._ref.call("history", {}))

    async def reset(self) -> None:
        await self._ref.call("reset", {})

    async def stop(self) -> None:
        await self._ref.stop()
        _AGENT_REGISTRY.pop(self._registry_key, None)


async def supervise(
    pydantic_agent: PydanticAIAgent[Any, Any],
    *,
    system: PyreSystem,
    name: str,
    max_restarts: int = 3,
    within_ms: int = 5000,
    supervisor: str | None = None,
) -> SupervisedPydanticAIAgent:
    """Wrap a pydantic-ai ``Agent`` in a Pyre supervised process.

    A crash inside a tool or model call causes Pyre to restart the bridge; because
    ``preserve_state_on_restart`` is on, the conversation history is retained and the
    next ``run()`` picks up exactly where the previous successful turn left off.
    """
    registry_key = f"{name}:{uuid4().hex}"
    _AGENT_REGISTRY[registry_key] = pydantic_agent
    ref = await system.spawn(
        _PydanticAIBridge,
        name=name,
        args={"registry_key": registry_key},
        max_restarts=max_restarts,
        within_ms=within_ms,
        supervisor=supervisor,
        preserve_state_on_restart=True,
    )
    return SupervisedPydanticAIAgent(_ref=ref, _registry_key=registry_key)
