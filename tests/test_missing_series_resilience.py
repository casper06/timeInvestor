"""
fix/missing-series-resilience: a series that doesn't exist (TOTALSI and IPGD,
proposed by the LLM in the thesis from the screenshots) or fails to load never
takes the whole correlation matrix down. It's computed with the rest and the
response lists the excluded ones with the reason.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import TimeSeriesData, TimeSeriesPoint
from backend.services.correlation_engine import CorrelationEngine
from backend.services.data_fetcher import (
    FREDDataFetcher,
    FredSeriesNotFoundError,
    MarketDataFetcher,
    MarketDataUnavailableError,
)

client = TestClient(app)
FIX = Path(__file__).parent / "fixtures"


def _points(name):
    return [TimeSeriesPoint(**p) for p in json.loads((FIX / name).read_text())]


@pytest.fixture
def thesis_sources(monkeypatch):
    """NVDA and MSFT load; UMCSENT exists in FRED; TOTALSI and IPGD don't."""
    nvda, msft = _points("nvda_daily.json"), _points("msft_daily.json")
    # Monthly points over the equities' window (first day of each month seen).
    months = sorted({p.timestamp[:7] for p in nvda})
    umcsent = [TimeSeriesPoint(timestamp=f"{m}-01", value=70 + (i * 7919 % 13)) for i, m in enumerate(months)]

    def hist(ticker, period="2y"):
        t = ticker.upper()
        if t == "NVDA":
            return TimeSeriesData(id="NVDA", name="NVIDIA Corp", type="equity", unit="USD", points=nvda, source="live")
        if t == "MSFT":
            return TimeSeriesData(id="MSFT", name="Microsoft Corp", type="equity", unit="USD", points=msft, source="live")
        raise MarketDataUnavailableError(f"yfinance no devolvió datos para {t}")

    def series(self, sid, *a, **k):
        if sid == "UMCSENT":
            return TimeSeriesData(id="UMCSENT", name="University of Michigan: Consumer Sentiment", type="macro",
                                  unit="Index 1966:Q1=100", points=umcsent, source="live")
        raise FredSeriesNotFoundError(sid)

    monkeypatch.setattr(MarketDataFetcher, "get_history", hist)
    monkeypatch.setattr(FREDDataFetcher, "get_series", series)


TYPES = {"NVDA": "equity", "MSFT": "equity", "TOTALSI": "macro", "IPGD": "macro", "UMCSENT": "macro"}


def test_the_matrix_is_computed_with_the_rest_and_lists_the_excluded(thesis_sources):
    res = CorrelationEngine.calculate_correlations(
        ["NVDA", "TOTALSI", "IPGD", "UMCSENT", "MSFT"], period="2y", series_types=TYPES)
    assert res.series_ids == ["NVDA", "UMCSENT", "MSFT"]
    assert len(res.pearson_matrix) == 3
    assert [e.series_id for e in res.excluded] == ["TOTALSI", "IPGD"]
    assert res.excluded[0].reason == str(FredSeriesNotFoundError("TOTALSI"))
    assert "no existe en FRED" in res.excluded[1].reason


def test_a_market_failure_is_excluded_too(thesis_sources):
    res = CorrelationEngine.calculate_correlations(["NVDA", "ZZZZ", "MSFT"], series_types={"ZZZZ": "equity"})
    assert res.series_ids == ["NVDA", "MSFT"]
    assert res.excluded[0].series_id == "ZZZZ"
    assert "yfinance no devolvió datos" in res.excluded[0].reason


def test_nothing_excluded_means_an_empty_list(thesis_sources):
    res = CorrelationEngine.calculate_correlations(["NVDA", "MSFT"])
    assert res.excluded == []


def test_fewer_than_two_left_is_an_error_that_names_the_excluded(thesis_sources):
    with pytest.raises(ValueError) as e:
        CorrelationEngine.calculate_correlations(["NVDA", "TOTALSI", "IPGD"], series_types=TYPES)
    msg = str(e.value)
    assert "Quedan 1 serie(s)" in msg
    assert "TOTALSI: La serie 'TOTALSI' no existe en FRED" in msg
    assert "IPGD: La serie 'IPGD' no existe en FRED" in msg


def test_synthetic_data_still_fails_the_whole_matrix(monkeypatch, thesis_sources):
    """Synthetic data isn't a load failure: mixing it in would be a fake result."""
    real = MarketDataFetcher.get_history

    def hist(ticker, period="2y"):
        data = real(ticker, period)
        return data.model_copy(update={"source": "synthetic"}) if ticker == "MSFT" else data

    monkeypatch.setattr(MarketDataFetcher, "get_history", hist)
    with pytest.raises(ValueError, match="sintética"):
        CorrelationEngine.calculate_correlations(["NVDA", "UMCSENT", "MSFT"], series_types=TYPES)


def test_the_route_answers_200_with_the_excluded(thesis_sources):
    r = client.post("/api/correlation", json={
        "series_ids": ["NVDA", "TOTALSI", "IPGD", "UMCSENT", "MSFT"], "series_types": TYPES})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["series_ids"] == ["NVDA", "UMCSENT", "MSFT"]
    assert [e["series_id"] for e in body["excluded"]] == ["TOTALSI", "IPGD"]


def test_the_route_answers_400_when_too_few_are_left(thesis_sources):
    r = client.post("/api/correlation", json={"series_ids": ["TOTALSI", "UMCSENT"], "series_types": TYPES})
    assert r.status_code == 400
    assert "TOTALSI: La serie 'TOTALSI' no existe en FRED" in r.json()["detail"]
