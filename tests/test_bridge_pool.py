from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from pyre_agents.bridge.codec import pack_envelope, unpack_envelope
from pyre_agents.bridge.framing import read_frame, write_frame
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType
from pyre_agents.bridge.transport import BridgeTransportPool


@pytest.mark.asyncio
async def test_multiplexed_pool_matches_responses_by_correlation_id_under_reordering() -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        first = unpack_envelope(await read_frame(reader))
        second = unpack_envelope(await read_frame(reader))

        # Respond in reverse order to validate correlation-id based demux.
        response_second = BridgeEnvelope(
            correlation_id=second.correlation_id,
            type=MessageType.RESULT,
            agent_id=second.agent_id,
            state=second.state,
            reply=second.message,
        )
        response_first = BridgeEnvelope(
            correlation_id=first.correlation_id,
            type=MessageType.RESULT,
            agent_id=first.agent_id,
            state=first.state,
            reply=first.message,
        )
        await write_frame(writer, pack_envelope(response_second))
        await write_frame(writer, pack_envelope(response_first))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, host="127.0.0.1", port=0)
    port = int(server.sockets[0].getsockname()[1])

    pool = await BridgeTransportPool.connect_tcp(
        "127.0.0.1",
        port,
        pool_size=1,
        max_in_flight_per_conn=8,
    )
    try:
        a = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="a",
            handler="handle_call",
            state=b"{}",
            message=b"a",
        )
        b = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="b",
            handler="handle_call",
            state=b"{}",
            message=b"b",
        )

        reply_a_task = asyncio.create_task(pool.request(a))
        reply_b_task = asyncio.create_task(pool.request(b))
        reply_a, reply_b = await asyncio.gather(reply_a_task, reply_b_task)

        assert reply_a.correlation_id == a.correlation_id
        assert reply_b.correlation_id == b.correlation_id
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_pool_reports_backpressure_when_saturated() -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        envelope = unpack_envelope(await read_frame(reader))
        await asyncio.sleep(0.1)
        response = BridgeEnvelope(
            correlation_id=envelope.correlation_id,
            type=MessageType.RESULT,
            agent_id=envelope.agent_id,
            state=envelope.state,
            reply=envelope.message,
        )
        await write_frame(writer, pack_envelope(response))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, host="127.0.0.1", port=0)
    port = int(server.sockets[0].getsockname()[1])

    pool = await BridgeTransportPool.connect_tcp(
        "127.0.0.1",
        port,
        pool_size=1,
        max_in_flight_per_conn=1,
    )
    try:
        first = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="a",
            handler="handle_call",
            state=b"{}",
            message=b"a",
        )
        second = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="a",
            handler="handle_call",
            state=b"{}",
            message=b"b",
        )

        pending = asyncio.create_task(pool.request(first))
        await asyncio.sleep(0.01)
        with pytest.raises(RuntimeError, match="saturated"):
            await pool.request(second)
        _ = await pending

        metrics = pool.metrics()
        assert metrics.backpressure_events >= 1
    finally:
        await pool.close()
        server.close()
        await server.wait_closed()
