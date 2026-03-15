# Contributing

Thanks for contributing to Pyre.

## Development setup

Requirements:

- Python 3.12+
- `uv`
- Elixir 1.16+ with `mix`

Install dependencies:

```bash
uv sync
cd elixir/pyre_bridge
mix deps.get
```

## Development workflow

Run the full local release gate before opening a PR:

```bash
uv run python scripts/release_gate.py
```

For faster iteration:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -q
cd elixir/pyre_bridge && mix test
```

## Guidelines

- Keep changes focused and scoped to a clear behavior or release concern.
- Add or update tests when behavior changes.
- Keep Python type checking and linting clean.
- Update docs when public APIs, packaging, or runtime contracts change.

## Pull requests

Include:

- a short summary of the change
- the motivation or user-facing impact
- verification steps you ran

If a change affects the Python-Elixir bridge contract, update the docs in `docs/`.
