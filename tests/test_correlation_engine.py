import pytest
from backend.services.correlation_engine import CorrelationEngine

def test_correlation_matrix_computation():
    series_ids = ["NVDA", "MSFT", "IPG2211A2N"]
    res = CorrelationEngine.calculate_correlations(series_ids, period="1y")

    assert len(res.series_ids) == 3
    assert len(res.pearson_matrix) == 3
    assert len(res.spearman_matrix) == 3
    assert res.common_observations > 10

    # Diagonal must be 1.0
    for i in range(3):
        assert abs(res.pearson_matrix[i][i] - 1.0) < 1e-4
        assert abs(res.spearman_matrix[i][i] - 1.0) < 1e-4

    # Symmetry
    for i in range(3):
        for j in range(3):
            assert abs(res.pearson_matrix[i][j] - res.pearson_matrix[j][i]) < 1e-4
            assert abs(res.spearman_matrix[i][j] - res.spearman_matrix[j][i]) < 1e-4
            assert -1.01 <= res.pearson_matrix[i][j] <= 1.01
            assert -1.01 <= res.spearman_matrix[i][j] <= 1.01
