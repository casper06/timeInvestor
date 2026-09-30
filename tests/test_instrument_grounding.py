"""4.21 — instruments checked against yfinance, and repaired by the LLM itself.

No network: yfinance is replaced by `fake_fetch`, whose payloads are the REAL
fields the live API returns (captured 2026-09-30). The provider is
`StubRepairLLM`, declared here — never a real client.

Pre-registered cases, both from the 4.10 evaluation:
  - "PSQ: inverso 3x Nasdaq-100 de Direxion" — PSQ is ProShares and -1x;
  - the ETF "IPO" (Renaissance IPO ETF) used as semiconductor exposure;
plus a ticker that doesn't exist at all.
"""
import asyncio

import pytest

from backend.schemas.models import TickerSuggestion
from backend.services.instrument_grounding import (
    DISCARDED,
    REPAIRED,
    VERIFIED,
    find_contradictions,
    ground_instruments,
)

# Exactly what yfinance .info returns for these tickers (live API, 2026-09-30).
FACTS = {
    "PSQ": {"symbol": "PSQ", "name": "ProShares Short QQQ", "quote_type": "ETF",
            "issuer": "ProShares", "category": "Trading--Inverse Equity",
            "legal_type": "Exchange Traded Fund"},
    "IPO": {"symbol": "IPO", "name": "Renaissance IPO ETF", "quote_type": "ETF",
            "issuer": "Renaissance Capital", "category": "Mid-Cap Growth",
            "legal_type": "Exchange Traded Fund"},
    "SOXX": {"symbol": "SOXX", "name": "iShares Semiconductor ETF", "quote_type": "ETF",
             "issuer": "iShares", "category": "Technology",
             "legal_type": "Exchange Traded Fund"},
    "NVDA": {"symbol": "NVDA", "name": "NVIDIA Corporation", "quote_type": "EQUITY",
             "issuer": None, "category": None, "legal_type": None},
    "SQQQ": {"symbol": "SQQQ", "name": "ProShares UltraPro Short QQQ", "quote_type": "ETF",
             "issuer": "ProShares", "category": "Trading--Inverse Equity",
             "legal_type": "Exchange Traded Fund"},
}


def fake_fetch(symbol):
    """Stands in for yfinance. Unknown tickers return None, like the real one."""
    return FACTS.get(symbol.strip().upper())


