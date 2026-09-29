"""
4.10 + 4.6 evaluation (pre-registered in docs/PLAN.md, commit 8b258da): the 4
theses with one prompt version × one model, raw outputs saved as they came.

  python scripts/thesis_prompt_eval.py --code <repo root with the prompt to test> --label nuevo \\
      --model gemini|haiku|sonnet --out <file.json>

`--code` is the repository whose backend is imported: main's (old prompt, in a
worktree) or this branch's (new prompt). The DB must be a COPY (Claude CLI
records its usage there): DATABASE_URL has to point at a file with "eval" in
its name.

Pre-registered protocol: one run per cell; a failure (429, 503, CLI) is retried
up to 3 times with at least 60 s in between; a mock answer (fallback) is never
counted as the model's: the cell is "sin dato", with the reason.

Gemini (free tier), closed budget (2026-09-28): GeminiBudget counts EVERY HTTP
request the SDK sends (retries and 429s included) and stops dead at the cap
(--max-requests, 6) before sending. No automatic retries: production's
_call_with_retry is replaced by a single attempt. A broken format is a result
(recorded, never re-asked, and the run stops). A per-minute 429 waits 60 s and
is retried ONCE, within the cap. A daily 429 stops everything. Requests are
sequential, at least 15 s apart. Every call is recorded with its status and
body (never the request headers, which carry the key).
"""
import argparse
import asyncio
import json
import os
import sys
import time

GEMINI_REQUEST_CAP = 6
MIN_GAP_SECONDS = 15.0
PER_MINUTE_WAIT_SECONDS = 60.0

def is_daily_quota(text) -> bool:
    """Gemini's 429 for the DAILY quota (quotaId ...PerDay..., e.g.
    GenerateRequestsPerDayPerProjectPerModel-FreeTier): retrying it only burns
    requests until the next day. A per-minute 429 (...PerMinute...) is worth
    retrying. Decided from the error body, not the status code (both are 429)."""
    return "PerDay" in str(text or "")


class BudgetExhausted(Exception):
    """The cap of HTTP requests to Gemini was reached: nothing more is sent."""


class GeminiBudget:
    """Counts every HTTP request google-genai sends, at the SDK's single choke
    point (BaseApiClient._request_once and its async twin: every retry of the
    SDK or ours goes through them). Refuses the one past the cap BEFORE it's
    sent, and spaces requests at least `min_gap` seconds apart."""

    def __init__(self, cap=GEMINI_REQUEST_CAP, min_gap=MIN_GAP_SECONDS, clock=time.monotonic, sleep=time.sleep):
        self.cap, self.min_gap, self.clock, self.sleep = cap, min_gap, clock, sleep
        self.calls = []          # one entry per request actually sent
        self.refused = 0         # requests refused by the cap (never sent)
        self.current = None      # thesis being evaluated, for the record
        self._last = None

    @property
    def exhausted(self):
        return len(self.calls) >= self.cap

    def _before(self):
        if self.exhausted:
            self.refused += 1
            raise BudgetExhausted(f"tope de {self.cap} pedidos HTTP a Gemini alcanzado; no se envió")
        if self._last is not None:
            wait = self.min_gap - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        self.calls.append({"n": len(self.calls) + 1, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "thesis": self.current, "status": None, "body": None})

    def _after_ok(self, resp):
        stream = getattr(resp, "response_stream", None)
        body = stream[0] if isinstance(stream, list) and stream else None
        self.calls[-1].update(status=200, body=body)

    def _after_error(self, e):
        self.calls[-1].update(status=getattr(e, "code", None) or type(e).__name__, body=str(e))

    def install(self):
        """Wraps the SDK's request functions; returns the function that undoes it."""
        from google.genai._api_client import BaseApiClient
        sync_once, async_once = BaseApiClient._request_once, BaseApiClient._async_request_once
        budget = self

        def request_once(api, http_request, stream=False):
            budget._before()
            try:
                resp = sync_once(api, http_request, stream)
            except Exception as e:
                budget._after_error(e)
                raise
            budget._after_ok(resp)
            return resp

        async def async_request_once(api, http_request, stream=False):
            budget._before()
            try:
                resp = await async_once(api, http_request, stream)
            except Exception as e:
                budget._after_error(e)
                raise
            budget._after_ok(resp)
            return resp

        BaseApiClient._request_once = request_once
        BaseApiClient._async_request_once = async_request_once

        def uninstall():
            BaseApiClient._request_once = sync_once
            BaseApiClient._async_request_once = async_once
        return uninstall


