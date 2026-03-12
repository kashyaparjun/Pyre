"""Result types for lifecycle handler callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class CallResult[StateT: BaseModel]:
    """Return type for Agent.handle_call."""

    reply: Any
    new_state: StateT