class StubRepairLLM:
    """A declared stand-in for a provider, for the repair pass only.

    Never touches the network. Records the prompts it is given and replays
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


def _ticker(**over):
    base = dict(symbol="NVDA", name="NVIDIA Corporation", sector="Tecnología",
                weight=0.25, thesis_role="Exposición a GPUs")
    base.update(over)
    return TickerSuggestion(**base)


def _run(tickers, client=None, thesis="Tesis de prueba"):
    return asyncio.run(ground_instruments(tickers, client=client, thesis=thesis, fetch=fake_fetch))


# --------------------------------------------------------------------------
# A correct instrument passes untouched
# --------------------------------------------------------------------------

def test_un_instrumento_correcto_queda_verificado():
    [out] = _run([_ticker()])
    assert out.grounding == VERIFIED
    assert out.verified_name == "NVIDIA Corporation"
    assert out.verified_type == "EQUITY"
    assert out.contradictions == []
    assert out.enters_analysis() is True
    assert out.grounding_note is None


def test_un_etf_bien_descripto_queda_verificado():
    [out] = _run([_ticker(symbol="SOXX", name="iShares Semiconductor ETF",
                          instrument_type="etf",
                          thesis_role="ETF de semiconductores de iShares")])
    assert out.grounding == VERIFIED
    assert out.verified_issuer == "iShares"


# --------------------------------------------------------------------------
# Case 1: "PSQ: inverso 3x Nasdaq-100 de Direxion"
# --------------------------------------------------------------------------

def test_psq_3x_direxion_detecta_emisor_y_apalancamiento():
    """The real 4.10 failure: wrong issuer AND wrong leverage, in one sentence."""
    item = _ticker(symbol="PSQ", name="ProShares Short QQQ", instrument_type="etf",
                   thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion")
    problems = find_contradictions(item, FACTS["PSQ"])

    assert any("Direxion" in p and "ProShares" in p for p in problems), problems
    assert any("3x" in p and "1x" in p for p in problems), problems


def test_psq_se_repara_con_los_datos_reales():
    item = _ticker(symbol="PSQ", name="ProShares Short QQQ", instrument_type="etf",
                   thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "PSQ", "accion": "corregir_descripcion",
        "thesis_role": "ETF inverso -1x del Nasdaq-100, de ProShares.",
        "justificacion": "El emisor es ProShares y el apalancamiento es -1x, no 3x de Direxion.",
    }]})

    [out] = _run([item], stub)

    assert out.grounding == REPAIRED
    assert out.thesis_role == "ETF inverso -1x del Nasdaq-100, de ProShares."
    assert out.original_thesis_role == "ETF inverso 3x del Nasdaq-100, de Direxion"
    assert "ProShares" in out.repair_justification
    assert out.enters_analysis() is True
    # The model was shown the real data and the specific contradictions.
    assert "ProShares" in stub.prompts[0]
    assert "Direxion" in stub.prompts[0]


def test_un_inverso_no_declarado_es_contradiccion():
    """SQQQ is inverse; describing it as plain exposure hides the sign."""
    item = _ticker(symbol="SQQQ", instrument_type="etf",
                   thesis_role="Exposición al Nasdaq-100 vía ProShares")
    problems = find_contradictions(item, FACTS["SQQQ"])
    assert any("inverso" in p for p in problems), problems


def test_ultrapro_se_lee_como_3x():
    """ProShares puts the multiplier in words: UltraPro = 3x."""
    item = _ticker(symbol="SQQQ", instrument_type="etf",
                   thesis_role="ETF inverso 2x del Nasdaq-100 de ProShares")
    problems = find_contradictions(item, FACTS["SQQQ"])
    assert any("2x" in p and "3x" in p for p in problems), problems


# --------------------------------------------------------------------------
# Case 2: the ETF "IPO" as semiconductor exposure
# --------------------------------------------------------------------------

def test_ipo_como_semiconductores_es_contradiccion():
    item = _ticker(symbol="IPO", name="Renaissance IPO ETF", instrument_type="etf",
                   sector="Semiconductores",
                   thesis_role="Exposición a semiconductores vía salidas a bolsa")
    problems = find_contradictions(item, FACTS["IPO"])
    assert any("semiconductores" in p and "Mid-Cap Growth" in p for p in problems), problems


def test_ipo_se_reemplaza_por_un_etf_real_de_semis():
    item = _ticker(symbol="IPO", name="Renaissance IPO ETF", instrument_type="etf",
                   sector="Semiconductores",
                   thesis_role="Exposición a semiconductores vía salidas a bolsa")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "IPO", "accion": "reemplazar_ticker", "nuevo_symbol": "SOXX",
        "thesis_role": "ETF de semiconductores de iShares.",
        "justificacion": "IPO es un fondo de salidas a bolsa, no de semiconductores.",
    }]})

    [out] = _run([item], stub)

    assert out.grounding == REPAIRED
    assert out.symbol == "SOXX"
    assert out.original_symbol == "IPO"
    assert out.verified_name == "iShares Semiconductor ETF"
    assert out.verified_issuer == "iShares"
    assert out.enters_analysis() is True


def test_un_reemplazo_que_no_existe_se_descarta():
    """The replacement is re-verified: a second invented ticker is not adopted."""
    item = _ticker(symbol="IPO", instrument_type="etf", sector="Semiconductores",
                   thesis_role="Exposición a semiconductores")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "IPO", "accion": "reemplazar_ticker", "nuevo_symbol": "SEMIX",
        "thesis_role": "ETF de semis", "justificacion": "otro",
    }]})

    [out] = _run([item], stub)
    assert out.grounding == DISCARDED
    assert out.symbol == "IPO", "no se adopta el ticker inexistente"
    assert "tampoco existe" in out.grounding_note


# --------------------------------------------------------------------------
# Case 3: a ticker that doesn't exist
# --------------------------------------------------------------------------

def test_un_ticker_inexistente_se_reemplaza():
    item = _ticker(symbol="NVDIA", name="Nvidia", thesis_role="Exposición a GPUs")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "NVDIA", "accion": "reemplazar_ticker", "nuevo_symbol": "NVDA",
        "thesis_role": "Exposición a GPUs de centro de datos.",
        "justificacion": "El ticker correcto de NVIDIA es NVDA.",
    }]})

    [out] = _run([item], stub)

    assert out.grounding == REPAIRED
    assert out.symbol == "NVDA"
    assert out.original_symbol == "NVDIA"
    assert out.verified_name == "NVIDIA Corporation"


def test_un_ticker_inexistente_no_se_arregla_reescribiendo_el_texto():
    """Rewording doesn't make a ticker exist."""
    item = _ticker(symbol="NVDIA", thesis_role="Exposición a GPUs")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "NVDIA", "accion": "corregir_descripcion",
        "thesis_role": "Texto nuevo igual de inútil.", "justificacion": "lo reescribo",
    }]})

    [out] = _run([item], stub)
    assert out.grounding == DISCARDED
    assert "solo reescribió el texto" in out.grounding_note


