"""Async transports for framed bridge envelopes.

Includes:
- `BridgeTransport`: simple single-flight stream transport
- `BridgeMultiplexedConnection`: one stream with in-flight correlation-id routing
- `BridgeTransportPool`: pooled multiplexed connections with adaptive in-flight gating
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

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

    @classmethod
    async def connect_unix(cls, path: str) -> BridgeTransport:
        """Connect to a Unix domain socket bridge endpoint."""
        reader, writer = await asyncio.open_unix_connection(path=path)
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


@dataclass(frozen=True)
class PoolMetrics:
    max_in_flight_observed: int
    backpressure_events: int


class BridgeMultiplexedConnection:
    """One transport connection supporting multiple in-flight requests.

    A background receive loop demultiplexes responses by correlation id.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        max_in_flight: int,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._max_in_flight = max_in_flight
        self._pending: dict[str, asyncio.Future[BridgeEnvelope]] = {}
        self._write_lock = asyncio.Lock()
        self._close_event = asyncio.Event()
        self._receiver_task: asyncio.Task[None] = asyncio.create_task(self._recv_loop())

    @classmethod
    async def connect_tcp(
        cls,
        host: str,
        port: int,
        *,
        max_in_flight: int,
    ) -> BridgeMultiplexedConnection:
        reader, writer = await asyncio.open_connection(host=host, port=port)
        return cls(reader, writer, max_in_flight=max_in_flight)

    @classmethod
    async def connect_unix(
        cls,
        path: str,
        *,
        max_in_flight: int,
    ) -> BridgeMultiplexedConnection:
        reader, writer = await asyncio.open_unix_connection(path=path)
        return cls(reader, writer, max_in_flight=max_in_flight)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def max_in_flight(self) -> int:
        return self._max_in_flight

    async def request(
        self, envelope: BridgeEnvelope, timeout_s: float | None = None
    ) -> BridgeEnvelope:
        if len(self._pending) >= self._max_in_flight:
            raise RuntimeError("connection in-flight limit reached")

        future: asyncio.Future[BridgeEnvelope] = asyncio.get_running_loop().create_future()
        self._pending[envelope.correlation_id] = future
        try:
            async with self._write_lock:
                await write_frame(self._writer, pack_envelope(envelope))
            if timeout_s is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout_s)
        finally:
            self._pending.pop(envelope.correlation_id, None)

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()
        if not self._receiver_task.done():
            self._receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receiver_task
        self._close_event.set()

    async def _recv_loop(self) -> None:
        try:
            while True:
                payload = await read_frame(self._reader)
                envelope = unpack_envelope(payload)
                future = self._pending.get(envelope.correlation_id)
                if future is not None and not future.done():
                    future.set_result(envelope)
        except Exception as exc:
            for pending in self._pending.values():
                if not pending.done():
                    pending.set_exception(
                        RuntimeError(f"connection receive loop terminated: {exc}")
                    )
        finally:
            self._close_event.set()


class BridgeTransportPool:
    """Pool of multiplexed bridge connections with adaptive in-flight gating."""

    def __init__(
        self,
        conns: list[BridgeMultiplexedConnection],
        *,
        max_in_flight_per_conn: int,
    ) -> None:
        self._conns = conns
        self._max_in_flight_per_conn = max_in_flight_per_conn
        self._next_idx = 0
        self._dispatch_lock = asyncio.Lock()
        self._backpressure_events = 0
        self._max_in_flight_observed = 0

    @classmethod
    async def connect_tcp(
        cls,
        host: str,
        port: int,
        *,
        pool_size: int,
        max_in_flight_per_conn: int,
    ) -> BridgeTransportPool:
        conns = [
            await BridgeMultiplexedConnection.connect_tcp(
                host,
                port,
                max_in_flight=max_in_flight_per_conn,
            )
            for _ in range(pool_size)
        ]
        return cls(conns, max_in_flight_per_conn=max_in_flight_per_conn)

    @classmethod
    async def connect_unix(
        cls,
        path: str,
        *,
        pool_size: int,
        max_in_flight_per_conn: int,
    ) -> BridgeTransportPool:
        conns = [
            await BridgeMultiplexedConnection.connect_unix(
                path,
                max_in_flight=max_in_flight_per_conn,
            )
            for _ in range(pool_size)
        ]
        return cls(conns, max_in_flight_per_conn=max_in_flight_per_conn)

    async def request(
        self, envelope: BridgeEnvelope, timeout_s: float | None = None
    ) -> BridgeEnvelope:
        conn = await self._pick_connection()
        return await conn.request(envelope, timeout_s=timeout_s)

    def metrics(self) -> PoolMetrics:
        return PoolMetrics(
            max_in_flight_observed=self._max_in_flight_observed,
            backpressure_events=self._backpressure_events,
        )

    async def close(self) -> None:
        for conn in self._conns:
            await conn.close()

    async def _pick_connection(self) -> BridgeMultiplexedConnection:
        # Optimized: Simple round-robin with minimal lock time
        async with self._dispatch_lock:
            idx = self._next_idx
            self._next_idx = (self._next_idx + 1) % len(self._conns)
            conn = self._conns[idx]

            # Check saturation
            if conn.pending_count >= self._max_in_flight_per_conn:
                self._backpressure_events += 1
                raise RuntimeError("transport pool saturated")

            # Update metrics
            total_pending = sum(c.pending_count for c in self._conns)
            if total_pending > self._max_in_flight_observed:
                self._max_in_flight_observed = total_pending

            return conn
