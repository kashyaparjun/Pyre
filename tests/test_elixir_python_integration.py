from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import signal
from asyncio.subprocess import Process
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest

from pyre_agents.bridge.codec import pack_payload, unpack_payload
from pyre_agents.bridge.framing import pack_frame
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType
from pyre_agents.bridge.transport import BridgeTransport

PORT_PATTERN = re.compile(r"PYRE_BRIDGE_PORT=(\d+)")


async def _start_elixir_bridge() -> tuple[Process, int]:
    repo_root = Path(__file__).resolve().parents[1]
    elixir_dir = repo_root / "elixir" / "pyre_bridge"

    process = await asyncio.create_subprocess_exec(
        "mix",
        "run",
        "--no-start",
        "scripts/start_bridge.exs",
        cwd=str(elixir_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert process.stdout is not None
    output_lines: list[str] = []
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=5)
        if not line:
            break
        decoded = line.decode("utf-8", errors="replace").strip()
        output_lines.append(decoded)
        match = PORT_PATTERN.search(decoded)
        if match:
            return process, int(match.group(1))

    await _stop_elixir_bridge(process)
    reason = "\n".join(output_lines) if output_lines else "<no output>"
    raise RuntimeError(f"failed to discover PYRE_BRIDGE_PORT from Elixir process output:\n{reason}")


async def _stop_elixir_bridge(process: Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


@pytest.fixture
async def elixir_bridge() -> AsyncIterator[tuple[str, int]]:
    if shutil.which("mix") is None:
        pytest.skip("mix is not available")
    process, port = await _start_elixir_bridge()
    try:
        yield "127.0.0.1", port
    finally:
        await _stop_elixir_bridge(process)


@pytest.mark.asyncio
async def test_elixir_ping_pong_roundtrip(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    try:
        correlation_id = str(uuid4())
        await transport.send_envelope(
            BridgeEnvelope(correlation_id=correlation_id, type=MessageType.PING)
        )
        response = await transport.recv_envelope()
        assert response.type is MessageType.PONG
        assert response.correlation_id == correlation_id
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_execute_result_roundtrip(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    try:
        correlation_id = str(uuid4())
        state = pack_payload({"turn": 5})
        message = pack_payload({"topic": "phase2"})
        await transport.send_envelope(
            BridgeEnvelope(
                correlation_id=correlation_id,
                type=MessageType.EXECUTE,
                agent_id="agent-1",
                handler="handle_call",
                state=state,
                message=message,
            )
        )
        response = await transport.recv_envelope()

        assert response.type is MessageType.RESULT
        assert response.correlation_id == correlation_id
        assert response.agent_id == "agent-1"
        assert unpack_payload(response.state or b"") == {"turn": 5}
        assert unpack_payload(response.reply or b"") == {"topic": "phase2"}
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_rejects_unknown_message_type(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    reader, writer = await asyncio.open_connection(host, port)
    try:
        payload = pack_payload({"correlation_id": str(uuid4()), "type": "nope"})
        writer.write(pack_frame(payload))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        assert data == b""
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_elixir_rejects_malformed_msgpack(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(pack_frame(b"\x81\xc1"))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1), timeout=2.0)
        assert data == b""
    finally:
        writer.close()
        await writer.wait_closed()


async def _bridge_spawn_agent(
    transport: BridgeTransport,
    *,
    agent_id: str,
    initial: int,
    group: str | None = None,
    strategy: str | None = None,
    parent: str | None = None,
    max_restarts: int | None = None,
    within_ms: int | None = None,
) -> None:
    spawn_opts: dict[str, object] = {"initial": initial}
    if group is not None:
        spawn_opts["group"] = group
    if strategy is not None:
        spawn_opts["strategy"] = strategy
    if parent is not None:
        spawn_opts["parent"] = parent
    if max_restarts is not None:
        spawn_opts["max_restarts"] = max_restarts
    if within_ms is not None:
        spawn_opts["within_ms"] = within_ms

    await transport.send_envelope(
        BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.SPAWN,
            agent_id=agent_id,
            message=pack_payload(spawn_opts),
        )
    )
    response = await transport.recv_envelope()
    assert response.type is MessageType.RESULT
    assert response.agent_id == agent_id


async def _bridge_call_agent(
    transport: BridgeTransport,
    *,
    agent_id: str,
    call_type: str,
    payload: dict[str, object],
) -> object:
    await transport.send_envelope(
        BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id=agent_id,
            handler="handle_call",
            state=pack_payload({}),
            message=pack_payload({"type": call_type, "payload": payload}),
        )
    )
    response = await transport.recv_envelope()
    assert response.agent_id == agent_id
    if response.type is MessageType.ERROR:
        detail = response.error.message if response.error is not None else "unknown bridge error"
        raise RuntimeError(detail)
    assert response.type is MessageType.RESULT
    decoded_reply = unpack_payload(response.reply or b"")
    assert isinstance(decoded_reply, dict)
    return decoded_reply["reply"]


async def _bridge_stop_agent(transport: BridgeTransport, *, agent_id: str) -> None:
    await transport.send_envelope(
        BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.STOP,
            agent_id=agent_id,
        )
    )
    _ = await transport.recv_envelope()


async def _bridge_wait_get(
    transport: BridgeTransport, *, agent_id: str, attempts: int = 20
) -> object:
    for idx in range(attempts):
        try:
            return await _bridge_call_agent(
                transport, agent_id=agent_id, call_type="get", payload={}
            )
        except RuntimeError:
            if idx == attempts - 1:
                raise
            await asyncio.sleep(0.02)
    raise RuntimeError("agent did not become available in time")


@pytest.mark.asyncio
async def test_elixir_supervision_one_for_all_over_bridge(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    group = f"group-{uuid4()}"
    first = f"first-{uuid4()}"
    second = f"second-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport,
            agent_id=first,
            initial=1,
            group=group,
            strategy="one_for_all",
        )
        await _bridge_spawn_agent(transport, agent_id=second, initial=10, group=group)

        assert await _bridge_call_agent(
            transport, agent_id=first, call_type="increment", payload={"amount": 5}
        ) == 6
        assert await _bridge_call_agent(
            transport, agent_id=second, call_type="increment", payload={"amount": 2}
        ) == 12

        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=first, call_type="boom", payload={})

        # one_for_all restarts all members in the group
        assert await _bridge_wait_get(transport, agent_id=first) == 1
        assert await _bridge_wait_get(transport, agent_id=second) == 10
    finally:
        await _bridge_stop_agent(transport, agent_id=first)
        await _bridge_stop_agent(transport, agent_id=second)
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_supervision_rest_for_one_over_bridge(elixir_bridge: tuple[str, int]) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    group = f"group-{uuid4()}"
    first = f"first-{uuid4()}"
    second = f"second-{uuid4()}"
    third = f"third-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport,
            agent_id=first,
            initial=1,
            group=group,
            strategy="rest_for_one",
        )
        await _bridge_spawn_agent(transport, agent_id=second, initial=10, group=group)
        await _bridge_spawn_agent(transport, agent_id=third, initial=100, group=group)

        assert await _bridge_call_agent(
            transport, agent_id=first, call_type="increment", payload={"amount": 5}
        ) == 6
        assert await _bridge_call_agent(
            transport, agent_id=second, call_type="increment", payload={"amount": 5}
        ) == 15
        assert await _bridge_call_agent(
            transport, agent_id=third, call_type="increment", payload={"amount": 5}
        ) == 105

        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=second, call_type="boom", payload={})

        # rest_for_one keeps older sibling but restarts crashed child and younger siblings
        assert await _bridge_wait_get(transport, agent_id=first) == 6
        assert await _bridge_wait_get(transport, agent_id=second) == 10
        assert await _bridge_wait_get(transport, agent_id=third) == 100
    finally:
        await _bridge_stop_agent(transport, agent_id=first)
        await _bridge_stop_agent(transport, agent_id=second)
        await _bridge_stop_agent(transport, agent_id=third)
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_supervision_group_restart_intensity_over_bridge(
    elixir_bridge: tuple[str, int],
) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    group = f"group-{uuid4()}"
    first = f"first-{uuid4()}"
    second = f"second-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport,
            agent_id=first,
            initial=1,
            group=group,
            strategy="one_for_all",
            max_restarts=1,
            within_ms=60_000,
        )
        await _bridge_spawn_agent(transport, agent_id=second, initial=10, group=group)

        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=first, call_type="boom", payload={})
        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=first, call_type="boom", payload={})

        with pytest.raises(RuntimeError):
            await _bridge_wait_get(transport, agent_id=first, attempts=5)
        with pytest.raises(RuntimeError):
            await _bridge_wait_get(transport, agent_id=second, attempts=5)
    finally:
        await transport.close()
