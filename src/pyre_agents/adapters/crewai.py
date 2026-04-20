"""Wrap a CrewAI Crew in a Pyre supervised process.

CrewAI's own fault story is thin: an exception in an agent or tool bubbles out of
``crew.kickoff()`` and kills the whole run. This adapter wraps a crew factory in a
supervised Pyre agent so that crashes are isolated from other concurrent crews and
a retry simply invokes a fresh crew instance without tearing down the surrounding
system.

Install with `pip install pyre-agents[crewai]`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from pyre_agents.agent import Agent
from pyre_agents.context import AgentContext
from pyre_agents.ref import AgentRef
from pyre_agents.results import CallResult

if TYPE_CHECKING:
    from crewai import Crew  # type: ignore[import-not-found]

    from pyre_agents.runtime import PyreSystem


# Keyed by a UUID generated per supervise() call. Factories are held here
# because a CrewAI Crew is not serializable through Pyre's args dict; the Pyre
# bridge stores only the key and looks up the factory on each kickoff. Entries
# are removed when the SupervisedCrew is stopped.
_FACTORY_REGISTRY: dict[str, Callable[[], Any]] = {}


class _CrewState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_key: str
    kickoffs: int = 0
    last_output: Any = None


async def _invoke_kickoff(crew: Any, inputs: dict[str, Any] | None) -> Any:
    """Call kickoff_async if available, otherwise run sync kickoff in a thread.

    Real CrewAI `kickoff()` does blocking network I/O; running it directly on the
    event loop would freeze every other supervised crew. We offload via
    `asyncio.to_thread` so concurrent crews actually run concurrently.
    """
    async_fn = getattr(crew, "kickoff_async", None)
    if callable(async_fn):
        if inputs is None:
            return await async_fn()
        return await async_fn(inputs=inputs)
    if inputs is None:
        return await asyncio.to_thread(crew.kickoff)
    return await asyncio.to_thread(crew.kickoff, inputs=inputs)


class _CrewAIBridge(Agent[_CrewState]):
    async def init(self, **args: object) -> _CrewState:
        key = str(args["registry_key"])
        if key not in _FACTORY_REGISTRY:
            raise RuntimeError(
                f"crew factory '{key}' is not registered; "
                "supervise() must run in the same process as .kickoff()"
            )
        return _CrewState(registry_key=key)

    async def handle_call(
        self,
        state: _CrewState,
        msg: dict[str, Any],
        ctx: AgentContext,
    ) -> CallResult[_CrewState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        if msg_type == "kickoff":
            factory = _FACTORY_REGISTRY[state.registry_key]
            crew = factory()
            inputs = payload.get("inputs")
            if inputs is not None and not isinstance(inputs, dict):
                raise TypeError("inputs must be a dict")
            output = await _invoke_kickoff(crew, inputs)
            new_state = _CrewState(
                registry_key=state.registry_key,
                kickoffs=state.kickoffs + 1,
                last_output=output,
            )
            return CallResult(reply=output, new_state=new_state)
        if msg_type == "kickoffs":
            return CallResult(reply=state.kickoffs, new_state=state)
        if msg_type == "last_output":
            return CallResult(reply=state.last_output, new_state=state)
        raise ValueError(f"unknown call type: {msg_type}")


@dataclass(frozen=True)
class SupervisedCrew:
    """Handle for a supervised CrewAI crew."""

    _ref: AgentRef
    _registry_key: str

    @property
    def name(self) -> str:
        return self._ref.name

    async def kickoff(self, inputs: dict[str, Any] | None = None) -> Any:
        return await self._ref.call("kickoff", {"inputs": inputs})

    async def kickoffs(self) -> int:
        return cast(int, await self._ref.call("kickoffs", {}))

    async def last_output(self) -> Any:
        return await self._ref.call("last_output", {})

    async def stop(self) -> None:
        await self._ref.stop()
        _FACTORY_REGISTRY.pop(self._registry_key, None)


async def supervise(
    crew_factory: Callable[[], Crew],
    *,
    system: PyreSystem,
    name: str,
    max_restarts: int = 3,
    within_ms: int = 5000,
    supervisor: str | None = None,
) -> SupervisedCrew:
    """Wrap a CrewAI crew factory in a Pyre supervised process.

    Accepts a *factory* (callable returning a fresh ``Crew``) rather than a crew
    instance because crews carry per-run state; a restart should get a clean
    instance. The kickoff counter and last output are preserved across restarts so
    callers can observe how many successful runs a crew has completed.
    """
    registry_key = f"{name}:{uuid4().hex}"
    _FACTORY_REGISTRY[registry_key] = crew_factory
    ref = await system.spawn(
        _CrewAIBridge,
        name=name,
        args={"registry_key": registry_key},
        max_restarts=max_restarts,
        within_ms=within_ms,
        supervisor=supervisor,
        preserve_state_on_restart=True,
    )
    return SupervisedCrew(_ref=ref, _registry_key=registry_key)
