from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import resource
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from pyre_agents import (
    Agent,
    AgentContext,
    AgentInvocationError,
    AgentNotFoundError,
    AgentTerminatedError,
    CallResult,
    Pyre,
    RestartStrategy,
)


@dataclass(frozen=True)
class LatencyMetrics:
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float


@dataclass(frozen=True)
class ResourceMetrics:
    cpu_percent_avg: float
    cpu_percent_peak: float
    cpu_seconds_total: float
    wall_seconds_total: float
    rss_peak_bytes_estimate: int
    python_heap_peak_bytes: int


@dataclass(frozen=True)
class RecoveryMetrics:
    configured_failure_agents: int
    agents_restarted: int
    recovery_ratio: float


@dataclass(frozen=True)
class WorkloadMetrics:
    agents: int
    workers: int
    attempts: int
    successes: int
    failures: int
    duration_seconds: float
    throughput_ops_per_sec: float
    total_messages_outbound: int
    total_messages_inbound: int


class BenchmarkState(BaseModel):
    name: str
    peers: list[str] = Field(default_factory=list)
    can_fail: bool = False
    crash_probability: float = 0.0
    min_sleep_ms: int = 3
    max_sleep_ms: int = 10
    processed_calls: int = 0
    inbound_messages: int = 0
    outbound_messages: int = 0
    incarnation: int = 1


class SimulatedAIAgent(Agent[BenchmarkState]):
    _init_counts: ClassVar[dict[str, int]] = {}

    @classmethod
    def init_count(cls, name: str) -> int:
        return cls._init_counts.get(name, 0)

    async def init(self, **args: Any) -> BenchmarkState:
        name = str(args["name"])
        next_count = self._init_counts.get(name, 0) + 1
        self._init_counts[name] = next_count
        return BenchmarkState(
            name=name,
            peers=list(args.get("peers", [])),
            can_fail=bool(args.get("can_fail", False)),
            crash_probability=float(args.get("crash_probability", 0.0)),
            min_sleep_ms=int(args.get("min_sleep_ms", 3)),
            max_sleep_ms=int(args.get("max_sleep_ms", 10)),
            incarnation=next_count,
        )

    async def handle_call(
        self, state: BenchmarkState, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[BenchmarkState]:
        msg_type = str(msg.get("type", ""))

        if msg_type == "simulate_turn":
            if state.can_fail and random.random() < state.crash_probability:
                raise RuntimeError(f"Injected failure in {state.name}")

            sleep_ms = random.randint(state.min_sleep_ms, state.max_sleep_ms)
            await asyncio.sleep(sleep_ms / 1000)

            next_state = state.model_copy(deep=True)
            next_state.processed_calls += 1

            if state.peers:
                peer = random.choice(state.peers)
                await ctx.send_after(peer, "peer_event", {"from": state.name}, delay_ms=0)
                next_state.outbound_messages += 1

            return CallResult(reply={"ok": True, "agent": state.name}, new_state=next_state)

        if msg_type == "stats":
            return CallResult(reply=state.model_dump(), new_state=state)

        return CallResult(reply={"ignored": msg_type}, new_state=state)

    async def handle_cast(
        self, state: BenchmarkState, msg: dict[str, Any], ctx: AgentContext
    ) -> BenchmarkState:
        if str(msg.get("type", "")) == "peer_event":
            next_state = state.model_copy(deep=True)
            next_state.inbound_messages += 1
            return next_state
        return state


class ResourceMonitor:
    def __init__(self, sample_interval_s: float = 0.2) -> None:
        self._sample_interval_s = sample_interval_s
        self._cpu_samples: list[float] = []
        self._rss_peak_raw = 0
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._cpu_start = 0.0
        self._wall_start = 0.0
        self._heap_peak = 0

    @staticmethod
    def _rss_to_bytes(ru_maxrss: int) -> int:
        # Linux typically reports KB; Darwin reports bytes.
        if ru_maxrss < 10_000_000:
            return ru_maxrss * 1024
        return ru_maxrss

    async def _run(self) -> None:
        prev_cpu = time.process_time()
        prev_wall = time.perf_counter()
        while self._running:
            await asyncio.sleep(self._sample_interval_s)
            usage = resource.getrusage(resource.RUSAGE_SELF)
            self._rss_peak_raw = max(self._rss_peak_raw, usage.ru_maxrss)
            now_cpu = time.process_time()
            now_wall = time.perf_counter()
            wall_delta = now_wall - prev_wall
            if wall_delta > 0:
                cpu_pct = ((now_cpu - prev_cpu) / wall_delta) * 100.0
                self._cpu_samples.append(cpu_pct)
            prev_cpu = now_cpu
            prev_wall = now_wall

    async def start(self) -> None:
        self._cpu_start = time.process_time()
        self._wall_start = time.perf_counter()
        tracemalloc.start()
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> ResourceMetrics:
        self._running = False
        if self._task is not None:
            await self._task

        cpu_total = max(0.0, time.process_time() - self._cpu_start)
        wall_total = max(0.000001, time.perf_counter() - self._wall_start)
        _, self._heap_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return ResourceMetrics(
            cpu_percent_avg=statistics.fmean(self._cpu_samples) if self._cpu_samples else 0.0,
            cpu_percent_peak=max(self._cpu_samples) if self._cpu_samples else 0.0,
            cpu_seconds_total=cpu_total,
            wall_seconds_total=wall_total,
            rss_peak_bytes_estimate=self._rss_to_bytes(self._rss_peak_raw),
            python_heap_peak_bytes=self._heap_peak,
        )


def percentile_ms(samples_ns: list[int], pct: float) -> float:
    if not samples_ns:
        return 0.0
    ordered = sorted(samples_ns)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index] / 1_000_000


