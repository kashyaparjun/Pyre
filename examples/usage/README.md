# Adapter usage examples

Minimal "how do I use this?" examples for each framework adapter — no
crash simulation, no supervision theatrics. Just the happy path that
shows how to wrap a native agent in Pyre with one function call.

For crash-recovery stories, see `examples/*_resilient.py` at the top
level. For an end-to-end multi-agent product built on these pieces,
see `examples/research_assistant.py`.

| File | What it shows |
|---|---|
| [`pydantic_ai_basic.py`](pydantic_ai_basic.py) | Wrap a `pydantic_ai.Agent` (deterministic `FunctionModel`, no key needed) |
| [`crewai_basic.py`](crewai_basic.py) | Wrap a CrewAI `Crew` factory |
| [`langgraph_basic.py`](langgraph_basic.py) | Wrap a LangGraph compiled graph factory |
| [`openai_agents_basic.py`](openai_agents_basic.py) | Wrap an `agents.Agent` with a stub `Runner` |
| [`google_adk_basic.py`](google_adk_basic.py) | Wrap a `google.adk.Agent` with a stub `Runner` + `SessionService` |

All five run without any API key. Swap the deterministic/stub pieces out
(one-arg changes, documented in each file) to go live against real
providers.

Filenames are suffixed with `_basic` so Python's import resolver doesn't
shadow the framework module with a same-named local script.
