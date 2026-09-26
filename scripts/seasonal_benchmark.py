"""
Seasonal benchmark (items 3.0c + 3.0d of docs/PLAN.md): which engine should the
selector use for seasonal FRED series?

Rivals, on the SAME cutoffs of each series and compared in pairs:
- seasonal naive (same month last year) — the floor any model has to beat;
- Damped Holt (current engine, no seasonal component);
- Holt-Winters, ETS(A,Ad,A) (3.0b);
- TimesFM 2.5 with its REAL weights (aborts if they don't load or if it falls
  back to Holt on any cutoff: a fallback is never counted as TimesFM);
- Prophet (optional dependency, requirements-prophet.txt).

    python scripts/seasonal_benchmark.py --replay data/snapshots/seasonal_benchmark_<fecha>.json --out results.json

Only --replay: the snapshot is built once from real data (see the PR / logbook
for how) and kept in data/snapshots/ (git-ignored). Same snapshot + same
versions -> identical results.

Per engine and cutoff (horizon 12 months):
- MASE scaled by the in-sample seasonal naive, mean |y_t - y_{t-12}| (3.0a),
  and MAPE;
- coverage and relative width of the 95% and 80% intervals. TimesFM's native
  quantiles are deciles (p10..p90), so it only has an 80% interval; its 95%
  is reported as unavailable, never approximated. Holt and Holt-Winters build
  a Gaussian interval in log, so their 80% one follows exactly from the same
  mu and se. Prophet's come from its own predictive samples (fixed seed). The
  seasonal naive uses the standard interval (Hyndman & Athanasopoulos, fpp3
  5.5): sigma from the in-sample seasonal differences, in log, constant for
  h <= m.
- wins against Holt-Winters (lower seasonal MASE on that cutoff), with a
  two-sided sign test.
Everything is also reported without the cutoffs whose 12-month window touches
2020.
"""
import argparse
import hashlib
import json
import logging
import math
import platform
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import holt_coverage_real as hc  # noqa: E402  (same cutoff grid as 2.5 / 3.0b)

SERIES = ["IPG2211A2N", "RSAFSNA", "HOUSTNSA", "MRTSSM4451USN"]
ENGINES = ["seasonal_naive", "holt", "holt_winters", "timesfm", "prophet"]
M = 12
H = 12
Z95 = stats.norm.ppf(0.975)
Z80 = stats.norm.ppf(0.90)
# Verdict rule: lowest mean seasonal MASE, but it only replaces Holt-Winters if
# it beats it on the paired cutoffs with a significant sign test.
SIGN_TEST_ALPHA = 0.05


def _fail(message: str) -> "NoReturn":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


# --- engines: each returns point (levels), and (lo95, hi95), (lo80, hi80) ---

def _gaussian_log_bands(res):
    """Holt / Holt-Winters give exp(mu ± z95·se); recover mu, se and rebuild
    both intervals exactly."""
    lo, hi = np.array(res.lower_bound), np.array(res.upper_bound)
    mu = (np.log(lo) + np.log(hi)) / 2.0
    se = (np.log(hi) - np.log(lo)) / (2.0 * Z95)
    return (np.exp(mu - Z95 * se), np.exp(mu + Z95 * se)), (np.exp(mu - Z80 * se), np.exp(mu + Z80 * se))


