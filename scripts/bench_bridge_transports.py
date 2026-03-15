"""Bridge benchmark harness for TCP and UDS transports.

Usage:
    uv run python scripts/bench_bridge_transports.py --transport both
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class TransportResult:
    transport: str
    latency: list[dict[str, float | int | str]]
    throughput: list[dict[str, float | int | str]]


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
        samples_ns.append(time.perf_counter_ns() - start_ns)

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

    return ThroughputResult(
        payload_label=payload_label,
        target_payload_bytes=target_payload_bytes,
        duration_seconds=duration_seconds,
        roundtrips=roundtrips,
        messages_per_second=roundtrips / duration_seconds,
    )


async def _run_transport_benchmark(
    *,
    transport_mode: str,
    iterations: int,
    throughput_seconds: float,
) -> dict[str, object]:
    payload_profiles: list[tuple[str, int]] = [
        ("small", 512),
        ("medium", 10_240),
        ("large", 1_048_576),
    ]
    server = BridgeServer(handle_bench_message)
    tmp_path: Path | None = None

    if transport_mode == "tcp":
        await server.start()
        client = await BridgeTransport.connect_tcp("127.0.0.1", server.port)
    elif transport_mode == "uds":
        with tempfile.TemporaryDirectory(prefix="pyre-bench-") as tmp_dir:
            tmp_path = Path(tmp_dir) / "bridge.sock"
            await server.start_unix(str(tmp_path))
            client = await BridgeTransport.connect_unix(str(tmp_path))
            return await _collect_results(
                client=client,
                server=server,
                payload_profiles=payload_profiles,
                iterations=iterations,
                throughput_seconds=throughput_seconds,
                transport_mode=transport_mode,
            )
    else:
        raise ValueError(f"unsupported transport mode: {transport_mode}")

    return await _collect_results(
        client=client,
        server=server,
        payload_profiles=payload_profiles,
        iterations=iterations,
        throughput_seconds=throughput_seconds,
        transport_mode=transport_mode,
    )


async def _collect_results(
    *,
    client: BridgeTransport,
    server: BridgeServer,
    payload_profiles: list[tuple[str, int]],
    iterations: int,
    throughput_seconds: float,
    transport_mode: str,
) -> dict[str, object]:
    try:
        latency_results: list[LatencyResult] = []
        throughput_results: list[ThroughputResult] = []
        for label, size in payload_profiles:
            latency_results.append(await run_latency(client, label, size, iterations))
            throughput_results.append(
                await run_throughput(client, label, size, throughput_seconds)
            )
    finally:
        await client.close()
        await server.close()

    return {
        "transport": transport_mode,
        "latency": [asdict(item) for item in latency_results],
        "throughput": [asdict(item) for item in throughput_results],
    }


async def run_benchmarks(
    *,
    transport: str,
    iterations: int,
    throughput_seconds: float,
) -> dict[str, object]:
    transports = [transport] if transport in {"tcp", "uds"} else ["tcp", "uds"]
    results: list[dict[str, object]] = []
    for mode in transports:
        results.append(
            await _run_transport_benchmark(
                transport_mode=mode,
                iterations=iterations,
                throughput_seconds=throughput_seconds,
            )
        )

    return {
        "benchmark": "pyre-bridge-multi-transport",
        "transport_results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bridge benchmarks on TCP and/or UDS.")
    parser.add_argument(
        "--transport",
        choices=["tcp", "uds", "both"],
        default="both",
        help="Transport mode to benchmark.",
    )
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--throughput-seconds", type=float, default=2.0)
    parser.add_argument("--json-output", type=str, default="")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    if args.iterations <= 0:
        raise ValueError("--iterations must be > 0")
    if args.throughput_seconds <= 0:
        raise ValueError("--throughput-seconds must be > 0")

    results = await run_benchmarks(
        transport=args.transport,
        iterations=args.iterations,
        throughput_seconds=args.throughput_seconds,
    )
    rendered = json.dumps(results, indent=2)
    print(rendered)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as file:
            file.write(rendered + "\n")

    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
