"""
What the copilot receives (fix/copilot-context): today's date and the period
of every figure, the FRED evidence, the LLM-picked companies labeled as such,
the missing data said out loud, and the same context and rules in every client
(Gemini, Gemini CLI, Claude CLI, OpenAI, Ollama) and in the mock. No network.
"""
import asyncio
import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.models import FundamentalsMetric, InterpretationContext, MacroEvidence, TimeSeriesData, TimeSeriesPoint
from backend.services import copilot_context
from backend.services import llm_router as lr
from backend.services.copilot_context import build_macro_evidence, interpretation_context_text

RULE = "Afirmá solo lo que está en los datos recibidos"
TODAY = date.today().isoformat()


def _fund(ticker, capex, revenue):
    return [FundamentalsMetric(ticker=ticker, metric="Capex (Billions USD)", period=p, value=v) for p, v in capex] + \
           [FundamentalsMetric(ticker=ticker, metric="Revenue (Billions USD)", period=p, value=v) for p, v in revenue]


def _ctx(**over):
    base = dict(
        thesis="Demanda eléctrica por centros de datos de IA", active_series_id="CEG",
        active_series_name="Constellation Energy", last_price=300.0, projected_target=310.0, horizon=60,
        frequency="daily", lower_bound=250.0, upper_bound=370.0, cagr=12.0,
        other_tickers=["ETN", "VST", "GEV", "PWR"], macro_series=["IPG2211A2N"],
        series_type="equity", last_observation_date="2026-09-25", target_date="2026-12-18",
        fundamentals=_fund("CEG", [("2025", 2.949), ("2024", 2.565)], [("2025", 25.533)])
        + _fund("ETN", [("2025", 0.919)], [("2025", 27.448)]),
        macro_evidence=[MacroEvidence(series_id="IPG2211A2N", name="Industrial Production: Electric and Gas Utilities",
                                      unit="Index 2017=100", frequency="monthly", last_date="2026-07-01",
                                      last_value=125.47, prior_date="2025-07-01", prior_value=121.0,
                                      change_abs=4.47, change_pct=3.694)],
    )
    base.update(over)
    return InterpretationContext(**base)


# ---- the context text ----

def test_context_has_today_and_the_period_of_every_figure():
    text = interpretation_context_text(_ctx(), today=date(2026, 9, 27))
    assert "Fecha de hoy: 2026-09-27." in text
    assert "Último precio real: 300.0000 (dato del 2026-09-25)" in text
    assert "al 2026-12-18" in text and "no es un dato" in text
    assert "CEG: capex: último ejercicio cerrado 2025: 2.95 B USD (2024: 2.56)" in text or \
           "CEG: capex: último ejercicio cerrado 2025: 2.95 B USD (2024: 2.57)" in text
    assert "ingresos: último ejercicio cerrado 2025: 25.53 B USD" in text
    assert "IPG2211A2N (Industrial Production: Electric and Gas Utilities): último dato 125.5 Index 2017=100 (2026-07-01, monthly)" in text
    assert "hace 12 meses 121 (2025-07-01): cambio +4.47, +3.7%" in text


def test_llm_picked_companies_are_labeled_and_missing_data_is_said():
    text = interpretation_context_text(_ctx())
    assert "Empresas de la cartera (no una muestra representativa; sus números no confirman la tesis):" in text
    assert "- Elegidas por el LLM al traducir la tesis: CEG, ETN, VST, GEV, PWR" in text
    assert "Sin fundamentales: VST, GEV, PWR (no se recibieron datos)." in text


def test_macro_series_speaks_of_value_not_price_and_no_macro_is_said():
    text = interpretation_context_text(_ctx(series_type="macro", active_series_id="IPG2211A2N", macro_series=[],
                                            macro_evidence=[]))
    assert "Último valor real" in text and "precio" not in text.split("Empresas")[0].lower()
    assert "Ninguna serie macro en la tesis" in text


def test_old_clients_capex_summary_keeps_its_periods():
    text = interpretation_context_text(_ctx(fundamentals=None, capex_summary={"CEG_2025": 2.949, "CEG_2024": 2.565}))
    assert "CEG: capex: último ejercicio cerrado 2025: 2.95 B USD" in text


# ---- FRED evidence ----

