"""
Usage example for Pyre with configurable batching.
"""

from pyre_agents import Pyre
from pyre_agents.bridge.batching import BatchingConfig, HIGH_THROUGHPUT, LOW_LATENCY, BALANCED


async def example_high_throughput():
    """High-throughput scenario - enable batching."""

    # For benchmarks, data pipelines, bulk processing
    system = await Pyre.start(
        batching=BatchingConfig.high_throughput()
        # Or: batching=HIGH_THROUGHPUT
    )

    # Connect with batching enabled
    bridge = await system.connect_bridge(
        host="localhost", port=9999, batching=BatchingConfig.high_throughput()
    )

    # Spawn agents - requests will be batched automatically
    agents = []
    for i in range(100):
        agent = await bridge.spawn_agent(f"worker-{i}")
        agents.append(agent)

    # Process data in parallel
    # Batching improves throughput by 30-40%
    # Latency increases by 20-50% but that's acceptable for bulk work
    results = await asyncio.gather(*[agent.call("process", {"data": item}) for item in data_batch])

    await system.stop()


async def example_low_latency():
    """Low-latency scenario - disable batching."""

    # For real-time APIs, user-facing operations
    system = await Pyre.start(
        batching=BatchingConfig.low_latency()
        # Or: batching=LOW_LATENCY
    )

    bridge = await system.connect_bridge(
        uds_path="/tmp/pyre.sock", batching=BatchingConfig.low_latency()
    )

    # Single user request - no batching
    # Fastest possible response time
    result = await bridge.agent("api-handler").call(
        "handle_request", {"user_id": user_id, "action": action}
    )

    await system.stop()


async def example_mixed_workload():
    """Mixed workload - use balanced config or toggle per connection."""

    system = await Pyre.start(batching=BatchingConfig.balanced())

    # API connection - low latency
    api_bridge = await system.connect_bridge(
        host="localhost", port=9999, batching=BatchingConfig.low_latency()
    )

    # Data pipeline connection - high throughput
    pipeline_bridge = await system.connect_bridge(
        host="localhost", port=9999, batching=BatchingConfig.high_throughput()
    )

    # Use api_bridge for user requests
    user_result = await api_bridge.agent("user-api").call("get_profile", {})

    # Use pipeline_bridge for bulk processing
    processed = await pipeline_bridge.agent("processor").call(
        "batch_process", {"items": large_dataset}
    )

    await system.stop()


async def example_custom_config():
    """Custom batching configuration."""

    config = BatchingConfig(
        enabled=True,
        batch_size=5,  # Small batches
        max_wait_ms=1.0,  # Short timeout
        min_batch_size=2,  # Flush if >=2 requests
    )

    system = await Pyre.start(batching=config)
    # ...


# Preset configurations:
#
# HIGH_THROUGHPUT - Max throughput for benchmarks/data pipelines
#   - batch_size: 20
#   - max_wait_ms: 5.0
#   - min_batch_size: 10
#   - Throughput gain: +35-40%
#   - Latency cost: +20-50%
#
# LOW_LATENCY - Min latency for real-time APIs
#   - batching disabled
#   - Fastest response time
#
# BALANCED - Good for mixed workloads
#   - batch_size: 10
#   - max_wait_ms: 2.0
#   - min_batch_size: 1
#   - Throughput gain: +25-30%
#   - Latency cost: +10-20%
