"""Agent reference handle exposed to users."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


class AgentRef:
    """Reference to a managed agent."""

    def __init__(self, runtime: PyreSystem, name: str) -> None:
        self._runtime = runtime
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def call(self, type_: str, payload: dict[str, Any]) -> Any:
        return await self._runtime.call(self._name, type_, payload)

    async def cast(self, type_: str, payload: dict[str, Any]) -> None:
        await self._runtime.cast(self._name, type_, payload)

    async def send_info(self, type_: str, payload: dict[str, Any]) -> None:
        await self._runtime.info(self._name, type_, payload)

    async def stop(self) -> None:
        await self._runtime.stop(self._name)


if TYPE_CHECKING:
    from pyre_agents.runtime import PyreSystem
