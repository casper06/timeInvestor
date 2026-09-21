import pytest
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

def test_market_data_fetcher_synthetic():
    # Synthetic equity fallback returns properly normalized points
    res = MarketDataFetcher._generate_synthetic_equity("TEST", period="1y")
    assert res.id == "TEST"
    assert res.type == "equity"
    assert len(res.points) > 50
    assert hasattr(res.points[0], "timestamp")
    assert hasattr(res.points[0], "value")
    assert isinstance(res.points[0].value, float)

def test_market_fundamentals_fallback():
    metrics = MarketDataFetcher._get_fallback_fundamentals("NVDA")
    assert len(metrics) > 0
    capex_metrics = [m for m in metrics if "Capex" in m.metric]
    rev_metrics = [m for m in metrics if "Revenue" in m.metric]
    assert len(capex_metrics) >= 3
    assert len(rev_metrics) >= 3

def test_fred_reference_series():
    fetcher = FREDDataFetcher()
    series = fetcher.get_series("IPG2211A2N")
    assert series.id == "IPG2211A2N"
    assert series.type == "macro"
    assert len(series.points) >= 24
    assert series.points[0].value > 0
