"""4.11 — every FRED ID the LLM proposes is checked against FRED before the UI.

No network and no keys: FRED's two endpoints (/fred/series for existence,
/fred/series/search for the concept) are served by httpx.MockTransport, with
the bodies the real API returns (shapes verified against the live API on
2026-09-26/27 and recorded in docs/PLAN.md 4.11).

This file covers the validation itself: what exists, what doesn't, and what
happens when FRED can't be reached. The repair pass — the LLM choosing a real
replacement for its own invented IDs — is in `test_fred_repair_pass.py`.
"""
import asyncio

import httpx
import pytest

from backend.schemas.models import MacroSuggestion
from backend.services import fred_grounding
from backend.services.fred_grounding import (
    DISCARDED,
    VERIFIED,
    ground_macro_series,
    search_fred_concept,
)

# FRED's real 400 body for an unknown series_id, on /fred/series.
NOT_EXIST = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}

UMCSENT_META = {
    "seriess": [{
        "id": "UMCSENT",
        "title": "University of Michigan: Consumer Sentiment",
        "units": "Index 1966:Q1=100",
        "frequency": "Monthly",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "seasonal_adjustment_short": "NSA",
        "notes": "...",
    }]
}

SEARCH_HITS = {
    "seriess": [
        {"id": "TOTALSA", "title": "Total Vehicle Sales", "frequency_short": "M",
         "seasonal_adjustment_short": "SAAR", "observation_start": "1976-01-01",
         "observation_end": "2026-08-01", "units_short": "Millions of Units"},
        {"id": "ALTSALES", "title": "Light Weight Vehicle Sales", "frequency_short": "M",
         "seasonal_adjustment_short": "SAAR", "observation_start": "1976-01-01",
         "observation_end": "2026-08-01", "units_short": "Millions of Units"},
    ]
}


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    """get_series_metadata caches by series_id; a leaked entry would make a
    test pass without ever touching the (mocked) API."""
    from backend.services.data_fetcher import cache
    monkeypatch.setattr(cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(cache, "set", lambda *a, **k: None)


def _install(monkeypatch, handler, key="test-key"):
    """Routes every httpx.Client in data_fetcher and fred_grounding to the mock."""
    import backend.services.data_fetcher as df

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(df.httpx, "Client", fake_client)
    monkeypatch.setattr(fred_grounding.httpx, "Client", fake_client)
    monkeypatch.setattr(df.settings, "FRED_API_KEY", key)
    monkeypatch.setattr(fred_grounding.settings, "FRED_API_KEY", key)


def _run(series, client=None):
    return asyncio.run(ground_macro_series(series, client=client))


def test_umcsent_existe_queda_verificado(monkeypatch):
    """A real ID is kept as-is and carries FRED's own title."""
    def handler(request):
        assert "/fred/series" in str(request.url)
        assert "search" not in str(request.url), "no se busca un ID que existe"
        return httpx.Response(200, json=UMCSENT_META)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="UMCSENT", name="Confianza del consumidor", category="Consumo")
    [out] = _run([item])

    assert out.series_id == "UMCSENT"
    assert out.grounding == VERIFIED
    assert out.fred_title == "University of Michigan: Consumer Sentiment"
    assert out.proposed_series_id is None
    assert out.grounding_note is None
    assert out.enters_analysis() is True


def test_id_inventado_sin_candidato_se_descarta(monkeypatch):
    """No candidate at all: discarded with a visible warning. The ID is never
    silently kept."""
    def handler(request):
        if "/fred/series/search" in str(request.url):
            return httpx.Response(200, json={"seriess": []})
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="TOTALSI", name="Concepto inexistente", category="Macro")
    [out] = _run([item])

    assert out.grounding == DISCARDED
    assert out.proposed_series_id == "TOTALSI"
    assert "no existe en FRED" in out.grounding_note
    assert out.enters_analysis() is False


def test_sin_clave_no_inventa_ni_rompe(monkeypatch):
    """Without a FRED key nothing can be verified: the LLM's ID is kept, marked
    unverified. Dropping real series because the key is missing would be worse."""
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no se debe llamar a FRED sin clave")

    _install(monkeypatch, handler, key="")
    item = MacroSuggestion(series_id="TOTALSI", name="Lo que sea", category="Macro")
    [out] = _run([item])

    assert out.grounding is None
    assert out.series_id == "TOTALSI"
    assert "No se pudo verificar" in out.grounding_note
    assert out.enters_analysis() is False, "sin verificar tampoco entra al analisis"


def test_fred_caido_no_descarta_series(monkeypatch):
    """A 500 from FRED is not "does not exist": the series survives, unverified."""
    def handler(request):
        return httpx.Response(500, text="boom")

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="UMCSENT", name="Confianza", category="Consumo")
    [out] = _run([item])

    assert out.grounding is None
    assert out.series_id == "UMCSENT"
    assert "no respondi" in out.grounding_note


def test_busca_con_el_concepto_en_ingles(monkeypatch):
    """FRED's search index is English-only (verified 2026-09-29: "new home
    sales" -> 2986 hits, the same concept in Spanish -> 0). The English concept
    wins over the Spanish `name`, or there would be nothing to repair from."""
    seen = {}

    def handler(request):
        if "/fred/series/search" in str(request.url):
            seen["search_text"] = dict(request.url.params).get("search_text")
            return httpx.Response(200, json=SEARCH_HITS)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(
        series_id="TOTALSI",
        name="Ventas totales de vehiculos",
        category="Consumo",
        search_concept_en="total vehicle sales",
    )
    _run([item])

    assert seen["search_text"] == "total vehicle sales"


def test_sin_concepto_en_ingles_cae_al_name(monkeypatch):
    """A provider that doesn't fill search_concept_en (the mock, an older
    cached thesis) still gets a search attempt."""
    seen = {}

    def handler(request):
        if "/fred/series/search" in str(request.url):
            seen["search_text"] = dict(request.url.params).get("search_text")
            return httpx.Response(200, json=SEARCH_HITS)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    _run([MacroSuggestion(series_id="IPGD", name="Vehicle sales", category="Consumo")])
    assert seen["search_text"] == "Vehicle sales"


def test_busqueda_usa_category_si_no_hay_name(monkeypatch):
    def handler(request):
        if "/fred/series/search" in str(request.url):
            assert dict(request.url.params).get("search_text") == "Tasas"
            return httpx.Response(200, json=SEARCH_HITS)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    _run([MacroSuggestion(series_id="IPGD", name="", category="Tasas")])


def test_search_sin_clave_no_devuelve_candidatos(monkeypatch):
    monkeypatch.setattr(fred_grounding.settings, "FRED_API_KEY", "")
    assert search_fred_concept("lo que sea") == []


def test_la_busqueda_devuelve_la_metadata_de_fred(monkeypatch):
    """The candidates carry FRED's own metadata: without it the model can't
    tell a quarterly price from a monthly quantity."""
    def handler(request):
        return httpx.Response(200, json=SEARCH_HITS)

    _install(monkeypatch, handler)
    [first, _] = search_fred_concept("total vehicle sales")

    assert first["series_id"] == "TOTALSA"
    assert first["title"] == "Total Vehicle Sales"
    assert first["frequency"] == "M"
    assert first["seasonal_adjustment"] == "SAAR"
    assert first["observation_start"] == "1976-01-01"
    assert first["units"] == "Millions of Units"
