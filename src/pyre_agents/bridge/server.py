"""Async bridge server spike for local protocol validation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from pyre_agents.bridge.codec import BridgeCodecError, pack_envelope, unpack_envelope
from pyre_agents.bridge.framing import FrameTooLargeError, read_frame, write_frame
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType

EnvelopeHandler = Callable[[BridgeEnvelope], Awaitable[BridgeEnvelope]]
HealthHook = Callable[["BridgeHealthEvent"], Awaitable[None] | None]


class BridgeHealthEventType(StrEnum):
    """Health event names emitted by BridgeServer."""

    SERVER_STARTED = "server_started"
    SERVER_STOPPED = "server_stopped"
    CONNECTION_OPENED = "connection_opened"
    CONNECTION_CLOSED = "connection_closed"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    CONNECTION_ERROR = "connection_error"


@dataclass(frozen=True)
class BridgeHealthEvent:
    """Structured health signal emitted from BridgeServer."""

    type: BridgeHealthEventType
    peer: tuple[str, int] | tuple[str, int, int, int] | None = None
    message_type: MessageType | None = None
    error: str | None = None


class BridgeServer:
    """Simple asyncio server that maps one envelope to one envelope."""

    def __init__(self, handler: EnvelopeHandler, on_health_event: HealthHook | None = None) -> None:
        self._handler = handler
        self._on_health_event = on_health_event
        self._server: asyncio.base_events.Server | None = None

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Start listening for bridge connections."""
        if self._server is not None:
            raise RuntimeError("BridgeServer is already started")

        self._server = await asyncio.start_server(self._handle_client, host=host, port=port)
        await self._emit_health(BridgeHealthEvent(type=BridgeHealthEventType.SERVER_STARTED))

    @property
    def port(self) -> int:
        """Return the bound port for TCP mode."""
        if self._server is None or self._server.sockets is None or not self._server.sockets:
            raise RuntimeError("BridgeServer is not started")
        return int(self._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        """Stop accepting new connections and close active sockets."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        await self._emit_health(BridgeHealthEvent(type=BridgeHealthEventType.SERVER_STOPPED))

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = cast(
            tuple[str, int] | tuple[str, int, int, int] | None,
            writer.get_extra_info("peername"),
        )
        await self._emit_health(
            BridgeHealthEvent(type=BridgeHealthEventType.CONNECTION_OPENED, peer=peer)
        )
        try:
            while True:
                payload = await read_frame(reader)
                envelope = unpack_envelope(payload)
                await self._emit_health(
                    BridgeHealthEvent(
                        type=BridgeHealthEventType.MESSAGE_RECEIVED,
                        peer=peer,
                        message_type=envelope.type,
                    )
                )
                response = await self._handler(envelope)
                await write_frame(writer, pack_envelope(response))
                await self._emit_health(
                    BridgeHealthEvent(
                        type=BridgeHealthEventType.MESSAGE_SENT,
                        peer=peer,
                        message_type=response.type,
                    )
                )
        except asyncio.IncompleteReadError:
            pass
        except (
            BridgeCodecError,
            ConnectionResetError,
            FrameTooLargeError,
            ValueError,
        ) as exc:
            await self._emit_health(
                BridgeHealthEvent(
                    type=BridgeHealthEventType.CONNECTION_ERROR,
                    peer=peer,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            await self._emit_health(
                BridgeHealthEvent(type=BridgeHealthEventType.CONNECTION_CLOSED, peer=peer)
            )

    async def _emit_health(self, event: BridgeHealthEvent) -> None:
        if self._on_health_event is None:
            return
        try:
            maybe_awaitable = self._on_health_event(event)
            if inspect.isawaitable(maybe_awaitable):
                await cast(Awaitable[Any], maybe_awaitable)
        except Exception:
            # Health hooks are best-effort and should not destabilize bridge operation.
            return