def make_peer_map(agent_names: list[str], peers_per_agent: int, seed: int) -> dict[str, list[str]]:
    rng = random.Random(seed)
    peer_map: dict[str, list[str]] = {}
    for name in agent_names:
        candidates = [candidate for candidate in agent_names if candidate != name]
        rng.shuffle(candidates)
        peer_map[name] = candidates[: min(peers_per_agent, len(candidates))]
    return peer_map


async def run_benchmark(
    *,
    agents: int,
    workers: int,
    attempts: int,
    failure_rate: float,
    crash_probability: float,
    min_sleep_ms: int,
    max_sleep_ms: int,
    peers_per_agent: int,
    seed: int,
) -> dict[str, Any]:
    random.seed(seed)
    agent_names = [f"agent-{idx:03d}" for idx in range(agents)]
    peer_map = make_peer_map(agent_names, peers_per_agent=peers_per_agent, seed=seed)

    failure_count = int(round(agents * failure_rate))
    failing_agents = (
        set(random.sample(agent_names, k=failure_count)) if failure_count > 0 else set()
    )

    system = await Pyre.start()
    await system.create_supervisor(
        name="benchmark-supervisor",
        strategy=RestartStrategy.ONE_FOR_ONE,
        max_restarts=max(10, attempts),
        within_ms=120_000,
    )

    refs: dict[str, Any] = {}
    for name in agent_names:
        refs[name] = await system.spawn(
            SimulatedAIAgent,
            name=name,
            args={
                "name": name,
                "peers": peer_map[name],
                "can_fail": name in failing_agents,
                "crash_probability": crash_probability,
                "min_sleep_ms": min_sleep_ms,
                "max_sleep_ms": max_sleep_ms,
            },
            max_restarts=max(10, attempts),
            within_ms=120_000,
            supervisor="benchmark-supervisor",
        )

    latencies_ns: list[int] = []
    latencies_lock = asyncio.Lock()
    success_count = 0
    failure_count_observed = 0
    counters_lock = asyncio.Lock()
    next_attempt = 0

    monitor = ResourceMonitor(sample_interval_s=0.2)
    start_ts = time.perf_counter()
    await monitor.start()

    async def worker_task() -> None:
        nonlocal next_attempt, success_count, failure_count_observed

        while True:
            async with counters_lock:
                if next_attempt >= attempts:
                    break
                attempt_id = next_attempt
                next_attempt += 1

            target = random.choice(agent_names)
            begin_ns = time.perf_counter_ns()
            try:
                await refs[target].call("simulate_turn", {"attempt": attempt_id})
                elapsed = time.perf_counter_ns() - begin_ns
                async with latencies_lock:
                    latencies_ns.append(elapsed)
                async with counters_lock:
                    success_count += 1
            except (AgentInvocationError, AgentTerminatedError, AgentNotFoundError):
                async with counters_lock:
                    failure_count_observed += 1

    tasks = [asyncio.create_task(worker_task()) for _ in range(workers)]
    await asyncio.gather(*tasks)

    duration_seconds = time.perf_counter() - start_ts
    resource_metrics = await monitor.stop()

    stats_replies = await asyncio.gather(
        *[refs[name].call("stats", {}) for name in agent_names],
        return_exceptions=True,
    )

    total_inbound = 0
    total_outbound = 0
    restarted_failure_agents = 0
    for name, reply in zip(agent_names, stats_replies, strict=True):
        if isinstance(reply, Exception):
            continue
        total_inbound += int(reply.get("inbound_messages", 0))
        total_outbound += int(reply.get("outbound_messages", 0))
        if name in failing_agents and int(reply.get("incarnation", 1)) > 1:
            restarted_failure_agents += 1

    agents_restarted = sum(
        max(0, SimulatedAIAgent.init_count(name) - 1) for name in failing_agents
    )

    await system.stop_system()

    latency = LatencyMetrics(
        p50_ms=percentile_ms(latencies_ns, 50),
        p90_ms=percentile_ms(latencies_ns, 90),
        p95_ms=percentile_ms(latencies_ns, 95),
        p99_ms=percentile_ms(latencies_ns, 99),
        mean_ms=(statistics.fmean(latencies_ns) / 1_000_000) if latencies_ns else 0.0,
        min_ms=(min(latencies_ns) / 1_000_000) if latencies_ns else 0.0,
        max_ms=(max(latencies_ns) / 1_000_000) if latencies_ns else 0.0,
    )

    recovery = RecoveryMetrics(
        configured_failure_agents=len(failing_agents),
        agents_restarted=agents_restarted,
        recovery_ratio=(
            restarted_failure_agents / len(failing_agents)
            if failing_agents
            else 1.0
        ),
    )

    workload = WorkloadMetrics(
        agents=agents,
        workers=workers,
        attempts=attempts,
        successes=success_count,
        failures=failure_count_observed,
        duration_seconds=duration_seconds,
        throughput_ops_per_sec=(success_count / duration_seconds) if duration_seconds > 0 else 0.0,
        total_messages_outbound=total_outbound,
        total_messages_inbound=total_inbound,
    )

    return {
        "benchmark": "pyre-self-benchmark",
        "platform": {
            "python": platform.python_version(),
            "system": platform.system(),
            "release": platform.release(),
        },
        "latency": asdict(latency),
        "resources": asdict(resource_metrics),
        "recovery": asdict(recovery),
        "workload": asdict(workload),
        "config": {
            "agents": agents,
            "workers": workers,
            "attempts": attempts,
            "failure_rate": failure_rate,
            "crash_probability": crash_probability,
            "min_sleep_ms": min_sleep_ms,
            "max_sleep_ms": max_sleep_ms,
            "peers_per_agent": peers_per_agent,
            "seed": seed,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Pyre with simulated async AI agents.")
    parser.add_argument("--agents", type=int, default=100)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--attempts", type=int, default=5000)
    parser.add_argument("--failure-rate", type=float, default=0.10)
    parser.add_argument("--crash-probability", type=float, default=0.02)
    parser.add_argument("--min-sleep-ms", type=int, default=3)
    parser.add_argument("--max-sleep-ms", type=int, default=10)
    parser.add_argument("--peers-per-agent", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-output", type=str, default="")
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()

    if args.agents <= 0:
        raise ValueError("--agents must be > 0")
    if args.workers <= 0:
        raise ValueError("--workers must be > 0")
    if args.attempts <= 0:
        raise ValueError("--attempts must be > 0")
    if not (0 <= args.failure_rate <= 1):
        raise ValueError("--failure-rate must be in [0,1]")
    if not (0 <= args.crash_probability <= 1):
        raise ValueError("--crash-probability must be in [0,1]")
    if args.min_sleep_ms < 0:
        raise ValueError("--min-sleep-ms must be >= 0")
    if args.max_sleep_ms < args.min_sleep_ms:
        raise ValueError("--max-sleep-ms must be >= --min-sleep-ms")
    if args.peers_per_agent <= 0:
        raise ValueError("--peers-per-agent must be > 0")

    report = await run_benchmark(
        agents=args.agents,
        workers=args.workers,
        attempts=args.attempts,
        failure_rate=args.failure_rate,
        crash_probability=args.crash_probability,
        min_sleep_ms=args.min_sleep_ms,
        max_sleep_ms=args.max_sleep_ms,
        peers_per_agent=args.peers_per_agent,
        seed=args.seed,
    )

    rendered = json.dumps(report, indent=2)
    print(rendered)

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as file:
            file.write(rendered + "\n")

    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
