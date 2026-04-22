"""CLI entrypoint for Pyre."""

from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from typing import Any

from pydantic import BaseModel

from pyre_agents import Agent, AgentContext, AgentInvocationError, CallResult, Pyre


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyre-agents",
        description="Pyre runtime utilities.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed pyre-agents version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "demo",
        help="Run the crash-safety demo: asyncio corrupts history, Pyre keeps it clean.",
    )
    subparsers.add_parser(
        "info",
        help="Show version, installed adapter extras, and what to try next.",
    )
    return parser


def _installed_version() -> str:
    try:
        return version("pyre-agents")
    except PackageNotFoundError:
        from pyre_agents import __version__

        return __version__


# --- `pyre-agents demo` — the 2-second pitch -------------------------------


class _ChatState(BaseModel):
    history: list[dict[str, str]] = []


_tool_calls = {"n": 0}


def _flaky_tool(topic: str) -> str:
    _tool_calls["n"] += 1
    if _tool_calls["n"] == 2:
        raise RuntimeError(f"transient failure on call 2 (topic={topic!r})")
    return f"facts about {topic}"


class _ChatAgent(Agent[_ChatState]):
    async def init(self, **args: Any) -> _ChatState:
        return _ChatState()

    async def handle_call(
        self, state: _ChatState, msg: dict[str, Any], ctx: AgentContext
    ) -> CallResult[_ChatState]:
        if msg["type"] == "get_history":
            return CallResult(reply=list(state.history), new_state=state)
        topic = str(msg["payload"]["topic"])
        fact = _flaky_tool(topic)
        new_history = [
            *state.history,
            {"role": "user", "content": topic},
            {"role": "assistant", "content": fact},
        ]
        return CallResult(reply=fact, new_state=_ChatState(history=new_history))


async def _run_demo() -> None:
    # Same scenario both variants share.
    topics = ("bees", "ants", "wasps")

    # Variant A: naive in-place mutation
    _tool_calls["n"] = 0
    raw_history: list[dict[str, str]] = []
    for topic in topics:
        try:
            raw_history.append({"role": "user", "content": topic})
            fact = _flaky_tool(topic)
            raw_history.append({"role": "assistant", "content": fact})
        except Exception as exc:
            print(f"  [asyncio]  turn {topic!r} crashed: {exc}")

    # Variant B: Pyre-supervised with atomic state commit
    _tool_calls["n"] = 0
    system = await Pyre.start()
    try:
        ref = await system.spawn(_ChatAgent, name="chat", preserve_state_on_restart=True)
        for topic in topics:
            try:
                await ref.call("turn", {"topic": topic})
            except AgentInvocationError as exc:
                print(f"  [pyre]     turn {topic!r} crashed: {exc}")
        pyre_history = await ref.call("get_history", {})
    finally:
        await system.stop_system()

    print()
    print("asyncio:")
    for m in raw_history:
        print(f"  {m['role']:9s} {m['content']}")
    print("pyre:")
    for m in pyre_history:
        print(f"  {m['role']:9s} {m['content']}")
    print()

    asyncio_clean = len(raw_history) % 2 == 0 and all(
        m["role"] == ("user" if i % 2 == 0 else "assistant")
        for i, m in enumerate(raw_history)
    )
    pyre_clean = len(pyre_history) % 2 == 0 and all(
        m["role"] == ("user" if i % 2 == 0 else "assistant")
        for i, m in enumerate(pyre_history)
    )
    print(
        f"asyncio: {len(raw_history)} messages, "
        f"{'clean' if asyncio_clean else 'CORRUPT (dangling user turn)'}."
    )
    print(
        f"pyre:    {len(pyre_history)} messages, "
        f"{'clean' if pyre_clean else 'corrupt'} — crash never touched committed state."
    )


# --- `pyre-agents info` — where to go next ---------------------------------

_ADAPTER_EXTRAS = (
    ("pydantic-ai", "pydantic_ai", "pyre_agents.adapters.pydantic_ai"),
    ("crewai", "crewai", "pyre_agents.adapters.crewai"),
    ("langgraph", "langgraph", "pyre_agents.adapters.langgraph"),
    ("openai-agents", "agents", "pyre_agents.adapters.openai_agents"),
    ("google-adk", "google.adk", "pyre_agents.adapters.google_adk"),
)


def _run_info() -> None:
    print(f"pyre-agents {_installed_version()}")
    print()
    print("Adapters:")
    any_installed = False
    for extra, probe_module, adapter_path in _ADAPTER_EXTRAS:
        present = find_spec(probe_module) is not None
        mark = "installed" if present else "not installed"
        if present:
            any_installed = True
        print(f"  {extra:13s}  {mark:14s}  {adapter_path}")
        if not present:
            print(f"  {'':13s}  install:        uv add 'pyre-agents[{extra}]'")
    print()
    print("Next:")
    print("  pyre-agents demo                       # 2-second pitch")
    print("  python examples/without_vs_with_pyre.py  # same demo, more detail")
    if any_installed:
        print("  python examples/research_assistant.py  # realistic multi-agent product")


def main() -> None:
    """Run the Pyre CLI."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.version:
        print(_installed_version())
        return

    if args.command == "demo":
        asyncio.run(_run_demo())
        return

    if args.command == "info":
        _run_info()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
