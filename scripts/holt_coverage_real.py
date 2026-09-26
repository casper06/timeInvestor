"""
Empirical coverage of DampedHoltForecastEngine's prediction interval on REAL
data (item 2.5 of docs/PLAN.md). Measurement only: the model is not changed.

The ~96% coverage documented for Holt's interval was validated on SIMULATED
series. This walk-forward checks it on real ones: many cutoffs per series, a
Holt forecast from each, and how often the real values land inside the
nominal 95% interval, per category and per horizon step.

Two steps, so a measurement can be reproduced exactly:

    python scripts/holt_coverage_real.py --fetch snapshot.json
    python scripts/holt_coverage_real.py --replay snapshot.json --out results.json

--fetch downloads the series through the app's own fetchers (needs
FRED_API_KEY; never synthetic data) and saves them in the same "values" format
scripts/smoke_real_data.py uses. --replay only reads that file. The snapshot is
not meant to be committed (it's third-party market data); its sha256 goes into
the results so a run can be matched to its data.

Besides coverage, each observation gets a standardized error recovered from the
interval itself: the engine builds [exp(mu - z*se), exp(mu + z*se)] on the log
scale, so mu = (ln lb + ln ub)/2 and se = (ln ub - ln lb)/(2z), and
s = (ln actual - mu)/se should be ~N(0, 1) if the interval is right. Its mean
shows bias, its std the width error, and 80% vs 95% coverage the tails.
"""
import argparse
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Data after this date is ignored, so a snapshot fetched later gives the same
# cutoffs (plus nothing new).
DATA_END = "2026-06-30"
SERIES = {
    # id: category
    "JNJ": "accion", "NVDA": "accion", "XOM": "accion", "JPM": "accion", "KO": "accion",
    "SPY": "etf", "QQQ": "etf", "XLE": "etf", "XLK": "etf",
    "IPG2211A2N": "fred", "INDPRO": "fred", "RSAFSNA": "fred", "HOUSTNSA": "fred", "UNRATE": "fred",
}
# Per category: points kept for the first fit, forecast horizon, horizon
# steps reported. Daily series = trading days; FRED ones here are monthly.
SETUP = {
    "accion": {"min_train": 250, "horizon": 60, "steps": [1, 5, 10, 20, 40, 60], "freq": "D"},
    "etf": {"min_train": 250, "horizon": 60, "steps": [1, 5, 10, 20, 40, 60], "freq": "D"},
    "fred": {"min_train": 120, "horizon": 12, "steps": [1, 3, 6, 12], "freq": "M"},
}
N_CUTOFFS = 24
NOMINAL = 0.95
Z95 = stats.norm.ppf(0.975)
Z80 = stats.norm.ppf(0.90)


def _fail(message: str) -> "NoReturn":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def fetch(out_path: str) -> None:
    from backend.config import settings
    from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher

    if not (settings.FRED_API_KEY and settings.FRED_API_KEY.strip()):
        _fail("falta FRED_API_KEY (en .env o en el entorno).")
    settings.ALLOW_SYNTHETIC_DATA = False

    snapshot = {"fetched_at": datetime.now(timezone.utc).isoformat(), "data_end": DATA_END, "series": {}}
    for sid, cat in SERIES.items():
        try:
            data = FREDDataFetcher().get_series(sid) if cat == "fred" else MarketDataFetcher.get_history(sid, period="5y")
        except Exception as e:
            _fail(f"{sid}: {type(e).__name__}: {e}")
        if data.source != "live":
            _fail(f"{sid} llegó con source={data.source!r}; solo se aceptan datos reales")
        values = {p.timestamp: p.value for p in data.points if p.timestamp <= DATA_END}
        snapshot["series"][sid] = {"category": cat, "values": values}
        print(f"{sid:11} {cat:6} {len(values)} puntos {min(values)}..{max(values)}")
    Path(out_path).write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")
    print(f"escrito {out_path}")


