"""Run the Phase 4 release verification sequence."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    elixir_root = repo_root / "elixir" / "pyre_bridge"

    _run(["uv", "run", "ruff", "check", "."], cwd=repo_root)
    _run(["uv", "run", "mypy", "."], cwd=repo_root)
    _run(["uv", "run", "pytest", "-q"], cwd=repo_root)
    _run(["mix", "test"], cwd=elixir_root)
    _run(["uv", "build"], cwd=repo_root)
    _run(["uv", "run", "python", "scripts/package_smoke.py"], cwd=repo_root)


if __name__ == "__main__":
    main()
