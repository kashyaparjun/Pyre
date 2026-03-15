from __future__ import annotations

import importlib.util
import json
import sys
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
                    "base_runtime_bytes_estimate": 40 * 1024 * 1024,
                    "absolute_base_runtime_bytes": 40 * 1024 * 1024,
                    "idle_beam_rss_bytes": 20 * 1024 * 1024,
                    "bridge_over_idle_beam_bytes": 20 * 1024 * 1024,
                }
            }
        },
        profile="rigorous",
        require_rigorous_for_validated=True,
    )

    assert verdict.status == "validated"
    assert "delta_vs_idle_beam=20.00MB" in verdict.detail


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
