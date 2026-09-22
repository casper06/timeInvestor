import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas.models import (
    TimeSeriesData,
    TimeSeriesPoint,
    FundamentalsMetric,
)
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher
from backend.services.llm_router import MockLLMClient
import backend.api.routes as routes

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data


def test_analyze_thesis_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda *args, **kwargs: MockLLMClient())
    response = client.post("/api/thesis", json={"thesis": "Demanda de energía por IA"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["tickers"]) > 0
    assert len(data["macro_series"]) > 0


def test_analyze_thesis_force_mock_ignores_configured_provider(monkeypatch):
    """
    /api/thesis?force_mock=true must call get_llm_client("mock") regardless of which
    provider is configured — this is what the frontend's mount-time bootstrap relies
    on to never spend real LLM quota without an explicit user action.
    """
    calls = []

    def fake_get_llm_client(provider=None):
        calls.append(provider)
        return MockLLMClient()

    monkeypatch.setattr(routes, "get_llm_client", fake_get_llm_client)
    response = client.post("/api/thesis?force_mock=true", json={"thesis": "Demanda de energía por IA"})
    assert response.status_code == 200
    data = response.json()
    assert data["provider_used"] == "mock-semantic-engine"
    assert calls == ["mock"]


def test_analyze_thesis_without_force_mock_uses_default_provider(monkeypatch):
    """Without force_mock, get_llm_client() is called with no override (the configured provider)."""
    calls = []

    def fake_get_llm_client(provider=None):
        calls.append(provider)
        return MockLLMClient()

    monkeypatch.setattr(routes, "get_llm_client", fake_get_llm_client)
    response = client.post("/api/thesis", json={"thesis": "Demanda de energía por IA"})
    assert response.status_code == 200
    assert calls == [None]


def test_market_data_endpoint(monkeypatch):
    mock_data = TimeSeriesData(
        id="NVDA",
        name="NVIDIA Corp",
        type="equity",
        unit="USD",
        points=[
            TimeSeriesPoint(timestamp="2024-01-01", value=150.0),
            TimeSeriesPoint(timestamp="2024-01-02", value=155.0),
        ],
        source="live",
    )
    monkeypatch.setattr(MarketDataFetcher, "get_history", lambda *args, **kwargs: mock_data)
    response = client.get("/api/data/market?ticker=NVDA&period=1y")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "NVDA"
    assert data["source"] == "live"


def test_macro_data_endpoint(monkeypatch):
    mock_data = TimeSeriesData(
        id="CPIAUCSL",
        name="Consumer Price Index",
        type="macro",
        unit="Index",
        points=[
            TimeSeriesPoint(timestamp="2024-01-01", value=300.0),
            TimeSeriesPoint(timestamp="2024-02-01", value=301.0),
        ],
        source="live",
    )
    monkeypatch.setattr(FREDDataFetcher, "get_series", lambda *args, **kwargs: mock_data)
    response = client.get("/api/data/macro?series_id=CPIAUCSL")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "CPIAUCSL"
    assert data["source"] == "live"


def test_forecast_endpoint():
    points = [
        {"timestamp": f"2024-01-{i:02d}", "value": 150.0 + i}
        for i in range(1, 10)
    ]
    response = client.post("/api/forecast", json={
        "points": points,
        "horizon": 5,
        "confidence": 0.95
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data["values"]) == 5
    assert len(data["lower_bound"]) == 5
    assert len(data["upper_bound"]) == 5


def test_fundamentals_endpoint(monkeypatch):
    mock_metrics = [
        FundamentalsMetric(
            ticker="NVDA",
            metric="Capital Expenditure",
            period="2023",
            value=3000000000.0,
            source="live",
        ),
        FundamentalsMetric(
            ticker="MSFT",
            metric="Capital Expenditure",
            period="2023",
            value=28000000000.0,
            source="live",
        ),
    ]
    monkeypatch.setattr(MarketDataFetcher, "get_fundamentals", lambda tickers: (mock_metrics, []))
    response = client.get("/api/data/fundamentals?tickers=NVDA,MSFT")
    assert response.status_code == 200
    data = response.json()
    assert len(data["metrics"]) == 2
    assert data["metrics"][0]["ticker"] == "NVDA"


def test_interpret_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "get_llm_client", lambda *args, **kwargs: MockLLMClient())
    response = client.post("/api/interpret", json={
        "thesis": "Demanda de energía por IA",
        "active_series_id": "NVDA",
        "last_price": 100.0,
        "projected_target": 120.0,
        "lower_bound": 90.0,
        "upper_bound": 140.0,
        "other_tickers": ["CEG"],
        "macro_series": ["IPG2211A2N"]
    })
    assert response.status_code == 200
    data = response.json()
    assert "what_data_says" in data
    assert "thesis_alignment" in data
    assert "next_series_suggestion" in data


def test_static_frontend_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "TimeInvestor" in response.text or "vite" in response.text.lower()
