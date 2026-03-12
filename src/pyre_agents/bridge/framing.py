"""Length-prefixed framing helpers for bridge transport."""

from __future__ import annotations

import asyncio
from typing import Final

HEADER_SIZE: Final[int] = 4
UINT32_MAX: Final[int] = 2**32 - 1


class FrameTooLargeError(ValueError):
    """Raised when a frame exceeds allowed size constraints."""


def pack_frame(payload: bytes) -> bytes:
    """Prefix a payload with a 4-byte big-endian length header."""
    payload_size = len(payload)
    if payload_size > UINT32_MAX:
        raise FrameTooLargeError(f"Frame size {payload_size} exceeds uint32 max")
    return payload_size.to_bytes(HEADER_SIZE, byteorder="big") + payload


async def read_frame(reader: asyncio.StreamReader, max_frame_size: int = UINT32_MAX) -> bytes:
    """Read one length-prefixed frame from an asyncio stream."""
    if max_frame_size <= 0:
        raise ValueError("max_frame_size must be positive")

    header = await reader.readexactly(HEADER_SIZE)
    payload_size = int.from_bytes(header, byteorder="big")
    if payload_size > max_frame_size:
        raise FrameTooLargeError(
            f"Frame size {payload_size} exceeds configured max_frame_size {max_frame_size}"
        )
    return await reader.readexactly(payload_size)


async def write_frame(writer: asyncio.StreamWriter, payload: bytes) -> None:
    """Write one length-prefixed frame to an asyncio stream."""
    writer.write(pack_frame(payload))
    await writer.drain()
