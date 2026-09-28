"""
Closed Gemini budget for the #54 evaluation (free tier): the harness counts
EVERY HTTP request the google-genai SDK sends and stops dead at the cap, never
retries a broken format, retries a per-minute 429 once, stops on a daily 429,
and spaces requests at least 15 s apart.

No real calls: a real google-genai Client over httpx.MockTransport, so the
count is taken where the SDK really sends.
"""
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from thesis_prompt_eval import (  # noqa: E402
    PER_MINUTE_WAIT_SECONDS,
    THESES,
    GeminiBudget,
    run_gemini_cells,
    single_attempt,
)

from backend.services import llm_router as lr  # noqa: E402

FAKE_KEY = "fake-key-must-not-be-recorded"
GOOD = {
    "summary": "Resumen", "mechanism": "Mecanismo",
    "tickers": [{"symbol": "XLU", "name": "Utilities Select Sector SPDR", "sector": "Utilities",
                 "weight": 0.5, "thesis_role": "Demanda", "instrument_type": "etf"}],
    "macro_series": [], "falsifiers": [{"condition": "Si la demanda cae"}],
}


def ok_body(text):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]}


def quota_429(quota_id):
    return {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED",
                      "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                   "violations": [{"quotaId": quota_id, "quotaValue": "20"}]}]}}


PER_MINUTE = quota_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
PER_DAY = quota_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
UNAVAILABLE = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}


class FakeGemini:
    """Answers each request with the next (status, json) of a script; counts hits."""

    def __init__(self, script):
        self.script = list(script)
        self.hits = 0

    def handler(self, request):
        self.hits += 1
        status, payload = self.script.pop(0) if self.script else (200, ok_body(json.dumps(GOOD)))
        return httpx.Response(status, json=payload)

    def make_client(self):
        from google import genai
        from google.genai import types
        c = lr.GeminiLLMClient(api_key=FAKE_KEY)
        c._client = genai.Client(api_key=FAKE_KEY, http_options=types.HttpOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(self.handler))))
        return c


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def harness(monkeypatch):
    """Budget installed on the SDK, production retry replaced by one attempt,
    fake time (nothing actually waits)."""
    clock = FakeClock()
    budget = GeminiBudget(cap=6, min_gap=15.0, clock=clock.clock, sleep=clock.sleep)
    undo_retry = single_attempt(lr)
    uninstall = budget.install()
    sent_at = []
    original_before = budget._before

    def before():
        original_before()
        sent_at.append(clock.t)
    monkeypatch.setattr(budget, "_before", before)
    yield budget, clock, sent_at
    uninstall()
    undo_retry()


def run(fake, budget, clock):
    return run_gemini_cells(THESES, fake.make_client, budget, "nuevo", sleep=clock.sleep)


def test_all_ok_uses_four_requests_spaced_at_least_15s(harness):
    budget, clock, sent_at = harness
    fake = FakeGemini([])
    cells = run(fake, budget, clock)
    assert [c["status"] for c in cells] == ["ok"] * 4
    assert fake.hits == 4 == len(budget.calls)
    assert all(b - a >= 15.0 for a, b in zip(sent_at, sent_at[1:]))
    assert cells[0]["response"]["tickers"][0]["symbol"] == "XLU"


def test_the_cap_stops_dead_at_six_real_requests(harness):
    """Per-minute 429 on every request: 1 + 1 retry per thesis. Theses 1-3 use
    6 requests; thesis 4's first request is refused before being sent."""
    budget, clock, _ = harness
    fake = FakeGemini([(429, PER_MINUTE)] * 20)
    cells = run(fake, budget, clock)
    assert fake.hits == 6 == len(budget.calls)
    assert budget.refused == 1
    assert [c["calls"] for c in cells] == [[1, 2], [3, 4], [5, 6], []]
    assert cells[3]["status"] == "sin dato"
    assert "tope" in cells[3]["reason"]
    # The per-minute retry waited 60 s, once per thesis.
    assert clock.sleeps.count(PER_MINUTE_WAIT_SECONDS) == 3


def test_a_per_minute_429_is_retried_once_then_counts(harness):
    budget, clock, _ = harness
    fake = FakeGemini([(429, PER_MINUTE), (200, ok_body(json.dumps(GOOD)))])
    cells = run(fake, budget, clock)
    assert cells[0]["status"] == "ok"
    assert cells[0]["calls"] == [1, 2]
    assert fake.hits == 5


def test_a_daily_429_stops_everything_after_one_request(harness):
    budget, clock, _ = harness
    fake = FakeGemini([(429, PER_DAY)])
    cells = run(fake, budget, clock)
    assert fake.hits == 1
    assert cells[0]["status"] == "sin dato"
    assert [c["status"] for c in cells[1:]] == ["no se intentó"] * 3
    assert "cupo diario" in cells[1]["reason"]


def test_a_broken_format_is_a_result_never_re_asked_and_stops(harness):
    budget, clock, _ = harness
    fake = FakeGemini([(200, ok_body("esto no es JSON {"))])
    cells = run(fake, budget, clock)
    assert fake.hits == 1
    assert cells[0]["status"] == "formato roto"
    assert [c["status"] for c in cells[1:]] == ["no se intentó"] * 3
    # The answer already received is kept for the diagnosis.
    assert "esto no es JSON {" in budget.calls[0]["body"]


def test_a_503_is_not_retried(harness):
    budget, clock, _ = harness
    fake = FakeGemini([(503, UNAVAILABLE)])
    cells = run(fake, budget, clock)
    assert cells[0]["status"] == "sin dato"
    assert cells[0]["calls"] == [1]
    assert [c["status"] for c in cells[1:]] == ["ok"] * 3
    assert fake.hits == 4


def test_the_key_is_never_recorded(harness):
    budget, clock, _ = harness
    run(FakeGemini([(429, PER_MINUTE), (503, UNAVAILABLE), (200, ok_body("x"))]), budget, clock)
    assert FAKE_KEY not in json.dumps(budget.calls, default=str)


def test_the_counter_sees_production_retries_too(monkeypatch):
    """Without the single-attempt patch, production's _call_with_retry sends 3
    requests for one 429: the counter catches all 3 (it sits under the SDK)."""
    monkeypatch.setattr(lr, "RETRY_DELAYS_SECONDS", [0, 0])
    clock = FakeClock()
    budget = GeminiBudget(cap=6, clock=clock.clock, sleep=clock.sleep)
    uninstall = budget.install()
    try:
        fake = FakeGemini([(429, PER_MINUTE)] * 3)
        import asyncio
        r = asyncio.run(fake.make_client().parse_thesis(THESES[0]))
    finally:
        uninstall()
    assert r.provider_used == "mock-semantic-engine"
    assert fake.hits == 3 == len(budget.calls)
