# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Added `preserve_state_on_restart` opt-in flag to `Pyre.spawn` and `AgentSpec`. When on, a restart after a handler crash reuses the last-committed state instead of re-invoking `init()`. Defaults off; existing callers are unaffected. Safe because Pyre only assigns `managed.state` after a handler returns successfully.
- Added `pyre_agents.adapters.pydantic_ai.supervise()` — wraps a pydantic-ai `Agent` in a supervised Pyre process so conversation history survives crashes that escape pydantic-ai's own error handling.
- Added `pyre_agents.adapters.crewai.supervise()` — wraps a CrewAI crew factory so crew crashes are isolated from each other. Sync `kickoff()` is offloaded via `asyncio.to_thread` so concurrent crews actually run concurrently.
- Added `pyre_agents.adapters.langgraph.supervise()` — wraps a LangGraph compiled-graph factory to isolate concurrent graph runs. Orthogonal to LangGraph's own Checkpointer (which handles within-graph durability); this adapter handles cross-graph isolation.
- Added `pyre-agents[pydantic-ai]`, `pyre-agents[crewai]`, and `pyre-agents[langgraph]` optional-deps extras.
- Added runnable examples in `examples/pydantic_ai_resilient.py`, `examples/crewai_resilient.py`, `examples/langgraph_resilient.py`, and a no-deps side-by-side in `examples/without_vs_with_pyre.py`.
- Added `examples/research_assistant.py`: a multi-perspective research workflow built on Pyre + the pydantic-ai adapter. Three supervised perspective agents run concurrently, one's provider crashes mid-run, Pyre isolates and restarts it with history intact, and a synthesizer combines the three outputs. Uses `FunctionModel` for a deterministic runnable demo; swap to a real model for live runs.

## 0.1.0 - 2026-03-13

- Implemented the Phase 1 bridge protocol, codec, framing, and transport baseline.
- Implemented the Phase 2 Python and Elixir agent lifecycle runtime.
- Implemented the Phase 3 supervision model and cross-runtime supervision tests.
- Completed the Phase 4 packaging and release workflow, including build and wheel smoke checks.
- Added public-release repository hygiene: license, contribution guides, security policy, and Markdown copies of the planning documents.
