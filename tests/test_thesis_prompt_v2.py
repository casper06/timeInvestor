"""
4.10, prompt de traducción v2: mechanism → FRED drivers → what would refute it
→ instruments (ETFs, commodities, rates before single stocks), SPY benchmark;
company facts carry a source or none. Every variant (Gemini, Gemini CLI,
Claude CLI, OpenAI, Ollama, mock) and the persistence. No network.
"""
import asyncio
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import llm_router as lr

THESES = [
    "Demanda eléctrica por centros de datos de IA",
    "La IA es una burbuja",
    "Impacto de tasas de interés en múltiplos tecnológicos",
    "Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.",
]
ORDER = ["1. Mecanismo causal", "2. Drivers medibles", "3. Qué la refutaría", "4. Instrumentos"]
V2 = {
    "summary": "s", "mechanism": "tasas más altas → menos permisos → menos inicios",
    "macro_series": [{"series_id": "MORTGAGE30US", "name": "m", "category": "Tasas",
                      "expected_correlation": "Negative", "mechanism_role": "causa"}],
    "falsifiers": [{"condition": "Si HOUST sube con tasas altas", "series_id": "HOUST"}, "Si PERMIT no cae"],
    "tickers": [{"symbol": "ITB", "name": "i", "sector": "x", "instrument_type": "etf", "weight": 0.6,
                 "thesis_role": "r", "source": None},
                {"symbol": "DHI", "name": "d", "sector": "x", "instrument_type": "stonk", "weight": 0.4,
                 "thesis_role": "r", "source": ""}],
    "rationales": {"ITB": "r"},
}


# ---- the prompt ----

# Claude CLI gets the rules through the --json-schema descriptions (a long
# system prompt makes it ignore the schema); what it receives is both.
CLAUDE_CLI_TEXT = lr.CLAUDE_CLI_SYSTEM_PROMPT + json.dumps(lr.CLAUDE_CLI_THESIS_SCHEMA, ensure_ascii=False)


@pytest.mark.parametrize("prompt", [lr.SYSTEM_PROMPT, CLAUDE_CLI_TEXT])
def test_both_prompt_variants_ask_in_the_v2_order(prompt):
    positions = [prompt.index(step) for step in ORDER]
    assert positions == sorted(positions)
    assert "Preferí ETFs sectoriales, commodities y tasas antes que acciones sueltas" in prompt
    assert "El benchmark es SPY, siempre" in prompt
    assert "No inventes fuentes" in prompt
    assert "inventes IDs de FRED" in prompt or "ni IDs de FRED" in prompt


def test_claude_cli_system_prompt_stays_short():
    """The failure seen: with the long numbered instructions as --system-prompt,
    haiku ignored --json-schema. The rules live in the schema instead."""
    assert len(lr.CLAUDE_CLI_SYSTEM_PROMPT) < 400 and "1." not in lr.CLAUDE_CLI_SYSTEM_PROMPT


def test_the_json_prompt_example_has_the_new_fields():
    for field in ('"mechanism"', '"falsifiers"', '"mechanism_role"', '"instrument_type"', '"source"'):
        assert field in lr.SYSTEM_PROMPT


# ---- one builder for every client ----

def test_builder_forces_spy_and_cleans_fields():
    r = lr._thesis_response("t", V2, "x")
    assert r.benchmark == "SPY" and r.prompt_version == 2
    assert r.mechanism.startswith("tasas más altas")
    assert [f.condition for f in r.falsifiers] == ["Si HOUST sube con tasas altas", "Si PERMIT no cae"]
    assert r.falsifiers[0].series_id == "HOUST" and r.falsifiers[1].series_id is None
    assert r.tickers[1].instrument_type is None     # not one of the allowed types
    assert r.tickers[1].source is None              # "" is no source
    assert r.macro_series[0].mechanism_role == "causa"


def test_old_shape_answers_still_parse():
    r = lr._thesis_response("t", {"summary": "s", "tickers": [{"symbol": "NVDA", "name": "n", "sector": "s",
                                  "weight": 1.0, "thesis_role": "r"}], "macro_series": [], "rationales": {}}, "x")
    assert r.mechanism is None and r.falsifiers == [] and r.benchmark == "SPY"


def _gemini():
    c = object.__new__(lr.GeminiLLMClient)
    c.api_key = "k"
    c._client = MagicMock()
    c._client.models.generate_content.return_value = MagicMock(text=json.dumps(V2), candidates=[])
    return c


def test_gemini_api_uses_the_v2_prompt_and_builder():
    c = _gemini()
    r = asyncio.run(c.parse_thesis("t"))
    assert lr.SYSTEM_PROMPT in c._client.models.generate_content.call_args.kwargs["contents"]
    assert r.provider_used == "gemini-3.6-flash" and r.benchmark == "SPY" and len(r.falsifiers) == 2


