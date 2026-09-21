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
