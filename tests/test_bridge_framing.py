from __future__ import annotations

import asyncio

import pytest

from pyre_agents.bridge.framing import FrameTooLargeError, pack_frame, read_frame


def test_pack_frame_prefixes_big_endian_length() -> None:
    payload = b"hello"
    framed = pack_frame(payload)

    assert framed[:4] == b"\x00\x00\x00\x05"
    assert framed[4:] == payload


@pytest.mark.asyncio
async def test_read_frame_returns_payload() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(pack_frame(b"ping"))
    reader.feed_eof()

    payload = await read_frame(reader)
    assert payload == b"ping"


@pytest.mark.asyncio
async def test_read_frame_raises_for_large_payload() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data((8).to_bytes(4, byteorder="big") + b"12345678")
    reader.feed_eof()

    with pytest.raises(FrameTooLargeError):
        await read_frame(reader, max_frame_size=4)


@pytest.mark.asyncio
async def test_read_frame_raises_for_truncated_payload() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data((10).to_bytes(4, byteorder="big") + b"short")
    reader.feed_eof()

    with pytest.raises(asyncio.IncompleteReadError):
        await read_frame(reader)
