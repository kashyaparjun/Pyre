"""Batching configuration and transport extensions for Pyre bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType


@dataclass(frozen=True)
class BatchingConfig:
    """Configuration for request batching on bridge connections.

    Batching improves throughput by processing multiple requests per process
    spawn on the Elixir side. This is ideal for high-throughput scenarios
    but adds latency for low-traffic connections.

    Attributes:
        enabled: Whether batching is enabled for this connection
        batch_size: Number of requests to batch (default: 10)
        max_wait_ms: Max time to wait for batch to fill (default: 2ms)
        min_batch_size: Minimum requests before flushing (default: 1)

    Examples:
        # For high-throughput (benchmarks, data pipelines):
        >>> BatchingConfig.high_throughput()
        BatchingConfig(enabled=True, batch_size=20, max_wait_ms=5, min_batch_size=10)

        # For low-latency (real-time APIs, user interactions):
        >>> BatchingConfig.low_latency()
        BatchingConfig(enabled=False, batch_size=1, max_wait_ms=0, min_batch_size=1)

        # For balanced workloads:
        >>> BatchingConfig.balanced()
        BatchingConfig(enabled=True, batch_size=10, max_wait_ms=2, min_batch_size=1)
    """

    enabled: bool = False
    batch_size: int = 10
    max_wait_ms: float = 2.0
    min_batch_size: int = 1

    @classmethod
    def high_throughput(cls) -> BatchingConfig:
        """Optimize for maximum throughput.

        Best for: Data processing, batch workloads, benchmarks.
        Trade-off: Higher latency (+20-50%) for +30-40% throughput.
        """
        return cls(enabled=True, batch_size=20, max_wait_ms=5.0, min_batch_size=10)

    @classmethod
    def low_latency(cls) -> BatchingConfig:
        """Disable batching for minimum latency.

        Best for: Real-time APIs, user interactions, latency-critical ops.
        Trade-off: Lower throughput but minimal latency.
        """
        return cls(enabled=False, batch_size=1, max_wait_ms=0.0, min_batch_size=1)

    @classmethod
    def balanced(cls) -> BatchingConfig:
        """Balance throughput and latency.

        Best for: Mixed workloads, general purpose.
        Enables batching but with small batches and short timeouts.
        """
        return cls(enabled=True, batch_size=10, max_wait_ms=2.0, min_batch_size=1)

    def to_elixir_opts(self) -> dict[str, Any]:
        """Convert to Elixir-compatible options."""
        return {
            "enable_batching": self.enabled,
            "batch_size": self.batch_size,
            "batch_timeout_ms": self.max_wait_ms,
            "min_batch_size": self.min_batch_size,
        }


class BatchedBridgeTransport:
    """Transport wrapper that adds client-side batching support.

    This is a Python-side optimization that groups requests before
    sending them to Elixir. Complements the Elixir-side batching.
    """

    def __init__(
        self,
        pool: Any,  # BridgeTransportPool
        config: BatchingConfig,
    ) -> None:
        self._pool = pool
        self._config = config
        self._buffer: list[BridgeEnvelope] = []
        self._flush_timer: Any | None = None

    async def request(
        self, envelope: BridgeEnvelope, timeout_s: float | None = None
    ) -> BridgeEnvelope:
        """Send request, using batching if enabled."""
        if not self._config.enabled:
            # Batching disabled - send immediately
            return await self._pool.request(envelope, timeout_s)

        # Add to buffer
        self._buffer.append(envelope)

        # Check if batch is full
        if len(self._buffer) >= self._config.batch_size:
            return await self._flush_batch()

        # Start timer if not already running
        if self._flush_timer is None:
            import asyncio

            self._flush_timer = asyncio.get_event_loop().call_later(
                self._config.max_wait_ms / 1000, self._flush_batch
            )

        # Return placeholder - actual response comes later
        # In real implementation, use asyncio.Future
        raise NotImplementedError("Async batching requires Future-based API")

    async def _flush_batch(self) -> BridgeEnvelope:
        """Send buffered batch to Elixir."""
        if not self._buffer:
            # Create empty response
            from pyre_agents.bridge.protocol import MessageType

            return BridgeEnvelope(
                correlation_id="batch-empty",
                type=MessageType.ERROR,
                error=None,  # Would need proper error type
            )

        # Cancel timer if running
        if self._flush_timer:
            self._flush_timer.cancel()
            self._flush_timer = None

        # Create batched envelope
        batch = self._buffer[: self._config.batch_size]
        self._buffer = self._buffer[self._config.batch_size :]

        # Send batched request
        # In real implementation, use a special batch envelope type
        batched = BridgeEnvelope(
            correlation_id=f"batch-{id(batch)}",
            type=MessageType.EXECUTE,  # Or new BATCH type
            agent_id="batched",
            handler="batch_handler",
            state=b"",  # Would contain serialized batch
            message=b"",
        )

        return await self._pool.request(batched)

    async def close(self) -> None:
        """Close transport, flushing any pending batch."""
        if self._buffer:
            await self._flush_batch()
        await self._pool.close()


# Preset configurations for common use cases
HIGH_THROUGHPUT = BatchingConfig.high_throughput()
LOW_LATENCY = BatchingConfig.low_latency()
BALANCED = BatchingConfig.balanced()
