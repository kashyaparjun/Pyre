---
tag: whitepaper-claims-apr09
status: ready
created_at: 2026-04-09T00:00:00Z
goal: Fix failing whitepaper claims E5 and E6 to achieve validated status
scope: 
  - scripts/validate_whitepaper_claims.py
  - tests/test_whitepaper_validation.py
  - src/pyre_agents/**/*.py
read_only:
  - pyre-whitepaper.md
  - docs/benchmarks/*.md
metric: count_of_validated_claims
direction: higher
verify: |
  python scripts/validate_whitepaper_claims.py --profile rigorous --transports both --json-output /tmp/validation.json && 
  python -c "
import json
with open('/tmp/validation.json') as f:
    data = json.load(f)
validated = sum(1 for v in data.get('claim_verdicts', []) if v.get('status') == 'validated')
partial = sum(1 for v in data.get('claim_verdicts', []) if v.get('status') == 'partially_validated')
print(validated + 0.5 * partial)
"
guard: uv run pytest -q tests/test_whitepaper_validation.py
baseline: 6.0
max_iterations: 25
time_budget_seconds: 600
branch: autoresearch/whitepaper-claims-apr09
---

# Autoresearch Config: whitepaper-claims-apr09

## Goal

Ensure all empirical whitepaper claims achieve validated status by:
1. Enabling UDS transport measurements for E1 (bridge latency) and E2 (throughput)
2. Running with rigorous profile to validate E3 (startup time)

Current status: E5 and E6 are already fixed! E4, A1-A3 are already validated. Only E1, E2, and E3 need attention.

## Problem Analysis

Based on the latest quick validation run (2026-04-09):

**Great news**: E5 and E6 are now passing! The commit "Rebaseline E5 and harden rigorous benchmark validation" (dd19787) appears to have fixed the underlying issues.

**Current Status:**
- **E5** (Memory scaling): `partially_validated` (base=127.24MB, slope=3.41KB/agent) ✓
- **E6** (Scheduler fairness): `validated` (blocking_factor=166.93) ✓

**Remaining Issues to Address:**

**E1 & E2** (UDS Transport): Currently `insufficient_evidence` - these claims require UDS (Unix Domain Socket) transport measurements, but the quick run only used TCP.

**E3** (Startup time): Currently `partially_validated` (704ms) with quick profile. Requires rigorous profile for full validation since `required_profile: "rigorous"`.

## Scope

Files the agent CAN modify:
- `scripts/validate_whitepaper_claims.py` - The validation script and benchmarks
- `tests/test_whitepaper_validation.py` - Tests for validation logic
- `src/pyre_agents/**/*.py` - Core library files if needed

Files the agent must NOT modify (read-only context):
- `pyre-whitepaper.md` - The whitepaper claims themselves
- `docs/benchmarks/*.md` - Historical validation reports

## Metric

- **Name**: Weighted count of validated claims (validated = 1.0, partially_validated = 0.5)
- **Direction**: Higher is better
- **Extract command**: 
  ```bash
  python scripts/validate_whitepaper_claims.py --profile rigorous --transports both --json-output /tmp/validation.json && \
  python -c "import json; data=json.load(open('/tmp/validation.json')); validated=sum(1 for v in data.get('claim_verdicts',[]) if v.get('status')=='validated'); partial=sum(1 for v in data.get('claim_verdicts',[]) if v.get('status')=='partially_validated'); print(validated + 0.5 * partial)"
  ```

## Verification

```bash
python scripts/validate_whitepaper_claims.py --profile rigorous --transports both --json-output /tmp/validation.json && python -c "
import json
with open('/tmp/validation.json') as f:
    data = json.load(f)
validated = sum(1 for v in data.get('claim_verdicts', []) if v.get('status') == 'validated')
partial = sum(1 for v in data.get('claim_verdicts', []) if v.get('status') == 'partially_validated')
print(validated + 0.5 * partial)
"
```

## Guard (regression prevention)

```bash
uv run pytest -q tests/test_whitepaper_validation.py
```

## Constraints

1. **DO NOT** modify the whitepaper claims themselves (pyre-whitepaper.md) - the goal is to make the implementation match the claims
2. Keep all existing tests passing
3. Maintain backward compatibility
4. The scheduler fairness benchmark must accurately demonstrate Python's lack of preemption when CPU-bound work runs
5. Memory measurements should be accurate and reproducible
6. **Multiple updates per iteration allowed** - You can make multiple changes in a single iteration, not just one

## Baseline

- **Value**: 6.0 (5 validated + 2 partially validated out of 13 total claims)
- **Commit**: dd19787
- **Date**: 2026-04-09

## Current Status (Quick Profile)

Based on the latest quick validation run:

- **E1** (Bridge latency): `insufficient_evidence` - needs UDS transport
- **E2** (Throughput): `insufficient_evidence` - needs UDS transport  
- **E3** (Startup time): `partially_validated` (704ms, needs rigorous profile)
- **E4** (Restart semantics): `validated` ✓
- **E5** (Memory scaling): `partially_validated` (base=127.24MB, slope=3.41KB) ✓
- **E6** (Scheduler fairness): `validated` (blocking_factor=166.93) ✓
- **A1-A3**: All `validated` ✓
- **F1-F4**: `unsupported_in_scope` (expected - future features)

## Specific Fix Targets

### E1 & E2 (UDS Transport Required)

**Issue**: Claims require UDS transport measurements but quick validation only ran TCP.

**Fix**: Ensure validation runs with `--transports both` flag to include UDS benchmarks.

These claims specifically state "Unix domain socket" performance characteristics, so they need UDS measurements to be validated.

### E3 (Startup Overhead)

**Current**: boot_median=704.1ms (partial with quick profile)  
**Target**: Needs rigorous profile for full validation

The E3 claim requires rigorous profile because `required_profile: "rigorous"` in its definition.

## Notes

The previous validation report (20260314T002805) showed E5 and E6 as failing, but the "Rebaseline E5 and harden rigorous benchmark validation" commit has since fixed those issues. The current codebase is in much better shape!

**To run full validation**:
```bash
uv run python scripts/validate_whitepaper_claims.py --profile rigorous --transports both --json-output /tmp/validation.json
```

**Quick validation** (for faster iteration):
```bash
uv run python scripts/validate_whitepaper_claims.py --profile quick --transports tcp --json-output /tmp/validation_quick.json
```

The "insufficient_evidence" status for E1/E2 in quick mode is expected - they simply weren't measured with UDS transport.

**Current weighted score calculation**:
- validated: 5 (counted as 1.0 each)
- partially_validated: 2 (counted as 0.5 each) 
- Total: 5 + 2×0.5 = 6.0
