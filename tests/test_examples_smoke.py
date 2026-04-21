"""Smoke tests: every shipped example runs and prints its expected payoff.

These spawn the example as a subprocess because the examples use module-level
globals (counters, registries) that would leak across pytest runs if imported.
Subprocess isolation matches how a real user invokes them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"


def _run(path: Path, timeout: float = 30.0) -> str:
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        timeout=timeout,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        f"{path.name} exited {result.returncode}\n"
        f"stdout:\n{result.stdout.decode()}\n"
        f"stderr:\n{result.stderr.decode()}"
    )
    return result.stdout.decode()


def test_without_vs_with_pyre_produces_clean_vs_corrupt() -> None:
    stdout = _run(EXAMPLES / "without_vs_with_pyre.py")
    assert "CORRUPT (dangling user turn)" in stdout
    assert "Pyre:        4 messages, clean" in stdout


def test_crewai_resilient_isolates_crash() -> None:
    stdout = _run(EXAMPLES / "crewai_resilient.py")
    assert "flaky crew crashed as expected" in stdout
    assert "healthy crew still working" in stdout
    assert "flaky crew recovered on retry" in stdout


def test_langgraph_resilient_isolates_crash() -> None:
    stdout = _run(EXAMPLES / "langgraph_resilient.py")
    assert "flaky graph crashed as expected" in stdout
    assert "healthy graph still working" in stdout
    assert "flaky graph recovered on retry" in stdout


def test_pydantic_ai_resilient_preserves_history_across_crash() -> None:
    pytest.importorskip("pydantic_ai", reason="pydantic-ai extra not installed")
    stdout = _run(EXAMPLES / "pydantic_ai_resilient.py", timeout=60.0)
    assert "turn 1:" in stdout
    assert "turn 2 crashed as expected" in stdout
    assert "turn 3:" in stdout
    assert "history=4" in stdout


def test_research_assistant_recovers_and_synthesizes() -> None:
    pytest.importorskip("pydantic_ai", reason="pydantic-ai extra not installed")
    stdout = _run(EXAMPLES / "research_assistant.py", timeout=60.0)
    assert "[risk] crashed" in stdout
    assert "Pyre restarted the bridge. retrying..." in stdout
    assert "history length = 4" in stdout
    assert "Synthesis:" in stdout
    # All three perspective outputs land in the synthesis step.
    assert "[technical]" in stdout
    assert "[business]" in stdout
    assert "[risk]" in stdout
