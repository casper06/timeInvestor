from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data

def test_analyze_thesis_endpoint():
    response = client.post("/api/thesis", json={"thesis": "Demanda de energía por IA"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["tickers"]) > 0
    assert len(data["macro_series"]) > 0

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

def test_fundamentals_endpoint():
    response = client.get("/api/data/fundamentals?tickers=NVDA,MSFT")
    assert response.status_code == 200
    data = response.json()
    assert len(data["metrics"]) > 0

def test_interpret_endpoint():
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
