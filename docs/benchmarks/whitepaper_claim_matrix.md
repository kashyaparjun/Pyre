# Whitepaper Claim Matrix (March 2026)

This matrix maps whitepaper claims to validation methods, thresholds, and scope handling.

| Claim ID | Class | Exact Quote | Evidence Type | Metric | Validation Threshold | Partial Threshold | Required Profile | Caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | empirical | "The bridge round-trip for a typical agent message (under 1KB of state) adds 0.1-0.3ms of latency." | benchmark | `bridge.uds.small.p50_ms`, `bridge.uds.small.p99_ms` | `p50 <= 0.3` and `p99 <= 0.5` | `p50 <= 0.5` and `p99 <= 1.0` | rigorous | UDS transport required as source-of-truth; faster-than-claim lower bound is valid. |
| E2 | empirical | "The Unix domain socket bridge supports 50,000-100,000 messages per second." | benchmark | `bridge.uds.small.messages_per_second` | `median >= 50000` | `median >= 10000` | rigorous | UDS transport required as source-of-truth. |
| E3 | empirical | "Booting the Elixir runtime adds 500-1000ms to application startup." | benchmark | `startup.boot_ms` | `median <= 1000` | `median <= 1500` | rigorous | Local machine variance expected; faster-than-claim lower bound is valid. |
| E4 | empirical | "Supervisors restart child processes when they fail" with `one_for_one`/`one_for_all`/`rest_for_one` semantics. | integration_test | `recovery.restart_success_ratio`, strategy checks | `ratio >= 0.99` and all checks pass | `ratio >= 0.90` and >=2 checks pass | quick | Strategy behavior verified through bridge execution. |
| E5 | empirical | "The Elixir runtime adds approximately 30MB of base memory ... Each agent ... 2-5KB" | benchmark | `memory_scaling.elixir.absolute_base_runtime_bytes`, `bytes_per_agent` | `base in [20,45]MB` and `slope in [2,5]KB/agent` | `base in [15,60]MB` and `slope <= 10KB/agent` | rigorous | Absolute RSS is verdict source; idle-BEAM delta is reported as context. |
| E6 | empirical | "No preemption within Python ... CPU-intensive operation ... will block the Python worker." | benchmark | `scheduler_fairness.no_preemption_timer_drift.blocking_factor_p99` | `blocking_factor >= 2.0` | `blocking_factor >= 1.3` | quick | Timer-drift amplification under synthetic CPU burn in `serial_python_worker` mode. |
| A1 | architectural | "Developers write pure Python and interact with Python APIs." | static_analysis | API/doc evidence presence | all required evidence present | >=2 required evidence present | quick | Non-benchmark architectural claim. |
| A2 | architectural | "State is serialized across the bridge and constrained to serializable models." | static_analysis | runtime + codec/protocol test evidence | all evidence present | >=2 evidence present | quick | Validated via code/test linkage. |
| A3 | architectural | "Bridge/runtime observability provides lifecycle and error visibility." | integration_test | health API + health tests evidence | all evidence present | API exists with at least one test evidence | quick | Evidence-linked architectural validation. |
| F1 | future/distributed | "Distributed clustering for cross-machine agents" (future direction). | blocked_future | blocked by scope | `unsupported_in_scope` | n/a | quick | Local single-node validation only. |
| F2 | future/distributed | "Hot code reloading" (future direction). | blocked_future | blocked by unimplemented feature | `unsupported_in_scope` | n/a | quick | No runtime mechanism in current repo. |
| F3 | future/distributed | "Streaming bridge message types" (future direction). | blocked_future | blocked by protocol scope | `unsupported_in_scope` | n/a | quick | Current protocol is request/response only. |
| F4 | future/distributed | "WASM-based isolation alternative" (future direction). | blocked_future | blocked by unimplemented backend | `unsupported_in_scope` | n/a | quick | No WASM runtime backend present. |

## Evidence Rubric

- `empirical`: benchmark/integration metrics are evaluated against strict threshold + partial rule.
- `architectural`: verdict derived from explicit evidence mapping (code paths/tests/docs), not performance stats.
- `future/distributed`: explicit `unsupported_in_scope` for local single-node runs with concrete blockers.
- Gate policy: when `--require-rigorous-for-validated=true`, `quick` cannot produce publication-grade `validated` for claims requiring `rigorous`.
- Transport rule: UDS-tagged claims require UDS measurements; TCP-only data is insufficient for UDS claim validation.
