from __future__ import annotations

import asyncio
import contextlib
import os
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
UDS_PATTERN = re.compile(r"PYRE_BRIDGE_UDS_PATH=(.+)")


async def _start_elixir_bridge(
    *, env_overrides: dict[str, str] | None = None
) -> tuple[Process, int | None, str | None]:
    repo_root = Path(__file__).resolve().parents[1]
    elixir_dir = repo_root / "elixir" / "pyre_bridge"
    env = {**os.environ, **(env_overrides or {})}

    process = await asyncio.create_subprocess_exec(
        "mix",
        "run",
        "--no-start",
        "scripts/start_bridge.exs",
        cwd=str(elixir_dir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert process.stdout is not None
    output_lines: list[str] = []
    discovered_port: int | None = None
    discovered_uds_path: str | None = None
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=5)
        if not line:
            break
        decoded = line.decode("utf-8", errors="replace").strip()
        output_lines.append(decoded)
        match = PORT_PATTERN.search(decoded)
        if match:
            discovered_port = int(match.group(1))
        uds_match = UDS_PATTERN.search(decoded)
        if uds_match:
            discovered_uds_path = uds_match.group(1).strip()
        if discovered_port is not None or discovered_uds_path is not None:
            return process, discovered_port, discovered_uds_path

    await _stop_elixir_bridge(process)
    reason = "\n".join(output_lines) if output_lines else "<no output>"
    raise RuntimeError(
        "failed to discover bridge endpoint from Elixir process output:\n" + reason
    )


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
    process, port, _ = await _start_elixir_bridge()
    assert port is not None
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
async def test_elixir_ping_pong_roundtrip_over_uds() -> None:
    if shutil.which("mix") is None:
        pytest.skip("mix is not available")
    uds_path = f"/tmp/pyre_bridge_test_{uuid4().hex}.sock"
    process, _port, discovered_uds = await _start_elixir_bridge(
        env_overrides={
            "PYRE_BRIDGE_TRANSPORT_MODE": "uds",
            "PYRE_BRIDGE_UDS_PATH": uds_path,
        }
    )
    assert discovered_uds is not None
    transport = await BridgeTransport.connect_unix(discovered_uds)
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
        await _stop_elixir_bridge(process)


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
    initial: int = 0,
    handler: str | None = None,
    role: str | None = None,
    worker_id: str | None = None,
    group: str | None = None,
    strategy: str | None = None,
    parent: str | None = None,
    max_restarts: int | None = None,
    within_ms: int | None = None,
) -> None:
    spawn_opts: dict[str, object] = {"initial": initial}
    if handler is not None:
        spawn_opts["handler"] = handler
    if role is not None:
        spawn_opts["role"] = role
    if worker_id is not None:
        spawn_opts["worker_id"] = worker_id
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


async def _bridge_get_status(transport: BridgeTransport, *, agent_id: str) -> dict[str, object]:
    status = await _bridge_call_agent(
        transport, agent_id=agent_id, call_type="get_status", payload={}
    )
    assert isinstance(status, dict)
    return status


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


async def _bridge_wait_status(
    transport: BridgeTransport, *, agent_id: str, attempts: int = 20
) -> dict[str, object]:
    for idx in range(attempts):
        try:
            return await _bridge_get_status(transport, agent_id=agent_id)
        except RuntimeError:
            if idx == attempts - 1:
                raise
            await asyncio.sleep(0.02)
    raise RuntimeError("agent did not become available in time")


async def _bridge_wait_unavailable(
    transport: BridgeTransport, *, agent_id: str, attempts: int = 20
) -> None:
    for idx in range(attempts):
        try:
            await _bridge_get_status(transport, agent_id=agent_id)
        except RuntimeError:
            return
        if idx == attempts - 1:
            break
        await asyncio.sleep(0.02)
    raise AssertionError(f"agent {agent_id} remained available")


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