def test_build_macro_evidence_computes_the_12_month_change_and_keeps_failures(monkeypatch):
    def fake(sid):
        if sid == "NOPE":
            raise ValueError("La serie 'NOPE' no existe en FRED")
        pts = [TimeSeriesPoint(timestamp=f"{2025 + (m // 12)}-{m % 12 + 1:02d}-01", value=100.0 + m) for m in range(19)]
        return TimeSeriesData(id=sid, name="Idx", type="macro", unit="Index", points=pts, source="live")
    monkeypatch.setattr(copilot_context, "_fetch_series", fake)
    ev = build_macro_evidence(["IDX", "nope"])
    assert ev[0].last_date == "2026-07-01" and ev[0].last_value == 118.0
    assert ev[0].prior_date == "2025-07-01" and ev[0].prior_value == 106.0
    assert ev[0].change_pct == pytest.approx((118 / 106 - 1) * 100)
    assert ev[1].series_id == "NOPE" and "no existe en FRED" in ev[1].missing_reason


def test_interpret_route_fills_the_fred_evidence(monkeypatch):
    def fake(sid):
        pts = [TimeSeriesPoint(timestamp=f"{2025 + (m // 12)}-{m % 12 + 1:02d}-01", value=100.0 + m) for m in range(19)]
        return TimeSeriesData(id=sid, name="Idx", type="macro", unit="Index", points=pts, source="live")
    monkeypatch.setattr(copilot_context, "_fetch_series", fake)
    monkeypatch.setattr(lr.settings, "LLM_PROVIDER", "mock")
    r = TestClient(app).post("/api/interpret", json={
        "thesis": "t", "active_series_id": "CEG", "last_price": 1.0, "projected_target": 1.1,
        "lower_bound": 0.9, "upper_bound": 1.2, "other_tickers": ["VST"], "macro_series": ["IPG2211A2N"],
        "series_type": "equity",
    })
    assert r.status_code == 200, r.text
    assert "IPG2211A2N subió +11.3% en 12 meses (último dato 2026-07-01)" in r.json()["thesis_alignment"]


# ---- every client gets the same context and rules ----

PAYLOAD = {"what_data_says": "a", "thesis_alignment": "b", "next_series_suggestion": "c", "suggested_series_id": "IPG2211A2N"}


def _check(prompt_text: str):
    assert f"Fecha de hoy: {TODAY}." in prompt_text
    assert "último ejercicio cerrado 2025" in prompt_text
    assert "Sin fundamentales: VST, GEV, PWR" in prompt_text
    assert RULE in prompt_text


def test_gemini_api_gets_the_context_and_rules():
    client = object.__new__(lr.GeminiLLMClient)
    client.api_key = "k"
    client._client = MagicMock()
    client._client.models.generate_content.return_value = MagicMock(text=json.dumps(PAYLOAD), candidates=[])
    asyncio.run(client.interpret_situation(_ctx()))
    _check(client._client.models.generate_content.call_args.kwargs["contents"])


@pytest.mark.parametrize("cls", ["GeminiCliLLMClient", "ClaudeCliLLMClient"])
def test_cli_clients_get_the_context_and_rules(cls):
    client = object.__new__(getattr(lr, cls))
    client.model = "haiku"
    seen = {}

    def fake_run(prompt, system_prompt=None, json_schema=None):
        seen["text"] = prompt + "\n" + (system_prompt or "")
        return dict(PAYLOAD)
    client._run = fake_run
    asyncio.run(client.interpret_situation(_ctx()))
    _check(seen["text"])


@pytest.mark.parametrize("cls,field", [("OpenAILLMClient", "messages"), ("OllamaLLMClient", "prompt")])
def test_http_clients_get_the_context_and_rules(monkeypatch, cls, field):
    seen = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            content = json.dumps(PAYLOAD)
            return {"choices": [{"message": {"content": content}}], "response": content}

    class FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["payload"] = json
            return FakeResp()

    monkeypatch.setattr(lr.httpx, "AsyncClient", FakeAsyncClient)
    client = getattr(lr, cls)(api_key="k") if cls == "OpenAILLMClient" else getattr(lr, cls)()
    asyncio.run(client.interpret_situation(_ctx()))
    p = seen["payload"]
    text = "\n".join(m["content"] for m in p["messages"]) if field == "messages" else p["prompt"]
    _check(text)


# ---- the mock says only what the data says ----

