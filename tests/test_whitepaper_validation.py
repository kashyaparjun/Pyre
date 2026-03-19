from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any


def _load_validation_module() -> Any:
    repo_root = Path(__file__).resolve().parents[1]
    target = repo_root / "scripts" / "validate_whitepaper_claims.py"
    spec = importlib.util.spec_from_file_location("validate_whitepaper_claims_for_tests", target)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_apply_gating_requires_rigorous_for_validated() -> None:
    module = _load_validation_module()

    status, gate = module.apply_gating(
        base_status="validated",
        profile="quick",
        require_rigorous=True,
        required_profile="rigorous",
    )

    assert status == "partially_validated"
    assert gate == "provisional_quick"


def test_claim_transport_source_requires_uds() -> None:
    module = _load_validation_module()
    claims = module.claim_definitions()
    e1 = next(item for item in claims if item.claim_id == "E1")

    source_none = module.claim_transport_source(e1, {"summary": {"tcp": {}}})
    source_uds = module.claim_transport_source(e1, {"summary": {"uds": {}}})

    assert source_none == "none"
    assert source_uds == "uds"


def test_evaluate_claim_reports_insufficient_evidence_without_uds() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E1")

    verdict = module.evaluate_claim(
        claim,
        suites={"bridge_suite": {"summary": {"tcp": {}}}},
        profile="rigorous",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "insufficient_evidence"
    assert "required transport" in verdict.detail


def test_report_contains_new_schema_fields(tmp_path: Path) -> None:
    module = _load_validation_module()

    report = {
        "benchmark": "whitepaper-claim-validation",
        "generated_at_utc": "2026-03-13T00:00:00+00:00",
        "profile": "quick",
        "claim_scope": "all",
        "require_rigorous_for_validated": True,
        "transports": "both",
        "publication_ready": False,
        "environment": {
            "python": "3.12.7",
            "platform": "Darwin",
            "mix_version": "mix",
            "erlang_version": "28",
        },
        "controls": {},
        "claims": [
            {
                "claim_id": "E1",
                "class": "empirical",
                "evidence_type": "benchmark",
                "required_profile": "rigorous",
                "transport_required": "uds",
            }
        ],
        "claim_verdicts": [
            {
                "claim_id": "E1",
                "status": "insufficient_evidence",
                "detail": "required transport 'uds' not measured",
                "class": "empirical",
                "evidence_type": "benchmark",
                "gate_status": "not_applicable",
                "required_profile": "rigorous",
                "transport_source": "none",
                "blockers": ["missing transport measurement: uds"],
            }
        ],
        "coverage_summary": {
            "by_class": {"empirical": 1},
            "by_status": {"insufficient_evidence": 1},
        },
        "transport_concurrency_profile": {},
        "backpressure_events": {},
        "queue_depth_percentiles": {},
        "restart_latency_percentiles": {},
        "raw_artifacts": {},
        "suite_summary": {},
    }

    out = tmp_path / "report.json"
    out.write_text(json.dumps(report), encoding="utf-8")

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert "coverage_summary" in loaded
    assert "publication_ready" in loaded
    verdict = loaded["claim_verdicts"][0]
    assert "gate_status" in verdict
    assert "transport_source" in verdict
    assert "blockers" in verdict

    rendered = module.render_markdown(report)
    assert "Coverage Summary" in rendered


def test_start_elixir_bridge_mix_waits_for_both_endpoints(monkeypatch: Any) -> None:
    module = _load_validation_module()
    calls: list[tuple[str, object, float]] = []

    async def fake_wait_for_tcp_ready(port: int, timeout_s: float) -> None:
        calls.append(("tcp", port, timeout_s))

    async def fake_wait_for_uds_ready(path: str, timeout_s: float) -> None:
        calls.append(("uds", path, timeout_s))

    class FakeStdout:
        def __init__(self) -> None:
            self._sent = False

        async def readline(self) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return b"PYRE_BRIDGE_PORT=4100 PYRE_BRIDGE_UDS_PATH=/tmp/pyre_test.sock\n"

    fake_process = types.SimpleNamespace(stdout=FakeStdout(), returncode=None)

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> object:
        return fake_process

    monkeypatch.setattr(module, "_wait_for_tcp_ready", fake_wait_for_tcp_ready)
    monkeypatch.setattr(module, "_wait_for_uds_ready", fake_wait_for_uds_ready)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    bridge = module.asyncio.run(
        module._start_elixir_bridge_mix(
            Path("/tmp"),
            transport_mode="both",
            perf_mode=False,
        )
    )

    assert bridge.port == 4100
    assert bridge.uds_path == "/tmp/pyre_test.sock"
    assert ("tcp", 4100, 10.0) in calls
    assert ("uds", "/tmp/pyre_test.sock", 10.0) in calls


def test_connect_pool_uds_retries_then_succeeds(monkeypatch: Any) -> None:
    module = _load_validation_module()
    attempts = {"count": 0}

    async def fake_connect_unix(
        path: str,
        *,
        pool_size: int,
        max_in_flight_per_conn: int,
    ) -> object:
        _ = (path, pool_size, max_in_flight_per_conn)
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionRefusedError("not ready")
        return object()

    monkeypatch.setattr(module.BridgeTransportPool, "connect_unix", fake_connect_unix)

    bridge = module.BridgeProcessInfo(
        process=types.SimpleNamespace(returncode=0),
        port=None,
        uds_path="/tmp/retry.sock",
        startup_mode="mix",
    )
    pool = module.asyncio.run(
        module._connect_pool(
            "uds",
            bridge,
            pool_size=8,
            max_in_flight_per_conn=64,
        )
    )

    assert pool is not None
    assert attempts["count"] == 3


def test_run_bridge_stress_suite_uses_selected_transport(monkeypatch: Any) -> None:
    module = _load_validation_module()
    seen: list[str] = []

    async def fake_microbench(
        repo_root: Path,
        *,
        transport: str,
        iterations: int,
        throughput_seconds: float,
        in_flight_depths: list[int],
    ) -> dict[str, object]:
        _ = (repo_root, iterations, throughput_seconds, in_flight_depths)
        seen.append(transport)
        return {
            "transport_results": [
                {
                    "transport": transport,
                    "payload_results": [
                        {
                            "payload_label": "small",
                            "concurrency_sweep": [
                                {
                                    "in_flight_depth": 1,
                                    "messages_per_second": 1000.0,
                                    "p99_ms": 0.3,
                                    "p50_ms": 0.1,
                                    "p95_ms": 0.2,
                                    "busy_errors": 0,
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "run_elixir_transport_microbench", fake_microbench)
    config = module.ProfileConfig(
        name="quick",
        warmup_runs=1,
        measured_runs=1,
        bridge_iterations=100,
        bridge_throughput_seconds=1.0,
        ab_agents=1,
        ab_workers=1,
        ab_attempts=1,
        memory_counts=[100],
        startup_runs=1,
    )

    tcp_result = module.asyncio.run(module.run_bridge_stress_suite(Path("."), config, "tcp"))
    both_result = module.asyncio.run(module.run_bridge_stress_suite(Path("."), config, "both"))

    assert seen == ["tcp", "uds"]
    assert tcp_result["transport"] == "tcp"
    assert both_result["transport"] == "uds"


def test_e1_accepts_faster_than_claimed_lower_bound() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E1")

    verdict = module.evaluate_claim(
        claim,
        suites={
            "bridge_suite": {
                "summary": {
                    "uds": {
                        "small_p50_ms": {"median": 0.06},
                        "small_p99_ms": {"median": 0.20},
                        "small_messages_per_second": {"median": 20000.0},
                    }
                }
            }
        },
        profile="rigorous",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "validated"


def test_e3_accepts_faster_startup_than_lower_bound() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E3")

    verdict = module.evaluate_claim(
        claim,
        suites={"startup_overhead": {"boot_ms": {"median": 420.0}}},
        profile="rigorous",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "validated"


def test_e5_reports_absolute_and_idle_beam_delta_in_detail() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E5")

    verdict = module.evaluate_claim(
        claim,
        suites={
            "memory_scaling": {
                "elixir_bridge": {
                    "fit": {"bytes_per_agent": 3.5 * 1024},
                    "base_runtime_bytes_estimate": 143 * 1024 * 1024,
                    "absolute_base_runtime_bytes": 143 * 1024 * 1024,
                    "idle_beam_rss_bytes": 123 * 1024 * 1024,
                    "bridge_over_idle_beam_bytes": 20 * 1024 * 1024,
                }
            }
        },
        profile="rigorous",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "validated"
    assert "delta_vs_idle_beam=20.00MB" in verdict.detail


def test_e5_memory_threshold_transitions() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E5")

    cases = [
        (143.0, 2.9, "validated"),
        (95.0, 2.9, "partially_validated"),
        (79.0, 2.9, "not_validated"),
        (143.0, 10.1, "not_validated"),
    ]
    for base_mb, slope_kb, expected in cases:
        verdict = module.evaluate_claim(
            claim,
            suites={
                "memory_scaling": {
                    "elixir_bridge": {
                        "fit": {"bytes_per_agent": slope_kb * 1024},
                        "base_runtime_bytes_estimate": base_mb * 1024 * 1024,
                        "absolute_base_runtime_bytes": base_mb * 1024 * 1024,
                    }
                }
            },
            profile="rigorous",
            require_rigorous_for_validated=True,
        )
        assert verdict.status == expected


def test_e6_uses_timer_drift_metric_when_available() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E6")

    verdict = module.evaluate_claim(
        claim,
        suites={
            "scheduler_fairness": {
                "python_no_preemption_blocking_factor_p99": 0.2,
                "no_preemption_timer_drift": {
                    "blocking_factor_p99": 2.4,
                    "blocked_tick_ratio": 0.33,
                },
                "modes": {
                    "serial_python_worker": {"blocking_factor_p99": 0.9},
                    "pooled_workers": {"blocking_factor_p99": 0.8},
                },
            }
        },
        profile="quick",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "validated"


def test_e6_timer_drift_verdict_threshold_transitions() -> None:
    module = _load_validation_module()
    claim = next(item for item in module.claim_definitions() if item.claim_id == "E6")

    cases = [
        (2.01, "validated"),
        (1.31, "partially_validated"),
        (1.29, "not_validated"),
    ]
    for factor, expected in cases:
        verdict = module.evaluate_claim(
            claim,
            suites={
                "scheduler_fairness": {
                    "no_preemption_timer_drift": {"blocking_factor_p99": factor},
                    "modes": {"serial_python_worker": {"blocking_factor_p99": 0.1}},
                }
            },
            profile="quick",
            require_rigorous_for_validated=True,
        )
        assert verdict.status == expected
