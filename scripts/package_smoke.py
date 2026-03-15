"""Build artifact smoke test for the published wheel."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _latest_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("pyre_agents-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"no wheel found in {dist_dir}")
    return wheels[-1]


def _smoke_runtime_snippet() -> str:
    return """
import asyncio
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
        payload = msg["payload"]
        assert isinstance(payload, dict)
        amount = int(payload.get("amount", 1))
        next_state = CounterState(count=state.count + amount)
        return CallResult(reply=next_state.count, new_state=next_state)

async def main() -> None:
    system = await Pyre.start()
    try:
        ref = await system.spawn(CounterAgent, name="counter", args={"initial": 4})
        value = await ref.call("increment", {"amount": 2})
        assert value == 6, value
    finally:
        await system.stop_system()

asyncio.run(main())
"""


def _smoke_metadata_snippet() -> str:
    return """
from importlib.metadata import version

assert version("pyre-agents") == "0.1.0"
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run wheel install + runtime smoke checks.")
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Directory containing built wheel artifacts (default: dist).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = (repo_root / args.dist_dir).resolve()
    wheel = _latest_wheel(dist_dir)

    with tempfile.TemporaryDirectory(prefix="pyre-package-smoke-") as tmp:
        env_dir = Path(tmp) / "venv"
        _run(["uv", "venv", str(env_dir)])
        python = env_dir / "bin" / "python"

        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--quiet",
                str(wheel),
            ]
        )
        _run([str(python), "-m", "pyre_agents.cli", "--version"])
        _run([str(python), "-c", _smoke_metadata_snippet()])
        _run([str(python), "-m", "pyre_agents.cli", "demo"])
        _run([str(python), "-c", _smoke_runtime_snippet()])

        scripts_dir = env_dir / "bin"
        if not (scripts_dir / "pyre-agents").exists():
            raise FileNotFoundError("console entrypoint 'pyre-agents' was not installed")
        if shutil.which("pyre-agents", path=str(scripts_dir)) is None:
            raise RuntimeError("console entrypoint 'pyre-agents' is not executable")


if __name__ == "__main__":
    main()