@pytest.mark.parametrize("cls", ["GeminiCliLLMClient", "ClaudeCliLLMClient"])
def test_cli_clients_use_the_v2_prompt_and_builder(cls):
    c = object.__new__(getattr(lr, cls))
    c.model = "haiku"
    seen = {}

    def fake_run(prompt, system_prompt=None, json_schema=None):
        seen.update(prompt=prompt, system=system_prompt, schema=json_schema)
        return dict(V2)
    c._run = fake_run
    r = asyncio.run(c.parse_thesis("t"))
    assert r.mechanism and r.benchmark == "SPY" and len(r.falsifiers) == 2
    if cls == "ClaudeCliLLMClient":
        assert seen["system"] == lr.CLAUDE_CLI_SYSTEM_PROMPT and seen["schema"] is lr.CLAUDE_CLI_THESIS_SCHEMA
        assert {"mechanism", "falsifiers"} <= set(seen["schema"]["required"])
        ticker = seen["schema"]["properties"]["tickers"]["items"]
        assert "instrument_type" in ticker["required"] and "source" in ticker["properties"]
    else:
        assert lr.SYSTEM_PROMPT in seen["prompt"]


@pytest.mark.parametrize("cls", ["OpenAILLMClient", "OllamaLLMClient"])
def test_http_clients_use_the_v2_prompt_and_builder(monkeypatch, cls):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(V2)}}], "response": json.dumps(V2)}

    class AC:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["payload"] = json
            return Resp()

    monkeypatch.setattr(lr.httpx, "AsyncClient", AC)
    c = lr.OpenAILLMClient(api_key="k") if cls == "OpenAILLMClient" else lr.OllamaLLMClient()
    r = asyncio.run(c.parse_thesis("t"))
    p = seen["payload"]
    text = "\n".join(m["content"] for m in p["messages"]) if "messages" in p else p["prompt"]
    assert lr.SYSTEM_PROMPT in text
    assert r.benchmark == "SPY" and len(r.falsifiers) == 2


# ---- the mock ----

@pytest.mark.parametrize("thesis", THESES)
def test_mock_follows_v2(thesis):
    r = asyncio.run(lr.MockLLMClient().parse_thesis(thesis))
    assert r.benchmark == "SPY" and r.prompt_version == 2
    assert r.mechanism.startswith("Plantilla local por palabras clave, sin análisis de un LLM.")
    assert r.tickers[0].instrument_type != "stock"                 # ETFs / rates first
    assert abs(sum(t.weight for t in r.tickers) - 1.0) < 1e-9
    assert all(t.source is None for t in r.tickers)                # it asserts no company facts
    assert "SPY" not in [t.symbol for t in r.tickers]


def test_mock_bubble_thesis_does_not_pretend_to_know_the_mechanism():
    r = asyncio.run(lr.MockLLMClient().parse_thesis("La IA es una burbuja"))
    assert "No reconoció el tema" in r.mechanism and r.falsifiers == []


def test_mock_housing_thesis_has_measurable_falsifiers():
    r = asyncio.run(lr.MockLLMClient().parse_thesis(THESES[3]))
    assert [m.series_id for m in r.macro_series] == ["MORTGAGE30US", "PERMIT", "HOUST"]
    assert all(f.series_id for f in r.falsifiers)


# ---- persistence ----

def test_saved_thesis_keeps_mechanism_falsifiers_and_benchmark():
    c = TestClient(app)
    created = c.post("/api/theses", json={
        "title": "Vivienda", "prompt": THESES[3], "summary": "s",
        "tickers": [{"symbol": "ITB", "name": "i", "sector": "x", "weight": 1.0, "thesis_role": "r",
                     "instrument_type": "etf"}],
        "macro_series": [{"series_id": "HOUST", "name": "h", "category": "Vivienda", "mechanism_role": "efecto"}],
        "rationales": {}, "mechanism": "m", "falsifiers": [{"condition": "Si HOUST sube", "series_id": "HOUST"}],
        "benchmark": "SPY", "prompt_version": 2,
    }).json()
    detail = c.get(f"/api/theses/{created['id']}").json()
    assert detail["mechanism"] == "m" and detail["benchmark"] == "SPY" and detail["prompt_version"] == 2
    assert detail["falsifiers"] == [{"condition": "Si HOUST sube", "series_id": "HOUST"}]
    assert detail["tickers"][0]["instrument_type"] == "etf"
    assert detail["macro_series"][0]["mechanism_role"] == "efecto"
