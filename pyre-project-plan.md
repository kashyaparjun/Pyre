# Pyre

_Converted from the original DOCX for repository readability. Treat this as reference material; the README and PROJECT_STATUS.md reflect the current implementation state._

BEAM-Powered Agent Framework for Python

## Project Plan
Version 1.0  —  March 2026

## 1. Executive Summary
Pyre is an open-source Python library that gives AI agent developers the reliability and concurrency primitives of the Erlang/Elixir BEAM virtual machine without requiring them to learn or install Elixir. Developers write pure Python. Under the hood, Pyre boots a pre-compiled Elixir runtime that handles process supervision, message routing, fault recovery, and state management. The actual agent logic — LLM API calls, tool execution, data processing — runs in a Python process controlled by the Elixir orchestrator.
The project addresses a fundamental gap in the Python AI ecosystem: every major agent framework (LangChain, CrewAI, AutoGen, PydanticAI) builds orchestration on top of Python’s asyncio, which provides cooperative multitasking at best and no fault tolerance at all. When an agent crashes, the entire pipeline fails. When a developer needs hundreds of concurrent agents, they fight the GIL. Pyre eliminates these problems by delegating orchestration to a runtime purpose-built for exactly this class of workload.

## 2. Goals and Non-Goals
## 2.1 Goals
- Zero Elixir exposure: A Python developer should never need to install Erlang, write Elixir code, or know that the BEAM is involved. The Elixir runtime ships as a bundled binary inside the pip package.
- True fault tolerance: If an agent crashes (unhandled exception, API timeout, OOM), its supervisor restarts it automatically. Other agents are unaffected. This must work without any error-handling code in the developer’s agent logic.
- Scalable concurrency: Support 10,000+ concurrent agents on a single machine, each with isolated state and an independent mailbox. Performance should be bottlenecked by external API rate limits, not by the framework.
- Familiar API: The developer-facing API should feel like natural Python — classes, async methods, Pydantic models, type hints. No novel paradigms to learn beyond the message-passing pattern.
- Bridge performance: The IPC overhead between Elixir and Python should be under 1ms for typical agent messages, making it negligible compared to LLM API latency.
## 2.2 Non-Goals
- Not a BEAM reimplementation: We do not attempt to rebuild the BEAM scheduler, reduction counting, or per-process GC in Python. We use the real BEAM.
- Not an agent framework: Pyre provides infrastructure (processes, supervision, messaging), not opinions about how agents should think, plan, or use tools. It’s a runtime, not a cognitive architecture.
- Not a hosted service: Pyre runs entirely on the developer’s machine or server. No cloud dependency, no API keys for Pyre itself.

## 3. Project Phases and Timeline
The project is organized into six phases spanning 16 weeks. Each phase has a clear deliverable and success criteria.

| Phase | Duration | Deliverable | Success Criteria |
| --- | --- | --- | --- |
| Phase 1: Bridge Protocol | Weeks 1–3 | Standalone Elixir–Python IPC | 100K msgs/sec, <1ms P99 latency |
| Phase 2: Agent Lifecycle | Weeks 4–6 | Spawn, call, cast, crash/restart | Basic agent example runs end-to-end |
| Phase 3: Supervision Trees | Weeks 7–8 | Hierarchical supervisors | Nested supervision with all 3 strategies |
| Phase 4: Packaging | Weeks 9–10 | pip install pyre-agents | Works on Linux, macOS (x64/ARM), Windows |
| Phase 5: Advanced Features | Weeks 11–14 | Snapshots, telemetry, timers, groups | All advanced examples passing |
| Phase 6: Docs and Launch | Weeks 15–16 | Documentation site, PyPI publish | Public launch, 5-min quickstart works |

