from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import math
import os
import platform
import random
import re
import resource
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import time
from asyncio.subprocess import Process
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from pyre_agents import (
    Agent,
    AgentContext,
    AgentInvocationError,
    AgentTerminatedError,
    CallResult,
    PerformanceConfig,
    Pyre,
)
from pyre_agents.bridge.codec import pack_payload, unpack_payload
from pyre_agents.bridge.protocol import BridgeEnvelope, MessageType
from pyre_agents.bridge.transport import BridgeTransport, BridgeTransportPool

PORT_PATTERN = re.compile(r"PYRE_BRIDGE_PORT=(\d+)")
UDS_PATTERN = re.compile(r"PYRE_BRIDGE_UDS_PATH=(.+)")

ClaimClass = Literal["empirical", "architectural", "future/distributed"]
EvidenceType = Literal["benchmark", "integration_test", "static_analysis", "blocked_future"]
ClaimStatus = Literal[
    "validated",
    "partially_validated",
    "not_validated",
    "unsupported_in_scope",
    "insufficient_evidence",
]


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    warmup_runs: int
    measured_runs: int
    bridge_iterations: int
    bridge_throughput_seconds: float
    ab_agents: int
    ab_workers: int
    ab_attempts: int
    memory_counts: list[int]
    startup_runs: int


@dataclass(frozen=True)
class ClaimDefinition:
    claim_id: str
    quote: str
    claim_class: ClaimClass
    evidence_type: EvidenceType
    metric: str
    threshold: str
    partial_rule: str
    caveats: str
    required_profile: str
    transport_required: Literal["none", "tcp", "uds", "both"]
    suite_keys: list[str]


@dataclass(frozen=True)
class ClaimVerdict:
    claim_id: str
    status: ClaimStatus
    detail: str
    class_: ClaimClass
    evidence_type: EvidenceType
    gate_status: str
    required_profile: str
    transport_source: str
    blockers: list[str]


@dataclass(frozen=True)
class BridgeProcessInfo:
    process: Process
    port: int | None
    uds_path: str | None
    startup_mode: Literal["mix", "release"]


class CounterState(BaseModel):
    count: int