@pytest.mark.asyncio
async def test_elixir_workflow_coordinator_collects_worker_results_over_bridge(
    elixir_bridge: tuple[str, int],
) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    group = f"workflow-{uuid4()}"
    coordinator = f"coordinator-{uuid4()}"
    worker_a = f"worker-a-{uuid4()}"
    worker_b = f"worker-b-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport,
            agent_id=coordinator,
            handler="workflow",
            role="coordinator",
            group=group,
            strategy="one_for_one",
        )
        await _bridge_spawn_agent(
            transport,
            agent_id=worker_a,
            handler="workflow",
            role="worker",
            worker_id=worker_a,
            group=group,
        )
        await _bridge_spawn_agent(
            transport,
            agent_id=worker_b,
            handler="workflow",
            role="worker",
            worker_id=worker_b,
            group=group,
        )

        registered = await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="register_workers",
            payload={"worker_ids": [worker_a, worker_b]},
        )
        assert registered == {"workers": [worker_a, worker_b]}

        batch = await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="dispatch_batch",
            payload={
                "assignments": [
                    {"worker_id": worker_a, "task_id": "research", "units": 2},
                    {"worker_id": worker_b, "task_id": "summarize", "units": 3},
                ]
            },
        )
        assert isinstance(batch, dict)
        assert batch == {
            "round": 1,
            "results": [
                {"worker_id": worker_a, "task_id": "research", "units": 2, "sequence": 1},
                {"worker_id": worker_b, "task_id": "summarize", "units": 3, "sequence": 1},
            ],
            "worker_count": 2,
        }

        coordinator_status = await _bridge_get_status(transport, agent_id=coordinator)
        worker_a_status = await _bridge_get_status(transport, agent_id=worker_a)
        worker_b_status = await _bridge_get_status(transport, agent_id=worker_b)

        assert coordinator_status == {
            "role": "coordinator",
            "workers": [worker_a, worker_b],
            "rounds": 1,
            "last_results": batch["results"],
            "total_units": 5,
        }
        assert worker_a_status == {
            "role": "worker",
            "worker_id": worker_a,
            "completed_tasks": [batch["results"][0]],
            "total_units": 2,
        }
        assert worker_b_status == {
            "role": "worker",
            "worker_id": worker_b,
            "completed_tasks": [batch["results"][1]],
            "total_units": 3,
        }

        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=worker_a, call_type="boom", payload={})

        # one_for_one keeps the coordinator alive while the crashed worker restarts cleanly
        restarted_worker = await _bridge_wait_status(transport, agent_id=worker_a)
        assert restarted_worker == {
            "role": "worker",
            "worker_id": worker_a,
            "completed_tasks": [],
            "total_units": 0,
        }
        assert await _bridge_get_status(transport, agent_id=worker_b) == worker_b_status
        assert await _bridge_get_status(transport, agent_id=coordinator) == coordinator_status

        second_batch = await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="dispatch_batch",
            payload={"assignments": [{"worker_id": worker_a, "task_id": "retry", "units": 4}]},
        )
        assert isinstance(second_batch, dict)
        assert second_batch == {
            "round": 2,
            "results": [{"worker_id": worker_a, "task_id": "retry", "units": 4, "sequence": 1}],
            "worker_count": 2,
        }
        assert await _bridge_get_status(transport, agent_id=coordinator) == {
            "role": "coordinator",
            "workers": [worker_a, worker_b],
            "rounds": 2,
            "last_results": second_batch["results"],
            "total_units": 9,
        }
    finally:
        await _bridge_stop_agent(transport, agent_id=coordinator)
        await _bridge_stop_agent(transport, agent_id=worker_a)
        await _bridge_stop_agent(transport, agent_id=worker_b)
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_workflow_group_restart_resets_coordinator_and_workers_over_bridge(
    elixir_bridge: tuple[str, int],
) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    group = f"workflow-group-{uuid4()}"
    coordinator = f"coordinator-{uuid4()}"
    worker_a = f"worker-a-{uuid4()}"
    worker_b = f"worker-b-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport,
            agent_id=coordinator,
            handler="workflow",
            role="coordinator",
            group=group,
            strategy="one_for_all",
        )
        await _bridge_spawn_agent(
            transport,
            agent_id=worker_a,
            handler="workflow",
            role="worker",
            worker_id=worker_a,
            group=group,
        )
        await _bridge_spawn_agent(
            transport,
            agent_id=worker_b,
            handler="workflow",
            role="worker",
            worker_id=worker_b,
            group=group,
        )

        await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="register_workers",
            payload={"worker_ids": [worker_a, worker_b]},
        )
        await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="dispatch_batch",
            payload={
                "assignments": [
                    {"worker_id": worker_a, "task_id": "phase-a", "units": 1},
                    {"worker_id": worker_b, "task_id": "phase-b", "units": 2},
                ]
            },
        )

        with pytest.raises(RuntimeError):
            await _bridge_call_agent(transport, agent_id=worker_a, call_type="boom", payload={})

        coordinator_status = await _bridge_wait_status(transport, agent_id=coordinator)
        worker_a_status = await _bridge_wait_status(transport, agent_id=worker_a)
        worker_b_status = await _bridge_wait_status(transport, agent_id=worker_b)

        assert coordinator_status == {
            "role": "coordinator",
            "workers": [],
            "rounds": 0,
            "last_results": [],
            "total_units": 0,
        }
        assert worker_a_status == {
            "role": "worker",
            "worker_id": worker_a,
            "completed_tasks": [],
            "total_units": 0,
        }
        assert worker_b_status == {
            "role": "worker",
            "worker_id": worker_b,
            "completed_tasks": [],
            "total_units": 0,
        }

        # After a one_for_all reset the workflow must re-register workers and can continue cleanly.
        assert await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="register_workers",
            payload={"worker_ids": [worker_a, worker_b]},
        ) == {"workers": [worker_a, worker_b]}
        resumed_batch = await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="dispatch_batch",
            payload={"assignments": [{"worker_id": worker_b, "task_id": "phase-c", "units": 5}]},
        )
        assert isinstance(resumed_batch, dict)
        assert resumed_batch == {
            "round": 1,
            "results": [{"worker_id": worker_b, "task_id": "phase-c", "units": 5, "sequence": 1}],
            "worker_count": 2,
        }
    finally:
        await _bridge_stop_agent(transport, agent_id=coordinator)
        await _bridge_stop_agent(transport, agent_id=worker_a)
        await _bridge_stop_agent(transport, agent_id=worker_b)
        await transport.close()


