"""
Scores the 4.10 evaluation (criteria pre-registered in docs/PLAN.md, 8b258da).

Mechanical, computed here:
  C1a  FRED IDs that exist (/fred/series)
  C3a  SPY in the MODEL's output (the app forces it in v2 regardless; reported apart)
  C3b  weight in single stocks (yfinance quoteType == EQUITY), weights normalized to 1
  C3c  first instrument is not a single stock
Manual (C1b, C2, C4): read from --judgments, a JSON written by hand, with the
reason for every call. `--sheet` prints what's needed to judge each run.

  python scripts/thesis_prompt_score.py --runs <dir with *.json> --sheet
  python scripts/thesis_prompt_score.py --runs <dir> --judgments <file> --out <results.json> --md <table.md>
"""
import argparse
import glob
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
_fred_cache, _qt_cache = {}, {}


def fred_title(sid):
    if sid not in _fred_cache:
        from backend.config import settings
        r = httpx.get("https://api.stlouisfed.org/fred/series",
                      params={"series_id": sid, "api_key": settings.FRED_API_KEY, "file_type": "json"}, timeout=15)
        s = r.json().get("seriess") if r.status_code == 200 else None
        _fred_cache[sid] = s[0]["title"] if s else None
    return _fred_cache[sid]


def quote_type(sym):
    if sym not in _qt_cache:
        import yfinance as yf
        try:
            _qt_cache[sym] = yf.Ticker(sym).info.get("quoteType") or "desconocido"
        except Exception:
            _qt_cache[sym] = "desconocido"
    return _qt_cache[sym]


def load(runs_dir):
    out = []
    for f in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        out += json.load(open(f, encoding="utf-8"))
    return out


def mechanical(run):
    r = run["response"]
    series = [m["series_id"] for m in r["macro_series"]]
    exists = {sid: fred_title(sid) is not None for sid in series}
    tickers = r["tickers"]
    total = sum(t["weight"] for t in tickers) or 1.0
    types = {t["symbol"]: quote_type(t["symbol"]) for t in tickers}
    stock_w = sum(t["weight"] for t in tickers if types[t["symbol"]] == "EQUITY") / total
    raw_text = json.dumps(run.get("model_raw") or {k: v for k, v in r.items() if k != "benchmark"}, ensure_ascii=False)
    return {
        "C1a": f"{sum(exists.values())}/{len(series)}",
        "series_exist": exists,
        "C3a_modelo": "SPY" in raw_text,
        "C3a_app": r.get("benchmark") == "SPY",
        "C3b": round(stock_w, 3),
        "C3c": types[tickers[0]["symbol"]] != "EQUITY" if tickers else None,
        "quote_types": types,
    }


def sheet(runs):
    for run in runs:
        key = f"{run['label']}|{run['model']}|{run['thesis']}"
        print(f"\n######## {key}  [{run['status']}]")
        if run["status"] != "ok":
            print("  fallas:", run["failed_attempts"])
            continue
        r = run["response"]
        m = mechanical(run)
        print("  mecanismo:", r.get("mechanism"))
        print("  resumen:", r["summary"][:400])
        for s in r["macro_series"]:
            print(f"  FRED {s['series_id']} -> {fred_title(s['series_id'])!r} | rol: {s.get('mechanism_role')}")
        print("  refutación:", [f["condition"] + (f" [{f.get('series_id')}]" if f.get("series_id") else "") for f in r.get("falsifiers", [])])
        for t in r["tickers"]:
            print(f"  {t['symbol']} {m['quote_types'][t['symbol']]} w={t['weight']} tipo={t.get('instrument_type')} source={t.get('source')!r}")
            print(f"     rol: {t['thesis_role']}")
            if r["rationales"].get(t["symbol"]):
                print(f"     racional: {r['rationales'][t['symbol']]}")
        print("  mecánicos:", {k: v for k, v in m.items() if k not in ('quote_types', 'series_exist')})


def table(runs, judgments):
    rows, results = [], []
    for run in runs:
        key = f"{run['label']}|{run['model']}|{run['thesis']}"
        if run["status"] != "ok":
            rows.append((run, None, None))
            results.append({"key": key, "status": run["status"], "failed_attempts": run["failed_attempts"]})
            continue
        m = mechanical(run)
        j = judgments[key]
        rows.append((run, m, j))
        results.append({"key": key, "status": "ok", "mechanical": m, "judgment": j})
    return rows, results


def md(rows):
    tid = {"Demanda": "T1", "La IA": "T2", "Impacto": "T3", "Las tasas": "T4"}
    lines = ["| Tesis | Prompt | Modelo | C1a existen | C1b relevantes | C2 refutación | C3a SPY (modelo) | C3b peso acciones | C3c 1º no acción | C4 hechos sin fuente |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for run, m, j in sorted(rows, key=lambda x: (x[0]["thesis"], x[0]["model"], x[0]["label"])):
        t = next(v for k, v in tid.items() if run["thesis"].startswith(k))
        if m is None:
            lines.append(f"| {t} | {run['label']} | {run['model']} | sin dato | | | | | | |")
            continue
        lines.append(f"| {t} | {run['label']} | {run['model']} | {m['C1a']} | {j['C1b']} | {j['C2']} | "
                     f"{'sí' if m['C3a_modelo'] else 'no'} | {m['C3b']:.0%} | {'sí' if m['C3c'] else 'no'} | {j['C4']} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--judgments")
    ap.add_argument("--out")
    ap.add_argument("--md")
    a = ap.parse_args()
    runs = load(a.runs)
    if a.sheet:
        sheet(runs)
        return
    judgments = json.load(open(a.judgments, encoding="utf-8"))
    rows, results = table(runs, judgments)
    json.dump({"runs": runs, "scores": results}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(a.md, "w", encoding="utf-8").write(md(rows) + "\n")
    print(md(rows))


if __name__ == "__main__":
    main()
