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
