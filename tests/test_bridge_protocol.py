from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from pyre_agents.bridge.protocol import BridgeEnvelope, BridgeErrorPayload, MessageType


def test_execute_envelope_requires_agent_handler_state_message() -> None:
    correlation_id = str(uuid4())

    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(
            {
                "correlation_id": correlation_id,
                "type": "execute",
                "agent_id": "agent-1",
            }
        )


def test_invalid_correlation_id_rejected() -> None:
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(
            {
                "correlation_id": "not-a-uuid",
                "type": "ping",
            }
        )


def test_error_envelope_requires_error_payload() -> None:
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(
            {
                "correlation_id": str(uuid4()),
                "type": "error",
                "agent_id": "agent-1",
            }
        )


def test_error_payload_validates() -> None:
    payload = BridgeErrorPayload(type="timeout", message="handler timed out", stack=None)
    assert payload.type == "timeout"


def test_unknown_message_type_rejected() -> None:
    with pytest.raises(ValidationError):
        BridgeEnvelope.model_validate(
            {
                "correlation_id": str(uuid4()),
                "type": "not-real",
            }
        )


def test_to_wire_dict_renders_enum_value() -> None:
    envelope = BridgeEnvelope(
        correlation_id=str(uuid4()),
        type=MessageType.PING,
    )

    wire = envelope.to_wire_dict()
    assert wire["type"] == "ping"