def single_attempt(lr):
    """Replaces production's _call_with_retry (3 attempts on 429/503) with one
    attempt; returns the function that undoes it."""
    original = lr._call_with_retry

    async def once(_label, operation):
        return await operation()
    lr._call_with_retry = once
    return lambda: setattr(lr, "_call_with_retry", original)


def run_gemini_cells(theses, make_client, budget, label, sleep=time.sleep, on_cell=None):
    """The Gemini cells under the closed budget (see the module docstring).
    `make_client()` returns a client whose parse_thesis makes ONE attempt."""
    results, stop = [], None
    for thesis in theses:
        base = {"thesis": thesis, "label": label, "model": "gemini"}
        if stop:
            results.append({**base, "status": "no se intentó", "reason": stop, "response": None, "calls": []})
            if on_cell:
                on_cell(results)
            continue
        budget.current = thesis
        first_call = len(budget.calls)
        per_minute_retried = False
        while True:
            n_before = len(budget.calls)
            t0 = time.time()
            r = asyncio.run(make_client().parse_thesis(thesis))
            seconds = round(time.time() - t0, 1)
            last = budget.calls[-1] if len(budget.calls) > n_before else None
            if r.provider_used != "mock-semantic-engine" and not r.fallback_reason:
                cell = r.model_dump()
                cell["seconds"] = seconds
                cell["run_at"] = time.strftime("%Y-%m-%d %H:%M")
                status, reason = "ok", None
                break
            cell, reason = None, r.fallback_reason
            if last is None:
                # Nothing was sent: the cap refused it.
                status = "sin dato"
                stop = f"tope de {budget.cap} pedidos alcanzado"
                break
            if last["status"] == 429:
                if is_daily_quota(last["body"]):
                    status, stop = "sin dato", f"cupo diario agotado ({last['at']})"
                    break
                if not per_minute_retried and not budget.exhausted:
                    per_minute_retried = True
                    sleep(PER_MINUTE_WAIT_SECONDS)
                    continue
                status = "sin dato"
                break
            if last["status"] == 200:
                # The model answered and the answer was unusable: a result, not
                # a failure to retry. Stop and report before touching the prompt.
                status, stop = "formato roto", f"formato roto en «{thesis}»; se frena para revisar"
                break
            status = "sin dato"      # other HTTP errors (503, 500, network): no retry
            break
        results.append({**base, "status": status, "reason": reason, "response": cell,
                        "calls": [c["n"] for c in budget.calls[first_call:]]})
        if on_cell:
            on_cell(results)
    return results


