#!/usr/bin/env python3
"""Run parallel experiments with different optimization variants."""

import asyncio
import json
from pathlib import Path

# Variants to test
VARIANTS = {
    "A": {
        "name": "Baseline (best so far)",
        "pool_size": 8,
        "max_in_flight": 64,
        "duration": 3.0,
        "iterations": 600,
    },
    "B": {
        "name": "Larger pool",
        "pool_size": 16,
        "max_in_flight": 128,
        "duration": 3.0,
        "iterations": 600,
    },
    "C": {
        "name": "Longer duration",
        "pool_size": 8,
        "max_in_flight": 64,
        "duration": 5.0,
        "iterations": 600,
    },
    "D": {
        "name": "More iterations",
        "pool_size": 8,
        "max_in_flight": 64,
        "duration": 3.0,
        "iterations": 1000,
    },
    "E": {
        "name": "Combined",
        "pool_size": 12,
        "max_in_flight": 96,
        "duration": 4.0,
        "iterations": 800,
    },
}

async def run_variant(variant_id, config, repo_root):
    """Run a single variant and return results."""
    output_file = f"/tmp/validation_{variant_id}.json"
    log_file = f".autoresearch/parallel/variant_{variant_id}.log"
    
    # Modify the script temporarily
    script_path = repo_root / "scripts" / "validate_whitepaper_claims.py"
    original_content = script_path.read_text()
    
    # Apply config changes
    modified = original_content.replace(
        "pool_size=8,",
        f"pool_size={config['pool_size']},"
    ).replace(
        "max_in_flight_per_conn=64,",
        f"max_in_flight_per_conn={config['max_in_flight']},"
    ).replace(
        'bridge_throughput_seconds=3.0,',
        f"bridge_throughput_seconds={config['duration']},"
    ).replace(
        "bridge_iterations=600,",
        f"bridge_iterations={config['iterations']},"
    )
    
    script_path.write_text(modified)
    
    try:
        # Run validation
        proc = await asyncio.create_subprocess_exec(
            "uv", "run", "python", "scripts/validate_whitepaper_claims.py",
            "--profile", "rigorous", "--transports", "both",
            "--json-output", output_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_root
        )
        
        stdout, stderr = await proc.communicate()
        
        # Write log
        with open(log_file, "w") as f:
            f.write(f"Variant {variant_id}: {config['name']}\n")
            f.write(f"Config: {config}\n\n")
            f.write(stdout.decode())
            f.write(stderr.decode())
        
        # Extract metric
        if Path(output_file).exists():
            with open(output_file) as f:
                data = json.load(f)
            
            # Find E2 throughput
            for v in data.get('claim_verdicts', []):
                if v.get('claim_id') == 'E2':
                    detail = v.get('detail', '')
                    # Extract mps from detail string like "median_mps=44816.0"
                    import re
                    match = re.search(r'median_mps=([\d.]+)', detail)
                    mps = float(match.group(1)) if match else 0
                    
                    validated = sum(1 for v in data.get('claim_verdicts', []) 
                                   if v.get('status') == 'validated')
                    partial = sum(1 for v in data.get('claim_verdicts', []) 
                                 if v.get('status') == 'partially_validated')
                    
                    return {
                        'variant': variant_id,
                        'name': config['name'],
                        'mps': mps,
                        'metric': validated + 0.5 * partial,
                        'config': config,
                    }
        
        return {'variant': variant_id, 'name': config['name'], 'mps': 0, 'metric': 0, 'config': config, 'error': 'No results'}
        
    finally:
        # Restore original
        script_path.write_text(original_content)

async def main():
    repo_root = Path("/Users/arjun/Documents/Pyre")
    
    print("Running parallel experiments...")
    print(f"Testing {len(VARIANTS)} variants concurrently\n")
    
    # Run all variants in parallel
    tasks = [run_variant(vid, config, repo_root) for vid, config in VARIANTS.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Find best
    best = None
    for r in results:
        if isinstance(r, dict) and 'mps' in r:
            if best is None or r['mps'] > best['mps']:
                best = r
    
    print("\n" + "="*60)
    print("RESULTS:")
    print("="*60)
    
    for r in sorted(results, key=lambda x: x.get('mps', 0) if isinstance(x, dict) else 0, reverse=True):
        if isinstance(r, dict):
            status = "✓ BEST" if r == best else ""
            print(f"\nVariant {r['variant']}: {r['name']} {status}")
            print(f"  Throughput: {r['mps']:.0f} mps")
            print(f"  Metric: {r['metric']}")
            if 'error' in r:
                print(f"  Error: {r['error']}")
    
    print(f"\n{'='*60}")
    if best:
        print(f"BEST VARIANT: {best['variant']} - {best['name']}")
        print(f"Throughput: {best['mps']:.0f} mps (target: 50000)")
        print(f"Gap: {50000 - best['mps']:.0f} mps ({(best['mps']/50000)*100:.1f}% of target)")
    
    return 0

if __name__ == "__main__":
    asyncio.run(main())
