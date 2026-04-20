"""Protocol models for bridge message envelopes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageType(StrEnum):
    """Supported bridge message types."""

    EXECUTE = "execute"
    RESULT = "result"
    ERROR = "error"
    REGISTER = "register"
    DEREGISTER = "deregister"
    SPAWN = "spawn"
    STOP = "stop"
    PING = "ping"
    PONG = "pong"


class BridgeErrorPayload(BaseModel):
    """Error payload returned by the worker or orchestrator."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    stack: str | None = None


class BridgeEnvelope(BaseModel):
    """Common envelope used by every bridge message."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=1)
    type: MessageType
    agent_id: str | None = None
    handler: str | None = None
    state: bytes | None = None
    message: bytes | None = None
    reply: bytes | None = None
    error: BridgeErrorPayload | None = None
    queue_depth: int | None = Field(default=None, ge=0)
    retry_after_ms: int | None = Field(default=None, ge=0)
    busy_reason: str | None = None

    @field_validator("correlation_id")
    @classmethod
    def _validate_correlation_id(cls, value: str) -> str:
        # A full uuid.UUID() parse was measurably expensive on the hot path, so
        # we use a shape check: 36 chars with hyphens at the UUID offsets and
        # hex everywhere else. Matches the spec without the parser cost.
        if len(value) != 36:
            raise ValueError("correlation_id must be a 36-char UUID string")
        for i, ch in enumerate(value):
            if i in (8, 13, 18, 23):
                if ch != "-":
                    raise ValueError("correlation_id has misplaced hyphen")
            elif ch not in "0123456789abcdefABCDEF":
                raise ValueError("correlation_id has non-hex character")
        return value

    @model_validator(mode="after")
    def _validate_by_message_type(self) -> BridgeEnvelope:
        if self.type is MessageType.EXECUTE:
            self._require_fields("agent_id", "handler", "state", "message")
        elif self.type is MessageType.RESULT:
            self._require_fields("agent_id", "state")
        elif self.type is MessageType.ERROR:
            self._require_fields("agent_id", "error")
        elif self.type in {
            MessageType.REGISTER,
            MessageType.DEREGISTER,
            MessageType.SPAWN,
            MessageType.STOP,
        }:
            self._require_fields("agent_id")
        return self

    def _require_fields(self, *field_names: str) -> None:
        for field_name in field_names:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} is required for message type '{self.type.value}'")

    def to_wire_dict(self) -> dict[str, Any]:
        """Convert envelope to a bridge-safe dictionary."""
        # Optimized: exclude_none reduces payload size and serialization time
        payload = self.model_dump(mode="python", exclude_none=True)
        payload["type"] = self.type.value
        return payload