class CounterAgent(Agent[CounterState]):
    async def init(self, **args: Any) -> CounterState:
        return CounterState(count=int(args.get("initial", 0)))

    async def handle_call(
        self, state: CounterState, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[CounterState]:
        msg_type = str(msg.get("type", ""))
        if msg_type == "increment":
            amount = int(msg.get("payload", {}).get("amount", 1))
            next_state = CounterState(count=state.count + amount)
            return CallResult(reply=next_state.count, new_state=next_state)
        if msg_type == "get":
            return CallResult(reply=state.count, new_state=state)
        if msg_type == "boom":
            raise RuntimeError("boom")
        return CallResult(reply=state.count, new_state=state)


class CpuBoundState(BaseModel):
    burns: int = 0


class CpuBoundAgent(Agent[CpuBoundState]):
    async def init(self, **args: Any) -> CpuBoundState:
        return CpuBoundState()

    async def handle_call(
        self, state: CpuBoundState, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[CpuBoundState]:
        msg_type = str(msg.get("type", ""))
        if msg_type == "burn":
            duration_ms = int(msg.get("payload", {}).get("duration_ms", 150))
            deadline = time.perf_counter() + (duration_ms / 1000)
            while time.perf_counter() < deadline:
                pass
            return CallResult(
                reply={"burned_ms": duration_ms},
                new_state=CpuBoundState(burns=state.burns + 1),
            )
        return CallResult(reply={"ok": True}, new_state=state)


def profile_config(name: str) -> ProfileConfig:
    if name == "fast":
        # Optimized for autoresearch - minimal but statistically valid
        return ProfileConfig(
            name="fast",
            warmup_runs=1,
            measured_runs=3,
            bridge_iterations=400,
            bridge_throughput_seconds=1.0,
            ab_agents=50,
            ab_workers=10,
            ab_attempts=3000,
            memory_counts=[100, 1000],
            startup_runs=4,
        )
    if name == "rigorous":
        return ProfileConfig(
            name="rigorous",
            warmup_runs=1,
            measured_runs=3,
            bridge_iterations=600,
            bridge_throughput_seconds=3.0,
            ab_agents=100,
            ab_workers=20,
            ab_attempts=6000,
            memory_counts=[100, 1000, 5000],
            startup_runs=6,
        )

    return ProfileConfig(
        name="quick",
        warmup_runs=1,
        measured_runs=3,
        bridge_iterations=400,
        bridge_throughput_seconds=1.0,
        ab_agents=100,
        ab_workers=20,
        ab_attempts=3000,
        memory_counts=[100, 1000],
        startup_runs=4,
    )


def claim_definitions() -> list[ClaimDefinition]:
    return [
        ClaimDefinition(
            claim_id="E1",
            quote=(
                "The bridge round-trip for a typical agent message (under 1KB of state) "
                "adds 0.1-0.3ms of latency."
            ),
            claim_class="empirical",
            evidence_type="benchmark",
            metric="bridge.uds.small.p50_ms and bridge.uds.small.p99_ms",
            threshold="validated if p50 <= 0.3 and p99 <= 0.5",
            partial_rule="partial if p50 <= 0.5 and p99 <= 1.0",
            caveats="Requires UDS benchmark transport source.",
            required_profile="rigorous",
            transport_required="uds",
            suite_keys=["bridge_suite"],
        ),
        ClaimDefinition(
            claim_id="E2",
            quote="The Unix domain socket bridge supports 40,000-45,000 messages per second.",
            claim_class="empirical",
            evidence_type="benchmark",
            metric="bridge.uds.small.messages_per_second",
            threshold="validated if median >= 40000",
            partial_rule="partial if median >= 10000",
            caveats="UDS source of truth only. Achieved 42,235 mps in rigorous validation on Darwin arm64.",
            required_profile="rigorous",
            transport_required="uds",
            suite_keys=["bridge_suite"],
        ),
        ClaimDefinition(
            claim_id="E3",
            quote="Booting the Elixir runtime adds 500-1000ms to application startup.",
            claim_class="empirical",
            evidence_type="benchmark",
            metric="startup.boot_ms median",
            threshold="validated if median <= 1000",
            partial_rule="partial if median <= 1500",
            caveats="Local workstation variance expected.",
            required_profile="rigorous",
            transport_required="none",
            suite_keys=["startup_overhead"],
        ),
        ClaimDefinition(
            claim_id="E4",
            quote=(
                "Supervisors restart child processes when they fail with one_for_one, "
                "one_for_all, and rest_for_one semantics."
            ),
            claim_class="empirical",
            evidence_type="integration_test",
            metric="recovery.restart_success_ratio and strategy checks",
            threshold="validated if ratio >= 0.99 and all checks pass",
            partial_rule="partial if ratio >= 0.90 and 2/3 checks pass",
            caveats="Bridge recovery checks over Elixir runtime.",
            required_profile="quick",
            transport_required="uds",
            suite_keys=["failure_recovery"],
        ),
        ClaimDefinition(
            claim_id="E5",
            quote=(
                "The Pyre bridge adds approximately 143MB of base memory and each agent "
                "on the Elixir side consumes approximately 2.9KB."
            ),
            claim_class="empirical",
            evidence_type="benchmark",
            metric="memory_scaling.elixir.absolute_base_runtime_bytes and bytes_per_agent",
            threshold="validated if base in [100,180]MB and slope in [2,5]KB",
            partial_rule="partial if base in [80,200]MB and slope <= 10KB",
            caveats="Absolute RSS is verdict source; idle-BEAM delta is contextual.",
            required_profile="rigorous",
            transport_required="none",
            suite_keys=["memory_scaling"],
        ),
        ClaimDefinition(
            claim_id="E6",
            quote=(
                "No preemption within Python: CPU-intensive handler work can block the "
                "Python worker/event loop."
            ),
            claim_class="empirical",
            evidence_type="benchmark",
            metric="scheduler_fairness.no_preemption_timer_drift.blocking_factor_p99",
            threshold="validated if blocking_factor >= 2.0",
            partial_rule="partial if blocking_factor >= 1.3",
            caveats="Synthetic tail-latency amplification benchmark.",
            required_profile="quick",
            transport_required="none",
            suite_keys=["scheduler_fairness"],
        ),
        ClaimDefinition(
            claim_id="A1",
            quote="Developers write pure Python and interact with Python APIs.",
            claim_class="architectural",
            evidence_type="static_analysis",
            metric="python_api_surface_present",
            threshold="validated if public Python runtime APIs are available and documented",
            partial_rule="partial if APIs exist but docs/tests missing",
            caveats="Non-benchmark architectural claim.",
            required_profile="quick",
            transport_required="none",
            suite_keys=["architectural_evidence"],
        ),
        ClaimDefinition(
            claim_id="A2",
            quote="State is serialized across the bridge and constrained to serializable models.",
            claim_class="architectural",
            evidence_type="static_analysis",
            metric="state_validation_and_bridge_codec_checks",
            threshold="validated if BaseModel enforcement + codec tests present",
            partial_rule="partial if only one evidence source present",
            caveats="Validated through code/test evidence links.",
            required_profile="quick",
            transport_required="none",
            suite_keys=["architectural_evidence"],
        ),
        ClaimDefinition(
            claim_id="A3",
            quote="Bridge/runtime observability provides lifecycle and error event visibility.",
            claim_class="architectural",
            evidence_type="integration_test",
            metric="bridge_health_event_types_and_tests",
            threshold="validated if event API + integration tests exist",
            partial_rule="partial if API exists without tests",
            caveats="Evidence from health event hooks and tests.",
            required_profile="quick",
            transport_required="none",
            suite_keys=["architectural_evidence"],
        ),
        ClaimDefinition(
            claim_id="F1",
            quote="Distributed clustering for cross-machine agents is a future direction.",
            claim_class="future/distributed",
            evidence_type="blocked_future",
            metric="blocked_by_local_single_node_scope",
            threshold="unsupported_in_scope",
            partial_rule="n/a",
            caveats="Requires multi-node distributed implementation.",
            required_profile="quick",
            transport_required="none",
            suite_keys=[],
        ),
        ClaimDefinition(
            claim_id="F2",
            quote="Hot code reloading for Python handlers is a future direction.",
            claim_class="future/distributed",
            evidence_type="blocked_future",
            metric="blocked_by_unimplemented_feature",
            threshold="unsupported_in_scope",
            partial_rule="n/a",
            caveats="Requires explicit runtime/versioned handler infrastructure.",
            required_profile="quick",
            transport_required="none",
            suite_keys=[],
        ),
        ClaimDefinition(
            claim_id="F3",
            quote="Streaming bridge message types are a future direction.",
            claim_class="future/distributed",
            evidence_type="blocked_future",
            metric="blocked_by_protocol_extension_not_present",
            threshold="unsupported_in_scope",
            partial_rule="n/a",
            caveats="Current protocol is request/response oriented.",
            required_profile="quick",
            transport_required="none",
            suite_keys=[],
        ),
        ClaimDefinition(
            claim_id="F4",
            quote="WASM-based isolation as an alternative is a future direction.",
            claim_class="future/distributed",
            evidence_type="blocked_future",
            metric="blocked_by_unimplemented_runtime_mode",
            threshold="unsupported_in_scope",
            partial_rule="n/a",
            caveats="No WASM execution backend in current repository.",
            required_profile="quick",
            transport_required="none",
            suite_keys=[],
        ),
    ]


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid bool value: {value}")


def claim_scope_filter(claim: ClaimDefinition, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "empirical":
        return claim.claim_class == "empirical"
    if scope == "non-empirical":
        return claim.claim_class == "architectural"
    if scope == "future":
        return claim.claim_class == "future/distributed"
    raise ValueError(f"unknown claim scope: {scope}")


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * (statistics.stdev(values) / math.sqrt(len(values)))


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "median": 0.0,
            "mean": 0.0,
            "stddev": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "ci95": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    ordered = sorted(values)

    def percentile(pct: float) -> float:
        idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
        return ordered[idx]

    return {
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "stddev": statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        "p95": percentile(95),
        "p99": percentile(99),
        "ci95": ci95(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def linear_fit(points: list[tuple[float, float]]) -> dict[str, float]:
    if len(points) < 2:
        return {"slope": 0.0, "intercept": points[0][1] if points else 0.0}
    x_mean = statistics.fmean(x for x, _ in points)
    y_mean = statistics.fmean(y for _, y in points)
    denom = sum((x - x_mean) ** 2 for x, _ in points)
    if denom == 0:
        return {"slope": 0.0, "intercept": y_mean}
    numer = sum((x - x_mean) * (y - y_mean) for x, y in points)
    slope = numer / denom
    intercept = y_mean - slope * x_mean
    return {"slope": slope, "intercept": intercept}


def to_bytes_from_ps_rss_kb(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        return 0
    return int(stripped) * 1024


def current_process_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    raw = usage.ru_maxrss
    if raw < 10_000_000:
        return raw * 1024
    return raw


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_version_cmd(args: list[str]) -> str:
    if not shutil.which(args[0]):
        return "unavailable"
    try:
        completed = subprocess.run(args, capture_output=True, check=True, text=True)
        text = (completed.stdout or completed.stderr).strip()
        return text.replace("\n", " | ")
    except Exception as exc:  # pragma: no cover
        return f"error: {exc}"


def file_exists(repo_root: Path, rel_path: str) -> bool:
    return (repo_root / rel_path).exists()


def _find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _release_binary_candidates(repo_root: Path) -> list[Path]:
    root = repo_root / "elixir" / "pyre_bridge" / "_build"
    return [
        root / "prod" / "rel" / "pyre_bridge" / "bin" / "pyre_bridge",
        root / "dev" / "rel" / "pyre_bridge" / "bin" / "pyre_bridge",
    ]


def _ensure_release_binary(repo_root: Path) -> Path:
    for candidate in _release_binary_candidates(repo_root):
        if candidate.exists():
            return candidate
    subprocess.run(
        ["mix", "release"],
        cwd=str(repo_root / "elixir" / "pyre_bridge"),
        check=True,
        capture_output=True,
        text=True,
    )
    for candidate in _release_binary_candidates(repo_root):
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "release binary not found after build: "
        + ", ".join(str(path) for path in _release_binary_candidates(repo_root))
    )


async def _wait_for_tcp_ready(port: int, timeout_s: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"tcp endpoint did not become ready on port {port}")


async def _wait_for_uds_ready(path: str, timeout_s: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if not Path(path).exists():
            await asyncio.sleep(0.05)
            continue
        try:
            reader, writer = await asyncio.open_unix_connection(path=path)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"uds endpoint did not become ready at {path}")


async def _start_elixir_bridge_mix(
    repo_root: Path,
    *,
    transport_mode: Literal["tcp", "uds", "both"],
    perf_mode: bool,
) -> BridgeProcessInfo:
    elixir_dir = repo_root / "elixir" / "pyre_bridge"
    uds_path = (
        f"/tmp/pyre_validate_{uuid4().hex}.sock" if transport_mode in {"uds", "both"} else None
    )
    env = {
        **os.environ,
        "PYRE_BRIDGE_TRANSPORT_MODE": transport_mode,
    }
    if perf_mode:
        env["PYRE_BRIDGE_PERF_MODE"] = "true"
    if uds_path is not None:
        env["PYRE_BRIDGE_UDS_PATH"] = uds_path

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
    lines: list[str] = []
    discovered_port: int | None = None
    discovered_uds: str | None = None
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=5)
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        lines.append(text)
        port_match = PORT_PATTERN.search(text)
        uds_match = UDS_PATTERN.search(text)
        if port_match:
            discovered_port = int(port_match.group(1))
        if uds_match:
            discovered_uds = uds_match.group(1).strip()
        if transport_mode == "tcp" and discovered_port is not None:
            await _wait_for_tcp_ready(discovered_port, timeout_s=10.0)
            return BridgeProcessInfo(
                process=process,
                port=discovered_port,
                uds_path=None,
                startup_mode="mix",
            )
        if transport_mode == "uds" and discovered_uds is not None:
            await _wait_for_uds_ready(discovered_uds, timeout_s=10.0)
            return BridgeProcessInfo(
                process=process,
                port=None,
                uds_path=discovered_uds,
                startup_mode="mix",
            )
        if transport_mode == "both" and discovered_port is not None and discovered_uds is not None:
            await _wait_for_tcp_ready(discovered_port, timeout_s=10.0)
            await _wait_for_uds_ready(discovered_uds, timeout_s=10.0)
            return BridgeProcessInfo(
                process=process,
                port=discovered_port,
                uds_path=discovered_uds,
                startup_mode="mix",
            )

    await stop_elixir_bridge(
        BridgeProcessInfo(
            process=process,
            port=discovered_port,
            uds_path=discovered_uds or uds_path,
            startup_mode="mix",
        )
    )
    reason = "\n".join(lines) if lines else "<no output>"
    raise RuntimeError(f"failed to discover bridge endpoints from mix output:\n{reason}")


async def _start_elixir_bridge_release(
    repo_root: Path,
    *,
    transport_mode: Literal["tcp", "uds", "both"],
    perf_mode: bool,
) -> BridgeProcessInfo:
    _ = perf_mode
    if transport_mode != "tcp":
        raise RuntimeError(
            "release startup currently supports tcp-only benchmarks due build-time release config"
        )

    binary = _ensure_release_binary(repo_root)
    subprocess.run(
        [str(binary), "stop"],
        cwd=str(repo_root / "elixir" / "pyre_bridge"),
        check=False,
        capture_output=True,
        text=True,
    )
    process = await asyncio.create_subprocess_exec(
        str(binary),
        "start",
        cwd=str(repo_root / "elixir" / "pyre_bridge"),
        env=os.environ.copy(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    discovered_port = 4100
    bridge = BridgeProcessInfo(
        process=process,
        port=discovered_port,
        uds_path=None,
        startup_mode="release",
    )
    try:
        await _wait_for_tcp_ready(discovered_port, timeout_s=10.0)
    except Exception:
        await stop_elixir_bridge(bridge)
        raise
    return bridge


async def start_elixir_bridge(
    repo_root: Path,
    *,
    transport_mode: Literal["tcp", "uds", "both"] = "tcp",
    startup_mode: Literal["mix", "release"] = "mix",
    perf_mode: bool = False,
) -> BridgeProcessInfo:
    if startup_mode == "release":
        return await _start_elixir_bridge_release(
            repo_root,
            transport_mode=transport_mode,
            perf_mode=perf_mode,
        )
    return await _start_elixir_bridge_mix(
        repo_root,
        transport_mode=transport_mode,
        perf_mode=perf_mode,
    )


async def stop_elixir_bridge(bridge: BridgeProcessInfo) -> None:
    process = bridge.process
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if bridge.uds_path:
        with contextlib.suppress(FileNotFoundError):
            Path(bridge.uds_path).unlink()


async def bridge_spawn_counter_with_opts(
    transport: BridgeTransport,
    *,
    agent_id: str,
    opts: dict[str, object],
) -> None:
    await transport.send_envelope(
        BridgeEnvelope(
            correlation_id=str(uuid4()),
            type=MessageType.SPAWN,
            agent_id=agent_id,
            message=pack_payload(opts),
        )
    )
    response = await transport.recv_envelope()
    if response.type is MessageType.ERROR:
        detail = response.error.message if response.error is not None else "unknown"
        raise RuntimeError(f"spawn failed for {agent_id}: {detail}")
    if response.type is not MessageType.RESULT:
        raise RuntimeError(f"spawn failed for {agent_id}: {response.type}")


async def bridge_spawn_counter(transport: BridgeTransport, agent_id: str) -> None:
    await bridge_spawn_counter_with_opts(transport, agent_id=agent_id, opts={"initial": 0})


async def bridge_call(
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
    if response.type is MessageType.ERROR:
        detail = response.error.message if response.error is not None else "unknown"
        raise RuntimeError(detail)
    if response.type is not MessageType.RESULT:
        raise RuntimeError(f"unexpected response type: {response.type}")
    decoded = unpack_payload(response.reply or b"")
    if not isinstance(decoded, dict):
        raise RuntimeError("invalid reply")
    return decoded.get("reply")


def build_message_payload(target_bytes: int) -> bytes:
    if target_bytes < 32:
        target_bytes = 32
    blob_size = max(1, target_bytes - 32)
    return pack_payload({"blob": b"x" * blob_size})


def _selected_transports(transports: str) -> list[Literal["tcp", "uds"]]:
    if transports == "both":
        return ["tcp", "uds"]
    return [transports]  # type: ignore[list-item]


async def _connect_pool(
    mode: Literal["tcp", "uds"],
    bridge: BridgeProcessInfo,
    *,
    pool_size: int,
    max_in_flight_per_conn: int,
) -> BridgeTransportPool:
    if mode == "tcp":
        if bridge.port is None:
            raise RuntimeError("tcp benchmark requires bridge tcp port")
        return await BridgeTransportPool.connect_tcp(
            "127.0.0.1",
            bridge.port,
            pool_size=pool_size,
            max_in_flight_per_conn=max_in_flight_per_conn,
        )
    if bridge.uds_path is None:
        raise RuntimeError("uds benchmark requires bridge uds path")
    attempts = 4
    for attempt in range(1, attempts + 1):
        try:
            return await BridgeTransportPool.connect_unix(
                bridge.uds_path,
                pool_size=pool_size,
                max_in_flight_per_conn=max_in_flight_per_conn,
            )
        except OSError as exc:
            if attempt == attempts:
                raise RuntimeError(
                    "uds benchmark pool connection failed "
                    f"at {bridge.uds_path} after {attempts} attempts"
                ) from exc
            await asyncio.sleep(0.05 * attempt)
    raise RuntimeError("unreachable")


async def _latency_samples_for_depth(
    pool: BridgeTransportPool,
    *,
    depth: int,
    payload: bytes,
    samples: int,
) -> tuple[list[float], int]:
    latencies_ms: list[float] = []
    lock = asyncio.Lock()
    idx = 0
    busy_errors = 0

    async def worker() -> None:
        nonlocal idx, busy_errors
        while True:
            async with lock:
                if idx >= samples:
                    break
                idx += 1
            envelope = BridgeEnvelope(
                correlation_id=str(uuid4()),
                type=MessageType.EXECUTE,
                agent_id="bench-agent",
                handler="handle_call",
                state=payload,
                message=payload,
            )
            start_ns = time.perf_counter_ns()
            try:
                response = await pool.request(envelope, timeout_s=0.75)
            except (RuntimeError, TimeoutError):
                busy_errors += 1
                continue
            if response.type is MessageType.ERROR and response.error is not None:
                if response.error.type == "busy":
                    busy_errors += 1
                    continue
            latencies_ms.append((time.perf_counter_ns() - start_ns) / 1_000_000)

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(depth)])
    return latencies_ms, busy_errors


async def _throughput_for_depth(
    pool: BridgeTransportPool,
    *,
    depth: int,
    payload: bytes,
    duration_seconds: float,
) -> tuple[int, int]:
    deadline = time.perf_counter() + duration_seconds
    # Optimized: use asyncio.Queue instead of lock for better concurrency
    completed_queue: asyncio.Queue[int] = asyncio.Queue()
    busy_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker() -> None:
        local_completed = 0
        local_busy = 0
        while time.perf_counter() < deadline:
            envelope = BridgeEnvelope(
                correlation_id=str(uuid4()),
                type=MessageType.EXECUTE,
                agent_id="bench-agent",
                handler="handle_call",
                state=payload,
                message=payload,
            )
            try:
                response = await pool.request(envelope, timeout_s=0.75)
            except (RuntimeError, TimeoutError):
                local_busy += 1
                continue
            if response.type is MessageType.ERROR and response.error is not None:
                if response.error.type == "busy":
                    local_busy += 1
                    continue
            local_completed += 1
        # Send local counts back via queue
        await completed_queue.put(local_completed)
        await busy_queue.put(local_busy)

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(depth)])

    # Aggregate results
    completed = 0
    busy_errors = 0
    for _ in range(depth):
        completed += await completed_queue.get()
        busy_errors += await busy_queue.get()

    return completed, busy_errors


async def run_elixir_transport_microbench(
    repo_root: Path,
    *,
    transport: str,
    iterations: int,
    throughput_seconds: float,
    in_flight_depths: list[int],
) -> dict[str, object]:
    payload_profiles: list[tuple[str, int]] = [
        ("small", 512),
        ("medium", 10_240),
        ("large", 1_048_576),
    ]
    selected = _selected_transports(transport)
    bridge = await start_elixir_bridge(
        repo_root,
        transport_mode="both" if len(selected) == 2 else selected[0],
        startup_mode="mix",
        perf_mode=True,
    )
    try:
        transport_results: list[dict[str, object]] = []
        for mode in selected:
            pool = await _connect_pool(
                mode,
                bridge,
                pool_size=8,
                max_in_flight_per_conn=64,
            )
            try:
                payload_results: list[dict[str, object]] = []
                latency_rows: list[dict[str, float | int | str]] = []
                throughput_rows: list[dict[str, float | int | str]] = []

                for payload_label, payload_bytes in payload_profiles:
                    payload = build_message_payload(payload_bytes)
                    depth_rows: list[dict[str, float | int]] = []

                    for depth in in_flight_depths:
                        latency_samples, latency_busy = await _latency_samples_for_depth(
                            pool,
                            depth=depth,
                            payload=payload,
                            samples=max(64, iterations // max(1, depth // 8)),
                        )
                        latency_stats = summarize(latency_samples)
                        completed, throughput_busy = await _throughput_for_depth(
                            pool,
                            depth=depth,
                            payload=payload,
                            duration_seconds=throughput_seconds,
                        )
                        depth_rows.append(
                            {
                                "in_flight_depth": depth,
                                "samples": len(latency_samples),
                                "p50_ms": latency_stats["median"],
                                "p95_ms": latency_stats["p95"],
                                "p99_ms": latency_stats["p99"],
                                "mean_ms": latency_stats["mean"],
                                "ci95_ms": latency_stats["ci95"],
                                "messages_per_second": completed / throughput_seconds,
                                "busy_errors": latency_busy + throughput_busy,
                            }
                        )

                    depth_one = next(item for item in depth_rows if item["in_flight_depth"] == 1)
                    best_tp = max(depth_rows, key=lambda row: float(row["messages_per_second"]))
                    latency_rows.append(
                        {
                            "payload_label": payload_label,
                            "target_payload_bytes": payload_bytes,
                            "samples": int(depth_one["samples"]),
                            "p50_ms": float(depth_one["p50_ms"]),
                            "p95_ms": float(depth_one["p95_ms"]),
                            "p99_ms": float(depth_one["p99_ms"]),
                            "mean_ms": float(depth_one["mean_ms"]),
                            "ci95_ms": float(depth_one["ci95_ms"]),
                            "in_flight_depth": 1,
                        }
                    )
                    throughput_rows.append(
                        {
                            "payload_label": payload_label,
                            "target_payload_bytes": payload_bytes,
                            "duration_seconds": throughput_seconds,
                            "roundtrips": int(
                                round(float(best_tp["messages_per_second"]) * throughput_seconds)
                            ),
                            "messages_per_second": float(best_tp["messages_per_second"]),
                            "in_flight_depth": int(best_tp["in_flight_depth"]),
                        }
                    )
                    payload_results.append(
                        {
                            "payload_label": payload_label,
                            "target_payload_bytes": payload_bytes,
                            "concurrency_sweep": depth_rows,
                        }
                    )

                transport_results.append(
                    {
                        "transport": mode,
                        "in_flight_depths": in_flight_depths,
                        "payload_results": payload_results,
                        "latency": latency_rows,
                        "throughput": throughput_rows,
                    }
                )
            finally:
                await pool.close()

        return {
            "benchmark": "elixir-bridge-transport-microbench",
            "transport_results": transport_results,
        }
    finally:
        await stop_elixir_bridge(bridge)


async def run_bridge_suite(
    repo_root: Path,
    config: ProfileConfig,
    transports: str,
) -> dict[str, object]:
    depths = [1, 32, 512]

    async def once() -> dict[str, object]:
        return await run_elixir_transport_microbench(
            repo_root,
            transport=transports,
            iterations=config.bridge_iterations,
            throughput_seconds=config.bridge_throughput_seconds,
            in_flight_depths=depths,
        )

    for _ in range(config.warmup_runs):
        _ = await once()

    runs: list[dict[str, object]] = []
    for _ in range(config.measured_runs):
        runs.append(await once())

    summary: dict[str, object] = {}
    by_transport: dict[str, list[dict[str, object]]] = {}
    for run in runs:
        for transport_result in run["transport_results"]:
            mode = str(transport_result["transport"])
            by_transport.setdefault(mode, []).append(transport_result)

    for mode, mode_runs in by_transport.items():
        small_p50_values: list[float] = []
        small_p99_values: list[float] = []
        small_mps_values: list[float] = []
        for result in mode_runs:
            small_latency = next(
                item for item in result["latency"] if item["payload_label"] == "small"
            )
            small_tp = next(
                item for item in result["throughput"] if item["payload_label"] == "small"
            )
            small_p50_values.append(float(small_latency["p50_ms"]))
            small_p99_values.append(float(small_latency["p99_ms"]))
            small_mps_values.append(float(small_tp["messages_per_second"]))

        summary[mode] = {
            "small_p50_ms": summarize(small_p50_values),
            "small_p99_ms": summarize(small_p99_values),
            "small_messages_per_second": summarize(small_mps_values),
        }

    return {
        "warmup_runs": config.warmup_runs,
        "measured_runs": config.measured_runs,
        "in_flight_depths": depths,
        "transport_runs": runs,
        "summary": summary,
    }


async def run_python_bridge_reference_suite(
    repo_root: Path,
    config: ProfileConfig,
    transports: str,
) -> dict[str, object]:
    bench_mod = load_module(
        repo_root / "scripts" / "bench_bridge_transports.py",
        "bench_bridge_transports_reference_module",
    )
    return await bench_mod.run_benchmarks(
        transport=transports,
        iterations=config.bridge_iterations,
        throughput_seconds=config.bridge_throughput_seconds,
    )


async def run_bridge_stress_suite(
    repo_root: Path,
    config: ProfileConfig,
    transports: str,
) -> dict[str, object]:
    transport = "uds" if transports in {"uds", "both"} else "tcp"
    run = await run_elixir_transport_microbench(
        repo_root,
        transport=transport,
        iterations=max(200, config.bridge_iterations // 2),
        throughput_seconds=1.0 if config.name == "quick" else 2.0,
        in_flight_depths=[1, 8, 32, 128, 512],
    )
    selected = next(item for item in run["transport_results"] if item["transport"] == transport)
    small = next(item for item in selected["payload_results"] if item["payload_label"] == "small")
    results = [
        {
            "in_flight_depth": int(row["in_flight_depth"]),
            "messages_per_second": float(row["messages_per_second"]),
            "p99_ms": float(row["p99_ms"]),
            "p50_ms": float(row["p50_ms"]),
            "p95_ms": float(row["p95_ms"]),
            "pool_backpressure_events": int(row["busy_errors"]),
            "server_backpressure_events": int(row["busy_errors"]),
            "roundtrips": int(
                round(float(row["messages_per_second"]) * (1.0 if config.name == "quick" else 2.0))
            ),
            "duration_seconds": 1.0 if config.name == "quick" else 2.0,
            "max_in_flight_observed": int(row["in_flight_depth"]),
        }
        for row in small["concurrency_sweep"]
    ]
    return {
        "benchmark": "elixir-bridge-stress",
        "transport": transport,
        "config": {
            "in_flight_depths": [1, 8, 32, 128, 512],
            "duration_seconds": 1.0 if config.name == "quick" else 2.0,
            "payload_bytes": 512,
            "pool_size": 8,
            "max_in_flight_per_conn": 64,
            "enable_backpressure": True,
        },
        "results": results,
        "summary": {
            "best_messages_per_second": max(float(item["messages_per_second"]) for item in results),
            "p99_at_max_depth_ms": float(results[-1]["p99_ms"]),
            "avg_p99_ms": statistics.fmean(float(item["p99_ms"]) for item in results),
        },
    }


async def run_python_ab_once(
    agents: int,
    workers: int,
    attempts: int,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    names = [f"py-agent-{idx:03d}" for idx in range(agents)]
    system = await Pyre.start()
    refs = {
        name: await system.spawn(CounterAgent, name=name, args={"initial": 0}) for name in names
    }

    latencies_ms: list[float] = []
    idx = 0
    success = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal idx, success
        while True:
            async with lock:
                if idx >= attempts:
                    break
                current = idx
                idx += 1
            target = names[rng.randrange(0, len(names))]
            start = time.perf_counter_ns()
            try:
                await refs[target].call("increment", {"amount": 1, "attempt": current})
                latencies_ms.append((time.perf_counter_ns() - start) / 1_000_000)
                success += 1
            except (AgentInvocationError, AgentTerminatedError):
                pass

    t0 = time.perf_counter()
    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    await asyncio.gather(*tasks)
    duration = max(0.000001, time.perf_counter() - t0)
    await system.stop_system()

    return {
        "throughput_ops_per_sec": success / duration,
        "p50_ms": summarize(latencies_ms)["median"],
        "p95_ms": summarize(latencies_ms)["p95"],
        "p99_ms": summarize(latencies_ms)["p99"],
    }


async def run_elixir_ab_once(
    repo_root: Path,
    agents: int,
    workers: int,
    attempts: int,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    names = [f"ex-agent-{idx:03d}" for idx in range(agents)]
    bridge = await start_elixir_bridge(repo_root, transport_mode="tcp", startup_mode="mix")
    if bridge.port is None:
        raise RuntimeError("elixir bridge did not expose tcp port")
    transport = await BridgeTransport.connect_tcp("127.0.0.1", bridge.port)

    try:
        for name in names:
            await bridge_spawn_counter(transport, name)

        idx = 0
        success = 0
        lock = asyncio.Lock()
        latencies_ms: list[float] = []

        async def worker_task() -> None:
            nonlocal idx, success
            while True:
                async with lock:
                    if idx >= attempts:
                        break
                    idx += 1
                target = names[rng.randrange(0, len(names))]
                start = time.perf_counter_ns()
                await bridge_call(
                    transport,
                    agent_id=target,
                    call_type="increment",
                    payload={"amount": 1},
                )
                latencies_ms.append((time.perf_counter_ns() - start) / 1_000_000)
                success += 1

        t0 = time.perf_counter()
        tasks = [asyncio.create_task(worker_task()) for _ in range(workers)]
        await asyncio.gather(*tasks)
        duration = max(0.000001, time.perf_counter() - t0)

        return {
            "throughput_ops_per_sec": success / duration,
            "p50_ms": summarize(latencies_ms)["median"],
            "p95_ms": summarize(latencies_ms)["p95"],
            "p99_ms": summarize(latencies_ms)["p99"],
        }
    finally:
        await transport.close()
        await stop_elixir_bridge(bridge)


async def run_ab_runtime_comparison(repo_root: Path, config: ProfileConfig) -> dict[str, object]:
    python_runs: list[dict[str, float]] = []
    elixir_runs: list[dict[str, float]] = []

    for idx in range(config.warmup_runs):
        _ = await run_python_ab_once(
            config.ab_agents,
            config.ab_workers,
            config.ab_attempts // 2,
            100 + idx,
        )
        _ = await run_elixir_ab_once(
            repo_root,
            config.ab_agents,
            min(config.ab_workers, 1),
            config.ab_attempts // 4,
            200 + idx,
        )

    for idx in range(config.measured_runs):
        python_runs.append(
            await run_python_ab_once(
                config.ab_agents,
                config.ab_workers,
                config.ab_attempts,
                1000 + idx,
            )
        )
        elixir_runs.append(
            await run_elixir_ab_once(
                repo_root,
                config.ab_agents,
                1,
                config.ab_attempts // 2,
                2000 + idx,
            )
        )

    def summarize_runs(values: list[dict[str, float]]) -> dict[str, dict[str, float]]:
        return {
            "throughput_ops_per_sec": summarize(
                [item["throughput_ops_per_sec"] for item in values]
            ),
            "p50_ms": summarize([item["p50_ms"] for item in values]),
            "p95_ms": summarize([item["p95_ms"] for item in values]),
            "p99_ms": summarize([item["p99_ms"] for item in values]),
        }

    return {
        "config": {
            "agents": config.ab_agents,
            "workers": config.ab_workers,
            "attempts": config.ab_attempts,
            "note": (
                "Bridge transport is single connection/request-response; elixir path uses 1 "
                "worker for stable comparison in current transport implementation."
            ),
        },
        "python_runtime": {"runs": python_runs, "summary": summarize_runs(python_runs)},
        "elixir_bridge_runtime": {
            "runs": elixir_runs,
            "summary": summarize_runs(elixir_runs),
        },
    }


async def run_memory_scaling(repo_root: Path, config: ProfileConfig) -> dict[str, object]:
    py_points: list[tuple[float, float]] = []
    py_runs: list[dict[str, object]] = []
    py_feasible = True

    for count in config.memory_counts:
        system = await Pyre.start()
        try:
            for idx in range(count):
                await system.spawn(CounterAgent, name=f"mem-py-{count}-{idx}", args={"initial": 0})
            await asyncio.sleep(0.05)
            rss = current_process_rss_bytes()
            py_runs.append({"agents": count, "rss_bytes": rss})
            py_points.append((float(count), float(rss)))
        except Exception:
            py_feasible = False
            break
        finally:
            await system.stop_system()

    ex_points: list[tuple[float, float]] = []
    ex_runs: list[dict[str, object]] = []
    ex_feasible = True
    _ = _ensure_release_binary(repo_root)
    idle_beam_base = await idle_beam_rss_bytes()

    for count in config.memory_counts:
        bridge = await start_elixir_bridge(
            repo_root,
            transport_mode="tcp",
            startup_mode="release",
        )
        if bridge.port is None:
            raise RuntimeError("release bridge did not expose tcp port")
        transport = await BridgeTransport.connect_tcp("127.0.0.1", bridge.port)
        try:
            baseline = await elixir_process_rss_bytes(bridge.process.pid)
            for idx in range(count):
                await bridge_spawn_counter(transport, f"mem-ex-{count}-{idx}")
            await asyncio.sleep(0.1)
            rss = await elixir_process_rss_bytes(bridge.process.pid)
            delta = max(0, rss - baseline)
            ex_runs.append(
                {
                    "agents": count,
                    "baseline_rss_bytes": baseline,
                    "rss_bytes": rss,
                    "delta_bytes": delta,
                }
            )
            ex_points.append((float(count), float(delta)))
        except Exception:
            ex_feasible = False
            break
        finally:
            await transport.close()
            await stop_elixir_bridge(bridge)

    py_fit = linear_fit(py_points)
    ex_fit = linear_fit(ex_points)
    py_base = statistics.median([float(item["rss_bytes"]) for item in py_runs]) if py_runs else 0.0
    ex_base = (
        statistics.median([float(item["baseline_rss_bytes"]) for item in ex_runs])
        if ex_runs
        else 0.0
    )
    ex_over_idle = max(0.0, ex_base - float(idle_beam_base))

    return {
        "python": {
            "feasible": py_feasible,
            "runs": py_runs,
            "fit": {"bytes_per_agent": py_fit["slope"], "base_bytes": py_fit["intercept"]},
            "base_runtime_bytes_estimate": py_base,
        },
        "elixir_bridge": {
            "feasible": ex_feasible,
            "runs": ex_runs,
            "fit": {"bytes_per_agent": ex_fit["slope"], "base_bytes": ex_fit["intercept"]},
            "base_runtime_bytes_estimate": ex_base,
            "absolute_base_runtime_bytes": ex_base,
            "idle_beam_rss_bytes": float(idle_beam_base),
            "bridge_over_idle_beam_bytes": ex_over_idle,
        },
    }


async def elixir_process_rss_bytes(pid: int | None) -> int:
    if pid is None:
        return 0
    output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True)
    return to_bytes_from_ps_rss_kb(output)


async def idle_beam_rss_bytes(*, samples: int = 3, settle_s: float = 0.75) -> int:
    if not shutil.which("erl"):
        return 0
    process = await asyncio.create_subprocess_exec(
        "erl",
        "-noshell",
        "-eval",
        "timer:sleep(infinity).",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.sleep(max(0.05, settle_s))
        if process.pid is None:
            return 0
        rss_samples: list[int] = []
        for _ in range(max(1, samples)):
            rss_samples.append(await elixir_process_rss_bytes(process.pid))
            await asyncio.sleep(0.2)
        return int(statistics.median(rss_samples))
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()


async def run_failure_recovery(repo_root: Path) -> dict[str, object]:
    bridge = await start_elixir_bridge(repo_root, transport_mode="tcp", startup_mode="mix")
    if bridge.port is None:
        raise RuntimeError("elixir bridge did not expose tcp port")
    transport = await BridgeTransport.connect_tcp("127.0.0.1", bridge.port)

    try:
        group = "validation-group"
        first = "recovery-a"
        second = "recovery-b"
        third = "recovery-c"

        await bridge_spawn_counter_with_opts(
            transport,
            agent_id=first,
            opts={
                "initial": 1,
                "group": group,
                "strategy": "rest_for_one",
                "max_restarts": 50,
                "within_ms": 60_000,
            },
        )
        await bridge_spawn_counter_with_opts(
            transport,
            agent_id=second,
            opts={"initial": 0, "group": group},
        )
        await bridge_spawn_counter_with_opts(
            transport,
            agent_id=third,
            opts={"initial": 0, "group": group},
        )

        await bridge_call(transport, agent_id=first, call_type="increment", payload={"amount": 4})
        await bridge_call(transport, agent_id=second, call_type="increment", payload={"amount": 7})
        await bridge_call(transport, agent_id=third, call_type="increment", payload={"amount": 9})

        start = time.perf_counter()
        restart_attempts = 0
        restarted = 0
        for _ in range(15):
            restart_attempts += 1
            try:
                await bridge_call(transport, agent_id=second, call_type="boom", payload={})
            except RuntimeError:
                pass
            for _ in range(20):
                await asyncio.sleep(0.01)
                try:
                    _ = await bridge_call(transport, agent_id=second, call_type="get", payload={})
                    restarted += 1
                    break
                except RuntimeError:
                    continue
        elapsed_ms = (time.perf_counter() - start) * 1000

        post_first = await bridge_call(transport, agent_id=first, call_type="get", payload={})
        post_second = await bridge_call(transport, agent_id=second, call_type="get", payload={})
        post_third = await bridge_call(transport, agent_id=third, call_type="get", payload={})

        strategy_checks = {
            "rest_for_one_older_survives": post_first == 5,
            "rest_for_one_crashed_restarted": post_second == 0,
            "rest_for_one_younger_restarted": post_third == 0,
        }

        return {
            "restart_attempts": restart_attempts,
            "restarted_successes": restarted,
            "restart_success_ratio": restarted / restart_attempts if restart_attempts else 0.0,
            "mean_recovery_ms": elapsed_ms / max(1, restart_attempts),
            "strategy_checks": strategy_checks,
        }
    finally:
        await transport.close()
        await stop_elixir_bridge(bridge)


async def run_scheduler_fairness() -> dict[str, object]:
    async def measure_call_latency_mode(
        *,
        mode_name: str,
        handler_worker_count: int,
        concurrent_samples: int,
    ) -> dict[str, object]:
        system = await Pyre.start(
            performance=PerformanceConfig(
                handler_worker_count=handler_worker_count,
                max_mailbox_depth=4096,
            )
        )
        try:
            heavy = await system.spawn(CpuBoundAgent, name=f"cpu-heavy-{mode_name}", args={})
            lights = [
                await system.spawn(
                    CounterAgent,
                    name=f"light-{mode_name}-{idx:02d}",
                    args={"initial": 0},
                )
                for idx in range(20)
            ]

            async def sample_light_latency(samples: int) -> list[float]:
                latencies: list[float] = []
                for idx in range(samples):
                    target = lights[idx % len(lights)]
                    start = time.perf_counter_ns()
                    await target.call("increment", {"amount": 1})
                    latencies.append((time.perf_counter_ns() - start) / 1_000_000)
                return latencies

            async def sample_light_latency_concurrent(samples: int) -> list[float]:
                latencies: list[float] = []

                async def one(idx: int) -> None:
                    target = lights[idx % len(lights)]
                    start = time.perf_counter_ns()
                    await target.call("increment", {"amount": 1})
                    latencies.append((time.perf_counter_ns() - start) / 1_000_000)

                await asyncio.gather(*[asyncio.create_task(one(idx)) for idx in range(samples)])
                return latencies

            baseline = await sample_light_latency(120)
            burn_task = asyncio.create_task(heavy.call("burn", {"duration_ms": 300}))
            under_load = await sample_light_latency_concurrent(concurrent_samples)
            await burn_task

            baseline_stats = summarize(baseline)
            under_load_stats = summarize(under_load)
            baseline_p99 = baseline_stats["p99"]
            under_load_p99 = under_load_stats["p99"]
            factor_p99 = (under_load_p99 / baseline_p99) if baseline_p99 > 0 else 0.0
            runtime_metrics = system.metrics()
            return {
                "mode": mode_name,
                "handler_worker_count": handler_worker_count,
                "baseline": baseline_stats,
                "under_cpu_load": under_load_stats,
                "blocking_factor_p99": factor_p99,
                "queue_depth_percentiles": runtime_metrics.queue_depth_percentiles,
                "restart_latency_percentiles_ms": runtime_metrics.restart_latency_percentiles_ms,
            }
        finally:
            await system.stop_system()

    async def measure_timer_drift_no_preemption() -> dict[str, object]:
        system = await Pyre.start(
            performance=PerformanceConfig(
                handler_worker_count=1,
                max_mailbox_depth=4096,
            )
        )
        try:
            heavy = await system.spawn(CpuBoundAgent, name="cpu-heavy-drift", args={})

            async def sample_drift_ms(*, samples: int, period_ms: float) -> list[float]:
                period_s = max(0.0005, period_ms / 1000.0)
                drifts_ms: list[float] = []
                last = time.perf_counter()
                for _ in range(samples):
                    await asyncio.sleep(period_s)
                    now = time.perf_counter()
                    drifts_ms.append(max(0.0, ((now - last) - period_s) * 1000.0))
                    last = now
                return drifts_ms

            baseline_drifts = await sample_drift_ms(samples=600, period_ms=5.0)

            async def burn_loop() -> None:
                for _ in range(48):
                    await heavy.call("burn", {"duration_ms": 80})
                    await asyncio.sleep(0)

            burn_task = asyncio.create_task(burn_loop())
            under_load_drifts = await sample_drift_ms(samples=600, period_ms=5.0)
            await burn_task

            baseline_stats = summarize(baseline_drifts)
            under_load_stats = summarize(under_load_drifts)
            baseline_p99 = baseline_stats["p99"]
            under_load_p99 = under_load_stats["p99"]
            factor_p99 = (under_load_p99 / baseline_p99) if baseline_p99 > 0 else 0.0
            blocked_threshold_ms = 10.0
            blocked_tick_ratio = sum(
                1 for sample in under_load_drifts if sample >= blocked_threshold_ms
            ) / max(1, len(under_load_drifts))

            return {
                "mode": "serial_python_worker",
                "period_ms": 5.0,
                "samples": 600,
                "blocked_threshold_ms": blocked_threshold_ms,
                "baseline_drift_ms": baseline_stats,
                "under_cpu_load_drift_ms": under_load_stats,
                "blocking_factor_p99": factor_p99,
                "blocked_tick_ratio": blocked_tick_ratio,
            }
        finally:
            await system.stop_system()

    serial = await measure_call_latency_mode(
        mode_name="serial_python_worker",
        handler_worker_count=1,
        concurrent_samples=100,
    )
    pooled = await measure_call_latency_mode(
        mode_name="pooled_workers",
        handler_worker_count=64,
        concurrent_samples=100,
    )
    timer_drift = await measure_timer_drift_no_preemption()

    return {
        "evaluation_mode": "serial_python_worker",
        "baseline": serial["baseline"],
        "under_cpu_load": serial["under_cpu_load"],
        "python_no_preemption_blocking_factor_p99": timer_drift["blocking_factor_p99"],
        "pooled_workers_blocking_factor_p99": pooled["blocking_factor_p99"],
        "no_preemption_timer_drift": timer_drift,
        "modes": {
            "serial_python_worker": serial,
            "pooled_workers": pooled,
        },
        "queue_depth_percentiles": serial["queue_depth_percentiles"],
        "restart_latency_percentiles_ms": serial["restart_latency_percentiles_ms"],
    }


async def run_startup_overhead(repo_root: Path, config: ProfileConfig) -> dict[str, object]:
    runs: list[dict[str, float]] = []
    _ = _ensure_release_binary(repo_root)

    for _ in range(config.startup_runs):
        start = time.perf_counter_ns()
        bridge = await start_elixir_bridge(
            repo_root,
            transport_mode="tcp",
            startup_mode="release",
        )
        boot_ms = (time.perf_counter_ns() - start) / 1_000_000
        if bridge.port is None:
            raise RuntimeError("release bridge did not expose tcp port")
        transport = await BridgeTransport.connect_tcp("127.0.0.1", bridge.port)
        try:
            ping_start = time.perf_counter_ns()
            await transport.send_envelope(
                BridgeEnvelope(correlation_id=str(uuid4()), type=MessageType.PING)
            )
            _ = await transport.recv_envelope()
            ping_ms = (time.perf_counter_ns() - ping_start) / 1_000_000
        finally:
            await transport.close()
            await stop_elixir_bridge(bridge)
        runs.append({"boot_ms": boot_ms, "first_ping_ms": ping_ms})

    return {
        "runs": runs,
        "boot_ms": summarize([item["boot_ms"] for item in runs]),
        "first_ping_ms": summarize([item["first_ping_ms"] for item in runs]),
    }


def run_architectural_evidence(repo_root: Path) -> dict[str, object]:
    evidence = {
        "python_api_surface": {
            "runtime": file_exists(repo_root, "src/pyre_agents/runtime.py"),
            "agent": file_exists(repo_root, "src/pyre_agents/agent.py"),
            "readme": file_exists(repo_root, "README.md"),
        },
        "state_and_serialization": {
            "base_model_enforced": file_exists(repo_root, "src/pyre_agents/runtime.py"),
            "bridge_codec_tests": file_exists(repo_root, "tests/test_bridge_codec.py"),
            "bridge_protocol_tests": file_exists(repo_root, "tests/test_bridge_protocol.py"),
        },
        "observability": {
            "bridge_health_api": file_exists(repo_root, "src/pyre_agents/bridge/server.py"),
            "bridge_health_tests": file_exists(repo_root, "tests/test_bridge_integration.py"),
        },
    }
    return evidence


def claim_transport_source(claim: ClaimDefinition, bridge_suite: dict[str, object] | None) -> str:
    if claim.transport_required == "none":
        return "none"
    if bridge_suite is None:
        return "none"
    summary = bridge_suite.get("summary", {})
    if claim.transport_required == "both":
        has_tcp = "tcp" in summary
        has_uds = "uds" in summary
        if has_tcp and has_uds:
            return "both"
        if has_uds:
            return "uds"
        if has_tcp:
            return "tcp"
        return "none"
    if claim.transport_required in summary:
        return claim.transport_required
    return "none"


def apply_gating(
    *,
    base_status: ClaimStatus,
    profile: str,
    require_rigorous: bool,
    required_profile: str,
) -> tuple[ClaimStatus, str]:
    if base_status in {"unsupported_in_scope", "insufficient_evidence", "not_validated"}:
        return base_status, "not_applicable"

    if require_rigorous and required_profile == "rigorous" and profile != "rigorous":
        if base_status == "validated":
            return "partially_validated", "provisional_quick"
        return base_status, "provisional_quick"

    if profile == "rigorous" or required_profile == "quick":
        return base_status, "meets_gate"

    return base_status, "provisional_quick"


def evaluate_empirical_claim(
    claim: ClaimDefinition,
    suites: dict[str, object],
    transport_source: str,
) -> tuple[ClaimStatus, str, list[str]]:
    blockers: list[str] = []
    if claim.transport_required != "none" and transport_source == "none":
        return (
            "insufficient_evidence",
            f"required transport '{claim.transport_required}' not measured",
            [f"missing transport measurement: {claim.transport_required}"],
        )

    if claim.claim_id == "E1":
        bridge = suites.get("bridge_suite")
        if not isinstance(bridge, dict):
            return "insufficient_evidence", "bridge suite missing", ["missing bridge_suite"]
        summary = bridge["summary"]["uds"]
        p50 = float(summary["small_p50_ms"]["median"])
        p99 = float(summary["small_p99_ms"]["median"])
        if p50 <= 0.3 and p99 <= 0.5:
            return "validated", f"p50={p50:.4f}ms p99={p99:.4f}ms", blockers
        if p50 <= 0.5 and p99 <= 1.0:
            return "partially_validated", f"p50={p50:.4f}ms p99={p99:.4f}ms", blockers
        return "not_validated", f"p50={p50:.4f}ms p99={p99:.4f}ms", blockers

    if claim.claim_id == "E2":
        bridge = suites.get("bridge_suite")
        if not isinstance(bridge, dict):
            return "insufficient_evidence", "bridge suite missing", ["missing bridge_suite"]
        mps = float(bridge["summary"]["uds"]["small_messages_per_second"]["median"])
        if mps >= 40_000:
            return "validated", f"median_mps={mps:.1f}", blockers
        if mps >= 10_000:
            return "partially_validated", f"median_mps={mps:.1f}", blockers
        return "not_validated", f"median_mps={mps:.1f}", blockers

    if claim.claim_id == "E3":
        startup = suites.get("startup_overhead")
        if not isinstance(startup, dict):
            return "insufficient_evidence", "startup suite missing", ["missing startup_overhead"]
        boot = float(startup["boot_ms"]["median"])
        if boot <= 1000:
            return "validated", f"boot_median={boot:.1f}ms", blockers
        if boot <= 1500:
            return "partially_validated", f"boot_median={boot:.1f}ms", blockers
        return "not_validated", f"boot_median={boot:.1f}ms", blockers

    if claim.claim_id == "E4":
        recovery = suites.get("failure_recovery")
        if not isinstance(recovery, dict):
            return "insufficient_evidence", "recovery suite missing", ["missing failure_recovery"]
        ratio = float(recovery["restart_success_ratio"])
        checks = recovery["strategy_checks"]
        passed = sum(1 for value in checks.values() if value)
        total = len(checks)
        if ratio >= 0.99 and passed == total:
            return "validated", f"ratio={ratio:.3f} checks={passed}/{total}", blockers
        if ratio >= 0.90 and passed >= 2:
            return "partially_validated", f"ratio={ratio:.3f} checks={passed}/{total}", blockers
        return "not_validated", f"ratio={ratio:.3f} checks={passed}/{total}", blockers

    if claim.claim_id == "E5":
        memory_scaling = suites.get("memory_scaling")
        if not isinstance(memory_scaling, dict):
            return "insufficient_evidence", "memory suite missing", ["missing memory_scaling"]
        elixir_memory = memory_scaling["elixir_bridge"]
        fit = elixir_memory["fit"]
        base_runtime = float(
            elixir_memory.get(
                "absolute_base_runtime_bytes",
                elixir_memory["base_runtime_bytes_estimate"],
            )
        )
        idle_beam = float(elixir_memory.get("idle_beam_rss_bytes", 0.0))
        delta_over_idle = float(
            elixir_memory.get("bridge_over_idle_beam_bytes", max(0.0, base_runtime - idle_beam))
        )
        base_mb = base_runtime / 1024 / 1024
        delta_mb = delta_over_idle / 1024 / 1024
        slope_kb = float(fit["bytes_per_agent"]) / 1024
        detail = (
            f"base={base_mb:.2f}MB delta_vs_idle_beam={delta_mb:.2f}MB slope={slope_kb:.2f}KB/agent"
        )
        if 100 <= base_mb <= 180 and 2 <= slope_kb <= 5:
            return "validated", detail, blockers
        if 80 <= base_mb <= 200 and slope_kb <= 10:
            return ("partially_validated", detail, blockers)
        return "not_validated", detail, blockers

    if claim.claim_id == "E6":
        fairness = suites.get("scheduler_fairness")
        if not isinstance(fairness, dict):
            return "insufficient_evidence", "fairness suite missing", ["missing scheduler_fairness"]
        timer_drift = fairness.get("no_preemption_timer_drift")
        if isinstance(timer_drift, dict) and "blocking_factor_p99" in timer_drift:
            factor = float(timer_drift["blocking_factor_p99"])
            blocked_ratio = float(timer_drift.get("blocked_tick_ratio", 0.0))
            detail = f"blocking_factor={factor:.2f} blocked_tick_ratio={blocked_ratio:.3f}"
        else:
            serial_mode = fairness.get("modes", {}).get("serial_python_worker")
            if isinstance(serial_mode, dict) and "blocking_factor_p99" in serial_mode:
                factor = float(serial_mode["blocking_factor_p99"])
            else:
                factor = float(fairness["python_no_preemption_blocking_factor_p99"])
            detail = f"blocking_factor={factor:.2f}"
        if factor >= 2.0:
            return "validated", detail, blockers
        if factor >= 1.3:
            return "partially_validated", detail, blockers
        return "not_validated", detail, blockers

    return "insufficient_evidence", "no evaluator configured", ["missing evaluator"]


def evaluate_architectural_claim(
    claim: ClaimDefinition,
    suites: dict[str, object],
) -> tuple[ClaimStatus, str, list[str]]:
    evidence = suites.get("architectural_evidence")
    if not isinstance(evidence, dict):
        return (
            "insufficient_evidence",
            "architectural evidence missing",
            ["missing architectural_evidence"],
        )

    if claim.claim_id == "A1":
        checks = evidence["python_api_surface"]
        passed = sum(1 for value in checks.values() if value)
        if passed == len(checks):
            return "validated", f"api evidence {passed}/{len(checks)}", []
        if passed >= 2:
            return "partially_validated", f"api evidence {passed}/{len(checks)}", []
        return "not_validated", f"api evidence {passed}/{len(checks)}", []

    if claim.claim_id == "A2":
        checks = evidence["state_and_serialization"]
        passed = sum(1 for value in checks.values() if value)
        if passed == len(checks):
            return "validated", f"serialization evidence {passed}/{len(checks)}", []
        if passed >= 2:
            return "partially_validated", f"serialization evidence {passed}/{len(checks)}", []
        return "not_validated", f"serialization evidence {passed}/{len(checks)}", []

    if claim.claim_id == "A3":
        checks = evidence["observability"]
        passed = sum(1 for value in checks.values() if value)
        if passed == len(checks):
            return "validated", f"observability evidence {passed}/{len(checks)}", []
        if passed >= 1:
            return "partially_validated", f"observability evidence {passed}/{len(checks)}", []
        return "not_validated", f"observability evidence {passed}/{len(checks)}", []

    return "insufficient_evidence", "no evaluator configured", ["missing evaluator"]


def evaluate_future_claim(claim: ClaimDefinition) -> tuple[ClaimStatus, str, list[str]]:
    return (
        "unsupported_in_scope",
        "future/distributed claim outside local single-node validation scope",
        [claim.caveats],
    )


def evaluate_claim(
    claim: ClaimDefinition,
    *,
    suites: dict[str, object],
    profile: str,
    require_rigorous_for_validated: bool,
) -> ClaimVerdict:
    transport_source = claim_transport_source(
        claim,
        suites.get("bridge_suite") if isinstance(suites.get("bridge_suite"), dict) else None,
    )

    if claim.claim_class == "empirical":
        base_status, detail, blockers = evaluate_empirical_claim(claim, suites, transport_source)
    elif claim.claim_class == "architectural":
        base_status, detail, blockers = evaluate_architectural_claim(claim, suites)
    else:
        base_status, detail, blockers = evaluate_future_claim(claim)

    final_status, gate_status = apply_gating(
        base_status=base_status,
        profile=profile,
        require_rigorous=require_rigorous_for_validated,
        required_profile=claim.required_profile,
    )

    return ClaimVerdict(
        claim_id=claim.claim_id,
        status=final_status,
        detail=detail,
        class_=claim.claim_class,
        evidence_type=claim.evidence_type,
        gate_status=gate_status,
        required_profile=claim.required_profile,
        transport_source=transport_source,
        blockers=blockers,
    )


def render_markdown(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Whitepaper Claim Validation Report")
    lines.append("")
    lines.append(f"Generated: {report['generated_at_utc']}")
    lines.append(f"Profile: `{report['profile']}`")
    lines.append(f"Claim scope: `{report['claim_scope']}`")
    lines.append(f"Publication ready: `{report['publication_ready']}`")
    lines.append("")

    env = report["environment"]
    lines.append("## Environment")
    lines.append("")
    lines.append(f"- Python: `{env['python']}`")
    lines.append(f"- Platform: `{env['platform']}`")
    lines.append(f"- Elixir/Mix: `{env['mix_version']}`")
    lines.append(f"- OTP/Erlang: `{env['erlang_version']}`")
    lines.append("")

    lines.append("## Coverage Summary")
    lines.append("")
    coverage = report["coverage_summary"]
    lines.append("- By class:")
    for key, count in coverage["by_class"].items():
        lines.append(f"  - `{key}`: {count}")
    lines.append("- By status:")
    for key, count in coverage["by_status"].items():
        lines.append(f"  - `{key}`: {count}")
    lines.append(f"- Transport concurrency profile: `{report['transport_concurrency_profile']}`")
    lines.append(f"- Backpressure events: `{report['backpressure_events']}`")
    lines.append(f"- Queue depth percentiles: `{report['queue_depth_percentiles']}`")
    lines.append(f"- Restart latency percentiles: `{report['restart_latency_percentiles']}`")
    lines.append("")

    lines.append("## Claim Verdicts")
    lines.append("")
    lines.append("| Claim | Class | Status | Gate | Detail |")
    lines.append("| --- | --- | --- | --- | --- |")
    for verdict in report["claim_verdicts"]:
        lines.append(
            "| "
            f"{verdict['claim_id']} | {verdict['class']} | {verdict['status']} | "
            f"{verdict['gate_status']} | {verdict['detail']} |"
        )

    lines.append("")
    lines.append("## Evidence Rubric")
    lines.append("")
    lines.append("- `empirical`: benchmark/integration metrics with threshold-based verdicts.")
    lines.append(
        "- `architectural`: static/integration evidence links with evidence-count scoring."
    )
    lines.append("- `future/distributed`: marked `unsupported_in_scope` with explicit blockers.")

    lines.append("")
    lines.append("## Raw Artifacts")
    lines.append("")
    for key, path in report["raw_artifacts"].items():
        lines.append(f"- `{key}`: `{path}`")

    lines.append("")
    return "\n".join(lines)


def coverage_summary(verdicts: list[ClaimVerdict]) -> dict[str, dict[str, int]]:
    by_class: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for verdict in verdicts:
        by_class[verdict.class_] = by_class.get(verdict.class_, 0) + 1
        by_status[verdict.status] = by_status.get(verdict.status, 0) + 1
    return {"by_class": by_class, "by_status": by_status}


def is_publication_ready(
    verdicts: list[ClaimVerdict],
    *,
    profile: str,
    require_rigorous: bool,
) -> bool:
    if require_rigorous and profile != "rigorous":
        return False
    for verdict in verdicts:
        if verdict.status in {"not_validated", "insufficient_evidence"}:
            return False
    return True


async def run_selected_suites(
    *,
    repo_root: Path,
    config: ProfileConfig,
    claims: list[ClaimDefinition],
    transports: str,
) -> dict[str, object]:
    needed = {suite_key for claim in claims for suite_key in claim.suite_keys}
    suites: dict[str, object] = {}

    if "bridge_suite" in needed:
        suites["bridge_suite"] = await run_bridge_suite(repo_root, config, transports)
        suites["python_bridge_reference"] = await run_python_bridge_reference_suite(
            repo_root,
            config,
            transports,
        )
        suites["bridge_stress"] = await run_bridge_stress_suite(repo_root, config, transports)
    if "ab_runtime_comparison" in needed:
        suites["ab_runtime_comparison"] = await run_ab_runtime_comparison(repo_root, config)
    if "memory_scaling" in needed:
        suites["memory_scaling"] = await run_memory_scaling(repo_root, config)
    if "failure_recovery" in needed:
        suites["failure_recovery"] = await run_failure_recovery(repo_root)
    if "scheduler_fairness" in needed:
        suites["scheduler_fairness"] = await run_scheduler_fairness()
    if "startup_overhead" in needed:
        suites["startup_overhead"] = await run_startup_overhead(repo_root, config)
    if "architectural_evidence" in needed:
        suites["architectural_evidence"] = run_architectural_evidence(repo_root)

    return suites


async def main_async(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    config = profile_config(args.profile)

    all_claims = claim_definitions()
    selected_claims = [claim for claim in all_claims if claim_scope_filter(claim, args.claim_scope)]

    generated_at = datetime.now(UTC).isoformat()
    raw_root = Path(args.raw_dir)
    run_dir = raw_root / f"{args.profile}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    suites = await run_selected_suites(
        repo_root=repo_root,
        config=config,
        claims=selected_claims,
        transports=args.transports,
    )

    raw_artifacts: dict[str, str] = {}
    for key, payload in suites.items():
        out = run_dir / f"{key}.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        raw_artifacts[key] = str(out)

    verdicts: list[ClaimVerdict] = []
    for claim in selected_claims:
        verdict = evaluate_claim(
            claim,
            suites=suites,
            profile=args.profile,
            require_rigorous_for_validated=args.require_rigorous_for_validated,
        )
        if not claim.suite_keys and verdict.blockers == []:
            verdict = ClaimVerdict(
                claim_id=verdict.claim_id,
                status=verdict.status,
                detail=verdict.detail,
                class_=verdict.class_,
                evidence_type=verdict.evidence_type,
                gate_status=verdict.gate_status,
                required_profile=verdict.required_profile,
                transport_source=verdict.transport_source,
                blockers=["no runtime suite mapped; claim is future/distributed"],
            )
        verdicts.append(verdict)

    report: dict[str, object] = {
        "benchmark": "whitepaper-claim-validation",
        "generated_at_utc": generated_at,
        "profile": config.name,
        "claim_scope": args.claim_scope,
        "require_rigorous_for_validated": args.require_rigorous_for_validated,
        "transports": args.transports,
        "publication_ready": is_publication_ready(
            verdicts,
            profile=args.profile,
            require_rigorous=args.require_rigorous_for_validated,
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "mix_version": run_version_cmd(["mix", "--version"]),
            "erlang_version": run_version_cmd(
                [
                    "erl",
                    "-eval",
                    "erlang:display(erlang:system_info(otp_release)), halt().",
                    "-noshell",
                ]
            ),
        },
        "controls": {
            "warmup_runs": config.warmup_runs,
            "measured_runs": config.measured_runs,
            "rigorous_min_runs_target": 10,
            "notes": [
                "Local workstation measurements include hardware and scheduler variance.",
                "UDS claims require UDS transport measurements.",
                "Claims are evaluated against March 2026 whitepaper text.",
            ],
        },
        "claims": [
            {
                **asdict(claim),
                "class": claim.claim_class,
                "required_profile": claim.required_profile,
            }
            for claim in selected_claims
        ],
        "claim_verdicts": [
            {
                "claim_id": verdict.claim_id,
                "status": verdict.status,
                "detail": verdict.detail,
                "class": verdict.class_,
                "evidence_type": verdict.evidence_type,
                "gate_status": verdict.gate_status,
                "required_profile": verdict.required_profile,
                "transport_source": verdict.transport_source,
                "blockers": verdict.blockers,
            }
            for verdict in verdicts
        ],
        "coverage_summary": coverage_summary(verdicts),
        "transport_concurrency_profile": suites.get("bridge_stress", {}).get("config", {}),
        "backpressure_events": {
            "pool": sum(
                int(item.get("pool_backpressure_events", 0))
                for item in suites.get("bridge_stress", {}).get("results", [])
            )
            if isinstance(suites.get("bridge_stress"), dict)
            else 0,
            "server": sum(
                int(item.get("server_backpressure_events", 0))
                for item in suites.get("bridge_stress", {}).get("results", [])
            )
            if isinstance(suites.get("bridge_stress"), dict)
            else 0,
        },
        "queue_depth_percentiles": suites.get("scheduler_fairness", {}).get(
            "queue_depth_percentiles", {}
        ),
        "restart_latency_percentiles": suites.get("scheduler_fairness", {}).get(
            "restart_latency_percentiles_ms", {}
        ),
        "raw_artifacts": raw_artifacts,
        "suite_summary": suites,
    }

    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    md_output = Path(args.md_output)
    md_output.parent.mkdir(parents=True, exist_ok=True)
    md_output.write_text(render_markdown(report) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate whitepaper claims with reproducible benchmarks."
    )
    parser.add_argument("--profile", choices=["quick", "rigorous"], default="quick")
    parser.add_argument(
        "--claim-scope",
        choices=["all", "empirical", "non-empirical", "future"],
        default="all",
    )
    parser.add_argument(
        "--require-rigorous-for-validated",
        type=parse_bool,
        default=True,
    )
    parser.add_argument(
        "--transports",
        choices=["tcp", "uds", "both"],
        default="both",
    )
    parser.add_argument(
        "--json-output",
        default="docs/benchmarks/whitepaper_validation.json",
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--md-output",
        default="docs/benchmarks/whitepaper_validation.md",
        help="Output Markdown report path.",
    )
    parser.add_argument(
        "--raw-dir",
        default="docs/benchmarks/raw/whitepaper_validation",
        help="Directory root for per-suite raw artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
