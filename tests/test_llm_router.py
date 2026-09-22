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
    verifying that /api/interpret returns provider_used == 'gemini-3.6-flash', not the mock.
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
    assert data["provider_used"] == "gemini-3.6-flash"
    assert data["what_data_says"] == fake_gemini_payload["what_data_says"]


def test_gemini_failure_exposes_reason(monkeypatch):
    """
    Forces GeminiLLMClient.models.generate_content to raise (simulating a retired
    model / auth / network failure) and verifies parse_thesis falls back to
    mock-semantic-engine AND surfaces the real exception text in fallback_reason,
    instead of silently swallowing it as before.
    """
    import asyncio
    from unittest.mock import MagicMock
    from backend.services.llm_router import GeminiLLMClient

    def mock_gemini_init(self, api_key=None):
        self.api_key = api_key or "fake-test-key-123"
        self._client = MagicMock()
        self._client.models.generate_content.side_effect = Exception(
            "404 NOT_FOUND. {'error': {'code': 404, 'message': "
            "'This model models/gemini-2.5-flash is no longer available to new users.'}}"
        )

    monkeypatch.setattr(GeminiLLMClient, "__init__", mock_gemini_init)

    client = GeminiLLMClient()
    resp = asyncio.run(client.parse_thesis("Demanda de energía por IA"))

    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_reason is not None
    assert "404" in resp.fallback_reason
    assert "no longer available" in resp.fallback_reason


class _FakeAPIError(Exception):
    """Stand-in for google.genai.errors.APIError — carries a `.code` int attribute,
    which is exactly what `_extract_status_code` looks for first."""
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"{code} {message}")


class AsyncNoopSleep:
    """Callable replacement for asyncio.sleep that returns immediately, so retry
    tests don't actually wait out the real backoff delays (1s, 3s)."""
    async def __call__(self, *args, **kwargs):
        return None


def test_retry_succeeds_on_second_attempt(monkeypatch):
    """
    GeminiLLMClient.parse_thesis: the underlying generate_content call fails with a
    503 (transient overload) on the first attempt and succeeds on the second.
    Verifies the retry recovers the REAL provider's response — not mock — and that
    only one retry (one extra call) was needed, with no artificial sleep delay.
    """
    import asyncio
    import json
    from unittest.mock import MagicMock
    from backend.services.llm_router import GeminiLLMClient

    # Don't actually wait out the backoff delays in the test suite.
    monkeypatch.setattr(asyncio, "sleep", AsyncNoopSleep())

    fake_payload = {
        "summary": "Recuperado tras retry",
        "tickers": [],
        "macro_series": [],
        "rationales": {},
    }
    mock_response = MagicMock()
    mock_response.text = json.dumps(fake_payload)

    call_count = {"n": 0}

    def flaky_generate_content(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise _FakeAPIError(503, "UNAVAILABLE. Model is currently overloaded.")
        return mock_response

    def mock_gemini_init(self, api_key=None):
        self.api_key = api_key or "fake-test-key-123"
        self._client = MagicMock()
        self._client.models.generate_content.side_effect = flaky_generate_content

    monkeypatch.setattr(GeminiLLMClient, "__init__", mock_gemini_init)

    client = GeminiLLMClient()
    resp = asyncio.run(client.parse_thesis("Demanda de energía por IA"))

    assert call_count["n"] == 2, "expected exactly one retry (2 total attempts)"
    assert resp.provider_used == "gemini-3.6-flash"
    assert resp.fallback_reason is None
    assert resp.summary == "Recuperado tras retry"


def test_no_retry_on_permanent_error(monkeypatch):
    """
    A 404 (model not found/retired — as with the real gemini-2.5-flash retirement)
    must NOT be retried: it will fail identically every time, so retrying just
    wastes ~4s of backoff for nothing. Verifies the underlying client is called
    exactly once before falling back to mock.
    """
    import asyncio
    from unittest.mock import MagicMock
    from backend.services.llm_router import GeminiLLMClient

    monkeypatch.setattr(asyncio, "sleep", AsyncNoopSleep())

    call_count = {"n": 0}

    def permanently_failing_generate_content(*args, **kwargs):
        call_count["n"] += 1
        raise _FakeAPIError(404, "NOT_FOUND. Model models/gemini-2.5-flash is no longer available.")

    def mock_gemini_init(self, api_key=None):
        self.api_key = api_key or "fake-test-key-123"
        self._client = MagicMock()
        self._client.models.generate_content.side_effect = permanently_failing_generate_content

    monkeypatch.setattr(GeminiLLMClient, "__init__", mock_gemini_init)

    client = GeminiLLMClient()
    resp = asyncio.run(client.parse_thesis("Demanda de energía por IA"))

    assert call_count["n"] == 1, "a permanent (404) error must not be retried"
    assert resp.provider_used == "mock-semantic-engine"
    assert resp.fallback_reason is not None
    assert "404" in resp.fallback_reason
    # Must NOT claim retries happened for a permanent error that was never retried.
    assert "intentos" not in resp.fallback_reason


def test_health_reports_actual_forecast_engine(monkeypatch):
    """
    Verifies /api/health returns the active forecast engine's real model_name
    (e.g. 'damped-holt-mle'), not a stale hardcoded 'mock' string left over
    from before StatisticalMockForecastEngine was renamed to DampedHoltForecastEngine.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.config import settings

    monkeypatch.setattr(settings, "FORECAST_ENGINE", "mock")
    monkeypatch.setattr(settings, "USE_REAL_TIMESFM", False)

    test_client = TestClient(app)
    resp = test_client.get("/api/health")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["forecast_engine"] == "damped-holt-mle"
    assert data["forecast_engine"] != "mock"