def test_un_ticker_inexistente_sin_reemplazo_se_descarta():
    item = _ticker(symbol="FAKEX", thesis_role="Lo que sea")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "FAKEX", "accion": "descartar",
        "justificacion": "No existe un instrumento que cubra ese rol.",
    }]})

    [out] = _run([item], stub)
    assert out.grounding == DISCARDED
    assert "No existe un instrumento" in out.grounding_note
    assert out.enters_analysis() is False


# --------------------------------------------------------------------------
# Type contradictions
# --------------------------------------------------------------------------

def test_declarar_etf_lo_que_es_accion_es_contradiccion():
    item = _ticker(symbol="NVDA", instrument_type="etf", thesis_role="ETF de GPUs")
    problems = find_contradictions(item, FACTS["NVDA"])
    assert any("ETF" in p and "acción" in p for p in problems), problems


def test_hablar_de_la_empresa_cuando_es_un_etf_es_contradiccion():
    item = _ticker(symbol="SOXX", instrument_type="etf",
                   thesis_role="La empresa lidera el mercado de semiconductores")
    problems = find_contradictions(item, FACTS["SOXX"])
    assert any("es un ETF" in p for p in problems), problems


# --------------------------------------------------------------------------
# What must NOT be flagged
# --------------------------------------------------------------------------

def test_una_afirmacion_no_verificable_no_es_contradiccion():
    """yfinance can confirm an issuer, not whether a company leads a market."""
    item = _ticker(symbol="NVDA", thesis_role="Líder indiscutido del mercado de GPUs de IA")
    assert find_contradictions(item, FACTS["NVDA"]) == []


def test_sin_apalancamiento_en_yfinance_no_se_contradice_el_del_llm():
    """Absence of evidence is not evidence of absence: SOXX reports no
    multiplier, so a claimed one is left alone rather than called false."""
    item = _ticker(symbol="SOXX", instrument_type="etf",
                   thesis_role="ETF de semiconductores 1x de iShares")
    problems = find_contradictions(item, FACTS["SOXX"])
    assert not any("apalancamiento" in p for p in problems), problems


def test_un_emisor_no_mencionado_no_es_contradiccion():
    item = _ticker(symbol="SOXX", instrument_type="etf", thesis_role="ETF de semiconductores")
    assert find_contradictions(item, FACTS["SOXX"]) == []


# --------------------------------------------------------------------------
# No LLM, and failures
# --------------------------------------------------------------------------