def _cutoff_indices(n: int, min_train: int, horizon: int) -> list:
    last = n - 1 - horizon  # the last cutoff still has `horizon` real points after it
    if last < min_train - 1:
        return []
    return sorted({int(round(x)) for x in np.linspace(min_train - 1, last, N_CUTOFFS)})


def _evaluate_series(dates: list, vals: list, setup: dict) -> list:
    """One record per (cutoff, horizon step) with coverage and standardized error."""
    from backend.schemas.models import TimeSeriesPoint
    from backend.services.forecast_engine import DampedHoltForecastEngine

    engine = DampedHoltForecastEngine()
    horizon = setup["horizon"]
    records = []
    for i in _cutoff_indices(len(vals), setup["min_train"], horizon):
        train = [TimeSeriesPoint(timestamp=d, value=v) for d, v in zip(dates[: i + 1], vals[: i + 1])]
        res = engine.forecast(train, horizon=horizon, confidence=NOMINAL, freq=setup["freq"])
        for h in range(1, horizon + 1):
            actual = vals[i + h]
            lb, ub = res.lower_bound[h - 1], res.upper_bound[h - 1]
            rec = {"cutoff": dates[i], "h": h, "inside95": lb <= actual <= ub,
                   "below": actual < lb, "above": actual > ub, "s": None}
            if lb > 0 and ub > lb and actual > 0:
                mu = (math.log(lb) + math.log(ub)) / 2.0
                se = (math.log(ub) - math.log(lb)) / (2.0 * Z95)
                rec["s"] = (math.log(actual) - mu) / se
            records.append(rec)
    return records


def _window_spread(records: list) -> dict:
    """Coverage of each cutoff's whole forecast window (as a single backtest in
    the app reports it), and how much it varies across cutoffs: one window on
    its own says little about calibration."""
    by_cut = {}
    for r in records:
        by_cut.setdefault(r["cutoff"], []).append(r["inside95"])
    cov = np.array([100.0 * np.mean(v) for v in by_cut.values()])
    worst = min(by_cut, key=lambda c: np.mean(by_cut[c]))
    return {
        "window_cov_min": float(cov.min()), "window_cov_p10": float(np.percentile(cov, 10)),
        "window_cov_median": float(np.median(cov)),
        "windows_below_80": int(np.sum(cov < 80.0)), "worst_cutoff": worst,
    }


def _summarize(records: list) -> dict:
    s = np.array([r["s"] for r in records if r["s"] is not None], dtype=float)
    n = len(records)
    return {
        "n": n,
        "coverage95": 100.0 * sum(r["inside95"] for r in records) / n,
        "below_pct": 100.0 * sum(r["below"] for r in records) / n,
        "above_pct": 100.0 * sum(r["above"] for r in records) / n,
        # Derived from the standardized error, not a separate 80% forecast.
        "coverage80": 100.0 * float(np.mean(np.abs(s) <= Z80)) if len(s) else None,
        "s_mean": float(np.mean(s)) if len(s) else None,
        "s_std": float(np.std(s, ddof=1)) if len(s) > 1 else None,
        "s_excess_kurtosis": float(stats.kurtosis(s)) if len(s) > 3 else None,
    }


