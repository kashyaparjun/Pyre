# Pyre

Write Python. Think in processes.

Pyre gives Python agents the fault-tolerance and supervision semantics of the
BEAM. One agent's crash can't kill the others. Conversation state survives
restarts. Your existing pydantic-ai or CrewAI code keeps working — the adapter
is one line.

## Why Pyre

Production agent systems hit three walls Python can't solve cleanly: massive
concurrency, fault isolation, and automatic recovery. Pyre wraps each agent in
a supervised BEAM process so:

- **True isolation**: Each agent is a BEAM process with its own heap. No shared mutable state.
- **Built-in supervision**: Crashed agents restart automatically. No try/except boilerplate.
- **Preemptive scheduling**: One slow agent can't starve the others.
- **State survives crashes**: Opt in to `preserve_state_on_restart` and the last-committed state is kept across restarts — conversation history, counters, anything.
- **Python-first API**: Pydantic state models, async handlers, familiar patterns.

## Cost model

Per-agent marginal memory (added for each new supervised agent), on top of a
fixed ~50MB Python interpreter and ~30MB Elixir node base:

| Model | Marginal per-agent memory | Isolation | Supervision |
|-------|---------------------------|-----------|-------------|
| Python multiprocessing | 10-50MB | ✓ | Manual |
| Python threading | 1-8MB | ✗ (GIL) | Manual |
| Python asyncio | ~KB | ✗ (shared heap) | Manual |
| Pyre | ~3.8KB BEAM process + ~1-2KB Python handler ≈ ~5KB | ✓ | Built-in |

10,000 active agents is ~80MB of fixed runtime plus ~50MB of per-agent overhead
— well under a 1GB container. Bridge throughput is ~43k messages/sec per
connection with 0.11ms median latency (p99: 0.20ms) on the validation rig, so
the bridge is not the bottleneck for any realistic LLM-bound workload.

## Status

- Phases 1–4 (bridge protocol, agent lifecycle, supervision trees, packaging): complete
- Adapters for [pydantic-ai](src/pyre_agents/adapters/pydantic_ai.py) and [CrewAI](src/pyre_agents/adapters/crewai.py): complete
- Current focus: Phase 5 (advanced features, more adapters)

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

## See it in 30 seconds

One file, no external deps, shows the punchline:

```bash
uv run python examples/without_vs_with_pyre.py
```

Same scenario — three conversation turns with a tool that crashes on the
middle one — runs twice: once in raw asyncio (history ends corrupt with a
dangling user message), once wrapped in Pyre (history stays clean because
state is only committed after a handler returns).

## Framework adapters

Pyre ships thin adapters that wrap existing Python agent frameworks so their
runs survive crashes without rewriting any agent code.

- **pydantic-ai** (`pyre-agents[pydantic-ai]`) — `pyre_agents.adapters.pydantic_ai.supervise(agent, system=..., name=...)` returns a supervised handle whose `.run(prompt)` threads `message_history` through a Pyre process. Crashes that escape pydantic-ai's own error handling trigger a restart that keeps the last-committed history intact.
- **CrewAI** (`pyre-agents[crewai]`) — `pyre_agents.adapters.crewai.supervise(crew_factory, system=..., name=...)` returns a supervised handle whose `.kickoff(inputs)` runs on a fresh `Crew` instance from the factory. One crew's crash cannot take down another supervised crew. Sync `kickoff()` is offloaded to a thread so concurrency is real.

Runnable crash-recovery demos:

```bash
uv run --with 'pydantic-ai>=1.0' python examples/pydantic_ai_resilient.py
uv run python examples/crewai_resilient.py
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
