# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- `pyre_agents.adapters.google_adk.supervise()` — fifth framework adapter, wraps a `google-adk` `Agent` so `Runner.run_async()` flows through a Pyre supervised process. Session state lives in the caller's `SessionService` (defaults to `InMemorySessionService`); `preserve_state_on_restart` keeps the `(user_id, session_id)` pointer across crashes so the next run continues the same session.
- `pyre-agents[google-adk]` optional-deps extra.
- `examples/google_adk_resilient.py` — runnable demo with a stub `Runner` + `SessionService` that simulates a transient 503 on turn 2. Swap the stubs out (one arg change) to run live against Gemini/Vertex.
- `pyre_agents.adapters.openai_agents.supervise()` — fourth framework adapter, wraps an `openai-agents` `Agent` so `Runner.run()` calls flow through a Pyre supervised process with automatic history threading via `to_input_list()`. `preserve_state_on_restart` keeps the last-committed input list intact across crashes.
- `pyre-agents[openai-agents]` optional-deps extra.
- `examples/openai_agents_resilient.py` — runnable demo using a real `openai-agents.Agent` with a stub `Runner` that simulates a transient 503 on turn 2. Swap the stub for the real Runner (one-line change) to go live against OpenAI.

## 0.2.0 - 2026-04-21

### Added

- `preserve_state_on_restart` opt-in flag on `Pyre.spawn` and `AgentSpec`. When on, a restart after a handler crash reuses the last-committed state instead of re-invoking `init()`. Defaults off; existing callers are unaffected. Safe because Pyre only assigns `managed.state` after a handler returns successfully.
- `pyre_agents.adapters.pydantic_ai.supervise()` — wraps a pydantic-ai `Agent` in a supervised Pyre process so conversation history survives crashes that escape pydantic-ai's own error handling.
- `pyre_agents.adapters.crewai.supervise()` — wraps a CrewAI crew factory so crew crashes are isolated from each other. Sync `kickoff()` is offloaded via `asyncio.to_thread` so concurrent crews actually run concurrently.
- `pyre_agents.adapters.langgraph.supervise()` — wraps a LangGraph compiled-graph factory to isolate concurrent graph runs. Orthogonal to LangGraph's own Checkpointer (which handles within-graph durability); this adapter handles cross-graph isolation.
- `pyre-agents[pydantic-ai]`, `pyre-agents[crewai]`, and `pyre-agents[langgraph]` optional-deps extras.
- Graceful shutdown: `stop_system(drain_timeout_s=5.0)` sets a shutting-down flag, rejects new calls with `SystemStoppedError`, awaits in-flight handlers up to the timeout, then clears tables.
- `SystemStoppedError` exception (raised on calls after shutdown begins).
- `pyre-agents demo` CLI subcommand now runs the asyncio-vs-Pyre crash-safety comparison end-to-end; new `pyre-agents info` subcommand reports installed adapter extras and next steps.
- Runnable crash-recovery examples: `examples/pydantic_ai_resilient.py`, `examples/crewai_resilient.py`, `examples/langgraph_resilient.py`.
- No-deps side-by-side: `examples/without_vs_with_pyre.py` — same scenario runs under raw asyncio (history ends corrupt) and Pyre (history stays clean) in one file.
- Dogfood: `examples/research_assistant.py` — multi-perspective research workflow with three supervised pydantic-ai agents, one crashing mid-run, plus a synthesizer. Deterministic by default via `FunctionModel`.
- Smoke tests for every shipped example (`tests/test_examples_smoke.py`) and for the CLI (`tests/test_cli.py`).

### Changed

- README retargeted around the fault-tolerance wedge and the adapter flow. Quickstart now shows a pydantic-ai one-liner; custom `Agent` subclassing moved to a later section.
- Cost-model table now reports honest marginal per-agent memory (`~3.8KB BEAM + ~1-2KB Python handler ≈ ~5KB`) on top of the fixed runtime base, instead of the earlier `~3.4KB` headline that only counted the BEAM side.

### Fixed

- `BridgeEnvelope.correlation_id` validator had been shortened to a non-empty-string check as a performance optimization, breaking the contract test. Replaced with a shape-only UUID check that keeps the contract without the full parse cost.
- Elixir `Codec.unpack_envelope` had dropped message-type validation for the same "performance" reason, so unknown types fell through to handler dispatch. Restored a cheap type check on the hot path.
- `src/pyre_agents/bridge/server.py` constructed a `BridgeEnvelope.error` from a raw `dict` — strict mypy error and a latent serialization mismatch. Now constructs `BridgeErrorPayload` explicitly.
- `scripts/release_gate.py` ran `mypy .`, which overrode the configured `packages = ["pyre_agents"]` scope and pulled scaffolding (scripts, benchmarks) into strict typecheck. Now honors the config scope.

## 0.1.0 - 2026-03-13

- Implemented the Phase 1 bridge protocol, codec, framing, and transport baseline.
- Implemented the Phase 2 Python and Elixir agent lifecycle runtime.
- Implemented the Phase 3 supervision model and cross-runtime supervision tests.
- Completed the Phase 4 packaging and release workflow, including build and wheel smoke checks.
- Added public-release repository hygiene: license, contribution guides, security policy, and Markdown copies of the planning documents.