def replay(snapshot_path: str, out_path: str) -> None:
    raw = Path(snapshot_path).read_bytes()
    snapshot = json.loads(raw)
    results = {
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_fetched_at": snapshot.get("fetched_at"),
        "data_end": snapshot.get("data_end"),
        "python": platform.python_version(),
        "nominal": NOMINAL,
        "n_cutoffs_target": N_CUTOFFS,
        "per_series": {},
        "per_category_step": {},
        "per_category": {},
    }
    by_cat = {}
    for sid, entry in snapshot["series"].items():
        cat = entry["category"]
        setup = SETUP[cat]
        dates = sorted(entry["values"])
        vals = [entry["values"][d] for d in dates]
        records = _evaluate_series(dates, vals, setup)
        n_cut = len({r["cutoff"] for r in records})
        if n_cut < 20:
            _fail(f"{sid}: solo {n_cut} cutoffs (mínimo 20)")
        results["per_series"][sid] = {"category": cat, "n_cutoffs": n_cut, **_summarize(records),
                                      **_window_spread(records)}
        by_cat.setdefault(cat, []).extend(records)

    for cat, records in by_cat.items():
        results["per_category"][cat] = _summarize(records)
        for h in SETUP[cat]["steps"]:
            results["per_category_step"][f"{cat}:h={h}"] = _summarize([r for r in records if r["h"] == h])

    Path(out_path).write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    _print_report(results)
    print(f"\nescrito {out_path}")


def _fmt(x, pat="{:.1f}"):
    return "-" if x is None else pat.format(x)


def _print_report(r: dict) -> None:
    print(f"snapshot sha256 {r['snapshot_sha256'][:16]}…  data_end {r['data_end']}  nominal {r['nominal']:.0%}")
    head = "| {:<16} | {:>6} | {:>8} | {:>8} | {:>7} | {:>7} | {:>6} | {:>6} | {:>7} |"
    row = head
    print("\nPor categoría y horizonte (h = pasos hacia adelante):")
    print(head.format("categoría:h", "n", "cob.95%", "cob.80%", "abajo%", "arriba%", "s_med", "s_std", "curt.ex"))
    for key, v in r["per_category_step"].items():
        print(row.format(key, v["n"], _fmt(v["coverage95"]), _fmt(v["coverage80"]), _fmt(v["below_pct"]),
                         _fmt(v["above_pct"]), _fmt(v["s_mean"], "{:.2f}"), _fmt(v["s_std"], "{:.2f}"),
                         _fmt(v["s_excess_kurtosis"], "{:.1f}")))
    print("\nPor categoría (todos los horizontes juntos):")
    for key, v in r["per_category"].items():
        print(row.format(key, v["n"], _fmt(v["coverage95"]), _fmt(v["coverage80"]), _fmt(v["below_pct"]),
                         _fmt(v["above_pct"]), _fmt(v["s_mean"], "{:.2f}"), _fmt(v["s_std"], "{:.2f}"),
                         _fmt(v["s_excess_kurtosis"], "{:.1f}")))
    print("\nPor serie (todos los horizontes juntos):")
    for key, v in r["per_series"].items():
        print(row.format(f"{key} ({v['n_cutoffs']}c)", v["n"], _fmt(v["coverage95"]), _fmt(v["coverage80"]),
                         _fmt(v["below_pct"]), _fmt(v["above_pct"]), _fmt(v["s_mean"], "{:.2f}"),
                         _fmt(v["s_std"], "{:.2f}"), _fmt(v["s_excess_kurtosis"], "{:.1f}")))
    print("\nCobertura 95% por ventana (cada cutoff = un backtest como el de la app):")
    wh = "| {:<11} | {:>7} | {:>7} | {:>8} | {:>10} | {:<12} |"
    print(wh.format("serie", "mín%", "p10%", "mediana%", "vent.<80%", "peor cutoff"))
    for key, v in r["per_series"].items():
        print(wh.format(key, _fmt(v["window_cov_min"]), _fmt(v["window_cov_p10"]), _fmt(v["window_cov_median"]),
                        f"{v['windows_below_80']}/{v['n_cutoffs']}", v["worst_cutoff"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", metavar="SNAPSHOT", help="baja las series reales y las guarda acá")
    group.add_argument("--replay", metavar="SNAPSHOT", help="mide sobre un snapshot ya bajado")
    parser.add_argument("--out", help="con --replay: JSON de resultados")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.fetch)
    else:
        if not args.out:
            parser.error("--replay necesita --out")
        replay(args.replay, args.out)


if __name__ == "__main__":
    main()
