"""
Tests for scripts/download_and_benchmark_timesfm.py's coverage-labeling logic.

Bug covered: the benchmark table compared every engine's interval coverage
against a hardcoded 95% target, even for TimesFM — whose quantile head only
exposes deciles (p10-p90, an 80% empirical interval declared via
fitted_params.actual_interval_pct), never a genuine 95% one. That mislabeled
TimesFM's coverage figures as if they were measured against the same standard
as Damped Holt / Naive Random Walk, understating them.

The script lives outside the `backend` package (it's a standalone CLI tool
under scripts/), so it's imported here by adding its directory to sys.path,
same technique the script itself uses for `backend`.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_and_benchmark_timesfm as bench  # noqa: E402
from backend.schemas.models import ForecastResponse  # noqa: E402


def _make_response(model_name: str, fitted_params=None, horizon: int = 10) -> ForecastResponse:
    return ForecastResponse(
        timestamps=[f"2024-01-{i:02d}" for i in range(1, horizon + 1)],
        values=[100.0] * horizon,
        lower_bound=[90.0] * horizon,
        upper_bound=[110.0] * horizon,
        model_name=model_name,
        is_fallback=False,
        fitted_params=fitted_params,
    )


def test_get_declared_interval_pct_reads_timesfm_actual_interval():
    """
    A TimesFM-shaped response with fitted_params.actual_interval_pct=80.0 must
    report 80.0 as its declared level — not the caller-supplied default (95.0),
    which is what the pre-fix code silently assumed for every engine.
    """
    tfm_res = _make_response(
        "timesfm-2.5-200m (cpu)",
        fitted_params={"requested_confidence_pct": 95.0, "actual_interval_pct": 80.0},
    )
    assert bench.get_declared_interval_pct(tfm_res, default=95.0) == 80.0
    # Must NOT silently fall back to the default when a real level is present.
    assert bench.get_declared_interval_pct(tfm_res, default=95.0) != 95.0


def test_get_declared_interval_pct_falls_back_for_holt():
    """
    Damped Holt serves a genuine interval at the requested confidence and never
    sets actual_interval_pct — get_declared_interval_pct must fall back to the
    caller's default (95.0) for it, not report None or crash.
    """
    holt_res = _make_response("damped-holt-mle", fitted_params={
        "alpha": 0.3, "beta": 0.1, "phi": 0.95, "sigma": 0.01
    })
    assert bench.get_declared_interval_pct(holt_res, default=95.0) == 95.0


def test_get_declared_interval_pct_handles_missing_fitted_params():
    """fitted_params=None (e.g. a raw dict-less engine) must not crash and must fall back."""
    res = _make_response("some-engine", fitted_params=None)
    assert bench.get_declared_interval_pct(res, default=95.0) == 95.0


def test_benchmark_uses_actual_interval_level():
    """
    format_coverage_label — the function run_precision_benchmark calls to build
    each table cell — must label TimesFM's coverage against its own declared
    80% level, not the hardcoded 95% used for every other engine. This is the
    core regression test for the bug: before the fix, every column's label
    said "Cob. 95%" regardless of which engine's response it described.
    """
    tfm_res = _make_response(
        "timesfm-2.5-200m (cpu)",
        fitted_params={"requested_confidence_pct": 95.0, "actual_interval_pct": 80.0},
    )
    label = bench.format_coverage_label(tfm_res, coverage_pct=91.2, default_pct=95.0)

    assert "80" in label, f"expected the real 80% level in the label, got: {label!r}"
    assert "95" not in label, f"must not claim 95% for a response that declared 80%, got: {label!r}"
    assert "91.2" in label

    # Holt-shaped response (no actual_interval_pct) must still show 95%, since
    # that IS the genuine level it serves.
    holt_res = _make_response("damped-holt-mle", fitted_params={"alpha": 0.3})
    holt_label = bench.format_coverage_label(holt_res, coverage_pct=100.0, default_pct=95.0)
    assert "95" in holt_label
    assert "100.0" in holt_label


def test_benchmark_calls_coverage_with_correct_level_not_hardcoded_95(monkeypatch):
    """
    End-to-end through run_precision_benchmark: mock a TimesFM-like engine whose
    forecast() reports actual_interval_pct=80.0, and verify the printed table row
    for TimesFM's coverage cell reflects 80%, never a hardcoded 95%, while Holt's
    row in the same run still correctly shows 95%.
    """
    import numpy as np
    from backend.schemas.models import TimeSeriesPoint

    printed_lines = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed_lines.append(" ".join(str(a) for a in args)))

    # Keep the benchmark fast and deterministic: shrink the synthetic series to
    # something small instead of running the full 512+60-point generator.
    def tiny_series():
        rng = np.random.default_rng(1)
        T, H = 40, 5
        vals = 100.0 + np.cumsum(rng.normal(0, 1, T + H))
        return {"Test Series": (vals[:T], vals[T:T + H])}

    monkeypatch.setattr(bench, "generate_benchmark_series", tiny_series)

    fake_tfm_engine = MagicMock()
    fake_tfm_engine._model = object()  # truthy sentinel so timesfm_available is True

    def fake_forecast(pts, horizon, confidence=0.95, freq="D"):
        return _make_response(
            "timesfm-2.5-200m (cpu)",
            fitted_params={"requested_confidence_pct": 95.0, "actual_interval_pct": 80.0},
            horizon=horizon,
        )

    fake_tfm_engine.forecast.side_effect = fake_forecast

    bench.run_precision_benchmark(real_tfm_engine=fake_tfm_engine)

    coverage_lines = [l for l in printed_lines if "Cobertura" in l or "Cob." in l]
    assert coverage_lines, "expected at least one coverage row to be printed"

    tfm_coverage_line = coverage_lines[0]
    assert "(80%)" in tfm_coverage_line, f"TimesFM's coverage cell must show its own 80% level: {tfm_coverage_line!r}"
    # The Holt cell in the SAME row must still show 95% — proves the fix is
    # per-engine, not a global change that broke Holt's correct labeling.
    assert "95%" in tfm_coverage_line, f"Holt's coverage cell in the same row must still show 95%: {tfm_coverage_line!r}"
