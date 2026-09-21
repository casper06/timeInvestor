import asyncio
import pytest
from backend.services.llm_router import MockLLMClient, get_llm_client

def test_mock_llm_client_datacenter_thesis():
    client = MockLLMClient()
    thesis = "Demanda eléctrica por centros de datos de IA"
    resp = asyncio.run(client.parse_thesis(thesis))
    
    assert resp.thesis == thesis
    assert len(resp.tickers) >= 3
    assert len(resp.macro_series) >= 1
    symbols = [t.symbol for t in resp.tickers]
    assert "NVDA" in symbols
    assert "CEG" in symbols or "VST" in symbols
    assert any(m.series_id == "IPG2211A2N" for m in resp.macro_series)
    assert resp.provider_used == "mock-semantic-engine"

def test_mock_llm_client_semiconductor_thesis():
    client = MockLLMClient()
    thesis = "Ciclo de Capex de semiconductores avanzados y litografía"
    resp = asyncio.run(client.parse_thesis(thesis))
    
    assert len(resp.tickers) >= 3
    symbols = [t.symbol for t in resp.tickers]
    assert "TSM" in symbols or "NVDA" in symbols or "ASML" in symbols

def test_get_llm_client_factory():
    client = get_llm_client("mock")
    assert isinstance(client, MockLLMClient)

def test_mock_llm_interpret_situation():
    from backend.schemas.models import InterpretationContext
    client = MockLLMClient()
    ctx = InterpretationContext(
        thesis="Demanda eléctrica por centros de datos de IA",
        active_series_id="NVDA",
        active_series_name="NVIDIA Corporation",
        last_price=120.0,
        projected_target=145.0,
        horizon=60,
        confidence=0.95,
        lower_bound=130.0,
        upper_bound=160.0,
        cagr=35.0,
        other_tickers=["CEG", "VST", "MSFT"],
        macro_series=["IPG2211A2N"]
    )
    resp = asyncio.run(client.interpret_situation(ctx))
    assert len(resp.what_data_says) > 0
    assert len(resp.thesis_alignment) > 0
    assert len(resp.next_series_suggestion) > 0
    assert resp.suggested_series_id in ("CEG", "VST", "IPG2211A2N")
    assert resp.provider_used == "mock-semantic-engine"


def test_interpretation_response_includes_provider(monkeypatch):
    """
    Calls POST /api/interpret with MockLLMClient forced (no GEMINI_API_KEY)
    and verifies that response includes provider_used == 'mock-semantic-engine'.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")

    test_client = TestClient(app)
    resp = test_client.post("/api/interpret", json={
        "thesis": "Demanda de energía por IA",
        "active_series_id": "NVDA",
        "last_price": 100.0,
        "projected_target": 120.0,
        "lower_bound": 90.0,
        "upper_bound": 140.0,
        "other_tickers": ["CEG"],
        "macro_series": ["IPG2211A2N"]
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider_used"] == "mock-semantic-engine"


def test_interpretation_response_provider_gemini(monkeypatch):
    """
    Monkeypatches Gemini client to simulate a successful API response without network,
    verifying that /api/interpret returns provider_used == 'gemini-2.5-flash', not the mock.
    """
    import json
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings
    from backend.services.llm_router import GeminiLLMClient

    fake_gemini_payload = {
        "what_data_says": "La serie muestra una clara trayectoria ascendente respaldada por fundamentales sólidos.",
        "thesis_alignment": "Los datos confirman plenamente la hipótesis de expansión de centros de datos.",
        "next_series_suggestion": "Se recomienda explorar la serie de producción eléctrica CEG.",
        "suggested_series_id": "CEG"
    }

    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(fake_gemini_payload)
    mock_genai_client.models.generate_content.return_value = mock_response

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-test-key-123")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    def mock_gemini_init(self, api_key=None):
        self.api_key = api_key or "fake-test-key-123"
        self._client = mock_genai_client

    monkeypatch.setattr(GeminiLLMClient, "__init__", mock_gemini_init)

    test_client = TestClient(app)
    resp = test_client.post("/api/interpret", json={
        "thesis": "Demanda de energía por IA",
        "active_series_id": "NVDA",
        "last_price": 100.0,
        "projected_target": 120.0,
        "lower_bound": 90.0,
        "upper_bound": 140.0,
        "other_tickers": ["CEG"],
        "macro_series": ["IPG2211A2N"]
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider_used"] == "gemini-2.5-flash"
    assert data["what_data_says"] == fake_gemini_payload["what_data_says"]
