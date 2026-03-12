"""Async transport client for framed bridge envelopes."""

from __future__ import annotations

import asyncio

from pyre_agents.bridge.codec import pack_envelope, unpack_envelope
from pyre_agents.bridge.framing import read_frame, write_frame
from pyre_agents.bridge.protocol import BridgeEnvelope


class BridgeTransport:
    """Async client transport around an asyncio stream pair."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect_tcp(cls, host: str, port: int) -> BridgeTransport:
        """Connect to a TCP bridge endpoint."""
        reader, writer = await asyncio.open_connection(host=host, port=port)
        return cls(reader, writer)

    async def send_envelope(self, envelope: BridgeEnvelope) -> None:
        """Serialize and send one envelope."""
        await write_frame(self._writer, pack_envelope(envelope))

    async def recv_envelope(self) -> BridgeEnvelope:
        """Receive and deserialize one envelope."""
        payload = await read_frame(self._reader)
        return unpack_envelope(payload)

    async def close(self) -> None:
        """Close the underlying stream writer."""
        self._writer.close()
        await self._writer.wait_closed()
