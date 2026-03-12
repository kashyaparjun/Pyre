# Phase 1 Bridge Benchmark Baseline

Date: 2026-03-12

## Command

```bash
uv run python scripts/bench_bridge.py --iterations 800 --throughput-seconds 1.5 --json-output docs/benchmarks/phase1_results.json
```

Raw machine-readable output:

- `docs/benchmarks/phase1_results.json`

## Latency (roundtrip)

| Payload | Target size | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| small | 512 bytes | 0.086000 | 0.183167 | 0.242083 | 0.103772 |
| medium | 10,240 bytes | 0.093417 | 0.175625 | 0.228041 | 0.104951 |
| large | 1,048,576 bytes | 2.494042 | 3.093375 | 3.297333 | 2.505658 |

## Throughput

| Payload | Target size | Duration (s) | Roundtrips | Messages/sec |
| --- | ---: | ---: | ---: | ---: |
| small | 512 bytes | 1.5 | 15,021 | 10,014.0 |
| medium | 10,240 bytes | 1.5 | 12,858 | 8,572.0 |
| large | 1,048,576 bytes | 1.5 | 567 | 378.0 |

## Acceptance check snapshot

- `p99_under_1ms_for_small_and_medium`: `true`
