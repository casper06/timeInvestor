import pytest
from backend.services.backtest_engine import BacktestEngine
from backend.services.data_fetcher import MarketDataFetcher

def test_backtest_engine_execution():
    # We fetch a series to find a valid historical date from 6 months ago
    hist = MarketDataFetcher.get_history("NVDA", period="2y")
    points = hist.points
    assert len(points) > 60

    # Pick a date from the middle of the series as cutoff
    cutoff_point = points[len(points) // 2]
    cutoff_date = cutoff_point.timestamp

    res = BacktestEngine.run_backtest(
        series_id="NVDA",
        cutoff_date=cutoff_date,
        horizon=30,
        confidence=0.95
    )

    assert res.series_id == "NVDA"
    assert res.cutoff_date == cutoff_date
    assert len(res.future_actual_values) > 0
    assert len(res.future_predicted_values) == len(res.future_actual_values)
    assert res.metrics.mae >= 0.0
    assert res.metrics.mape >= 0.0
    assert 0.0 <= res.metrics.directional_accuracy <= 100.0
    assert len(res.verdict) > 0
