import pytest
from backend.config import settings
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

def test_market_data_fetcher_synthetic():
    res = MarketDataFetcher._generate_synthetic_equity("TEST", period="1y")
    assert res.id == "TEST"
    assert res.type == "equity"
    assert res.source == "synthetic"
    assert "sintética" in res.source_detail.lower()
    assert len(res.points) > 50
    assert hasattr(res.points[0], "timestamp")
    assert hasattr(res.points[0], "value")
    assert isinstance(res.points[0].value, float)

def test_market_fundamentals_empty_warning(monkeypatch):
    # Mock yfinance Ticker to return empty statements
    class MockTicker:
        def __init__(self, sym):
            self.cashflow = None
            self.financials = None
    
    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", MockTicker)

    metrics, warnings = MarketDataFetcher.get_fundamentals(["TESTSYM"])
    assert len(metrics) == 0
    assert len(warnings) == 1
    assert "No se obtuvieron estados contables para TESTSYM" in warnings[0]

def test_fred_disallow_synthetic_by_default(monkeypatch):
    monkeypatch.setattr(settings, "FRED_API_KEY", "")
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", False)
    
    fetcher = FREDDataFetcher()
    with pytest.raises(ValueError) as excinfo:
        fetcher.get_series("IPG2211A2N")
    assert "ALLOW_SYNTHETIC_DATA=false" in str(excinfo.value)

def test_fred_reference_series_when_allowed(monkeypatch):
    monkeypatch.setattr(settings, "FRED_API_KEY", "")
    monkeypatch.setattr(settings, "ALLOW_SYNTHETIC_DATA", True)
    
    fetcher = FREDDataFetcher()
    series = fetcher.get_series("IPG2211A2N")
    assert series.id == "IPG2211A2N"
    assert series.type == "macro"
    assert series.source == "synthetic"
    assert len(series.points) >= 24
    assert series.points[0].value > 0
