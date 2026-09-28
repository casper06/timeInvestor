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
"""
import argparse
import asyncio
import json
import os
import sys
import time

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

    raw = {}
    if hasattr(lr, "_thesis_response"):          # new code: keep the model's raw JSON too
        original = lr._thesis_response

        def capture(thesis, data, provider_used, **kw):
            raw[thesis] = json.loads(json.dumps(data, default=str))
            return original(thesis, data, provider_used, **kw)
        lr._thesis_response = capture

    def client():
        if args.model == "gemini":
            return lr.GeminiLLMClient()
        return lr.ClaudeCliLLMClient(model=args.model)

    results = []
    for i, thesis in enumerate(THESES):
        if i:
            time.sleep(args.gap)
        attempts = []
        cell = None
        for attempt in range(3):
            if attempt:
                time.sleep(65)
            t0 = time.time()
            r = asyncio.run(client().parse_thesis(thesis))
            seconds = round(time.time() - t0, 1)
            if r.provider_used == "mock-semantic-engine" or r.fallback_reason:
                attempts.append({"seconds": seconds, "fallback_reason": r.fallback_reason})
                continue
            cell = r.model_dump()
            cell["seconds"] = seconds
            break
        results.append({"thesis": thesis, "label": args.label, "model": args.model,
                        "status": "ok" if cell else "sin dato", "response": cell,
                        "model_raw": raw.get(thesis), "failed_attempts": attempts})
        print(f"[{args.label}/{args.model}] {thesis[:40]}: {'ok' if cell else 'SIN DATO'} "
              f"({len(attempts)} intentos fallidos)", flush=True)
    json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