@pytest.mark.asyncio
async def test_elixir_workflow_stop_cleanup_breaks_follow_up_calls_over_bridge(
    elixir_bridge: tuple[str, int],
) -> None:
    host, port = elixir_bridge
    transport = await BridgeTransport.connect_tcp(host, port)
    coordinator = f"coordinator-{uuid4()}"
    worker = f"worker-{uuid4()}"
    try:
        await _bridge_spawn_agent(
            transport, agent_id=coordinator, handler="workflow", role="coordinator"
        )
        await _bridge_spawn_agent(
            transport,
            agent_id=worker,
            handler="workflow",
            role="worker",
            worker_id=worker,
        )

        await _bridge_call_agent(
            transport,
            agent_id=coordinator,
            call_type="register_workers",
            payload={"worker_ids": [worker]},
        )

        await _bridge_stop_agent(transport, agent_id=coordinator)
        await _bridge_stop_agent(transport, agent_id=worker)

        await _bridge_wait_unavailable(transport, agent_id=coordinator)
        await _bridge_wait_unavailable(transport, agent_id=worker)

        with pytest.raises(RuntimeError):
            await _bridge_get_status(transport, agent_id=coordinator)
        with pytest.raises(RuntimeError):
            await _bridge_get_status(transport, agent_id=worker)
    finally:
        await transport.close()
