# Pyre

BEAM-powered agent framework for Python with cross-runtime supervision between Python and Elixir.

## Status

- Phase 1 (Bridge Protocol): complete
- Phase 2 (Agent Lifecycle): complete
- Phase 3 (Supervision Trees + bridge health hooks): complete
- Current focus: Phase 4 (packaging + release workflow)

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for milestone details and verification snapshots.

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
```

Run Python checks:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -q
```

Run Elixir checks:

```bash
cd elixir/pyre_bridge
mix test
```

Run CLI:

```bash
uv run pyre-agents
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
    ref = await system.spawn(CounterAgent, name="counter", args={"initial": 2})
    print(await ref.call("increment", {}))  # 3
    await system.stop_system()
```

## Cross-runtime integration

- Python cross-runtime tests are in `tests/test_elixir_python_integration.py`
- Elixir bridge launcher used by tests: `elixir/pyre_bridge/scripts/start_bridge.exs`
- Elixir runtime implementation: `elixir/pyre_bridge/lib/pyre_bridge`

To run only cross-runtime tests:

```bash
uv run pytest -q tests/test_elixir_python_integration.py
```

## Repository map

- Python package: `src/pyre_agents`
- Python tests: `tests`
- Elixir bridge app: `elixir/pyre_bridge`
- Benchmarks and contracts: `docs`
- Utilities: `scripts`

## Project references

- `pyre-technical-document.docx`
- `pyre-project-plan.docx`
- `pyre-whitepaper.docx`
