# Pyre

Write Python. Think in processes.

Run 10,000 stateful agents on a single machine. Each agent is an isolated BEAM process (~3.4KB), supervised by OTP, with automatic crash recovery. Your logic stays in Python.

## Status

- Phase 1 (Bridge Protocol): complete
- Phase 2 (Agent Lifecycle): complete
- Phase 3 (Supervision Trees + bridge health hooks): complete
- Phase 4 (packaging + release workflow): complete
- Current focus: Phase 5 (advanced features)

## Why Pyre

Stateful agents at scale. A Python process costs 10-50MB. A Pyre agent costs ~2.9KB. That's the difference between a cluster and a laptop.

- **True isolation**: Each agent is a BEAM process with its own heap. No shared mutable state.
- **Built-in supervision**: Crashed agents restart automatically. No try/except boilerplate.
- **Preemptive scheduling**: One slow agent can't starve the others.
- **Python-first API**: Pydantic state models, async handlers, familiar patterns.

## Cost model

| Model | Per-agent memory | Isolation | Supervision |
|-------|------------------|-----------|-------------|
| Python multiprocessing | 10-50MB | ✓ | Manual |
| Python threading | 1-8MB | ✗ (GIL) | Manual |
| Python asyncio | ~KB | ✗ (shared heap) | Manual |
| Pyre (BEAM process) | ~3.4KB | ✓ | Built-in |

Validated performance: 43,123 messages/sec throughput, 0.11ms median latency (p99: 0.20ms).

## What is implemented

- Python runtime lifecycle:
  - `Pyre.start()`, `spawn`, `call`, `cast`, `send_after`, `stop`
- Python supervision trees:
  - `one_for_one`, `one_for_all`, `rest_for_one`
  - nested supervisor groups and restart intensity
- Bridge protocol:
  - MessagePack envelopes + 4-byte big-endian framing
  - transport/server integration and negative-path handling
- Elixir bridge/runtime:
  - grouped supervisors with restart strategy semantics
  - cross-runtime spawn/execute/stop behavior
- Bridge health monitoring:
  - structured connection/message/error lifecycle events from Python `BridgeServer`

## Requirements

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)
- Elixir + Mix (required for Elixir runtime and cross-runtime tests)

## Quickstart

Install dependencies:

```bash
uv sync
cd elixir/pyre_bridge
mix deps.get
```

Run Python checks:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -q
```

Run Elixir checks:

```bash
(cd elixir/pyre_bridge && mix test)
```

Run CLI:

```bash
uv run pyre-agents --version
uv run pyre-agents demo
```

## Minimal Python runtime example

```python
from pydantic import BaseModel
from pyre_agents import Agent, AgentContext, CallResult, Pyre


class CounterState(BaseModel):
    count: int


class CounterAgent(Agent[CounterState]):
    async def init(self, **args: object) -> CounterState:
        return CounterState(count=int(args.get("initial", 0)))

    async def handle_call(
        self, state: CounterState, msg: dict[str, object], ctx: AgentContext
    ) -> CallResult[CounterState]:
        if msg["type"] == "increment":
            next_state = CounterState(count=state.count + 1)
            return CallResult(reply=next_state.count, new_state=next_state)
        return CallResult(reply=state.count, new_state=state)


async def main() -> None:
    system = await Pyre.start()
    try:
        ref = await system.spawn(CounterAgent, name="counter", args={"initial": 2})
        print(await ref.call("increment", {}))  # 3
    finally:
        await system.stop_system()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
```

## Cross-runtime integration

- Python cross-runtime tests are in `tests/test_elixir_python_integration.py`
- Elixir bridge launcher used by tests: `elixir/pyre_bridge/scripts/start_bridge.exs`
- Elixir runtime implementation: `elixir/pyre_bridge/lib/pyre_bridge`

To run only cross-runtime tests:

```bash
uv run pytest -q tests/test_elixir_python_integration.py
```

## Packaging and release gates

- Phase 4 packaging notes: `docs/packaging/phase4.md`
- Unified local release gate:

```bash
uv run python scripts/release_gate.py
```

- Artifact smoke test only:

```bash
uv build
uv run python scripts/package_smoke.py
```

## Documentation

- Packaging and release notes: `docs/packaging/phase4.md`
- Bridge contract: `docs/contracts/bridge_python_elixir_contract.md`
- Benchmark notes: `docs/benchmarks/phase1.md`
- Technical architecture: `TECHNICAL_DOCUMENT.md`
- Whitepaper: `WHITEPAPER.md`

## Repository map

- Python package: `src/pyre_agents`
- Python tests: `tests`
- Elixir bridge app: `elixir/pyre_bridge`
- Benchmarks and contracts: `docs`
- Utilities: `scripts`

## Community

- Contributing guide: `CONTRIBUTING.md`
- Code of conduct: `CODE_OF_CONDUCT.md`
- Security policy: `SECURITY.md`
- License: `LICENSE`
