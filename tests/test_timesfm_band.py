"""
TimesFM band and interval levels (item 3.0e).

TimesFM 2.5 returns quantile_forecast with columns [mean, q_1, ..., q_n] where
q = config.quantiles. The engine used to read column 0 (the mean) as p10, so
the band was [mean, p90]. These tests use a SIMULATED model with a known
output whose mean is deliberately above p90: reading column 0 as the lower
bound would put it above the upper one.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.schemas.models import ForecastResponse, TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import MarketDataFetcher
from backend.services.forecast_engine import (
    BaseForecastEngine,
    DampedHoltForecastEngine,
    TimesFMForecastEngine,
)

H = 5
STANDARD_QUANTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


class FakeTimesFMModel:
    """Known output: q-quantile = 100 + 100*(q - 0.5) (p10=60, p50=100,
    p90=140); point = p50; the MEAN column is 999, far above p90."""

    def __init__(self, quantiles=STANDARD_QUANTILES, extra_columns=0):
        self.model = SimpleNamespace(config=SimpleNamespace(quantiles=list(quantiles)))
        self._quantiles = list(quantiles)
        self._extra = extra_columns

    def forecast(self, horizon, inputs):
        cols = [np.full(horizon, 999.0)]  # column 0: the mean
        cols += [np.full(horizon, 100 + 100 * (q - 0.5)) for q in self._quantiles]
        cols += [np.full(horizon, -1.0)] * self._extra
        quantile_forecast = np.stack(cols, axis=-1)[None, :, :]
        point = np.full((1, horizon), 100.0)
        return point, quantile_forecast


@pytest.fixture
def fake_timesfm():
    previous = TimesFMForecastEngine._instance

    def build(model):
        engine = object.__new__(TimesFMForecastEngine)
        engine._initialized = True
        engine._fallback_engine = DampedHoltForecastEngine()
        engine.device = "cpu"
        engine._model = model
        TimesFMForecastEngine._instance = engine
        return engine

    yield build
    TimesFMForecastEngine._instance = previous


def _points(n=60):
    return [TimeSeriesPoint(timestamp=f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", value=100.0 + i * 0.1) for i in range(n)]


def test_band_is_p10_p90_and_contains_the_point(fake_timesfm):
    res = fake_timesfm(FakeTimesFMModel()).forecast(_points(), horizon=H, confidence=0.95)

    assert not res.is_fallback
    assert res.lower_bound == [60.0] * H   # p10, not the mean (999)
    assert res.upper_bound == [140.0] * H  # p90
    assert all(lo <= v <= hi for lo, v, hi in zip(res.lower_bound, res.values, res.upper_bound))
    assert res.interval_level == pytest.approx(0.80)  # declared, whatever was requested
    assert res.fitted_params["actual_interval_pct"] == 80.0


def test_quantile_columns_are_found_by_value_not_position(fake_timesfm):
    """If the config listed its quantiles in another order, the band must still
    be p10-p90 (not "second and last column")."""
    shuffled = [0.9, 0.5, 0.1, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6]
    res = fake_timesfm(FakeTimesFMModel(quantiles=shuffled)).forecast(_points(), horizon=H, confidence=0.95)

    assert res.lower_bound == [60.0] * H
    assert res.upper_bound == [140.0] * H


def test_unexpected_quantile_layout_falls_back_explicitly(fake_timesfm):
    res = fake_timesfm(FakeTimesFMModel(extra_columns=1)).forecast(_points(), horizon=H, confidence=0.95)

    assert res.is_fallback
    assert res.fallback_kind == "inference_error"
    assert "Formato de cuantiles inesperado" in res.fallback_reason
    assert res.interval_level == pytest.approx(0.95)  # Holt answered, at the requested level


def test_holt_and_holt_winters_declare_the_requested_level():
    res = DampedHoltForecastEngine().forecast(_points(), horizon=H, confidence=0.80)
    assert res.interval_level == pytest.approx(0.80)


class _FixedBandEngine(BaseForecastEngine):
    """Declares an 80% interval that never contains anything (coverage 0%)."""

    def forecast(self, points, horizon=30, confidence=0.95, freq="D"):
        last = points[-1].value
        return ForecastResponse(
            timestamps=[f"t{i}" for i in range(horizon)], values=[last] * horizon,
            lower_bound=[-2.0] * horizon, upper_bound=[-1.0] * horizon,
            model_name="fixed-band", interval_level=0.80,
        )


def test_backtest_judges_coverage_against_the_delivered_level(monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "nvda_daily.json"
    pts = [TimeSeriesPoint(**p) for p in json.loads(fixture.read_text())]
    series = TimeSeriesData(id="NVDA", name="NVIDIA", type="equity", unit="USD", points=pts, source="live")
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *a, **kw: series)

    res = BacktestEngine.run_backtest(
        series_id="NVDA", cutoff_date=pts[180].timestamp, horizon=30, confidence=0.95,
        engine_override=_FixedBandEngine(),
    )

    assert res.interval_level == pytest.approx(0.80)
    warning = next(w for w in res.warnings if w.startswith("Subcobertura"))
    assert "(80%)" in warning and "95%" not in warning
