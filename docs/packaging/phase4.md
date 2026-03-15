# Phase 4 Packaging and Release Workflow

Phase 4 closes the gap between a working Phase 3 prototype and a releasable repository.

## What is now in place

- Python package metadata is defined in `pyproject.toml`.
- `uv build` produces both an sdist and a wheel.
- `scripts/package_smoke.py` installs the built wheel into a fresh virtual environment and verifies:
  - CLI version output
  - CLI demo execution
  - minimal runtime spawn/call behavior
- `scripts/release_gate.py` runs the combined Python, Elixir, build, and packaging checks.
- `.github/workflows/ci.yml` runs the release gate on pushes and pull requests.

## Local release gate

Run the full verification sequence from the repository root:

```bash
uv run python scripts/release_gate.py
```

This runs:

1. `uv run ruff check .`
2. `uv run mypy .`
3. `uv run pytest -q`
4. `mix test` in `elixir/pyre_bridge`
5. `uv build`
6. `uv run python scripts/package_smoke.py`

## Installation options

From source:

```bash
uv sync --dev
```

From built artifacts:

```bash
uv build
python -m pip install dist/pyre_agents-0.1.0-py3-none-any.whl
```

## Compatibility matrix

| Component | Supported baseline |
| --- | --- |
| Python package | Python 3.12+ |
| Python tooling | `uv` |
| Elixir bridge | Elixir 1.16+ |
| Verified in CI | Elixir 1.19.5 / OTP 27.3 |
| Bridge transport | TCP loopback |

## Elixir bridge startup contract

The bridge reads the following environment variables:

- `PYRE_BRIDGE_HOST`
- `PYRE_BRIDGE_PORT`
- `PYRE_BRIDGE_RECV_TIMEOUT_MS`
- `PYRE_BRIDGE_GROUP_MAX_RESTARTS`
- `PYRE_BRIDGE_GROUP_MAX_SECONDS`

For integration tests, `elixir/pyre_bridge/scripts/start_bridge.exs` sets the port to `0`,
starts the app, and prints `PYRE_BRIDGE_PORT=<port>` to stdout.

## Troubleshooting

- If `mix test` fails because dependencies are missing, run `mix deps.get` in `elixir/pyre_bridge`.
- If the package smoke test fails during install, rebuild artifacts with `uv build` before rerunning it.
- If cross-runtime tests fail, confirm `mix` is available on `PATH` and the bridge can boot with `mix run --no-start scripts/start_bridge.exs`.

## Release checklist

1. Run `uv run python scripts/release_gate.py`.
2. Confirm `dist/` contains a fresh wheel and sdist built from the current commit.
3. Review `README.md`, `PROJECT_STATUS.md`, and this document for version/status accuracy.
4. Tag the release only after the full gate passes.
