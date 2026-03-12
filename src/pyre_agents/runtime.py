"""Runtime orchestration surface for Python agents."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from pydantic import BaseModel

from pyre_agents.agent import Agent
from pyre_agents.context import AgentContext
from pyre_agents.errors import AgentInvocationError, AgentNotFoundError, AgentTerminatedError
from pyre_agents.ref import AgentRef
from pyre_agents.supervision import RestartPolicy, RestartStrategy, SupervisorSpec
from pyre_agents.worker import Worker

ROOT_SUPERVISOR = "__root__"
ROOT_POLICY = RestartPolicy(max_restarts=1_000_000, within_ms=60_000)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    args: dict[str, Any]
    restart_policy: RestartPolicy
    supervisor: str


@dataclass
class ManagedAgent:
    spec: AgentSpec
    agent: Agent[Any]
    state: BaseModel
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    terminated: bool = False
    crash_times: deque[float] = field(default_factory=deque)


@dataclass
class SupervisorGroup:
    spec: SupervisorSpec
    children: list[str] = field(default_factory=list)
    child_supervisors: list[str] = field(default_factory=list)
    crash_times: deque[float] = field(default_factory=deque)
    terminated: bool = False


class PyreSystem:
    """In-process runtime implementing lifecycle and supervision behavior."""

    def __init__(self) -> None:
        self._agents: dict[str, ManagedAgent] = {}
        self._worker = Worker()
        self._started = False
        self._supervisors: dict[str, SupervisorGroup] = {
            ROOT_SUPERVISOR: SupervisorGroup(
                spec=SupervisorSpec(
                    name=ROOT_SUPERVISOR,
                    strategy=RestartStrategy.ONE_FOR_ONE,
                    restart_policy=ROOT_POLICY,
                    parent=None,
                )
            )
        }

    @classmethod
    async def start(cls) -> PyreSystem:
        runtime = cls()
        runtime._started = True
        return runtime

    async def stop_system(self) -> None:
        self._agents.clear()
        self._supervisors = {
            ROOT_SUPERVISOR: SupervisorGroup(
                spec=SupervisorSpec(
                    name=ROOT_SUPERVISOR,
                    strategy=RestartStrategy.ONE_FOR_ONE,
                    restart_policy=ROOT_POLICY,
                    parent=None,
                )
            )
        }
        self._started = False

    async def create_supervisor(
        self,
        *,
        name: str,
        strategy: RestartStrategy = RestartStrategy.ONE_FOR_ONE,
        max_restarts: int = 3,
        within_ms: int = 5000,
        parent: str | None = None,
    ) -> None:
        if not self._started:
            raise RuntimeError("PyreSystem is not started")
        if name in self._supervisors:
            raise ValueError(f"Supervisor '{name}' already exists")
        if name == ROOT_SUPERVISOR:
            raise ValueError(f"'{ROOT_SUPERVISOR}' is reserved")

        parent_name = parent or ROOT_SUPERVISOR
        parent_group = self._supervisors.get(parent_name)
        if parent_group is None:
            raise ValueError(f"Supervisor '{parent_name}' not found")
        if parent_group.terminated:
            raise AgentTerminatedError(f"Supervisor '{parent_name}' is terminated")

        self._supervisors[name] = SupervisorGroup(
            spec=SupervisorSpec(
                name=name,
                strategy=strategy,
                restart_policy=RestartPolicy(max_restarts=max_restarts, within_ms=within_ms),
                parent=parent_name,
            )
        )
        parent_group.child_supervisors.append(name)

    async def spawn(
        self,
        agent_cls: type[Agent[Any]],
        *,
        name: str,
        args: dict[str, Any] | None = None,
        max_restarts: int = 3,
        within_ms: int = 5000,
        strategy: RestartStrategy = RestartStrategy.ONE_FOR_ONE,
        supervisor: str | None = None,
    ) -> AgentRef:
        if not self._started:
            raise RuntimeError("PyreSystem is not started")
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already exists")

        supervisor_name = supervisor or ROOT_SUPERVISOR
        group = self._supervisors.get(supervisor_name)
        if group is None:
            raise ValueError(f"Supervisor '{supervisor_name}' not found")
        if group.terminated:
            raise AgentTerminatedError(f"Supervisor '{supervisor_name}' is terminated")
        if strategy != RestartStrategy.ONE_FOR_ONE and supervisor is None:
            raise ValueError(
                "Agent-level strategy is no longer supported; create a supervisor group instead"
            )

        init_args = args or {}
        agent = agent_cls()
        state = await agent.init(**init_args)
        if not isinstance(state, BaseModel):
            raise TypeError("Agent.init must return a Pydantic BaseModel")

        managed = ManagedAgent(
            spec=AgentSpec(
                name=name,
                args=init_args,
                restart_policy=RestartPolicy(max_restarts=max_restarts, within_ms=within_ms),
                supervisor=supervisor_name,
            ),
            agent=agent,
            state=state,
        )
        self._agents[name] = managed
        group.children.append(name)
        return AgentRef(self, name)

    async def stop(self, name: str) -> None:
        managed = self._agents.pop(name, None)
        if managed is None:
            return
        group = self._supervisors.get(managed.spec.supervisor)
        if group is not None and name in group.children:
            group.children.remove(name)

    async def call(self, name: str, type_: str, payload: dict[str, Any]) -> Any:
        managed = self._get_managed(name)
        msg = {"type": type_, "payload": payload}
        ctx = AgentContext(self, name)
        async with managed.lock:
            self._ensure_not_terminated(managed)
            try:
                outcome = await self._worker.run_call(managed.agent, managed.state, msg, ctx)
                managed.state = outcome.new_state
                return outcome.reply
            except Exception as exc:
                await self._handle_crash(managed, exc)
                raise AgentInvocationError(f"Agent '{name}' crashed during call") from exc

    async def cast(self, name: str, type_: str, payload: dict[str, Any]) -> None:
        managed = self._get_managed(name)
        msg = {"type": type_, "payload": payload}
        ctx = AgentContext(self, name)
        async with managed.lock:
            self._ensure_not_terminated(managed)
            try:
                managed.state = await self._worker.run_cast(managed.agent, managed.state, msg, ctx)
            except Exception as exc:
                await self._handle_crash(managed, exc)

    async def info(self, name: str, type_: str, payload: dict[str, Any]) -> None:
        managed = self._get_managed(name)
        msg = {"type": type_, "payload": payload}
        ctx = AgentContext(self, name)
        async with managed.lock:
            self._ensure_not_terminated(managed)
            try:
                managed.state = await self._worker.run_info(managed.agent, managed.state, msg, ctx)
            except Exception as exc:
                await self._handle_crash(managed, exc)

    async def send_after(
        self, name: str, type_: str, payload: dict[str, Any], delay_ms: int
    ) -> asyncio.Task[None]:
        async def _run() -> None:
            await asyncio.sleep(delay_ms / 1000)
            await self.cast(name, type_, payload)

        return asyncio.create_task(_run())

    async def _handle_crash(self, managed: ManagedAgent, original_error: Exception) -> None:
        self._record_crash(managed.crash_times, managed.spec.restart_policy)
        if len(managed.crash_times) > managed.spec.restart_policy.max_restarts:
            managed.terminated = True
            raise AgentTerminatedError(
                f"Agent '{managed.spec.name}' exceeded restart policy"
            ) from original_error

        group = self._get_supervisor(managed.spec.supervisor)
        self._record_crash(group.crash_times, group.spec.restart_policy)
        if len(group.crash_times) > group.spec.restart_policy.max_restarts:
            self._terminate_supervisor(group.spec.name)
            raise AgentTerminatedError(
                f"Supervisor '{group.spec.name}' exceeded restart policy"
            ) from original_error

        for name in self._restart_targets(group, managed.spec.name):
            child = self._get_managed(name)
            if child.terminated:
                continue
            await self._restart_agent(child)

    async def _restart_agent(self, managed: ManagedAgent) -> None:
        replacement = type(managed.agent)()
        state = await replacement.init(**managed.spec.args)
        if not isinstance(state, BaseModel):
            raise TypeError("Agent.init must return a Pydantic BaseModel")
        managed.agent = replacement
        managed.state = state

    def _restart_targets(self, group: SupervisorGroup, crashed_name: str) -> list[str]:
        if crashed_name not in group.children:
            return [crashed_name]

        if group.spec.strategy == RestartStrategy.ONE_FOR_ONE:
            return [crashed_name]
        if group.spec.strategy == RestartStrategy.ONE_FOR_ALL:
            return list(group.children)

        crash_index = group.children.index(crashed_name)
        return group.children[crash_index:]

    def _terminate_supervisor(self, supervisor_name: str) -> None:
        group = self._get_supervisor(supervisor_name)
        group.terminated = True
        for child_name in group.children:
            child = self._agents.get(child_name)
            if child is not None:
                child.terminated = True
        for child_supervisor_name in group.child_supervisors:
            self._terminate_supervisor(child_supervisor_name)

    def _record_crash(self, crash_times: deque[float], policy: RestartPolicy) -> None:
        now = monotonic()
        window_s = policy.within_ms / 1000
        crash_times.append(now)
        while crash_times and crash_times[0] < now - window_s:
            crash_times.popleft()

    def _get_managed(self, name: str) -> ManagedAgent:
        managed = self._agents.get(name)
        if managed is None:
            raise AgentNotFoundError(f"Agent '{name}' not found")
        return managed

    def _get_supervisor(self, name: str) -> SupervisorGroup:
        supervisor = self._supervisors.get(name)
        if supervisor is None:
            raise ValueError(f"Supervisor '{name}' not found")
        return supervisor

    def _ensure_not_terminated(self, managed: ManagedAgent) -> None:
        if managed.terminated:
            raise AgentTerminatedError(f"Agent '{managed.spec.name}' is terminated")


class Pyre:
    """Public lifecycle API."""

    @staticmethod
    async def start() -> PyreSystem:
        return await PyreSystem.start()

    @staticmethod
    def from_runtime(runtime: PyreSystem) -> Callable[[], PyreSystem]:
        return lambda: runtime
