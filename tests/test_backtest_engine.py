import json
from pathlib import Path
import pytest
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import MarketDataFetcher

def test_backtest_engine_execution(monkeypatch):
    # Load offline deterministic fixture
    fixture_path = Path(__file__).parent / "fixtures" / "nvda_daily.json"
    raw_pts = json.loads(fixture_path.read_text())
    points = [TimeSeriesPoint(**p) for p in raw_pts]
    fixture_series = TimeSeriesData(
        id="NVDA",
        name="NVIDIA Corp",
        type="equity",
        unit="USD",
        points=points,
        source="live"
    )

    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *args, **kwargs: fixture_series)

    # Cutoff in the middle (e.g. index 180 of 252)
    cutoff_point = points[180]
    cutoff_date = cutoff_point.timestamp

    res = BacktestEngine.run_backtest(
        series_id="NVDA",
        cutoff_date=cutoff_date,
        horizon=30,
        confidence=0.95
    )

    assert res.series_id == "NVDA"
    assert res.cutoff_date == cutoff_date
    assert len(res.future_actual_values) == 30
    assert len(res.future_predicted_values) == 30
    assert res.metrics.mae >= 0.0
    assert res.metrics.mape >= 0.0
    assert res.metrics.smape >= 0.0
    assert res.metrics.mase >= 0.0
    assert 0.0 <= res.metrics.directional_accuracy <= 100.0
    assert 0.0 <= res.interval_coverage <= 100.0
    assert res.naive_metrics is not None
    assert res.naive_metrics.mae >= 0.0
    assert len(res.verdict) > 0


# ---------------------------------------------------------------------------
# TimesFM falling back to Holt inside run_backtest must be visible.
# ---------------------------------------------------------------------------

def _nvda_fixture(monkeypatch):
    fixture_path = Path(__file__).parent / "fixtures" / "nvda_daily.json"
    points = [TimeSeriesPoint(**p) for p in json.loads(fixture_path.read_text())]
    series = TimeSeriesData(id="NVDA", name="NVIDIA Corp", type="equity", unit="USD", points=points, source="live")
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *args, **kwargs: series)
    return points


@pytest.fixture
def timesfm_with_failing_inference():
    """The real TimesFMForecastEngine code path with "loaded" weights whose
    inference raises: forecast() catches it and answers with Holt, exactly as
    it does in production when TimesFM fails on a given input."""
    from backend.services.forecast_engine import DampedHoltForecastEngine, TimesFMForecastEngine

    class _FailingModel:
        def forecast(self, *args, **kwargs):
            raise RuntimeError("simulated TimesFM inference failure")

    previous = TimesFMForecastEngine._instance
    engine = object.__new__(TimesFMForecastEngine)
    engine._initialized = True
    engine._fallback_engine = DampedHoltForecastEngine()
    engine.device = "cpu"
    engine._model = _FailingModel()
    TimesFMForecastEngine._instance = engine
    yield engine
    TimesFMForecastEngine._instance = previous


def test_backtest_reports_timesfm_fallback(monkeypatch, timesfm_with_failing_inference):
    from backend.services.forecast_engine import DampedHoltForecastEngine

    points = _nvda_fixture(monkeypatch)
    cutoff = points[180].timestamp

    res = BacktestEngine.run_backtest(
        series_id="NVDA", cutoff_date=cutoff, horizon=30, engine_override=timesfm_with_failing_inference,
    )

    assert res.is_fallback is True
    assert "fallback" in res.model_name
    assert res.fallback_kind == "inference_error"
    assert "simulated TimesFM inference failure" in res.fallback_reason

    # Proof that the metrics really are Holt's: same numbers as a Holt run.
    holt = BacktestEngine.run_backtest(
        series_id="NVDA", cutoff_date=cutoff, horizon=30, engine_override=DampedHoltForecastEngine(),
    )
    assert res.metrics.mase == holt.metrics.mase
    assert res.future_predicted_values == holt.future_predicted_values


def test_backtest_without_fallback_reports_engine(monkeypatch):
    from backend.services.forecast_engine import DampedHoltForecastEngine

    points = _nvda_fixture(monkeypatch)
    res = BacktestEngine.run_backtest(
        series_id="NVDA", cutoff_date=points[180].timestamp, horizon=30,
        engine_override=DampedHoltForecastEngine(),
    )

    assert res.is_fallback is False
    assert res.model_name == "damped-holt-mle"
    assert res.fallback_kind is None and res.fallback_reason is None


def test_backtest_fallback_kinds(monkeypatch, timesfm_with_failing_inference):
    """The two causes where waiting does NOT help are told apart from a
    one-off inference error, so the UI can say "intervene" vs "retry"."""
    points = _nvda_fixture(monkeypatch)
    cutoff = points[100].timestamp
    engine = timesfm_with_failing_inference

    too_long = BacktestEngine.run_backtest(series_id="NVDA", cutoff_date=cutoff, horizon=140, engine_override=engine)
    assert too_long.is_fallback and too_long.fallback_kind == "horizon_exceeded"
    assert "140" in too_long.fallback_reason

    engine._model = None
    not_loaded = BacktestEngine.run_backtest(series_id="NVDA", cutoff_date=cutoff, horizon=30, engine_override=engine)
    assert not_loaded.is_fallback and not_loaded.fallback_kind == "not_loaded"