## 3.1 Phase 1: The Bridge Protocol (Weeks 1–3)
This is the foundation. If the bridge is slow or unreliable, nothing else works. We build the communication layer between Elixir and Python in isolation: Unix domain socket transport, MessagePack serialization, and length-prefixed framing. The deliverable is a standalone Elixir application and Python script that exchange messages at high throughput with sub-millisecond latency.
Key tasks:
- Design and implement the bridge envelope format (correlation ID, message type, agent ID, handler, serialized state/message/reply/error)
- Implement the Elixir socket server using gen_tcp with Unix domain sockets
- Implement the Python socket client with asyncio stream reader/writer
- Implement MessagePack serialization on both sides (msgpax for Elixir, msgpack for Python)
- Implement 4-byte length-prefixed framing for stream message boundaries
- Write throughput and latency benchmarks
- Test with payloads ranging from 100 bytes to 5MB (simulating large conversation histories)
## 3.2 Phase 2: Agent Lifecycle (Weeks 4–6)
Implement the core agent primitives. A developer should be able to define an agent as a Python class, spawn it (creating a GenServer in Elixir and registering its handler in Python), send it messages via call/cast, and observe automatic restart after a crash.
Key tasks:
- Implement Pyre.AgentServer GenServer in Elixir (state management, bridge delegation)
- Implement Pyre.AgentSupervisor as a DynamicSupervisor
- Implement the Python Agent base class with init/handle_call/handle_cast/handle_info
- Implement the AgentRef handle (the object developers use to communicate with agents)
- Implement the AgentContext (for agent-to-agent communication within handlers)
- Implement the Python worker dispatch loop (handler registry, message routing)
- Implement the Pyre.start() lifecycle (boot Elixir binary, establish socket, handshake)
- Write integration tests for spawn, call, cast, crash, and restart
## 3.3 Phase 3: Supervision Trees (Weeks 7–8)
Add hierarchical supervision with all three OTP restart strategies: one_for_one (restart only the crashed child), one_for_all (restart all children), and rest_for_one (restart the crashed child and all children started after it). Implement the SystemSupervisor that monitors the Python worker process and restarts it if it dies.
Key tasks:
- Implement system.create_supervisor() API for user-defined supervision hierarchies
- Map Python supervision config to Elixir Supervisor.child_spec
- Implement NodeMonitor for Python process health checking
- Test: kill the Python process, verify all agents restart when it comes back
- Test: nested supervisor trees with mixed strategies
- Test: max_restarts intensity limiting (shutdown after too many crashes)
## 3.4 Phase 4: Packaging and Distribution (Weeks 9–10)
Package the Elixir release into self-contained binaries for all target platforms using Burrito. Build the pip package with platform-specific wheels that include the correct binary. The developer experience must be: pip install pyre-agents, import, and go.
Key tasks:
- Configure Burrito builds for linux-x64, linux-arm64, darwin-x64, darwin-arm64, win32-x64
- Build platform-specific Python wheels using setuptools with binary data files
- Implement runtime launcher (locate binary, spawn, health-check, connect)
- Handle edge cases: port conflicts, stale processes, permission issues
- Test on CI across all platforms (GitHub Actions matrix)
- Measure cold-start time (target: under 1 second from Pyre.start() to ready)
## 3.5 Phase 5: Advanced Features (Weeks 11–14)
Build the features that make Pyre production-ready: state snapshots for long-running workflows, telemetry for observability, scheduled messages for polling and retry patterns, agent groups for broadcasting, and backpressure controls for flow management.
Key tasks:
- State snapshots: serialize all GenServer states, persist to disk, restore on startup
- Telemetry: pipe Elixir :telemetry events across the bridge, expose Python callbacks
- Timers: implement send_after via Process.send_after on the Elixir side
- Agent groups: implement using Elixir pg module, expose cast_all/call_all
- Backpressure: configurable mailbox limits with overflow strategies (drop_oldest, drop_newest, reject)
- LLM streaming support: design a stream message type for incremental token delivery
- Write comprehensive examples: research pipeline, tool-using agent, multi-agent debate, map-reduce
## 3.6 Phase 6: Documentation and Launch (Weeks 15–16)
Write documentation, build the docs site, record a demo video, write the launch blog post, and publish to PyPI. The documentation is more important than the code — if a developer can’t figure out how to use Pyre in five minutes, the architecture doesn’t matter.
Key tasks:
- Write quickstart guide (5 minutes to first running agent)
- Write conceptual guides: processes, supervision, messaging, state management
- Write API reference (auto-generated from docstrings)
- Build documentation site (MkDocs with Material theme)
- Record demo video showing fault tolerance in action
- Write launch blog post explaining the architecture and motivation
- Publish to PyPI, tag v0.1.0 on GitHub

## 4. Team and Resources
The core team requires three skillsets, which could be covered by as few as two people or as many as five depending on depth of expertise:
- Elixir/OTP engineer (1–2): Responsible for the GenServer implementations, supervision tree design, bridge protocol (Elixir side), Burrito packaging, and telemetry integration. Must have deep OTP experience — this person designs the fault-tolerance guarantees.
- Python systems engineer (1–2): Responsible for the Python library API, bridge client, asyncio integration, Pydantic state models, pip packaging, and the developer experience. Must understand Python’s async internals deeply.
- Documentation and DevRel (1): Responsible for the docs site, quickstart guide, examples, demo video, and launch blog post. Should be technical enough to write accurate code examples but focused on clarity and developer experience.

Infrastructure requirements:
- CI/CD: GitHub Actions with matrix builds across 5 platforms
- Benchmarking: Dedicated machine for reproducible performance testing
- Documentation: MkDocs deployment (GitHub Pages or Netlify)
- Package registry: PyPI account for pyre-agents

## 5. Risks and Mitigations

Risk
Likelihood
Impact
Mitigation
Bridge latency too high for tight message loops
Low
Medium
Batch messages on the bridge; most agent workloads are I/O-bound so this likely won’t matter
Burrito binary too large (>100MB)
Medium
Medium
Strip ERTS, use Bakeware as alternative, explore WASM compilation
State serialization failures (non-serializable Python objects in state)
High
Low
Enforce Pydantic models for state; fail fast with clear error messages at spawn time
Developer confusion about the Elixir dependency
Medium
High
Never expose Elixir in errors, logs, or docs; wrap all Elixir errors in Python exceptions
Platform-specific bugs in bundled binary
Medium
High
Extensive CI matrix; beta program with early adopters on each platform
Python GIL blocking handler execution
Low
Medium
Handlers are async; CPU-bound work should use ProcessPoolExecutor

## 6. Success Metrics
We measure success at two levels: technical quality and developer adoption.
## 6.1 Technical Metrics (at launch)
- Bridge latency: P50 < 0.2ms, P99 < 1ms for messages under 10KB
- Cold start: Pyre.start() to ready in under 1 second
- Concurrency: 10,000 concurrent agents on a single machine (16GB RAM)
- Fault recovery: agent restart after crash in under 50ms
- Binary size: bundled Elixir runtime under 50MB compressed
- Zero Elixir surface area: no Elixir terms in any user-facing error, log, or API
## 6.2 Adoption Metrics (3 months post-launch)
- PyPI downloads: 5,000+ in first month
- GitHub stars: 1,000+
- Community examples or blog posts: 10+
- At least one production deployment reported by an external team
- Documentation: quickstart completion rate above 80% (measured via analytics)
