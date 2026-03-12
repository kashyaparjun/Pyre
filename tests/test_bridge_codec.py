from __future__ import annotations

from uuid import uuid4

import pytest

from pyre_agents.bridge.codec import (
    BridgeCodecError,
    pack_envelope,
    pack_payload,
    unpack_envelope,
    unpack_payload,
)
from pyre_agents.bridge.protocol import BridgeEnvelope, BridgeErrorPayload, MessageType


def test_envelope_roundtrip() -> None:
    envelope = BridgeEnvelope(
        correlation_id=str(uuid4()),
        type=MessageType.RESULT,
        agent_id="researcher-1",
        state=pack_payload({"turn": 3}),
        reply=pack_payload({"ok": True}),
    )

    raw = pack_envelope(envelope)
    decoded = unpack_envelope(raw)

    assert decoded.correlation_id == envelope.correlation_id
    assert decoded.type is MessageType.RESULT
    assert decoded.agent_id == "researcher-1"
    assert unpack_payload(decoded.state or b"") == {"turn": 3}
    assert unpack_payload(decoded.reply or b"") == {"ok": True}


def test_unpack_envelope_rejects_non_dict() -> None:
    not_dict = pack_payload(["not", "an", "envelope"])
    with pytest.raises(BridgeCodecError):
        unpack_envelope(not_dict)


def test_unpack_payload_rejects_invalid_msgpack() -> None:
    with pytest.raises(BridgeCodecError):
        unpack_payload(b"\x81\xc1")


def test_pack_payload_rejects_unsupported_type() -> None:
    with pytest.raises(BridgeCodecError):
        pack_payload({uuid4()})


def test_error_envelope_roundtrip() -> None:
    envelope = BridgeEnvelope(
        correlation_id=str(uuid4()),
        type=MessageType.ERROR,
        agent_id="researcher-2",
        error=BridgeErrorPayload(type="runtime_error", message="boom", stack="trace"),
    )

    decoded = unpack_envelope(pack_envelope(envelope))
    assert decoded.error is not None
    assert decoded.error.message == "boom"
