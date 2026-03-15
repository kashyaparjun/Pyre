# Whitepaper Claim Validation Report

Generated: 2026-03-15T16:29:38.641944+00:00
Profile: `quick`
Claim scope: `all`
Publication ready: `False`

## Environment

- Python: `3.12.7`
- Platform: `Darwin 25.3.0 (arm64)`
- Elixir/Mix: `Erlang/OTP 28 [erts-16.3] [source] [64-bit] [smp:8:8] [ds:8:8:10] [async-threads:1] [jit] [dtrace] |  | Mix 1.19.5 (compiled with Erlang/OTP 28)`
- OTP/Erlang: `"28"`

## Coverage Summary

- By class:
  - `empirical`: 6
  - `architectural`: 3
  - `future/distributed`: 4
- By status:
  - `insufficient_evidence`: 2
  - `partially_validated`: 1
  - `validated`: 5
  - `not_validated`: 1
  - `unsupported_in_scope`: 4
- Transport concurrency profile: `{'in_flight_depths': [1, 8, 32, 128, 512], 'duration_seconds': 1.0, 'payload_bytes': 512, 'pool_size': 8, 'max_in_flight_per_conn': 64, 'enable_backpressure': True}`
- Backpressure events: `{'pool': 0, 'server': 0}`
- Queue depth percentiles: `{'p50': 1.0, 'p95': 1.0, 'p99': 1.0}`
- Restart latency percentiles: `{'p50': 0.0, 'p95': 0.0, 'p99': 0.0}`

## Claim Verdicts

| Claim | Class | Status | Gate | Detail |
| --- | --- | --- | --- | --- |
| E1 | empirical | insufficient_evidence | not_applicable | required transport 'uds' not measured |
| E2 | empirical | insufficient_evidence | not_applicable | required transport 'uds' not measured |
| E3 | empirical | partially_validated | provisional_quick | boot_median=674.3ms |
| E4 | empirical | validated | meets_gate | ratio=1.000 checks=3/3 |
| E5 | empirical | not_validated | not_applicable | base=143.15MB delta_vs_idle_beam=74.63MB slope=2.90KB/agent |
| E6 | empirical | validated | meets_gate | blocking_factor=55.73 blocked_tick_ratio=0.027 |
| A1 | architectural | validated | meets_gate | api evidence 3/3 |
| A2 | architectural | validated | meets_gate | serialization evidence 3/3 |
| A3 | architectural | validated | meets_gate | observability evidence 2/2 |
| F1 | future/distributed | unsupported_in_scope | not_applicable | future/distributed claim outside local single-node validation scope |
| F2 | future/distributed | unsupported_in_scope | not_applicable | future/distributed claim outside local single-node validation scope |
| F3 | future/distributed | unsupported_in_scope | not_applicable | future/distributed claim outside local single-node validation scope |
| F4 | future/distributed | unsupported_in_scope | not_applicable | future/distributed claim outside local single-node validation scope |

## Evidence Rubric

- `empirical`: benchmark/integration metrics with threshold-based verdicts.
- `architectural`: static/integration evidence links with evidence-count scoring.
- `future/distributed`: marked `unsupported_in_scope` with explicit blockers.

## Raw Artifacts

- `bridge_suite`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/bridge_suite.json`
- `python_bridge_reference`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/python_bridge_reference.json`
- `bridge_stress`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/bridge_stress.json`
- `memory_scaling`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/memory_scaling.json`
- `failure_recovery`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/failure_recovery.json`
- `scheduler_fairness`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/scheduler_fairness.json`
- `startup_overhead`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/startup_overhead.json`
- `architectural_evidence`: `docs/benchmarks/raw/whitepaper_validation/quick_20260315T162938Z/architectural_evidence.json`

