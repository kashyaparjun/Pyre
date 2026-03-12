"""Supervision configuration for runtime-managed agents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RestartStrategy(StrEnum):
    """Supported restart strategies."""

    ONE_FOR_ONE = "one_for_one"
    ONE_FOR_ALL = "one_for_all"
    REST_FOR_ONE = "rest_for_one"


@dataclass(frozen=True)
class RestartPolicy:
    """Restart intensity bounds for a managed agent."""

    max_restarts: int = 3
    within_ms: int = 5000


@dataclass(frozen=True)
class SupervisorSpec:
    """Configuration for a supervisor group."""

    name: str
    strategy: RestartStrategy = RestartStrategy.ONE_FOR_ONE
    restart_policy: RestartPolicy = RestartPolicy()
    parent: str | None = None