def run_seasonal_naive(train, dates):
    y = np.log(np.asarray(train, dtype=float))
    point_log = np.array([y[-M:][(h - 1) % M] for h in range(1, H + 1)])
    resid = y[M:] - y[:-M]
    sigma = float(np.sqrt(np.mean(resid ** 2)))
    k = np.array([(h - 1) // M for h in range(1, H + 1)])
    se = sigma * np.sqrt(k + 1)
    return (np.exp(point_log),
            (np.exp(point_log - Z95 * se), np.exp(point_log + Z95 * se)),
            (np.exp(point_log - Z80 * se), np.exp(point_log + Z80 * se)))


def _points(train, dates):
    from backend.schemas.models import TimeSeriesPoint
    return [TimeSeriesPoint(timestamp=d, value=v) for d, v in zip(dates, train)]


def run_holt(train, dates):
    from backend.services.forecast_engine import DampedHoltForecastEngine
    res = DampedHoltForecastEngine().forecast(_points(train, dates), horizon=H, confidence=0.95, freq="M")
    b95, b80 = _gaussian_log_bands(res)
    return np.array(res.values), b95, b80


def run_holt_winters(train, dates):
    from backend.services.forecast_engine import HoltWintersForecastEngine
    res = HoltWintersForecastEngine().forecast(_points(train, dates), horizon=H, confidence=0.95, freq="M")
    b95, b80 = _gaussian_log_bands(res)
    return np.array(res.values), b95, b80


# TimesFM 2.5 returns 10 quantile columns: [mean, p10, p20, ..., p90]
# (timesfm_2p5 config: quantiles 0.1..0.9, decode_index=5 is p50, and the
# point forecast is column 5). TimesFMForecastEngine (as of 2026-09-26) builds
# its band from column 0 (the MEAN) and the last column (p90), so the band the
# app shows is [mean, p90], not p10-p90. Here the REAL native p10/p90 are
# read from the model; the app's band is also recorded, to show the impact.
TFM_P10_COL, TFM_P90_COL = 1, 9


def run_timesfm(train, dates):
    from backend.services.forecast_engine import TimesFMForecastEngine
    engine = TimesFMForecastEngine()
    res = engine.forecast(_points(train, dates), horizon=H, confidence=0.95, freq="M")
    if res.is_fallback:
        _fail(f"TimesFM cayó a Holt en el cutoff {dates[-1]} ({res.fallback_reason}); no se cuenta como TimesFM")
    context = np.asarray(train[-engine.MAX_CONTEXT:], dtype=np.float64)
    point, quantiles = engine._model.forecast(horizon=H, inputs=[context])
    if quantiles.shape[-1] != 10:
        _fail(f"TimesFM devolvió {quantiles.shape[-1]} columnas de cuantiles, se esperaban 10")
    q = quantiles[0, :H, :]
    if not np.allclose(np.round(point[0, :H], 2), res.values):
        _fail(f"el punto de TimesFM no coincide con el del motor en {dates[-1]}")
    app_band = (np.array(res.lower_bound), np.array(res.upper_bound))
    return np.array(res.values), None, (q[:, TFM_P10_COL], q[:, TFM_P90_COL]), app_band


def run_prophet(train, dates):
    import pandas as pd
    from prophet import Prophet
    df = pd.DataFrame({"ds": pd.to_datetime(dates), "y": np.log(np.asarray(train, dtype=float))})
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model.fit(df)
    future = model.make_future_dataframe(periods=H, freq="MS", include_history=False)
    point_log = np.asarray(model.predict(future)["yhat"], dtype=float)
    np.random.seed(len(train))  # predictive samples are random; fixed per cutoff
    samples = np.asarray(model.predictive_samples(future)["yhat"], dtype=float)  # (H, n_samples)
    q = lambda p: np.exp(np.quantile(samples, p, axis=1))  # noqa: E731
    return np.exp(point_log), (q(0.025), q(0.975)), (q(0.10), q(0.90))


RUNNERS = {"seasonal_naive": run_seasonal_naive, "holt": run_holt, "holt_winters": run_holt_winters,
           "timesfm": run_timesfm, "prophet": run_prophet}


# --- evaluation ------------------------------------------------------------

def _touches_2020(cutoff: str) -> bool:
    """12-month window after `cutoff` overlaps calendar 2020."""
    y, mth = int(cutoff[:4]), int(cutoff[5:7])
    first = y * 12 + mth + 1   # month index (year*12 + 1..12) of the first forecast month
    last = first + H - 1
    return not (last < 2020 * 12 + 1 or first > 2020 * 12 + 12)


def _cutoff_record(actual, train, point, b95, b80):
    scale = float(np.mean(np.abs(np.asarray(train[M:]) - np.asarray(train[:-M]))))
    err = np.abs(actual - point)
    rec = {"mase_s": float(np.mean(err) / scale), "mape": float(np.mean(err / np.abs(actual)) * 100)}
    for tag, band in (("95", b95), ("80", b80)):
        if band is None:
            rec[f"cov{tag}"] = None
            rec[f"width{tag}"] = None
        else:
            lo, hi = band
            rec[f"cov{tag}"] = float(np.mean((actual >= lo) & (actual <= hi)) * 100)
            rec[f"width{tag}"] = float(np.mean((hi - lo) / actual) * 100)
    return rec


def _aggregate(recs: list, hw_recs: list) -> dict:
    def mean(key):
        vals = [r[key] for r in recs if r[key] is not None]
        return float(np.mean(vals)) if vals else None
    wins = sum(r["mase_s"] < h["mase_s"] for r, h in zip(recs, hw_recs))
    losses = sum(r["mase_s"] > h["mase_s"] for r, h in zip(recs, hw_recs))
    p = float(stats.binomtest(wins, wins + losses, 0.5).pvalue) if wins + losses else None
    out = {"n_cutoffs": len(recs), "mase_s": mean("mase_s"), "mape": mean("mape"),
           "cov95": mean("cov95"), "cov80": mean("cov80"), "width95": mean("width95"), "width80": mean("width80"),
           "wins_vs_hw": wins, "losses_vs_hw": losses, "sign_test_p": p}
    if recs and "cov80_app_band" in recs[0]:
        out["cov80_app_band"] = mean("cov80_app_band")
    return out


def _verdict(agg: dict) -> dict:
    """Lowest mean seasonal MASE replaces Holt-Winters only with a significant
    sign test against it; otherwise Holt-Winters stays (simpler, no weights,
    no non-commercial license)."""
    best = min(agg, key=lambda e: agg[e]["mase_s"])
    if best == "holt_winters":
        return {"engine": "holt_winters", "why": "menor MASE estacional medio"}
    b = agg[best]
    if b["sign_test_p"] is not None and b["sign_test_p"] < SIGN_TEST_ALPHA and b["wins_vs_hw"] > b["losses_vs_hw"]:
        return {"engine": best, "why": f"menor MASE estacional y le gana a HW {b['wins_vs_hw']}-{b['losses_vs_hw']} "
                                      f"(p={b['sign_test_p']:.3f})"}
    return {"engine": "holt_winters",
            "why": f"{best} tuvo menor MASE medio pero no le gana a HW de forma significativa "
                   f"({b['wins_vs_hw']}-{b['losses_vs_hw']}, p={b['sign_test_p']:.3f})"}


def replay(snapshot_path: str, out_path: str, engines: list) -> None:
    from backend.schemas.models import TimeSeriesPoint
    from backend.services.forecast_engine import TimesFMForecastEngine
    from backend.services.seasonality import detect_seasonality

    if "timesfm" in engines and not TimesFMForecastEngine.is_available():
        _fail("TimesFM no está disponible (pesos sin cargar o USE_REAL_TIMESFM=false). No se simula: se frena.")
    if "prophet" in engines:
        try:
            import prophet  # noqa: F401
        except ImportError:
            _fail("Prophet no está instalado: pip install -r requirements-prophet.txt -c requirements.lock")
        for name in ("cmdstanpy", "prophet"):
            logging.getLogger(name).setLevel(logging.WARNING)

    raw = Path(snapshot_path).read_bytes()
    snapshot = json.loads(raw)
    versions = {"python": platform.python_version()}
    for pkg in ("numpy", "pandas", "statsmodels", "timesfm", "torch", "prophet"):
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = None
    result = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "versions": versions, "engines": engines,
              "horizon": H, "series": {}, "pooled": {}, "pooled_ex2020": {}}

    pooled = {e: [] for e in engines}
    pooled_ex = {e: [] for e in engines}
    setup = hc.SETUP["fred"]
    for sid in SERIES:
        vals_map = snapshot["series"][sid]["values"]
        dates = sorted(vals_map)
        vals = [vals_map[d] for d in dates]
        grid = hc._cutoff_indices(len(vals), setup["min_train"], H)
        usable = [i for i in grid if detect_seasonality(
            [TimeSeriesPoint(timestamp=d, value=v) for d, v in zip(dates[: i + 1], vals[: i + 1])]).is_seasonal]
        per_engine = {e: [] for e in engines}
        cutoffs = []
        for i in usable:
            train, tdates = vals[: i + 1], dates[: i + 1]
            actual = np.asarray(vals[i + 1: i + 1 + H], dtype=float)
            cutoffs.append(dates[i])
            for e in engines:
                out = RUNNERS[e](train, tdates)
                point, b95, b80 = out[:3]
                rec = _cutoff_record(actual, train, np.asarray(point, dtype=float), b95, b80)
                if len(out) > 3:  # TimesFM: coverage of the band the app shows today
                    lo, hi = out[3]
                    rec["cov80_app_band"] = float(np.mean((actual >= lo) & (actual <= hi)) * 100)
                rec["cutoff"] = dates[i]
                per_engine[e].append(rec)
        ex_idx = [k for k, c in enumerate(cutoffs) if not _touches_2020(c)]
        s_out = {"cutoffs": cutoffs, "n_dropped_not_seasonal": len(grid) - len(usable), "all": {}, "ex2020": {},
                 "per_cutoff": per_engine}
        for e in engines:
            s_out["all"][e] = _aggregate(per_engine[e], per_engine["holt_winters"])
            s_out["ex2020"][e] = _aggregate([per_engine[e][k] for k in ex_idx],
                                            [per_engine["holt_winters"][k] for k in ex_idx])
            pooled[e] += per_engine[e]
            pooled_ex[e] += [per_engine[e][k] for k in ex_idx]
        s_out["verdict"] = _verdict(s_out["all"])
        s_out["verdict_ex2020"] = _verdict(s_out["ex2020"])
        result["series"][sid] = s_out
        print(f"{sid}: {len(usable)} cutoffs ({len(ex_idx)} sin 2020) → {s_out['verdict']['engine']}")

    for e in engines:
        result["pooled"][e] = _aggregate(pooled[e], pooled["holt_winters"])
        result["pooled_ex2020"][e] = _aggregate(pooled_ex[e], pooled_ex["holt_winters"])

    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    _print(result)
    print(f"\nescrito {out_path}")


def _f(x, pat="{:.1f}"):
    return "n/d" if x is None else pat.format(x)


def _print(r: dict) -> None:
    head = "| {:<14} | {:<14} | {:>3} | {:>7} | {:>6} | {:>6} | {:>6} | {:>7} | {:>7} | {:>8} | {:>6} |"
    for block, title in (("all", "Todos los cutoffs"), ("ex2020", "Sin ventanas que tocan 2020")):
        print(f"\n{title}:")
        print(head.format("serie", "motor", "n", "MASE_s", "MAPE%", "cob95", "cob80", "ancho95", "ancho80",
                          "vs HW", "p"))
        for sid, s in r["series"].items():
            for e, a in s[block].items():
                print(head.format(sid, e, a["n_cutoffs"], _f(a["mase_s"], "{:.3f}"), _f(a["mape"], "{:.2f}"),
                                  _f(a["cov95"]), _f(a["cov80"]), _f(a["width95"]), _f(a["width80"]),
                                  f"{a['wins_vs_hw']}-{a['losses_vs_hw']}", _f(a["sign_test_p"], "{:.3f}")))
        pooled = r["pooled"] if block == "all" else r["pooled_ex2020"]
        for e, a in pooled.items():
            print(head.format("TODAS", e, a["n_cutoffs"], _f(a["mase_s"], "{:.3f}"), _f(a["mape"], "{:.2f}"),
                              _f(a["cov95"]), _f(a["cov80"]), _f(a["width95"]), _f(a["width80"]),
                              f"{a['wins_vs_hw']}-{a['losses_vs_hw']}", _f(a["sign_test_p"], "{:.3f}")))
    print("\nTimesFM: cobertura de la banda que muestra HOY la app ([media, p90]) vs la p10-p90 real:")
    for sid, s in r["series"].items():
        a = s["all"].get("timesfm")
        if a:
            print(f"  {sid:14} banda de la app {_f(a.get('cov80_app_band'))}% | p10-p90 real {_f(a['cov80'])}%")
    print("\nVeredicto por serie (todos / sin 2020):")
    for sid, s in r["series"].items():
        print(f"  {sid:14} {s['verdict']['engine']:14} ({s['verdict']['why']}) / "
              f"{s['verdict_ex2020']['engine']} ({s['verdict_ex2020']['why']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--replay", required=True, metavar="SNAPSHOT")
    parser.add_argument("--out", required=True)
    parser.add_argument("--engines", default=",".join(ENGINES),
                        help=f"subconjunto de {ENGINES} (holt_winters es obligatorio: es la referencia)")
    args = parser.parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = set(engines) - set(ENGINES)
    if unknown:
        parser.error(f"motores desconocidos: {sorted(unknown)}")
    if "holt_winters" not in engines:
        parser.error("holt_winters es la referencia de las comparaciones en pares")
    replay(args.replay, args.out, engines)


if __name__ == "__main__":
    main()
