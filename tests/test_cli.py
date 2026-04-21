"""Smoke tests for the pyre-agents CLI."""

from __future__ import annotations

import subprocess
import sys


def _run(*args: str, timeout: float = 20.0) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pyre_agents.cli", *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return result.returncode, result.stdout.decode(), result.stderr.decode()


def test_cli_version_prints_something_version_shaped() -> None:
    code, stdout, _ = _run("--version")
    assert code == 0
    assert stdout.strip()  # non-empty


def test_cli_demo_shows_corrupt_vs_clean_contrast() -> None:
    code, stdout, stderr = _run("demo")
    assert code == 0, f"demo exited {code}, stderr:\n{stderr}"
    # Asyncio side corrupted; Pyre side clean.
    assert "CORRUPT (dangling user turn)" in stdout
    assert "pyre:" in stdout and "clean" in stdout
    # Both sides hit the crash.
    assert "[asyncio]" in stdout
    assert "[pyre]" in stdout


def test_cli_info_lists_adapters_and_next_steps() -> None:
    code, stdout, _ = _run("info")
    assert code == 0
    assert "pyre-agents" in stdout
    assert "pydantic-ai" in stdout
    assert "crewai" in stdout
    assert "langgraph" in stdout
    assert "Next:" in stdout
    assert "pyre-agents demo" in stdout


def test_cli_no_command_prints_help() -> None:
    code, stdout, _ = _run()
    assert code == 0
    assert "usage:" in stdout.lower() or "usage" in stdout.lower()
