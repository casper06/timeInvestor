"""4.11 — the LLM repairs its own invalid FRED IDs, in one extra call.

No network and no keys: FRED's endpoints are served by httpx.MockTransport with
the bodies the real API returns, and the provider is `StubRepairLLM` — declared
here, never a real client. It records the prompt it was given and replays a
scripted answer, so a test can assert both what the model was shown and what
the code does with its reply. The real Claude CLI Sonnet run is in ADR-0033.

Cases, as pre-registered: TOTALSI and IPGD (invented, don't exist) and UMCSENT
(real).
"""
import asyncio

import httpx
import pytest

from backend.schemas.models import MacroSuggestion
from backend.services import fred_grounding
from backend.services.fred_grounding import (
    DISCARDED,
    REPAIRED,
    VERIFIED,
    ground_macro_series,
)

NOT_EXIST = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}

UMCSENT_META = {"seriess": [{"id": "UMCSENT", "title": "University of Michigan: Consumer Sentiment"}]}
HSN1F_META = {"seriess": [{"id": "HSN1F", "title": "New One Family Houses Sold: United States"}]}

# What fred/series/search really returns for "new home sales" (live API,
# 2026-09-29): MSPUS first — a PRICE, for a thesis about how many houses get
# built. That is exactly why the model, and not the ranking, decides.
SEARCH_HOME = {
    "seriess": [
        {"id": "MSPUS", "title": "Median Sales Price of New Houses Sold for the United States",
         "frequency_short": "Q", "seasonal_adjustment_short": "NSA",
         "observation_start": "1963-01-01", "observation_end": "2026-04-01", "units_short": "$"},
        {"id": "ASPUS", "title": "Average Sales Price of Houses Sold for the United States",
         "frequency_short": "Q", "seasonal_adjustment_short": "NSA",
         "observation_start": "1963-01-01", "observation_end": "2026-04-01", "units_short": "$"},
        {"id": "HSN1F", "title": "New One Family Houses Sold: United States",
         "frequency_short": "M", "seasonal_adjustment_short": "SAAR",
         "observation_start": "1963-01-01", "observation_end": "2026-08-01",
         "units_short": "Thousands of Units"},
    ]
}


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    from backend.services.data_fetcher import cache
    monkeypatch.setattr(cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(cache, "set", lambda *a, **k: None)


def _install(monkeypatch, handler, key="test-key"):
    import backend.services.data_fetcher as df

    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(df.httpx, "Client", fake_client)
    monkeypatch.setattr(fred_grounding.httpx, "Client", fake_client)
    monkeypatch.setattr(df.settings, "FRED_API_KEY", key)
    monkeypatch.setattr(fred_grounding.settings, "FRED_API_KEY", key)


class StubRepairLLM:
    """A declared stand-in for a provider, for the repair pass only.

    Never touches the network. Records every prompt it is given and returns the
    scripted answers in order.
    """
    supports_json_completion = True

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    async def complete_json(self, system_prompt, user_prompt, json_schema):
        self.prompts.append(user_prompt)
        if not self.answers:
            raise AssertionError("StubRepairLLM recibio mas llamadas que respuestas")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _home_handler(request):
    url = str(request.url)
    if "/fred/series/search" in url:
        return httpx.Response(200, json=SEARCH_HOME)
    if "series_id=HSN1F" in url:
        return httpx.Response(200, json=HSN1F_META)
    if "series_id=UMCSENT" in url:
        return httpx.Response(200, json=UMCSENT_META)
    return httpx.Response(400, json=NOT_EXIST)


def _totalsi():
    return MacroSuggestion(series_id="TOTALSI", name="Ventas totales de viviendas nuevas",
                           category="Vivienda", search_concept_en="new home sales")


def _run(series, client, mechanism="Las tasas altas frenan los inicios de obra."):
    return asyncio.run(ground_macro_series(series, client=client, mechanism=mechanism))


# --------------------------------------------------------------------------
# 1. The repair pass picks FROM the candidate list
# --------------------------------------------------------------------------

def test_la_reparacion_elige_de_la_lista(monkeypatch):
    _install(monkeypatch, _home_handler)
    stub = StubRepairLLM({"decisiones": [{
        "id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HSN1F",
        "justificacion": "Mide cantidad de viviendas vendidas, no su precio.",
    }]})

    [out] = _run([_totalsi()], stub)

    assert out.grounding == REPAIRED
    assert out.series_id == "HSN1F"
    assert out.proposed_series_id == "TOTALSI"
    assert out.fred_title == "New One Family Houses Sold: United States"
    assert out.repair_justification == "Mide cantidad de viviendas vendidas, no su precio."
    assert out.enters_analysis() is True
    assert out.candidates == []

    prompt = stub.prompts[0]
    assert "frenan los inicios de obra" in prompt, "el mecanismo va en el pedido"
    assert "MSPUS" in prompt and "HSN1F" in prompt, "van los candidatos"
    assert "Thousands of Units" in prompt, "con su metadata"


def test_no_adopta_el_primer_resultado_de_la_busqueda(monkeypatch):
    """MSPUS ranks first; the model picked HSN1F. The ranking never decides."""
    _install(monkeypatch, _home_handler)
    stub = StubRepairLLM({"decisiones": [{
        "id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HSN1F",
        "justificacion": "Cantidad, no precio.",
    }]})
    [out] = _run([_totalsi()], stub)
    assert out.series_id == "HSN1F"
    assert out.series_id != "MSPUS"


# --------------------------------------------------------------------------
# 2. An ID outside the candidate list is rejected
# --------------------------------------------------------------------------

def test_un_id_fuera_de_la_lista_se_rechaza(monkeypatch):
    """The model invents another ID instead of choosing: rejected and discarded,
    never trusted just because it looks real."""
    _install(monkeypatch, _home_handler)
    stub = StubRepairLLM({"decisiones": [{
        "id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HOUSTNSA",
        "justificacion": "Me parece mejor.",
    }]})

    [out] = _run([_totalsi()], stub)

    assert out.grounding == DISCARDED
    assert out.series_id == "TOTALSI", "no se adopta el ID inventado"
    assert "no estaba entre los candidatos" in out.grounding_note
    assert out.enters_analysis() is False


def test_un_elegido_que_fred_no_confirma_se_descarta(monkeypatch):
    """The candidate came from FRED, but the choice is verified again on the way
    back: if FRED doesn't confirm it, the series is discarded."""
    def handler(request):
        if "/fred/series/search" in str(request.url):
            return httpx.Response(200, json=SEARCH_HOME)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    stub = StubRepairLLM({"decisiones": [{
        "id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HSN1F", "justificacion": "x",
    }]})

    [out] = _run([_totalsi()], stub)
    assert out.grounding == DISCARDED
    assert "no pudo verificarse" in out.grounding_note


# --------------------------------------------------------------------------
# 3. "descartar"
# --------------------------------------------------------------------------

def test_descartar_funciona_con_su_motivo(monkeypatch):
    _install(monkeypatch, _home_handler)
    stub = StubRepairLLM({"decisiones": [{
        "id_invalido": "TOTALSI", "accion": "descartar",
        "justificacion": "Ningun candidato mide inicios de construccion.",
    }]})

    [out] = _run([_totalsi()], stub)

    assert out.grounding == DISCARDED
    assert "Ningun candidato mide inicios de construccion." in out.grounding_note
    assert out.enters_analysis() is False


def test_si_la_reparacion_no_se_pronuncia_se_descarta(monkeypatch):
    _install(monkeypatch, _home_handler)
    [out] = _run([_totalsi()], StubRepairLLM({"decisiones": []}))
    assert out.grounding == DISCARDED
    assert "no se pronunci" in out.grounding_note


# --------------------------------------------------------------------------
# 4. One reformulation, and no more
# --------------------------------------------------------------------------

def test_una_reformulacion_y_despues_elige(monkeypatch):
    seen = []

    def handler(request):
        url = str(request.url)
        if "/fred/series/search" in url:
            seen.append(dict(request.url.params).get("search_text"))
            return httpx.Response(200, json=SEARCH_HOME)
        if "series_id=HSN1F" in url:
            return httpx.Response(200, json=HSN1F_META)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    stub = StubRepairLLM(
        {"decisiones": [{"id_invalido": "TOTALSI", "accion": "reformular",
                         "nueva_busqueda": "housing starts", "justificacion": "Busco inicios de obra."}]},
        {"decisiones": [{"id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HSN1F",
                         "justificacion": "Es lo mas cercano a cantidad construida."}]},
    )

    [out] = _run([_totalsi()], stub)

    assert seen == ["new home sales", "housing starts"], "se reformulo exactamente una vez"
    assert out.grounding == REPAIRED
    assert out.series_id == "HSN1F"
    assert out.reformulations == 1
    assert len(stub.prompts) == 2


def test_una_segunda_reformulacion_no_se_concede(monkeypatch):
    """The budget is one. Asking again ends in a discard, never a loop."""
    _install(monkeypatch, _home_handler)
    reformulate = {"decisiones": [{"id_invalido": "TOTALSI", "accion": "reformular",
                                   "nueva_busqueda": "housing starts", "justificacion": "otra vez"}]}
    stub = StubRepairLLM(reformulate, reformulate)

    [out] = _run([_totalsi()], stub)

    assert out.grounding == DISCARDED
    assert out.reformulations == 1
    assert len(stub.prompts) == 2, "dos llamadas como mucho: la inicial y la reformulada"


def test_una_reformulacion_sin_candidatos_se_descarta(monkeypatch):
    def handler(request):
        if "/fred/series/search" in str(request.url):
            text = dict(request.url.params).get("search_text")
            return httpx.Response(200, json=SEARCH_HOME if text == "new home sales" else {"seriess": []})
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    stub = StubRepairLLM({"decisiones": [{"id_invalido": "TOTALSI", "accion": "reformular",
                                          "nueva_busqueda": "nada de nada", "justificacion": "probemos"}]})
    [out] = _run([_totalsi()], stub)
    assert out.grounding == DISCARDED
    assert "reformulada" in out.grounding_note


# --------------------------------------------------------------------------
# 5. No LLM: discard. Never the search's first hit.
# --------------------------------------------------------------------------

def test_sin_llm_se_descarta_nunca_el_primer_resultado(monkeypatch):
    _install(monkeypatch, _home_handler)
    [out] = _run([_totalsi()], None)

    assert out.grounding == DISCARDED
    assert out.series_id == "TOTALSI", "no se adopta MSPUS ni ningun otro candidato"
    assert "no hay un LLM disponible" in out.grounding_note
    assert out.enters_analysis() is False


def test_un_proveedor_sin_complete_json_es_lo_mismo_que_sin_llm(monkeypatch):
    """The mock has supports_json_completion = False."""
    class MockLike:
        supports_json_completion = False

    _install(monkeypatch, _home_handler)
    [out] = _run([_totalsi()], MockLike())
    assert out.grounding == DISCARDED
    assert "no hay un LLM disponible" in out.grounding_note


def test_si_la_reparacion_falla_se_descarta(monkeypatch):
    _install(monkeypatch, _home_handler)
    stub = StubRepairLLM(RuntimeError("el proveedor se cayo"))
    [out] = _run([_totalsi()], stub)
    assert out.grounding == DISCARDED
    assert "falló" in out.grounding_note or "fall" in out.grounding_note
    assert out.series_id == "TOTALSI"


# --------------------------------------------------------------------------
# 6. The whole pre-registered case, in one pass
# --------------------------------------------------------------------------

def test_caso_completo_totalsi_ipgd_umcsent(monkeypatch):
    """One translation: one real ID, one repaired, one discarded — and a single
    extra call covering both invalid ones."""
    def handler(request):
        url = str(request.url)
        if "/fred/series/search" in url:
            text = dict(request.url.params).get("search_text")
            if text == "new home sales":
                return httpx.Response(200, json=SEARCH_HOME)
            return httpx.Response(200, json={"seriess": [
                {"id": "IPG3344S", "title": "Industrial Production: Semiconductor",
                 "frequency_short": "M", "seasonal_adjustment_short": "SA",
                 "observation_start": "1972-01-01", "observation_end": "2026-08-01",
                 "units_short": "Index 2017=100"}]})
        if "series_id=UMCSENT" in url:
            return httpx.Response(200, json=UMCSENT_META)
        if "series_id=HSN1F" in url:
            return httpx.Response(200, json=HSN1F_META)
        return httpx.Response(400, json=NOT_EXIST)

    _install(monkeypatch, handler)
    stub = StubRepairLLM({"decisiones": [
        {"id_invalido": "TOTALSI", "accion": "elegir", "series_id": "HSN1F",
         "justificacion": "Cantidad de viviendas vendidas."},
        {"id_invalido": "IPGD", "accion": "descartar",
         "justificacion": "Solo hay semiconductores, no bienes duraderos en general."},
    ]})

    out = _run([
        _totalsi(),
        MacroSuggestion(series_id="IPGD", name="Produccion industrial de bienes duraderos",
                        category="Industria", search_concept_en="industrial production durable goods"),
        MacroSuggestion(series_id="UMCSENT", name="Confianza del consumidor", category="Consumo"),
    ], stub)

    assert [s.grounding for s in out] == [REPAIRED, DISCARDED, VERIFIED]
    assert [s.series_id for s in out] == ["HSN1F", "IPGD", "UMCSENT"]
    assert [s.enters_analysis() for s in out] == [True, False, True]
    assert len(stub.prompts) == 1, "una sola llamada extra para los dos invalidos"


def test_el_copiloto_recibe_los_descartados_como_sin_medir():
    """Defensive check (4.11): a discarded ID measures nothing, so the copilot
    is told the link went unmeasured instead of it quietly disappearing."""
    from backend.schemas.models import InterpretationContext
    from backend.services.copilot_context import interpretation_context_text

    ctx = InterpretationContext(
        thesis="Las tasas hipotecarias frenan la construccion",
        active_series_id="MORTGAGE30US",
        last_price=6.3, projected_target=6.0, lower_bound=5.5, upper_bound=6.5,
        series_type="macro",
        macro_series=["MORTGAGE30US"],
        unresolved_macro_series=["IPGD"],
    )
    text = interpretation_context_text(ctx)

    assert "Sin medir: IPGD" in text
    assert "- IPGD:" not in text, "no aparece como evidencia medida"


def test_sin_descartados_el_contexto_no_habla_de_sin_medir():
    from backend.schemas.models import InterpretationContext
    from backend.services.copilot_context import interpretation_context_text

    ctx = InterpretationContext(
        thesis="t", active_series_id="MORTGAGE30US", last_price=1.0, projected_target=1.0,
        lower_bound=0.9, upper_bound=1.1, series_type="macro", macro_series=["MORTGAGE30US"],
    )
    assert "Sin medir" not in interpretation_context_text(ctx)
