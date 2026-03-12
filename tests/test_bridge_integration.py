from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from pyre_agents.bridge.codec import pack_payload, unpack_payload
from pyre_agents.bridge.framing import pack_frame
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType
from pyre_agents.bridge.server import BridgeHealthEvent, BridgeHealthEventType, BridgeServer
from pyre_agents.bridge.transport import BridgeTransport


@pytest.mark.asyncio
async def test_ping_pong_roundtrip() -> None:
    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        assert envelope.type is MessageType.PING
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    server = BridgeServer(handler)
    await server.start()
    transport = await BridgeTransport.connect_tcp("127.0.0.1", server.port)

    correlation_id = str(uuid4())
    await transport.send_envelope(
        BridgeEnvelope(correlation_id=correlation_id, type=MessageType.PING)
    )
    response = await transport.recv_envelope()

    assert response.correlation_id == correlation_id
    assert response.type is MessageType.PONG

    await transport.close()
    await server.close()


@pytest.mark.asyncio
async def test_execute_result_roundtrip() -> None:
    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        assert envelope.type is MessageType.EXECUTE
        assert envelope.agent_id == "researcher-1"
        incoming = unpack_payload(envelope.message or b"")

        state = unpack_payload(envelope.state or b"")
        next_turn = int(state["turn"]) + 1
        return BridgeEnvelope(
            correlation_id=envelope.correlation_id,
            type=MessageType.RESULT,
            agent_id=envelope.agent_id,
            state=pack_payload({"turn": next_turn}),
            reply=pack_payload({"echo": incoming["query"]}),
        )

    server = BridgeServer(handler)
    await server.start()
    transport = await BridgeTransport.connect_tcp("127.0.0.1", server.port)

    correlation_id = str(uuid4())
    await transport.send_envelope(
        BridgeEnvelope(
            correlation_id=correlation_id,
            type=MessageType.EXECUTE,
            agent_id="researcher-1",
            handler="handle_call",
            state=pack_payload({"turn": 2}),
            message=pack_payload({"query": "ai safety"}),
        )
    )

    response = await transport.recv_envelope()
    assert response.type is MessageType.RESULT
    assert response.correlation_id == correlation_id
    assert response.agent_id == "researcher-1"
    assert unpack_payload(response.state or b"") == {"turn": 3}
    assert unpack_payload(response.reply or b"") == {"echo": "ai safety"}

    await transport.close()
    await server.close()


@pytest.mark.asyncio
async def test_server_closes_connection_on_malformed_msgpack() -> None:
    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    server = BridgeServer(handler)
    await server.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(pack_frame(b"\x81\xc1"))
    await writer.drain()

    data = await asyncio.wait_for(reader.read(1), timeout=1.0)
    assert data == b""

    writer.close()
    await writer.wait_closed()
    await server.close()


@pytest.mark.asyncio
async def test_server_closes_connection_on_unknown_message_type() -> None:
    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    server = BridgeServer(handler)
    await server.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    invalid_envelope = {
        "correlation_id": str(uuid4()),
        "type": "unknown_type",
    }
    writer.write(pack_frame(pack_payload(invalid_envelope)))
    await writer.drain()

    data = await asyncio.wait_for(reader.read(1), timeout=1.0)
    assert data == b""

    writer.close()
    await writer.wait_closed()
    await server.close()


@pytest.mark.asyncio
async def test_server_emits_health_events_for_connection_lifecycle() -> None:
    events: list[BridgeHealthEventType] = []

    def on_health(event: BridgeHealthEvent) -> None:
        events.append(event.type)

    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    server = BridgeServer(handler, on_health_event=on_health)
    await server.start()
    transport = await BridgeTransport.connect_tcp("127.0.0.1", server.port)

    await transport.send_envelope(
        BridgeEnvelope(correlation_id=str(uuid4()), type=MessageType.PING)
    )
    _ = await transport.recv_envelope()

    await transport.close()
    await asyncio.sleep(0.02)
    await server.close()

    assert events[0] is BridgeHealthEventType.SERVER_STARTED
    assert BridgeHealthEventType.CONNECTION_OPENED in events
    assert BridgeHealthEventType.MESSAGE_RECEIVED in events
    assert BridgeHealthEventType.MESSAGE_SENT in events
    assert BridgeHealthEventType.CONNECTION_CLOSED in events
    assert events[-1] is BridgeHealthEventType.SERVER_STOPPED


@pytest.mark.asyncio
async def test_server_emits_connection_error_health_event() -> None:
    observed_errors: list[str] = []

    def on_health(event: BridgeHealthEvent) -> None:
        if event.type is BridgeHealthEventType.CONNECTION_ERROR and event.error is not None:
            observed_errors.append(event.error)

    async def handler(envelope: BridgeEnvelope) -> BridgeEnvelope:
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    server = BridgeServer(handler, on_health_event=on_health)
    await server.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(pack_frame(b"\x81\xc1"))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1), timeout=1.0)
    assert data == b""

    writer.close()
    await writer.wait_closed()
    await asyncio.sleep(0.02)
    await server.close()

    assert observed_errors
    assert any("BridgeCodecError" in value for value in observed_errors)
