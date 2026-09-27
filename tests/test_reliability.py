"""
"No confiable" mark (item 2.6). Synthetic series generated only for these
tests: a quiet random walk that ends in a two-step level jump (+25%, then
x3.3), like UNRATE in March-April 2020, which makes damped Holt hand the jump
to the trend and extrapolate it.
"""
import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import InterpretationContext, TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import FREDDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine
from backend.services.llm_router import MockLLMClient
from backend.services.reliability import FLAG_X, explosion_index, max_historical_move, reliability_warning

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

client = TestClient(app)


def _quiet(n=300, seed=7):
    rng = np.random.default_rng(seed)
    return list(4 * np.exp(np.cumsum(rng.normal(0, 0.02, n))))


def _jump(n=300):
    v = _quiet(n)
    return v + [v[-1] * 1.25, v[-1] * 1.25 * 3.3]


def _pts(values):
    return [{"timestamp": f"{2000 + i // 12:04d}-{i % 12 + 1:02d}-01", "value": float(x)} for i, x in enumerate(values)]


# ---- the index ----

def test_index_compares_with_the_largest_move_ever_seen():
    hist = [100, 110, 100, 121]            # largest 1-step move: log(1.21)
    assert max_historical_move(hist, 1, True) == pytest.approx(np.log(1.21))
    assert explosion_index(hist, 121 * 1.21, 1) == pytest.approx(1.0)
    assert explosion_index(hist, 121 * 1.21 ** 3, 1) == pytest.approx(3.0)


def test_index_is_none_for_a_series_that_never_moved():
    assert explosion_index([5, 5, 5, 5], 6, 2) is None


def test_non_positive_series_use_absolute_differences():
    hist = [-1.0, 1.0, -1.0, 1.0]           # largest 1-step move: 2
    assert explosion_index(hist, 5.0, 1) == pytest.approx(2.0)


def test_no_warning_for_a_plausible_forecast():
    hist = _quiet()
    assert reliability_warning(hist, [hist[-1] * 1.01] * 12, "12 meses") is None


# ---- the API: marked, never changed ----

def test_holt_explosion_after_a_jump_is_marked_and_not_trimmed():
    pts = _pts(_jump())
    body = client.post("/api/forecast", json={"points": pts, "horizon": 12}).json()
    direct = DampedHoltForecastEngine().forecast(
        [TimeSeriesPoint(**p) for p in pts], horizon=12, confidence=0.95, freq="M")
    assert body["values"] == direct.values, "the mark must not change any number"
    assert body["values"][-1] > 1e5  # the explosion itself is still there
    assert body["reliable"] is False
    assert "no confiable" in body["reliability_warning"].lower()
    assert "12 meses" in body["reliability_warning"]


def test_quiet_series_is_reliable():
    body = client.post("/api/forecast", json={"points": _pts(_quiet()), "horizon": 12}).json()
    assert body["reliable"] is True and body["reliability_warning"] is None


def test_backtest_carries_the_mark_and_the_warning(monkeypatch):
    values = _jump() + list(np.full(20, _jump()[-1] * 0.8))
    pts = [TimeSeriesPoint(**p) for p in _pts(values)]
    series = TimeSeriesData(id="JUMPY", name="j", type="macro", unit="%", points=pts, source="live")
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda self, sid: series)
    cutoff = pts[301].timestamp  # training ends WITH the jump
    res = BacktestEngine.run_backtest("JUMPY", cutoff, horizon=12, is_macro=True,
                                      engine_override=DampedHoltForecastEngine())
    assert res.reliable is False
    assert any("no confiable" in w.lower() for w in res.warnings)


def test_copilot_says_it_instead_of_narrating_it():
    warning = reliability_warning(_jump(), [5e6] * 12, "12 meses")
    ctx = InterpretationContext(
        thesis="t", active_series_id="UNRATE", last_price=7.5, projected_target=5e6, horizon=12,
        frequency="monthly", lower_bound=1.0, upper_bound=1e7, cagr=1e9, reliability_warning=warning,
    )
    resp = asyncio.run(MockLLMClient().interpret_situation(ctx))
    assert "no confiable" in resp.what_data_says.lower()
    assert "expansión alcista" not in resp.what_data_says


def test_threshold_is_the_pre_registered_one():
    assert FLAG_X == 2.0


# ---- the experimental variants of the diagnosis script ----

def test_robust_variant_without_clipping_is_the_production_engine():
    from holt_explosion import make_robust_holt
    pts = [TimeSeriesPoint(**p) for p in _pts(_jump())]
    prod = DampedHoltForecastEngine().forecast(pts, horizon=12, confidence=0.8, freq="M")
    same = make_robust_holt("none")().forecast(pts, horizon=12, confidence=0.8, freq="M")
    assert (same.values, same.lower_bound, same.upper_bound) == (prod.values, prod.lower_bound, prod.upper_bound)


def test_variant_c_keeps_the_jump_in_the_level_without_exploding():
    from holt_explosion import make_robust_holt
    v = _jump()
    pts = [TimeSeriesPoint(**p) for p in _pts(v)]
    c = make_robust_holt("trend")().forecast(pts, horizon=12, confidence=0.8, freq="M")
    assert explosion_index(v, c.values[-1], 12) <= FLAG_X
    assert c.values[-1] > v[-3]  # it didn't ignore the jump either
