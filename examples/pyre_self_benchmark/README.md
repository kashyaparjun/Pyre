# Pyre Self Benchmark Example

This example benchmarks Pyre by running 100 simulated AI-like agents with no external AI calls.

## What it does

- Spawns 100 agents (default)
- Simulates AI latency using `asyncio.sleep`
- Performs inter-agent communication (`call` + `cast`)
- Exercises message passing under concurrency
- Injects failures into 10% of agents and measures restart/recovery
- Reports latency percentiles (p50/p90/p95/p99), throughput, CPU, and RAM usage

## Run

From the repo root:

```bash
uv run python examples/pyre_self_benchmark/benchmark.py
```

Custom run:

```bash
uv run python examples/pyre_self_benchmark/benchmark.py \
  --agents 100 \
  --workers 30 \
  --attempts 8000 \
  --failure-rate 0.10 \
  --crash-probability 0.02 \
  --json-output docs/benchmarks/pyre_self_benchmark_results.json
```

## Output

The script prints JSON with:

- `latency`: p50/p90/p95/p99 + mean/min/max (ms)
- `workload`: throughput, successes/failures, message counts
- `recovery`: how many of the failing agents restarted
- `resources`: CPU usage and peak RAM estimate
- `config`: benchmark parameters used

## Notes

- CPU% is process CPU usage sampled over wall time, so values above 100% are possible on multi-core systems.
- RAM peak uses `ru_maxrss` from `resource.getrusage`; units vary by OS and are normalized to a bytes estimate.
