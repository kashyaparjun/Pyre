"""CLI entrypoint for Pyre."""

from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import PackageNotFoundError, version


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyre-agents",
        description="Pyre runtime utilities and packaging smoke entrypoint.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed pyre-agents version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("demo", help="Run a minimal local runtime demo.")
    return parser


def _installed_version() -> str:
    try:
        return version("pyre-agents")
    except PackageNotFoundError:
        from pyre_agents import __version__

        return __version__


async def _run_demo() -> None:
    from pydantic import BaseModel

    from pyre_agents import Agent, AgentContext, CallResult, Pyre

    class CounterState(BaseModel):
        count: int

    class CounterAgent(Agent[CounterState]):
        async def init(self, **args: object) -> CounterState:
            initial_obj = args.get("initial", 0)
            initial = initial_obj if isinstance(initial_obj, int) else int(str(initial_obj))
            return CounterState(count=initial)

        async def handle_call(
            self, state: CounterState, msg: dict[str, object], ctx: AgentContext
        ) -> CallResult[CounterState]:
            if msg["type"] == "increment":
                payload = msg["payload"]
                assert isinstance(payload, dict)
                amount = int(payload.get("amount", 1))
                next_state = CounterState(count=state.count + amount)
                return CallResult(reply=next_state.count, new_state=next_state)
            return CallResult(reply=state.count, new_state=state)

    system = await Pyre.start()
    try:
        counter = await system.spawn(CounterAgent, name="counter", args={"initial": 2})
        value = await counter.call("increment", {"amount": 3})
        print(f"counter={value}")
    finally:
        await system.stop_system()


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

    parser.print_help()