def test_sin_llm_una_descripcion_falsa_se_descarta():
    """A false description is never silently kept."""
    item = _ticker(symbol="PSQ", instrument_type="etf",
                   thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion")
    [out] = _run([item], None)

    assert out.grounding == DISCARDED
    assert "no hay un LLM disponible" in out.grounding_note
    assert out.enters_analysis() is False


def test_un_proveedor_sin_complete_json_es_lo_mismo_que_sin_llm():
    class MockLike:
        supports_json_completion = False

    [out] = _run([_ticker(symbol="FAKEX")], MockLike())
    assert out.grounding == DISCARDED


def test_si_la_correccion_falla_se_descarta():
    item = _ticker(symbol="PSQ", instrument_type="etf",
                   thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion")
    [out] = _run([item], StubRepairLLM(RuntimeError("el proveedor se cayo")))
    assert out.grounding == DISCARDED
    assert "fall" in out.grounding_note


def test_yfinance_caido_deja_el_instrumento_sin_verificar():
    def boom(symbol):
        raise RuntimeError("yfinance no responde")

    [out] = asyncio.run(ground_instruments([_ticker()], client=None, fetch=boom))
    assert out.grounding is None
    assert out.symbol == "NVDA", "no se descarta por un problema de red"
    assert "no respondió" in out.grounding_note
    assert out.enters_analysis() is False


# --------------------------------------------------------------------------
# The whole pre-registered case, in one pass
# --------------------------------------------------------------------------

def test_caso_completo_psq_ipo_inexistente_y_uno_bueno():
    stub = StubRepairLLM({"decisiones": [
        {"symbol": "PSQ", "accion": "corregir_descripcion",
         "thesis_role": "ETF inverso -1x del Nasdaq-100, de ProShares.",
         "justificacion": "Es ProShares y -1x."},
        {"symbol": "IPO", "accion": "reemplazar_ticker", "nuevo_symbol": "SOXX",
         "thesis_role": "ETF de semiconductores de iShares.",
         "justificacion": "IPO no es de semiconductores."},
        {"symbol": "FAKEX", "accion": "descartar", "justificacion": "No existe."},
    ]})

    out = _run([
        _ticker(symbol="PSQ", instrument_type="etf", thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion"),
        _ticker(symbol="IPO", instrument_type="etf", sector="Semiconductores",
                thesis_role="Exposición a semiconductores"),
        _ticker(symbol="FAKEX", thesis_role="Lo que sea"),
        _ticker(symbol="NVDA", thesis_role="Exposición a GPUs"),
    ], stub)

    assert [t.grounding for t in out] == [REPAIRED, REPAIRED, DISCARDED, VERIFIED]
    assert [t.symbol for t in out] == ["PSQ", "SOXX", "FAKEX", "NVDA"]
    assert [t.enters_analysis() for t in out] == [True, True, False, True]
    assert len(stub.prompts) == 1, "una sola llamada extra para los tres problematicos"


def test_una_correccion_que_sigue_mintiendo_queda_marcada():
    """The repair isn't trusted just because it came from the model: if the new
    text still contradicts the data, it's recorded instead of quietly accepted.
    A second round would be a loop."""
    item = _ticker(symbol="PSQ", instrument_type="etf",
                   thesis_role="ETF inverso 3x del Nasdaq-100, de Direxion")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "PSQ", "accion": "corregir_descripcion",
        "thesis_role": "ETF inverso 3x del Nasdaq-100, de Direxion (sigue mal).",
        "justificacion": "no cambié nada real",
    }]})

    [out] = _run([item], stub)

    assert out.grounding == REPAIRED
    assert out.contradictions, "la contradicción que quedó se registra"
    assert "todavía no coincide" in out.grounding_note


def test_un_reemplazo_con_descripcion_coherente_queda_limpio():
    item = _ticker(symbol="IPO", instrument_type="etf", sector="Semiconductores",
                   thesis_role="Exposición a semiconductores")
    stub = StubRepairLLM({"decisiones": [{
        "symbol": "IPO", "accion": "reemplazar_ticker", "nuevo_symbol": "SOXX",
        "thesis_role": "ETF de semiconductores de iShares.",
        "justificacion": "IPO no es de semis.",
    }]})

    [out] = _run([item], stub)
    assert out.grounding == REPAIRED
    assert out.contradictions == []
