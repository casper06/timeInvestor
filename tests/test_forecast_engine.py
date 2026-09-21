import pytest
from backend.schemas.models import TimeSeriesPoint
from backend.services.forecast_engine import StatisticalMockForecastEngine, TimesFMForecastEngine

def test_statistical_mock_forecast():
    engine = StatisticalMockForecastEngine()
    
    # Generate simple historical series
    points = [
        TimeSeriesPoint(timestamp=f"2024-01-{i:02d}", value=100.0 + i * 1.5)
        for i in range(1, 20)
    ]
    
    horizon = 10
    confidence = 0.95
    resp = engine.forecast(points, horizon=horizon, confidence=confidence, freq="D")
    
    # Verify TimesFM schema conformance
    assert len(resp.timestamps) == horizon
    assert len(resp.values) == horizon
    assert len(resp.lower_bound) == horizon
    assert len(resp.upper_bound) == horizon
    assert resp.model_name == "damped-holt-mle"
    assert resp.is_fallback is False

    # Lower bound must be <= forecast value <= upper bound
    for v, lb, ub in zip(resp.values, resp.lower_bound, resp.upper_bound):
        assert lb <= v, f"Lower bound {lb} must be <= value {v}"
        assert v <= ub, f"Value {v} must be <= upper bound {ub}"

def test_timesfm_adapter_fallback():
    engine = TimesFMForecastEngine()
    points = [
        TimeSeriesPoint(timestamp="2024-01-01", value=50.0),
        TimeSeriesPoint(timestamp="2024-01-02", value=52.0),
        TimeSeriesPoint(timestamp="2024-01-03", value=51.5),
    ]
    resp = engine.forecast(points, horizon=5)
    assert len(resp.values) == 5
    assert "damped-holt-mle" in resp.model_name
    assert resp.is_fallback is True
