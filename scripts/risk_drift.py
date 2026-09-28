"""
Risk simulation with the historical trend vs centered returns (fix/risk-simulation).

For one portfolio, VaR/CVaR (95%, 99%) and the probabilities of losing more
than 10/20/30% with the returns as they were (the period's mean included, the
old behaviour) and centered on 0 per asset. Each cell is run with SEEDS
different seeds, so the effect of the trend can be told apart from Monte
Carlo noise.

  python scripts/risk_drift.py --tickers CEG ETN VST GEV PWR            # live, saves a snapshot
  python scripts/risk_drift.py --replay data/snapshots/risk_drift_<date>.json

Prices come from yfinance (2 years, as RiskEngine.align_historical_returns
uses); the snapshot keeps them so the numbers can be re-run exactly.
"""
import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.schemas.models import PortfolioRiskRequest  # noqa: E402
from backend.services.risk_engine import RiskEngine  # noqa: E402

SEEDS = list(range(1, 21))
HORIZONS = [30, 90, 252]
METHODS = ["bootstrap", "student_t", "gaussian"]
N_SIMS = 10_000


def fetch_snapshot(tickers):
    from backend.services.data_fetcher import MarketDataFetcher
    out = {}
    for t in tickers:
        s = MarketDataFetcher.get_history(t, period="2y")
        if s.source != "live":
            raise SystemExit(f"{t}: datos {s.source}, no live. Se frena.")
        out[t] = {p.timestamp: p.value for p in s.points}
    return {"created_at": date.today().isoformat(), "period": "2y", "source": "yfinance", "prices": out}


def returns_from(snapshot, tickers):
    import pandas as pd
    cols = {}
    for t in tickers:
        s = pd.Series(snapshot["prices"][t]).sort_index()
        s.index = pd.to_datetime(s.index)
        cols[t] = np.log(s / s.shift(1)).dropna()
    df = pd.DataFrame(cols).dropna()
    return df.values, list(df.columns), str(df.index[0].date()), str(df.index[-1].date())


def run(returns, tickers, method, horizon, drift, seed, weights):
    RiskEngine.align_historical_returns = staticmethod(lambda tk, period="2y": (returns, tickers))
    req = PortfolioRiskRequest(tickers=tickers, weights=weights, horizon_days=horizon, method=method,
                               n_simulations=N_SIMS, seed=seed, drift=drift)
    r = RiskEngine.evaluate_risk(req)
    return {"var95": r.metrics["95%"].var_pct, "cvar95": r.metrics["95%"].cvar_pct,
            "var99": r.metrics["99%"].var_pct, "cvar99": r.metrics["99%"].cvar_pct,
            "p10": r.prob_loss_10pct, "p20": r.prob_loss_20pct, "p30": r.prob_loss_30pct,
            "drift_annual": r.historical_drift_annual}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=["CEG", "ETN", "VST", "GEV", "PWR"])
    ap.add_argument("--replay")
    ap.add_argument("--out", default=str(ROOT / "docs" / "results" / f"risk_drift_{date.today().isoformat()}.json"))
    args = ap.parse_args()

    if args.replay:
        raw = Path(args.replay).read_bytes()
        snapshot = json.loads(raw)
        tickers = list(snapshot["prices"])
    else:
        tickers = [t.upper() for t in args.tickers]
        snapshot = fetch_snapshot(tickers)
        raw = json.dumps(snapshot, sort_keys=True).encode()
        snap_path = ROOT / "data" / "snapshots" / f"risk_drift_{snapshot['created_at']}.json"
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_bytes(raw)
        print(f"snapshot: {snap_path}")
    sha = hashlib.sha256(raw).hexdigest()

    returns, cols, start, end = returns_from(snapshot, tickers)
    weights = {t: 1.0 / len(cols) for t in cols}
    result = {"snapshot_sha256": sha, "tickers": cols, "weights": "iguales", "start": start, "end": end,
              "n_returns": len(returns), "n_simulations": N_SIMS, "seeds": SEEDS, "cells": []}
    for method in METHODS:
        for h in HORIZONS:
            for drift in ("historical", "centered"):
                runs = [run(returns, cols, method, h, drift, s, weights) for s in SEEDS]
                cell = {"method": method, "horizon": h, "drift": drift}
                for k in ("var95", "cvar95", "var99", "cvar99", "p10", "p20", "p30"):
                    vals = np.array([x[k] for x in runs])
                    cell[k] = {"mean": float(vals.mean()), "sd_seeds": float(vals.std(ddof=1))}
                cell["drift_annual"] = runs[0]["drift_annual"]
                result["cells"].append(cell)
                print(f"{method:9} h={h:3} {drift:10} VaR95 {cell['var95']['mean']:.4f}±{cell['var95']['sd_seeds']:.4f} "
                      f"CVaR95 {cell['cvar95']['mean']:.4f} VaR99 {cell['var99']['mean']:.4f} "
                      f"P>10% {cell['p10']['mean']:.3f} P>20% {cell['p20']['mean']:.3f} P>30% {cell['p30']['mean']:.3f}")
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"deriva histórica anual de la cartera: {result['cells'][0]['drift_annual']:+.4f} (log)")
    print(f"escrito: {args.out}")


if __name__ == "__main__":
    main()
