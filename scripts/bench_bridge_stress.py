"""High-concurrency UDS bridge stress benchmark with pooled/multiplexed client.

Usage:
    uv run python scripts/bench_bridge_stress.py --in-flight-depths 1,8,32,128
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
from pyre_agents.bridge.transport import BridgeTransportPool


@dataclass(frozen=True)
class DepthResult:
    in_flight_depth: int
    roundtrips: int
    duration_seconds: float
    messages_per_second: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_in_flight_observed: int
    pool_backpressure_events: int
    server_backpressure_events: int


def percentile(samples_ms: list[float], pct: float) -> float:
    if not samples_ms:
        return 0.0
    ordered = sorted(samples_ms)
    idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


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
        agent_id="stress",
        error={"type": "unsupported", "message": "unsupported message", "stack": None},
    )


async def run_depth(
    pool: BridgeTransportPool,
    *,
    depth: int,
    duration_seconds: float,
    payload: bytes,
) -> tuple[int, list[float]]:
    deadline = time.perf_counter() + duration_seconds
    latencies_ms: list[float] = []
    roundtrips = 0
    counter_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal roundtrips
        while time.perf_counter() < deadline:
            cid = str(uuid4())
            envelope = BridgeEnvelope(
                correlation_id=cid,
                type=MessageType.EXECUTE,
                agent_id="stress-agent",
                handler="handle_call",
                state=payload,
                message=payload,
            )
            start_ns = time.perf_counter_ns()
            response = await pool.request(envelope, timeout_s=2.0)
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            if response.type is MessageType.RESULT:
                latencies_ms.append(elapsed_ms)
                async with counter_lock:
                    roundtrips += 1

    tasks = [asyncio.create_task(worker()) for _ in range(depth)]
    await asyncio.gather(*tasks)
    return roundtrips, latencies_ms


async def run_benchmark(
    *,
    in_flight_depths: list[int],
    duration_seconds: float,
    payload_bytes: int,
    pool_size: int,
    max_in_flight_per_conn: int,
    enable_backpressure: bool,
) -> dict[str, object]:
    payload = pack_payload({"blob": b"x" * max(1, payload_bytes - 32)})
    with tempfile.TemporaryDirectory(prefix="pyre-stress-") as tmp_dir:
        sock_path = str(Path(tmp_dir) / "bridge.sock")
        server = BridgeServer(
            handle_bench_message,
            max_in_flight=(pool_size * max_in_flight_per_conn) if enable_backpressure else 0,
            retry_after_ms=5,
        )
        await server.start_unix(sock_path)
        pool = await BridgeTransportPool.connect_unix(
            sock_path,
            pool_size=pool_size,
            max_in_flight_per_conn=max_in_flight_per_conn,
        )
        try:
            results: list[DepthResult] = []
            for depth in in_flight_depths:
                roundtrips, latencies_ms = await run_depth(
                    pool,
                    depth=depth,
                    duration_seconds=duration_seconds,
                    payload=payload,
                )
                pool_metrics = pool.metrics()
                server_metrics = server.metrics()
                results.append(
                    DepthResult(
                        in_flight_depth=depth,
                        roundtrips=roundtrips,
                        duration_seconds=duration_seconds,
                        messages_per_second=roundtrips / duration_seconds,
                        p50_ms=percentile(latencies_ms, 50),
                        p95_ms=percentile(latencies_ms, 95),
                        p99_ms=percentile(latencies_ms, 99),
                        max_in_flight_observed=pool_metrics.max_in_flight_observed,
                        pool_backpressure_events=pool_metrics.backpressure_events,
                        server_backpressure_events=server_metrics.backpressure_events,
                    )
                )

            return {
                "benchmark": "pyre-bridge-stress",
                "transport": "uds",
                "config": {
                    "in_flight_depths": in_flight_depths,
                    "duration_seconds": duration_seconds,
                    "payload_bytes": payload_bytes,
                    "pool_size": pool_size,
                    "max_in_flight_per_conn": max_in_flight_per_conn,
                    "enable_backpressure": enable_backpressure,
                },
                "results": [asdict(item) for item in results],
                "summary": {
                    "best_messages_per_second": max(item.messages_per_second for item in results)
                    if results
                    else 0.0,
                    "p99_at_max_depth_ms": results[-1].p99_ms if results else 0.0,
                    "avg_p99_ms": statistics.fmean(item.p99_ms for item in results)
                    if results
                    else 0.0,
                },
            }
        finally:
            await pool.close()
            await server.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UDS pooled/multiplexed bridge stress benchmark."
    )
    parser.add_argument("--in-flight-depths", type=str, default="1,8,32,128")
    parser.add_argument("--duration-seconds", type=float, default=1.0)
    parser.add_argument("--payload-bytes", type=int, default=512)
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--max-in-flight-per-conn", type=int, default=64)
    parser.add_argument("--enable-backpressure", action="store_true")
    parser.add_argument("--json-output", type=str, default="")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    depths = [int(item) for item in args.in_flight_depths.split(",") if item.strip()]
    results = await run_benchmark(
        in_flight_depths=depths,
        duration_seconds=args.duration_seconds,
        payload_bytes=args.payload_bytes,
        pool_size=args.pool_size,
        max_in_flight_per_conn=args.max_in_flight_per_conn,
        enable_backpressure=args.enable_backpressure,
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
