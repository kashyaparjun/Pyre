# Contributing

Thanks for contributing to Pyre.

## Development setup

Requirements:

- Python 3.12+
- `uv`
- Elixir 1.16+ with `mix`

Install dependencies (include the optional adapter extras so all tests
and examples can run):

```bash
uv sync --all-extras --dev
cd elixir/pyre_bridge
mix deps.get
```

## Development workflow

Run the full local release gate before opening a PR. It mirrors CI
exactly (ruff, mypy, pytest, mix test, uv build, package smoke):

```bash
uv run python scripts/release_gate.py
```

For faster iteration:

```bash
uv run ruff check .
uv run mypy              # honors packages = ["pyre_agents"] scope; do not pass "."
uv run pytest -q
(cd elixir/pyre_bridge && mix test)
```

## Adding a framework adapter

Adapters live in `src/pyre_agents/adapters/`. The existing three
(`pydantic_ai.py`, `crewai.py`, `langgraph.py`) are the template —
each is a single module that exposes `supervise(...)` and a thin
handle dataclass. Minimum checklist for a new adapter:

- A process-level registry keyed by UUID (third-party objects aren't
  serializable through Pyre's args dict).
- Lazy / TYPE_CHECKING imports from the third-party library with
  `# type: ignore[import-not-found, unused-ignore]`.
- Stub-based tests under `tests/test_<framework>_adapter.py` — no
  network, no real LLM calls.
- A runnable crash-recovery example under `examples/` with a smoke
  test entry in `tests/test_examples_smoke.py`.
- An optional-dep extra in `pyproject.toml`'s
  `[project.optional-dependencies]`.

## Guidelines

- Keep changes focused and scoped to a clear behavior or release concern.
- Add or update tests when behavior changes.
- Keep Python type checking and linting clean.
- Update docs (README, CHANGELOG, and any relevant section under `docs/`)
  when public APIs, packaging, or runtime contracts change.

## Pull requests

Include:

- a short summary of the change
- the motivation or user-facing impact
- verification steps you ran

If a change affects the Python-Elixir bridge contract, update the docs in `docs/`.
