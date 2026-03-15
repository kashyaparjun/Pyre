# Whitepaper Claim Validation Report

Generated: 2026-03-13T23:28:05.583093+00:00
Profile: `rigorous`
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
  - `partially_validated`: 2
  - `validated`: 5
  - `not_validated`: 2
  - `unsupported_in_scope`: 4
- Transport concurrency profile: `{'in_flight_depths': [1, 8, 32, 128, 512], 'duration_seconds': 2.0, 'payload_bytes': 512, 'pool_size': 8, 'max_in_flight_per_conn': 64, 'enable_backpressure': True}`
- Backpressure events: `{'pool': 0, 'server': 0}`
- Queue depth percentiles: `{'p50': 1.0, 'p95': 1.0, 'p99': 1.0}`
- Restart latency percentiles: `{'p50': 0.0, 'p95': 0.0, 'p99': 0.0}`

## Claim Verdicts

| Claim | Class | Status | Gate | Detail |
| --- | --- | --- | --- | --- |
| E1 | empirical | partially_validated | meets_gate | p50=0.0616ms p99=0.1405ms |
| E2 | empirical | partially_validated | meets_gate | median_mps=13739.5 |
| E3 | empirical | validated | meets_gate | boot_median=546.3ms |
| E4 | empirical | validated | meets_gate | ratio=1.000 checks=3/3 |
| E5 | empirical | not_validated | not_applicable | base=94.41MB slope=4.80KB/agent |
| E6 | empirical | not_validated | not_applicable | blocking_factor=0.31 |
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

- `bridge_suite`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/bridge_suite.json`
- `bridge_stress`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/bridge_stress.json`
- `memory_scaling`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/memory_scaling.json`
- `failure_recovery`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/failure_recovery.json`
- `scheduler_fairness`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/scheduler_fairness.json`
- `startup_overhead`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/startup_overhead.json`
- `architectural_evidence`: `docs/benchmarks/raw/whitepaper_validation_20260314T002805/rigorous_20260313T232805Z/architectural_evidence.json`

