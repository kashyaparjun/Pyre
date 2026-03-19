# AGENTS.md

Guide for coding agents working in the Pyre codebase.

## Project Overview

Pyre is a BEAM-powered agent framework for Python with cross-runtime supervision between Python and Elixir. It provides actor-style systems with OTP-inspired restart semantics while keeping agent logic in Python.

**Structure:**
- Python package: `src/pyre_agents`
- Python tests: `tests`
- Elixir bridge: `elixir/pyre_bridge`
- Scripts: `scripts`
- Docs: `docs`

## Build Commands

### Python

```bash
uv sync                                    # Install dependencies
uv run ruff check .                        # Lint
uv run ruff check . --fix                  # Lint with auto-fix
uv run mypy .                              # Type check
uv run pytest -q                           # Run all tests
uv run pytest -q tests/test_phase2_lifecycle.py  # Run single test file
uv run pytest -q tests/test_phase2_lifecycle.py::test_spawn_call_and_cast  # Run single test
uv run pytest -q -k "lifecycle"            # Run tests matching pattern
uv run python scripts/release_gate.py      # Full release validation
```

### Elixir

```bash
cd elixir/pyre_bridge && mix deps.get      # Install dependencies
cd elixir/pyre_bridge && mix test          # Run all tests
cd elixir/pyre_bridge && mix test test/pyre_bridge/agent_lifecycle_test.exs  # Single file
cd elixir/pyre_bridge && mix test test/pyre_bridge/agent_lifecycle_test.exs:8  # Single test (by line)
```

### Cross-Runtime Integration Tests

```bash
uv run pytest -q tests/test_elixir_python_integration.py  # Python-Elixir bridge tests
```

## Code Style: Python

### Imports

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from pyre_agents.errors import PyreError
```

Order: `from __future__` → stdlib → third-party → local. Use `collections.abc` for typing.

### Formatting

- Line length: 100 (configured in pyproject.toml)
- Ruff rules: E (errors), F (pyflakes), I (isort), UP (pyupgrade)
- Run `uv run ruff check . --fix` before committing

### Types

- Strict mypy is enabled (`strict = true`)
- Use explicit types; avoid `Any` when possible
- Generic classes use PEP 695 syntax:

```python
class Agent[StateT: BaseModel]:
    async def handle_call(self, state: StateT, msg: dict[str, Any], ctx: AgentContext) -> CallResult[StateT]:
        ...
```

- Use `TypeGuard` or `isinstance` for type narrowing
- Prefer `list[X]`, `dict[K, V]` over `List`, `Dict`

### Naming

- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- Internal module imports in TYPE_CHECKING blocks to avoid circular imports

### Data Models

- Use Pydantic `BaseModel` for state and wire formats
- Use `@dataclass(frozen=True)` for immutable config/spec objects
- Use `StrEnum` for string enumerations

```python
class CounterState(BaseModel):
    count: int

@dataclass(frozen=True)
class RestartPolicy:
    max_restarts: int = 3
    within_ms: int = 5000

class MessageType(StrEnum):
    EXECUTE = "execute"
    RESULT = "result"
```

### Error Handling

- Use custom exceptions from `pyre_agents.errors`:
  - `PyreError` (base)
  - `AgentNotFoundError`
  - `AgentInvocationError`
  - `AgentTerminatedError`
- Chain exceptions with `from`:

```python
raise AgentInvocationError(f"Agent '{name}' crashed") from exc
```

### Docstrings

- Module-level docstring at top of file
- Class docstrings for public classes
- Method docstrings for public API methods

```python
"""Runtime orchestration surface for Python agents."""

class PyreSystem:
    """In-process runtime implementing lifecycle and supervision behavior."""

    async def spawn(self, agent_cls: type[Agent[Any]], *, name: str) -> AgentRef:
        """Spawn a new agent with the given name."""
```

### Tests

- Use `pytest.mark.asyncio` for async tests
- Place test fixtures/classes at top of file, tests below
- Name tests `test_<behavior>`, e.g., `test_crash_triggers_restart_with_initial_state`
- Clean up with `await system.stop_system()` in finally block or at test end

```python
@pytest.mark.asyncio
async def test_spawn_call_and_cast() -> None:
    system = await Pyre.start()
    ref = await system.spawn(CounterAgent, name="counter", args={"initial": 2})
    assert await ref.call("get", {}) == 2
    await system.stop_system()
```

## Code Style: Elixir

### Module Structure

```elixir
defmodule PyreBridge.AgentServer do
  @moduledoc """
  Phase 2 stateful agent process.
  """

  use GenServer

  defstruct [:name, :handler_module, :state]

  @type server_state :: %__MODULE__{
          name: String.t(),
          handler_module: module(),
          state: term()
        }

  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    ...
  end

  @impl true
  def handle_call({:call, type, payload}, _from, %__MODULE__{} = state) do
    ...
  end
end
```

### Conventions

- `@moduledoc` for module documentation
- `@spec` for public function specs
- `@impl true` for callback implementations
- `defstruct` for server state
- Snake_case atoms for message types: `:call`, `:cast`, `:error`
- Pattern match in function heads and `case` expressions

### Tests

```elixir
defmodule PyreBridge.AgentLifecycleTest do
  use ExUnit.Case, async: false

  alias PyreBridge.AgentServer

  test "spawn call cast and restart semantics" do
    name = "counter-#{System.unique_integer([:positive])}"
    assert {:ok, _pid} = AgentSupervisor.start_agent(...)
    assert {:ok, 2} = AgentServer.call(name, "get", %{})
  end
end
```

## Pre-Commit Checklist

1. `uv run ruff check .` - no lint errors
2. `uv run mypy .` - no type errors
3. `uv run pytest -q` - all tests pass
4. `(cd elixir/pyre_bridge && mix test)` - Elixir tests pass (if Elixir installed)

## Key Files

- `pyproject.toml` - Python config (ruff, mypy, pytest)
- `elixir/pyre_bridge/mix.exs` - Elixir config
- `docs/contracts/bridge_python_elixir_contract.md` - Bridge protocol spec
- `README.md` - Quickstart and architecture overview
