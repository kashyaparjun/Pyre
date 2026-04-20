"""Wrap a LangGraph compiled graph in a Pyre supervised process.

LangGraph already has its own durability story — set a Checkpointer and a graph
can resume mid-run after a crash, keyed by ``thread_id``. This adapter does
not replace that; what it adds is **isolation for many concurrent graphs**.
Spawn N supervised wrappers and a crash inside one graph does not touch the
others. You also get a uniform ``supervise()`` surface alongside the pydantic-ai
and CrewAI adapters.

Because LangGraph's Checkpointer already handles within-graph state, this
adapter does **not** enable ``preserve_state_on_restart``. A crashed graph
restart reinitializes — users that want durable mid-run resume should rely on
LangGraph's Checkpointer as the source of truth.

Install with `pip install pyre-agents[langgraph]`.
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
    from langgraph.graph.state import CompiledStateGraph  # type: ignore[import-not-found]

    from pyre_agents.runtime import PyreSystem


# Keyed by a UUID generated per supervise() call. Factories are held here
# because a LangGraph CompiledStateGraph is not serializable through Pyre's
# args dict; the Pyre bridge stores only the key and looks up the factory on
# each invoke. Entries are removed when the SupervisedGraph is stopped.
_FACTORY_REGISTRY: dict[str, Callable[[], Any]] = {}


class _GraphState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_key: str
    invocations: int = 0


async def _invoke_graph(graph: Any, input_: Any, config: dict[str, Any] | None) -> Any:
    """Call graph.ainvoke if available, otherwise offload sync invoke to a thread."""
    async_fn = getattr(graph, "ainvoke", None)
    if callable(async_fn):
        if config is None:
            return await async_fn(input_)
        return await async_fn(input_, config=config)
    sync_fn = graph.invoke
    if config is None:
        return await asyncio.to_thread(sync_fn, input_)
    return await asyncio.to_thread(sync_fn, input_, config=config)


class _LangGraphBridge(Agent[_GraphState]):
    async def init(self, **args: object) -> _GraphState:
        key = str(args["registry_key"])
        if key not in _FACTORY_REGISTRY:
            raise RuntimeError(
                f"LangGraph factory '{key}' is not registered; "
                "supervise() must run in the same process as .invoke()"
            )
        return _GraphState(registry_key=key)

    async def handle_call(
        self,
        state: _GraphState,
        msg: dict[str, Any],
        ctx: AgentContext,
    ) -> CallResult[_GraphState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        if msg_type == "invoke":
            factory = _FACTORY_REGISTRY[state.registry_key]
            graph = factory()
            input_ = payload["input"]
            config = payload.get("config")
            if config is not None and not isinstance(config, dict):
                raise TypeError("config must be a dict")
            result = await _invoke_graph(graph, input_, config)
            new_state = _GraphState(
                registry_key=state.registry_key,
                invocations=state.invocations + 1,
            )
            return CallResult(reply=result, new_state=new_state)
        if msg_type == "invocations":
            return CallResult(reply=state.invocations, new_state=state)
        raise ValueError(f"unknown call type: {msg_type}")


@dataclass(frozen=True)
class SupervisedGraph:
    """Handle for a supervised LangGraph compiled graph."""

    _ref: AgentRef
    _registry_key: str

    @property
    def name(self) -> str:
        return self._ref.name

    async def invoke(self, input_: Any, config: dict[str, Any] | None = None) -> Any:
        return await self._ref.call("invoke", {"input": input_, "config": config})

    async def invocations(self) -> int:
        return cast(int, await self._ref.call("invocations", {}))

    async def stop(self) -> None:
        await self._ref.stop()
        _FACTORY_REGISTRY.pop(self._registry_key, None)


async def supervise(
    graph_factory: Callable[[], CompiledStateGraph],
    *,
    system: PyreSystem,
    name: str,
    max_restarts: int = 3,
    within_ms: int = 5000,
    supervisor: str | None = None,
) -> SupervisedGraph:
    """Wrap a LangGraph compiled graph factory in a Pyre supervised process.

    Accepts a *factory* (callable returning a ``CompiledStateGraph``) rather
    than a graph instance so each invocation — including restarts after a
    crash — gets a fresh compiled graph. If the graph has a Checkpointer,
    ``config={"configurable": {"thread_id": ...}}`` threaded through ``invoke``
    continues to work exactly as it does without Pyre.
    """
    registry_key = f"{name}:{uuid4().hex}"
    _FACTORY_REGISTRY[registry_key] = graph_factory
    ref = await system.spawn(
        _LangGraphBridge,
        name=name,
        args={"registry_key": registry_key},
        max_restarts=max_restarts,
        within_ms=within_ms,
        supervisor=supervisor,
    )
    return SupervisedGraph(_ref=ref, _registry_key=registry_key)
