"""
ForecastResponse.seasonality: the 3.0a detector on the forecast points, so the
UI can tell a seasonal series apart (it hides the 'inercia' card there).
"""
from backend.services.engine_selector import EngineSelector
from tests.test_seasonality import _business_daily, _monthly, random_walk_series, seasonal_trend_series


def test_seasonal_monthly_series_is_flagged():
    res = EngineSelector.select(_monthly(seasonal_trend_series()), series_id="ZZSEAS", horizon=12)
    assert res.seasonality is not None
    assert res.seasonality.is_seasonal and res.seasonality.period == 12


def test_daily_series_is_not_evaluated_for_seasonality():
    res = EngineSelector.select(_business_daily(random_walk_series(n=300)), series_id="ZZDAILY", horizon=30)
    assert res.seasonality is not None and res.seasonality.is_seasonal is False
    assert "No evaluada" in res.seasonality.reason
