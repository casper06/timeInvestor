import json
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
