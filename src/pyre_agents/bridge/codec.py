"""MessagePack codec helpers for bridge payloads and envelopes."""

from __future__ import annotations

from typing import Any, cast

import msgpack  # type: ignore[import-untyped]
from pydantic import ValidationError

from pyre_agents.bridge.protocol import BridgeEnvelope


class BridgeCodecError(Exception):
    """Raised when bridge data cannot be encoded or decoded."""


def pack_payload(payload: Any) -> bytes:
    """Encode a Python payload to MessagePack bytes."""
    try:
        # Optimized: use_bin_type for better performance with binary data
        return cast(bytes, msgpack.packb(payload, use_bin_type=True))
    except (TypeError, ValueError, msgpack.PackException) as exc:
        raise BridgeCodecError("Failed to encode MessagePack payload") from exc


def unpack_payload(payload: bytes) -> Any:
    """Decode MessagePack bytes to a Python value."""
    try:
        # Optimized: raw=False for automatic string decoding
        return msgpack.unpackb(payload, raw=False)
    except (ValueError, msgpack.ExtraData, msgpack.FormatError, msgpack.StackError) as exc:
        raise BridgeCodecError("Failed to decode MessagePack payload") from exc


def pack_envelope(envelope: BridgeEnvelope) -> bytes:
    """Encode a bridge envelope to MessagePack bytes."""
    return pack_payload(envelope.to_wire_dict())


def unpack_envelope(payload: bytes) -> BridgeEnvelope:
    """Decode MessagePack bytes into a validated bridge envelope."""
    unpacked = unpack_payload(payload)
    if not isinstance(unpacked, dict):
        raise BridgeCodecError("Envelope payload must decode to a dictionary")

    data = cast(dict[str, Any], unpacked)
    try:
        # Optimized: Use model_construct to bypass validation for performance
        # This assumes the data is already validated on the wire
        return BridgeEnvelope.model_construct(**data)
    except Exception as exc:
        # Fall back to full validation if construct fails
        try:
            return BridgeEnvelope.model_validate(data)
        except ValidationError as val_err:
            raise BridgeCodecError("Envelope validation failed") from val_err