THESES = [
    "Demanda eléctrica por centros de datos de IA",
    "La IA es una burbuja",
    "Impacto de tasas de interés en múltiplos tecnológicos",
    "Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", required=True, choices=["gemini", "haiku", "sonnet"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--gap", type=int, default=20, help="seconds between theses (Gemini free tier: 5/min)")
    ap.add_argument("--cli-timeout", type=int, default=120,
                    help="Claude CLI timeout, the SAME for both code versions (main had 45 s, this branch 120 s)")
    ap.add_argument("--max-requests", type=int, default=GEMINI_REQUEST_CAP,
                    help="Gemini: cap of HTTP requests for the whole run (retries and 429s count)")
    args = ap.parse_args()

    assert "eval" in os.environ.get("DATABASE_URL", ""), "DATABASE_URL tiene que ser una COPIA (con 'eval' en el nombre)"
    sys.path.insert(0, os.path.abspath(args.code))
    import logging
    logging.disable(logging.CRITICAL)
    from backend.services import llm_router as lr

    # Same CLI timeout for old and new code, so the comparison is about the prompt.
    original_run = lr._run_cli_subprocess

    def run_with_timeout(*a, **k):
        k["timeout"] = args.cli_timeout
        return original_run(*a, **k)
    lr._run_cli_subprocess = run_with_timeout

    # The evaluation never retries a daily-quota 429 (production's
    # _call_with_retry retries every 429 twice): each retry costs a request of
    # the same exhausted daily quota. Per-minute 429s keep being retried.
    original_retryable = lr._is_retryable

    def retryable(exc):
        return False if is_daily_quota(exc) else original_retryable(exc)
    lr._is_retryable = retryable

    raw = {}
    if hasattr(lr, "_thesis_response"):          # new code: keep the model's raw JSON too
        original = lr._thesis_response

        def capture(thesis, data, provider_used, **kw):
            raw[thesis] = json.loads(json.dumps(data, default=str))
            return original(thesis, data, provider_used, **kw)
        lr._thesis_response = capture

    if args.model == "gemini":
        # Single attempt: the only retry is the harness's own, for a per-minute 429.
        single_attempt(lr)
        budget = GeminiBudget(cap=args.max_requests)
        uninstall = budget.install()

        def save(results):
            json.dump({"cap": budget.cap, "requests_sent": len(budget.calls), "requests_refused": budget.refused,
                       "cells": results, "http_calls": budget.calls},
                      open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        try:
            results = run_gemini_cells(THESES, lr.GeminiLLMClient, budget, args.label, on_cell=save)
        finally:
            uninstall()
        for c in results:
            c["model_raw"] = raw.get(c["thesis"])
        save(results)
        for c in results:
            print(f"[{args.label}/gemini] {c['thesis'][:40]}: {c['status']} (pedidos {c['calls']})", flush=True)
        print(f"pedidos enviados: {len(budget.calls)} de {budget.cap}", flush=True)
        return

    def client():
        return lr.ClaudeCliLLMClient(model=args.model)

    results = []
    daily_quota_hit = None
    for i, thesis in enumerate(THESES):
        if i and not daily_quota_hit:
            time.sleep(args.gap)
        attempts = []
        cell = None
        for attempt in range(3):
            if daily_quota_hit:
                # Daily quota exhausted: no more requests today; the cell is
                # "sin dato" with that reason, never a mix of days.
                attempts.append({"seconds": 0.0, "fallback_reason": f"no se intentó: cupo diario agotado ({daily_quota_hit})"})
                break
            if attempt:
                time.sleep(65)
            t0 = time.time()
            r = asyncio.run(client().parse_thesis(thesis))
            seconds = round(time.time() - t0, 1)
            if r.provider_used == "mock-semantic-engine" or r.fallback_reason:
                attempts.append({"seconds": seconds, "fallback_reason": r.fallback_reason})
                if is_daily_quota(r.fallback_reason):
                    daily_quota_hit = time.strftime("%Y-%m-%d %H:%M")
                continue
            cell = r.model_dump()
            cell["seconds"] = seconds
            cell["run_at"] = time.strftime("%Y-%m-%d %H:%M")
            break
        results.append({"thesis": thesis, "label": args.label, "model": args.model,
                        "status": "ok" if cell else "sin dato", "response": cell,
                        "model_raw": raw.get(thesis), "failed_attempts": attempts})
        print(f"[{args.label}/{args.model}] {thesis[:40]}: {'ok' if cell else 'SIN DATO'} "
              f"({len(attempts)} intentos fallidos)", flush=True)
    json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
