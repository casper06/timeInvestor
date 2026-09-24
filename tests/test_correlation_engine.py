import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.correlation_engine import CorrelationEngine
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

def test_correlation_matrix_computation(monkeypatch):
    fix_dir = Path(__file__).parent / "fixtures"
    nvda_pts = [TimeSeriesPoint(**p) for p in json.loads((fix_dir / "nvda_daily.json").read_text())]
    msft_pts = [TimeSeriesPoint(**p) for p in json.loads((fix_dir / "msft_daily.json").read_text())]

    s_nvda = TimeSeriesData(id="NVDA", name="NVIDIA Corp", type="equity", unit="USD", points=nvda_pts, source="live")
    s_msft = TimeSeriesData(id="MSFT", name="Microsoft Corp", type="equity", unit="USD", points=msft_pts, source="live")

    def mock_hist(ticker, period="2y"):
        return s_nvda if ticker.upper() == "NVDA" else s_msft

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_hist)

    series_ids = ["NVDA", "MSFT"]
    res = CorrelationEngine.calculate_correlations(series_ids, period="1y", mode="returns")

    assert len(res.series_ids) == 2
    assert len(res.pearson_matrix) == 2
    assert len(res.spearman_matrix) == 2
    assert len(res.p_values_pearson) == 2
    assert len(res.p_values_spearman) == 2
    assert res.common_observations > 200

    # Diagonal must be 1.0
    for i in range(2):
        assert abs(res.pearson_matrix[i][i] - 1.0) < 1e-4
        assert abs(res.spearman_matrix[i][i] - 1.0) < 1e-4
        assert res.p_values_pearson[i][i] == 0.0

    # Symmetry
    for i in range(2):
        for j in range(2):
            assert abs(res.pearson_matrix[i][j] - res.pearson_matrix[j][i]) < 1e-4
            assert abs(res.spearman_matrix[i][j] - res.spearman_matrix[j][i]) < 1e-4
            assert -1.01 <= res.pearson_matrix[i][j] <= 1.01
            assert -1.01 <= res.spearman_matrix[i][j] <= 1.01
            assert 0.0 <= res.p_values_pearson[i][j] <= 1.0


def test_correlation_matrix_reflects_active_portfolio(monkeypatch):
    """
    Reproduces the reported "0 activos" bug: a portfolio of 5 equity tickers
    (ASML/AMAT/LRCX/KLAC/TSM-style) plus 3 FRED macro series. Root cause was
    FREDDataFetcher.get_series() querying FRED with sort_order=asc + limit=500,
    which for a long-running series (e.g. INDPRO, live since 1919) returns the
    OLDEST 500 observations — ending in 1960, decades before any 2024-2026
    equity data — producing zero overlapping dates once aligned, silently
    swallowed by the frontend as "0 activos" instead of a visible error.

    This test mocks FREDDataFetcher.get_series to return series whose recent
    tail overlaps the equities' 2-year window (as the real, fixed sort_order=desc
    behavior does), and asserts the resulting matrix actually contains all 8
    series — not a truncated/empty one.
    """
    fix_dir = Path(__file__).parent / "fixtures"
    nvda_pts = [TimeSeriesPoint(**p) for p in json.loads((fix_dir / "nvda_daily.json").read_text())]
    msft_pts = [TimeSeriesPoint(**p) for p in json.loads((fix_dir / "msft_daily.json").read_text())]

    equity_tickers = ["ASML", "AMAT", "LRCX", "KLAC", "TSM"]
    equity_data = {
        t: TimeSeriesData(id=t, name=f"{t} Corp", type="equity", unit="USD", points=nvda_pts if i % 2 == 0 else msft_pts, source="live")
        for i, t in enumerate(equity_tickers)
    }

    def mock_hist(ticker, period="2y"):
        return equity_data[ticker.upper()]

    monkeypatch.setattr(MarketDataFetcher, "get_history", mock_hist)

    # Recent monthly macro points overlapping the equities' date range (the
    # nvda/msft fixtures' dates), simulating the POST-FIX behavior where FRED
    # returns the most recent observations, not the oldest ones from decades ago.
    equity_dates = sorted(p.timestamp for p in nvda_pts)
    recent_start = datetime.strptime(equity_dates[0], "%Y-%m-%d")
    macro_points = [
        TimeSeriesPoint(timestamp=(recent_start + timedelta(days=30 * i)).strftime("%Y-%m-%d"), value=100.0 + i)
        for i in range(24)
    ]
    macro_series = {
        "INDPRO": TimeSeriesData(id="INDPRO", name="Industrial Production", type="macro", unit="Index", points=macro_points, source="live"),
        "PCU33443344": TimeSeriesData(id="PCU33443344", name="PPI Semiconductors", type="macro", unit="Index", points=macro_points, source="live"),
        "DGS10": TimeSeriesData(id="DGS10", name="10-Year Treasury", type="macro", unit="Percent", points=macro_points, source="live"),
    }

    def mock_fred_series(self, series_id, limit=500):
        return macro_series[series_id]

    monkeypatch.setattr(FREDDataFetcher, "get_series", mock_fred_series)

    all_ids = equity_tickers + list(macro_series.keys())
    res = CorrelationEngine.calculate_correlations(all_ids, period="2y", mode="returns")

    assert len(res.series_ids) == 8, (
        f"Expected all 8 portfolio series in the correlation matrix, got {len(res.series_ids)}: {res.series_ids}"
    )
    assert set(res.series_ids) == set(all_ids)
    assert res.common_observations >= 5
    assert len(res.pearson_matrix) == 8
    assert len(res.pearson_matrix[0]) == 8
