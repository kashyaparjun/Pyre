"""Wrap an OpenAI Agents SDK Agent in a Pyre supervised process.

The OpenAI Agents SDK (``openai-agents``) has its own session abstraction
and run-error handler hooks, but the escape hatch is thin: an exception
that bubbles out of ``Runner.run`` kills the run and any unsaved
intermediate turns. This adapter wraps the Runner call in a supervised
Pyre process so those crashes restart with the prior turn's committed
input-list intact.

Install with `pip install pyre-agents[openai-agents]`.
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
    from agents import Agent as OpenAIAgent  # type: ignore[import-not-found, unused-ignore]

    from pyre_agents.runtime import PyreSystem


# Keyed per supervise() call. Holds the live Agent instance (not
# serializable through Pyre's args dict) plus an optional pre-wired Runner
# override for tests.
_AGENT_REGISTRY: dict[str, tuple[Any, Any]] = {}


class _OpenAIState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    registry_key: str
    history: list[Any] = []


async def _resolve_runner(explicit: Any | None) -> Any:
    if explicit is not None:
        return explicit
    # Lazy import so the adapter module is safe to load without the extra
    # installed; the import only happens when .run() is actually called.
    from agents import Runner  # type: ignore[import-not-found, unused-ignore]

    return Runner


class _OpenAIBridge(Agent[_OpenAIState]):
    async def init(self, **args: object) -> _OpenAIState:
        key = str(args["registry_key"])
        if key not in _AGENT_REGISTRY:
            raise RuntimeError(
                f"openai-agents agent '{key}' is not registered; "
                "supervise() must run in the same process as .run()"
            )
        return _OpenAIState(registry_key=key)

    async def handle_call(
        self,
        state: _OpenAIState,
        msg: dict[str, Any],
        ctx: AgentContext,
    ) -> CallResult[_OpenAIState]:
        msg_type = str(msg["type"])
        payload = msg["payload"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        if msg_type == "run":
            user_input = payload["input"]
            max_turns = payload.get("max_turns")
            run_config = payload.get("run_config")
            context = payload.get("context")

            agent_obj, runner_override = _AGENT_REGISTRY[state.registry_key]
            runner = await _resolve_runner(runner_override)

            # Thread previously-committed history into the new input so the
            # Runner continues the conversation. The SDK accepts either a
            # string or a list of input items; when we have history, we
            # always hand it a list.
            if state.history:
                if isinstance(user_input, str):
                    run_input: Any = [
                        *state.history,
                        {"role": "user", "content": user_input},
                    ]
                else:
                    run_input = [*state.history, *user_input]
            else:
                run_input = user_input

            kwargs: dict[str, Any] = {}
            if max_turns is not None:
                kwargs["max_turns"] = int(max_turns)
            if run_config is not None:
                kwargs["run_config"] = run_config
            if context is not None:
                kwargs["context"] = context

            result = await runner.run(agent_obj, run_input, **kwargs)
            if not hasattr(result, "final_output"):
                raise RuntimeError(
                    "Runner.run result has no .final_output; "
                    "this adapter requires openai-agents>=0.2"
                )
            new_state = _OpenAIState(
                registry_key=state.registry_key,
                history=list(result.to_input_list()),
            )
            return CallResult(reply=result.final_output, new_state=new_state)
        if msg_type == "history":
            return CallResult(reply=list(state.history), new_state=state)
        if msg_type == "reset":
            return CallResult(
                reply=None,
                new_state=_OpenAIState(registry_key=state.registry_key),
            )
        raise ValueError(f"unknown call type: {msg_type}")


@dataclass(frozen=True)
class SupervisedOpenAIAgent:
    """Handle for a supervised openai-agents Agent."""

    _ref: AgentRef
    _registry_key: str

    @property
    def name(self) -> str:
        return self._ref.name

    async def run(
        self,
        input_: Any,
        *,
        max_turns: int | None = None,
        run_config: Any | None = None,
        context: Any | None = None,
    ) -> Any:
        return await self._ref.call(
            "run",
            {
                "input": input_,
                "max_turns": max_turns,
                "run_config": run_config,
                "context": context,
            },
        )

    async def history(self) -> list[Any]:
        return cast(list[Any], await self._ref.call("history", {}))

    async def reset(self) -> None:
        await self._ref.call("reset", {})

    async def stop(self) -> None:
        await self._ref.stop()
        _AGENT_REGISTRY.pop(self._registry_key, None)


async def supervise(
    agent: OpenAIAgent[Any],
    *,
    system: PyreSystem,
    name: str,
    max_restarts: int = 3,
    within_ms: int = 5000,
    supervisor: str | None = None,
    runner: Any | None = None,
) -> SupervisedOpenAIAgent:
    """Wrap an openai-agents ``Agent`` in a Pyre supervised process.

    ``runner`` can be passed to substitute the default ``agents.Runner``
    (useful in tests where you want to inject a stub that doesn't make real
    API calls). Defaults to the library's Runner, imported lazily on first
    ``.run()`` so the module is safe to load without the extra.
    """
    registry_key = f"{name}:{uuid4().hex}"
    _AGENT_REGISTRY[registry_key] = (agent, runner)
    ref = await system.spawn(
        _OpenAIBridge,
        name=name,
        args={"registry_key": registry_key},
        max_restarts=max_restarts,
        within_ms=within_ms,
        supervisor=supervisor,
        preserve_state_on_restart=True,
    )
    return SupervisedOpenAIAgent(_ref=ref, _registry_key=registry_key)
