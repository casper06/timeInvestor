"""
3.0f: seasonal plan B, evidence-backed catalog, and seasonal auto-discovery.
All series are SYNTHETIC with known structure, generated only for these tests.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from backend.config import settings
from backend.database.models import EngineDecisionModel
from backend.schemas.models import TimeSeriesPoint
from backend.services import auto_discovery
from backend.services.auto_discovery import AutoDiscoveryEngine
from backend.services.engine_selector import SEASONAL_FRED_CATALOG, EngineSelector
from backend.services.forecast_engine import (
    DampedHoltForecastEngine,
    HoltWintersForecastEngine,
    TimesFMForecastEngine,
)
from tests.test_auto_discovery import _mock_mini_backtest, db_session  # noqa: F401  (fixture)


def _monthly(values, start_year=2000):
    return [TimeSeriesPoint(timestamp=f"{start_year + i // 12:04d}-{i % 12 + 1:02d}-01", value=float(v))
            for i, v in enumerate(values)]


def seasonal(n=240, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return 100 * np.exp(0.002 * t) * (1 + 0.10 * np.sin(2 * np.pi * t / 12)) * np.exp(rng.normal(0, 0.01, n))


def random_walk(n=240, seed=3):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))


class _FakeTimesFM:
    """Loaded-model stand-in: quantiles [mean, p10..p90], point = p50."""
    model = SimpleNamespace(config=SimpleNamespace(quantiles=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]))

    def forecast(self, horizon, inputs):
        last = float(inputs[0][-1])
        cols = [np.full(horizon, last)] + [np.full(horizon, last * (1 + (q - 0.5) / 5)) for q in self.model.config.quantiles]
        return np.full((1, horizon), last), np.stack(cols, axis=-1)[None]


@pytest.fixture
def timesfm_running(monkeypatch):
    previous = TimesFMForecastEngine._instance
    engine = object.__new__(TimesFMForecastEngine)
    engine._initialized, engine.device, engine._model = True, "cpu", _FakeTimesFM()
    engine._fallback_engine = DampedHoltForecastEngine()
    TimesFMForecastEngine._instance = engine
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", True)
    yield engine
    TimesFMForecastEngine._instance = previous


# --- plan B -----------------------------------------------------------------

def test_plan_b_is_holt_winters_for_seasonal_series(monkeypatch):
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)
    res = EngineSelector.select(_monthly(seasonal()), series_id="IPG2211A2N", series_type="macro", horizon=12, freq="M")

    assert res.model_name.startswith("holt-winters")
    assert res.is_fallback is True
    assert "USE_REAL_TIMESFM=false" in res.engine_selection_reason
    assert "Plan B estacional: Holt-Winters" in res.engine_selection_reason


def test_plan_b_is_holt_for_non_seasonal_series(monkeypatch):
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)
    res = EngineSelector.select(_monthly(random_walk()), series_id="IPG2211A2N", series_type="macro", horizon=12, freq="M")

    assert res.model_name == "damped-holt-mle"
    assert "Plan B: Holt, serie no estacional" in res.engine_selection_reason


def test_holt_winters_failure_falls_back_to_holt_with_reason(monkeypatch):
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)

    def boom(self, *a, **kw):
        raise RuntimeError("ajuste MLE no convergió")

    monkeypatch.setattr(HoltWintersForecastEngine, "forecast", boom)
    res = EngineSelector.select(_monthly(seasonal()), series_id="IPG2211A2N", series_type="macro", horizon=12, freq="M")

    assert res.model_name == "damped-holt-mle"
    assert res.is_fallback is True
    assert "Holt-Winters no pudo correr (ajuste MLE no convergió)" in res.engine_selection_reason


def test_plan_b_keeps_timesfm_failure_cause(monkeypatch, timesfm_running):
    pts = _monthly(seasonal())
    res = EngineSelector.select(pts, series_id="IPG2211A2N", series_type="macro", horizon=200, freq="M")  # > 128

    assert res.model_name.startswith("holt-winters")
    assert res.fallback_kind == "horizon_exceeded"
    assert "TimesFM no corrió" in res.engine_selection_reason


# --- catalog ------------------------------------------------------------------

@pytest.mark.parametrize("sid,expected", [
    ("IPG2211A2N", "evidencia firme"),
    ("HOUSTNSA", "evidencia probable: le ganó a Holt-Winters en 18 de 24 cutoffs (p=0,023"),
    ("RSAFSNA", "evidencia probable, frágil"),
])
def test_catalog_reason_states_evidence_strength(timesfm_running, sid, expected):
    res = EngineSelector.select(_monthly(seasonal()), series_id=sid, series_type="macro", horizon=12, freq="M")
    assert res.model_name.startswith("timesfm")
    assert expected in res.engine_selection_reason
    assert "docs/results/seasonal_benchmark_2026-09-26.md" in res.engine_selection_reason


def test_catalog_routes_mrtssm_to_holt_winters(timesfm_running):
    assert SEASONAL_FRED_CATALOG["MRTSSM4451USN"].engine == "holt_winters"
    res = EngineSelector.select(_monthly(seasonal()), series_id="MRTSSM4451USN", series_type="macro", horizon=12, freq="M")
    assert res.model_name.startswith("holt-winters")
    assert "Holt-Winters por catálogo" in res.engine_selection_reason
    assert "p=0,152" in res.engine_selection_reason


# --- auto-discovery -------------------------------------------------------------

def test_seasonal_series_is_compared_against_holt_winters(db_session, monkeypatch):  # noqa: F811
    _, calls = _mock_mini_backtest(monkeypatch, tfm_available=True, seasonal=True, mase_holt=0.9, mase_tfm=1.1)
    decision = AutoDiscoveryEngine.decide(db_session, "SEASONALX", n_points=500)

    assert set(calls["baselines"]) == {"HoltWintersForecastEngine"}
    assert decision.baseline_engine == "holt_winters" and decision.metric == "mase_seasonal"
    assert decision.engine_choice == "holt_winters"


def test_non_seasonal_series_keeps_holt_baseline(db_session, monkeypatch):  # noqa: F811
    _, calls = _mock_mini_backtest(monkeypatch, tfm_available=True, seasonal=False)
    decision = AutoDiscoveryEngine.decide(db_session, "PLAINX", n_points=500)

    assert set(calls["baselines"]) == {"DampedHoltForecastEngine"}
    assert decision.baseline_engine == "holt" and decision.metric == "mase"


def test_old_seasonal_decision_is_reevaluated_against_holt_winters(db_session, monkeypatch):  # noqa: F811
    """A v2 decision (TimesFM vs plain Holt) for a seasonal series is stale in
    v3 and gets re-evaluated with Holt-Winters as the baseline."""
    _, calls = _mock_mini_backtest(monkeypatch, tfm_available=True, seasonal=True, mase_holt=0.9, mase_tfm=1.1)
    db_session.add(EngineDecisionModel(
        series_id="OLDSEAS", engine_choice="timesfm", mase_holt=2.0, mase_timesfm=1.1,
        n_points_at_evaluation=500, criteria_version=2,
    ))
    db_session.commit()

    decision = AutoDiscoveryEngine.decide(db_session, "OLDSEAS", n_points=500)

    assert auto_discovery.AUTO_DISCOVERY_CRITERIA_VERSION == 3
    assert calls["timesfm"] == 3 and set(calls["baselines"]) == {"HoltWintersForecastEngine"}
    assert decision.criteria_version == 3
    assert decision.engine_choice == "holt_winters"  # against Holt-Winters, TimesFM no longer wins


def test_selector_reason_names_holt_winters_and_seasonal_mase(db_session, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auto_discovery, "_available_timesfm_engine", lambda: None)
    db_session.add(EngineDecisionModel(
        series_id="SEASONALY", engine_choice="holt_winters", mase_holt=0.8, mase_timesfm=0.95,
        n_points_at_evaluation=240, criteria_version=3, baseline_engine="holt_winters", metric="mase_seasonal",
    ))
    db_session.commit()

    res = EngineSelector._try_auto_discovery(
        db_session, "SEASONALY", "macro", _monthly(seasonal()), 240, horizon=12, confidence=0.95, freq="M",
    )
    assert res.model_name.startswith("holt-winters")
    assert "Holt-Winters ganó MASE estacional 0.800 vs TimesFM 0.950" in res.engine_selection_reason