def test_mock_does_not_confirm_the_thesis_with_the_companies():
    resp = asyncio.run(lr.MockLLMClient().interpret_situation(_ctx(active_series_id="NVDA", other_tickers=["CEG", "VST"])))
    text = " ".join([resp.what_data_says, resp.thesis_alignment, resp.next_series_suggestion]).lower()
    # The old mock's claims, none of them in the data it received.
    for claim in ("confirman la", "respaldan", "hiperescaladores", "escasez de megavatios", "anuncios de capex"):
        assert claim not in text
    assert "no son una muestra representativa" in resp.thesis_alignment
    assert "Faltan fundamentales de: NVDA, VST." in resp.thesis_alignment
    assert "IPG2211A2N subió +3.7% en 12 meses" in resp.thesis_alignment
    assert resp.suggested_series_id == "IPG2211A2N"


def test_mock_without_world_evidence_says_it_cannot_tell():
    resp = asyncio.run(lr.MockLLMClient().interpret_situation(_ctx(macro_series=[], macro_evidence=[])))
    assert "no se puede decir si los datos confirman o contradicen la tesis" in resp.thesis_alignment


def test_evidence_uses_freds_title_and_units_never_a_guessed_unit(monkeypatch):
    def fake(sid):
        pts = [TimeSeriesPoint(timestamp=f"{2025 + (m // 12)}-{m % 12 + 1:02d}-01", value=3.5 + m * 0.05) for m in range(19)]
        if sid == "RATEX":   # FRED answered its metadata (fix/fred-metadata)
            return TimeSeriesData(id=sid, name="Market Yield on 10-Year", type="macro", unit="Percent", points=pts,
                                  source="live", metadata_source="fred", source_frequency="Monthly",
                                  seasonal_adjustment_short="NSA")
        return TimeSeriesData(id=sid, name=sid, type="macro", unit=None, points=pts, source="live",
                              metadata_source="unavailable", metadata_note="metadatos no disponibles: x")
    monkeypatch.setattr(copilot_context, "_fetch_series", fake)
    rate, unknown = build_macro_evidence(["RATEX", "PCUX"])
    assert rate.name == "Market Yield on 10-Year" and rate.unit == "Percent" and rate.seasonal_adjustment_short == "NSA"
    assert unknown.name is None and unknown.unit is None   # not "FRED Series PCUX" / "Index"
    text = interpretation_context_text(_ctx(macro_evidence=[rate, unknown]))
    assert "RATEX (Market Yield on 10-Year): último dato 4.4 Percent (2026-07-01, Monthly, NSA)" in text
    assert "cambio +0.60 puntos porcentuales" in text and "%" not in text.split("RATEX")[1].split("\n")[0].replace("Percent", "")
    assert "PCUX (título no informado): último dato 4.4 (unidad no informada)" in text
    mock = asyncio.run(lr.MockLLMClient().interpret_situation(_ctx(macro_evidence=[rate])))
    assert "RATEX subió +0.60 puntos porcentuales en 12 meses" in mock.thesis_alignment


# ---- who picked the companies: the LLM (or the user), never "manually" ----

def test_user_added_tickers_are_not_called_llm_picks():
    text = interpretation_context_text(_ctx(user_added_tickers=["PWR"]))
    assert "- Elegidas por el LLM al traducir la tesis: CEG, ETN, VST, GEV" in text
    assert "- Agregadas a mano por el usuario: PWR" in text
    mock = asyncio.run(lr.MockLLMClient().interpret_situation(_ctx(user_added_tickers=["PWR"])))
    assert "CEG, ETN, VST, GEV las eligió el LLM al traducir la tesis; PWR las agregó el usuario" in mock.thesis_alignment


@pytest.mark.parametrize("prompt", [lr.INTERPRETATION_SYSTEM_PROMPT, lr.CLAUDE_CLI_INTERPRETATION_SYSTEM_PROMPT])
def test_every_system_prompt_forbids_calling_the_pick_manual(prompt):
    assert 'No digas que se eligieron "manualmente", por un analista ni con un criterio sistemático: las eligió el LLM.' in prompt


def test_nothing_we_write_calls_the_pick_manual():
    """The only "manual" allowed is the prohibition in the rules, and the
    user's own additions ("Agregadas a mano")."""
    text = interpretation_context_text(_ctx())
    mock = asyncio.run(lr.MockLLMClient().interpret_situation(_ctx()))
    for t in (text, mock.what_data_says, mock.thesis_alignment, mock.next_series_suggestion):
        assert "manual" not in t.lower()
