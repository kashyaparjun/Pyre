"""Phase 1 bridge benchmark harness.

Usage:
    uv run python scripts/bench_bridge.py --iterations 1000 --throughput-seconds 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from uuid import uuid4

from pyre_agents.bridge.codec import pack_payload
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType
from pyre_agents.bridge.server import BridgeServer
from pyre_agents.bridge.transport import BridgeTransport


@dataclass(frozen=True)
class LatencyResult:
    payload_label: str
    target_payload_bytes: int
    samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float


@dataclass(frozen=True)
class ThroughputResult:
    payload_label: str
    target_payload_bytes: int
    duration_seconds: float
    roundtrips: int
    messages_per_second: float


def percentile_ms(samples_ns: list[int], pct: float) -> float:
    if not samples_ns:
        return 0.0
    ordered = sorted(samples_ns)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index] / 1_000_000


def build_message_payload(target_bytes: int) -> bytes:
    if target_bytes < 32:
        target_bytes = 32
    blob_size = max(1, target_bytes - 32)
    return pack_payload({"blob": b"x" * blob_size})


async def handle_bench_message(envelope: BridgeEnvelope) -> BridgeEnvelope:
    if envelope.type is MessageType.PING:
        return BridgeEnvelope(correlation_id=envelope.correlation_id, type=MessageType.PONG)

    if envelope.type is MessageType.EXECUTE:
        return BridgeEnvelope(
            correlation_id=envelope.correlation_id,
            type=MessageType.RESULT,
            agent_id=envelope.agent_id,
            state=envelope.state,
            reply=envelope.message,
        )

    return BridgeEnvelope(
        correlation_id=envelope.correlation_id,
        type=MessageType.ERROR,
        agent_id="bench",
    )


async def run_latency(
    transport: BridgeTransport, payload_label: str, target_payload_bytes: int, iterations: int
) -> LatencyResult:
    payload = build_message_payload(target_payload_bytes)
    samples_ns: list[int] = []

    for _ in range(iterations):
        envelope = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="bench-agent",
            handler="handle_call",
            state=payload,
            message=payload,
        )
        start_ns = time.perf_counter_ns()
        await transport.send_envelope(envelope)
        _ = await transport.recv_envelope()
        elapsed_ns = time.perf_counter_ns() - start_ns
        samples_ns.append(elapsed_ns)

    mean_ms = statistics.fmean(samples_ns) / 1_000_000
    return LatencyResult(
        payload_label=payload_label,
        target_payload_bytes=target_payload_bytes,
        samples=iterations,
        p50_ms=percentile_ms(samples_ns, 50),
        p95_ms=percentile_ms(samples_ns, 95),
        p99_ms=percentile_ms(samples_ns, 99),
        mean_ms=mean_ms,
        min_ms=min(samples_ns) / 1_000_000,
        max_ms=max(samples_ns) / 1_000_000,
    )


async def run_throughput(
    transport: BridgeTransport,
    payload_label: str,
    target_payload_bytes: int,
    duration_seconds: float,
) -> ThroughputResult:
    payload = build_message_payload(target_payload_bytes)
    roundtrips = 0
    deadline = time.perf_counter() + duration_seconds
    while time.perf_counter() < deadline:
        envelope = BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.EXECUTE,
            agent_id="bench-agent",
            handler="handle_call",
            state=payload,
            message=payload,
        )
        await transport.send_envelope(envelope)
        _ = await transport.recv_envelope()
        roundtrips += 1

    messages_per_second = roundtrips / duration_seconds
    return ThroughputResult(
        payload_label=payload_label,
        target_payload_bytes=target_payload_bytes,
        duration_seconds=duration_seconds,
        roundtrips=roundtrips,
        messages_per_second=messages_per_second,
    )


async def run_benchmarks(iterations: int, throughput_seconds: float) -> dict[str, object]:
    payload_profiles: list[tuple[str, int]] = [
        ("small", 512),
        ("medium", 10_240),
        ("large", 1_048_576),
    ]
    server = BridgeServer(handle_bench_message)
    await server.start()
    transport = await BridgeTransport.connect_tcp("127.0.0.1", server.port)
    try:
        latency_results: list[LatencyResult] = []
        throughput_results: list[ThroughputResult] = []
        for label, size in payload_profiles:
            latency_results.append(await run_latency(transport, label, size, iterations))
            throughput_results.append(
                await run_throughput(transport, label, size, throughput_seconds)
            )
    finally:
        await transport.close()
        await server.close()

    return {
        "benchmark": "pyre-bridge-phase1",
        "latency": [asdict(item) for item in latency_results],
        "throughput": [asdict(item) for item in throughput_results],
        "acceptance_checks": {
            "p99_under_1ms_for_small_and_medium": all(
                item.p99_ms < 1.0
                for item in latency_results
                if item.payload_label in {"small", "medium"}
            )
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1 bridge performance benchmarks.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1000,
        help="Latency samples per payload profile.",
    )
    parser.add_argument(
        "--throughput-seconds",
        type=float,
        default=2.0,
        help="Benchmark duration per payload profile for throughput.",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default="",
        help="Optional file path for JSON output.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    if args.iterations <= 0:
        raise ValueError("--iterations must be > 0")
    if args.throughput_seconds <= 0:
        raise ValueError("--throughput-seconds must be > 0")

    results = await run_benchmarks(args.iterations, args.throughput_seconds)
    output = json.dumps(results, indent=2)
    print(output)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as file:
            file.write(output + "\n")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
