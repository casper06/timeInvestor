"""4.11 — every FRED ID the LLM proposes is checked against FRED before the UI.

No network and no keys: FRED's two endpoints (/fred/series for existence,
/fred/series/search for the concept) are served by httpx.MockTransport, with
the bodies the real API returns (shapes verified against the live API on
2026-09-26/27 and recorded in docs/PLAN.md 4.11).

Cases, as pre-registered: TOTALSI and IPGD (the LLM invents them; they do not
exist) and UMCSENT (real).
"""
import httpx
import pytest

from backend.schemas.models import MacroSuggestion
from backend.services import fred_grounding
from backend.services.fred_grounding import (
    DISCARDED,
    SUGGESTED,
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
        {"id": "TOTALSA", "title": "Total Vehicle Sales"},
        {"id": "ALTSALES", "title": "Light Weight Vehicle Sales"},
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


def test_umcsent_existe_queda_verificado(monkeypatch):
    """A real ID is kept as-is and carries FRED's own title."""
    def handler(request):
        assert "/fred/series" in str(request.url)
        assert "search" not in str(request.url), "no se busca un ID que existe"
        return httpx.Response(200, json=UMCSENT_META)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="UMCSENT", name="Confianza del consumidor", category="Consumo")
    [out] = ground_macro_series([item])

    assert out.series_id == "UMCSENT"
    assert out.grounding == VERIFIED
    assert out.fred_title == "University of Michigan: Consumer Sentiment"
    assert out.proposed_series_id is None
    assert out.grounding_note is None


@pytest.mark.parametrize("fake_id", ["TOTALSI", "IPGD"])
def test_id_inventado_se_reemplaza_por_candidato_real(monkeypatch, fake_id):
    """TOTALSI / IPGD don't exist: the concept is searched and a REAL candidate
    is proposed, marked as suggested, keeping the original ID on the record."""
    seen = {"search_text": None}

    def handler(request):
        url = str(request.url)
        if "/fred/series/search" in url:
            seen["search_text"] = dict(request.url.params).get("search_text")
            return httpx.Response(200, json=SEARCH_HITS)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id=fake_id, name="Ventas totales de vehiculos", category="Consumo")
    [out] = ground_macro_series([item])

    assert out.grounding == SUGGESTED
    assert out.series_id == "TOTALSA", "se usa el ID real que devolvio FRED"
    assert out.proposed_series_id == fake_id
    assert out.fred_title == "Total Vehicle Sales"
    assert fake_id in out.grounding_note and "TOTALSA" in out.grounding_note
    assert seen["search_text"] == "Ventas totales de vehiculos", "se busca el concepto del LLM"


def test_id_inventado_sin_candidato_se_descarta(monkeypatch):
    """No candidate either: discarded, with a visible warning. The ID is never
    silently kept."""
    def handler(request):
        if "/fred/series/search" in str(request.url):
            return httpx.Response(200, json={"seriess": []})
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="TOTALSI", name="Concepto inexistente", category="Macro")
    [out] = ground_macro_series([item])

    assert out.grounding == DISCARDED
    assert out.proposed_series_id == "TOTALSI"
    assert "no existe en FRED" in out.grounding_note
    assert "no encontro" in out.grounding_note or "encontr" in out.grounding_note


def test_sin_clave_no_inventa_ni_rompe(monkeypatch):
    """Without a FRED key nothing can be verified: the LLM's ID is kept, marked
    unverified. Dropping real series because the key is missing would be worse."""
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("no se debe llamar a FRED sin clave")

    _install(monkeypatch, handler, key="")
    item = MacroSuggestion(series_id="TOTALSI", name="Lo que sea", category="Macro")
    [out] = ground_macro_series([item])

    assert out.grounding is None
    assert out.series_id == "TOTALSI"
    assert "No se pudo verificar" in out.grounding_note


def test_fred_caido_no_descarta_series(monkeypatch):
    """A 500 from FRED is not "does not exist": the series survives, unverified."""
    def handler(request):
        return httpx.Response(500, text="boom")

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="UMCSENT", name="Confianza", category="Consumo")
    [out] = ground_macro_series([item])

    assert out.grounding is None
    assert out.series_id == "UMCSENT"
    assert "no respondi" in out.grounding_note


def test_busqueda_usa_category_si_no_hay_name(monkeypatch):
    def handler(request):
        if "/fred/series/search" in str(request.url):
            assert dict(request.url.params).get("search_text") == "Tasas"
            return httpx.Response(200, json=SEARCH_HITS)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(series_id="IPGD", name="", category="Tasas")
    [out] = ground_macro_series([item])
    assert out.grounding == SUGGESTED


def test_search_sin_clave_devuelve_none(monkeypatch):
    monkeypatch.setattr(fred_grounding.settings, "FRED_API_KEY", "")
    assert search_fred_concept("lo que sea") is None


def test_mezcla_de_series_conserva_orden(monkeypatch):
    """A real one, an invented one and a discarded one: order is preserved and
    each carries its own verdict."""
    def handler(request):
        url = str(request.url)
        if "/fred/series/search" in url:
            text = dict(request.url.params).get("search_text")
            if text == "Ventas de vehiculos":
                return httpx.Response(200, json=SEARCH_HITS)
            return httpx.Response(200, json={"seriess": []})
        if "series_id=UMCSENT" in url:
            return httpx.Response(200, json=UMCSENT_META)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    out = ground_macro_series([
        MacroSuggestion(series_id="UMCSENT", name="Confianza", category="Consumo"),
        MacroSuggestion(series_id="TOTALSI", name="Ventas de vehiculos", category="Consumo"),
        MacroSuggestion(series_id="IPGD", name="Nada parecido", category="Macro"),
    ])

    assert [s.grounding for s in out] == [VERIFIED, SUGGESTED, DISCARDED]
    assert [s.series_id for s in out] == ["UMCSENT", "TOTALSA", "IPGD"]


def test_busca_con_el_concepto_en_ingles(monkeypatch):
    """FRED's search index is English-only (verified 2026-09-29: "new home
    sales" -> 2986 hits, the same concept in Spanish -> 0). The English concept
    wins over the Spanish `name`, or every invented ID would be discarded."""
    seen = {}

    def handler(request):
        if "/fred/series/search" in str(request.url):
            seen["search_text"] = dict(request.url.params).get("search_text")
            return httpx.Response(200, json={"seriess": [{"id": "MSPUS", "title": "Median Sales Price of New Houses Sold"}]})
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    item = MacroSuggestion(
        series_id="TOTALSI",
        name="Ventas totales de viviendas nuevas",
        category="Vivienda",
        search_concept_en="new home sales",
    )
    [out] = ground_macro_series([item])

    assert seen["search_text"] == "new home sales"
    assert out.series_id == "MSPUS"
    assert out.grounding == SUGGESTED


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
    [out] = ground_macro_series([MacroSuggestion(series_id="IPGD", name="Vehicle sales", category="Consumo")])
    assert seen["search_text"] == "Vehicle sales"
    assert out.grounding == SUGGESTED
