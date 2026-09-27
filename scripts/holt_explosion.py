"""
Holt explosion after a level jump (item 2.6 of docs/PLAN.md): diagnosis.

    python scripts/holt_explosion.py --replay data/snapshots/holt_coverage_2026-09-26.json --out results.json

1. Mechanism: UNRATE with cutoffs around the April 2020 jump, decomposed into
   fitted parameters, final level/trend, damped trend sum, median exp(y_hat)
   and the lognormal bias factor exp(var/2).
2. Scan: every series of the snapshot at cutoffs near 2008-09..2009-06 and
   2020-02..2020-07 (when the series covers them) and right at / after its 5
   largest one-step jumps; canonical horizon (daily 60, monthly 12) and 30.
   "Explosion index" X = |log(F_H / y_T)| / M_H, with M_H the largest
   |log(y_{t+H} / y_t)| seen in the training data: how far beyond anything
   the series ever did in H steps the forecast goes.
3. Options (--options, needs TimesFM): experimental Holt variants measured on
   the 24-cutoff grid against the current Holt — A (Huber-clipped error in
   level and trend), C (clipped only in the trend update) — plus how often
   the "no confiable" mark (X > 2) fires. Definitions pre-registered in the
   round log before measuring.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVENT_WINDOWS = [("2008-09-01", "2009-06-30"), ("2020-02-01", "2020-07-31")]
N_TOP_JUMPS = 5


def _points(entry):
    from backend.schemas.models import TimeSeriesPoint
    dates = sorted(entry["values"])
    return [TimeSeriesPoint(timestamp=d, value=entry["values"][d]) for d in dates]


# The index is the production one (backend/services/reliability.py, 2.6).
from backend.services.reliability import FLAG_X, explosion_index, max_historical_move  # noqa: E402,F401


HUBER_K = 2.0          # Gelper, Fried & Croux (2010)
JUMP_SIGMAS = 4.0      # a cutoff is a "jump" one if its last step is > 4 robust sigmas


def _robust_scale(y):
    d = np.diff(y)
    mad = np.median(np.abs(d - np.median(d)))
    return 1.4826 * mad if mad > 0 else float(np.std(d)) or 1e-6


def make_robust_holt(mode: str, k: float = HUBER_K):
    """Experimental damped Holt (2.6), a copy of DampedHoltForecastEngine's
    filter where the one-step error that updates the state is Huber-clipped
    to +-k*s (s = 1.4826 * MAD of the training first differences):
    mode 'both' (A) clips it in the level and trend updates, 'trend' (C) only
    in the trend update, 'none' is the production engine (checked in tests).
    The fit minimises the SSE of the clipped error; the interval variance is
    computed as in production (raw residuals)."""
    from scipy import optimize, stats
    from backend.schemas.models import ForecastResponse
    from backend.services.forecast_engine import DampedHoltForecastEngine

    class RobustHolt(DampedHoltForecastEngine):
        def forecast(self, points, horizon=30, confidence=0.95, freq="D"):
            sp = sorted(points, key=lambda p: p.timestamp)
            vals = np.array([p.value for p in sp], dtype=float)
            n = len(vals)
            use_log = np.all(vals > 0)
            y = np.log(vals) if use_log else vals.copy()
            s = _robust_scale(y)
            lim = k * s if mode != "none" else np.inf

            def filt(alpha, beta, phi, collect=False):
                level, trend = y[0], (y[1] - y[0]) if n > 1 else 0.0
                sse, res = 0.0, []
                for t in range(1, n):
                    y_hat = level + phi * trend
                    e = y[t] - y_hat
                    ec = min(max(e, -lim), lim)
                    sse += ec * ec
                    res.append(e)
                    level = y_hat + alpha * (ec if mode == "both" else e)
                    trend = phi * trend + alpha * beta * (ec if mode in ("both", "trend") else e)
                return (level, trend, res) if collect else sse

            try:
                opt = optimize.minimize(lambda p: filt(*p), [0.3, 0.1, 0.95], method="L-BFGS-B",
                                        bounds=[(0.01, 0.99), (0.01, 0.99), (0.80, 0.98)])
                alpha, beta, phi = opt.x
            except Exception:
                alpha, beta, phi = 0.3, 0.1, 0.95
            level, trend, residuals = filt(alpha, beta, phi, collect=True)
            sigma2 = float(np.mean(np.square(residuals))) if len(residuals) > 1 else 1e-4
            if sigma2 <= 0 or np.isnan(sigma2):
                sigma2 = 1e-4
            z = stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0)
            vals_out, lo, hi, c_sum = [], [], [], 0.0
            allow_negative = np.any(vals < 0)
            for h in range(1, horizon + 1):
                cum_phi = phi * (1.0 - phi ** h) / (1.0 - phi) if abs(1.0 - phi) > 1e-7 else float(h)
                y_hat_h = level + cum_phi * trend
                if h == 1:
                    var_h = sigma2
                else:
                    j = h - 1
                    c_j = alpha + alpha * beta * phi * (1.0 - phi ** j) / (1.0 - phi) if abs(1.0 - phi) > 1e-7 else alpha + alpha * beta * j
                    c_sum += c_j * c_j
                    var_h = sigma2 * (1.0 + c_sum)
                se_h = np.sqrt(var_h)
                if use_log:
                    pv, lb, ub = np.exp(y_hat_h + var_h / 2.0), np.exp(y_hat_h - z * se_h), np.exp(y_hat_h + z * se_h)
                else:
                    pv, lb, ub = y_hat_h, y_hat_h - z * se_h, y_hat_h + z * se_h
                    if not allow_negative:
                        lb = max(0.0, lb)
                vals_out.append(float(pv)); lo.append(float(lb)); hi.append(float(ub))  # like production since 2.11
            return ForecastResponse(
                timestamps=self._generate_future_timestamps(sp[-1].timestamp, horizon, freq),
                values=vals_out, lower_bound=lo, upper_bound=hi, interval_level=confidence,
                model_name=f"damped-holt-robust-{mode}", is_fallback=False,
                fitted_params={"alpha": round(float(alpha), 4), "beta": round(float(beta), 4),
                               "phi": round(float(phi), 4), "sigma": round(float(np.sqrt(sigma2)), 4)},
            )

    return RobustHolt


def is_jump_cutoff(train_values) -> bool:
    """Last step larger than JUMP_SIGMAS robust sigmas of the training steps."""
    v = np.asarray(train_values, dtype=float)
    d = np.diff(np.log(v)) if np.all(v > 0) else np.diff(v)
    if len(d) < 3:
        return False
    s = 1.4826 * np.median(np.abs(d[:-1] - np.median(d[:-1])))
    return bool(s > 0 and abs(d[-1] - np.median(d[:-1])) > JUMP_SIGMAS * s)


def run_holt(train, h, freq):
    from backend.services.forecast_engine import DampedHoltForecastEngine
    eng = DampedHoltForecastEngine()
    res = eng.forecast(train, horizon=h, confidence=0.80, freq=freq)
    return eng, res


def mechanism(entry, cutoffs, horizons):
    pts = _points(entry)
    rows = []
    for c in cutoffs:
        train = [p for p in pts if p.timestamp <= c]
        future = [p for p in pts if p.timestamp > c]
        for h in horizons:
            eng, res = run_holt(train, h, "M")
            st = eng.last_state
            a, b, phi, s2 = st["alpha"], st["beta"], st["phi"], st["sigma2"]
            cum_phi = phi * (1 - phi ** h) / (1 - phi)
            y_hat = st["level"] + cum_phi * st["trend"]
            c_sum = sum((a + a * b * phi * (1 - phi ** j) / (1 - phi)) ** 2 for j in range(1, h))
            var_h = s2 * (1 + c_sum)
            point = float(np.exp(y_hat + var_h / 2))
            assert abs(point - res.values[-1]) <= max(0.01, 1e-6 * point), (point, res.values[-1])
            rows.append({
                "cutoff": c, "h": h, "last": train[-1].value,
                "alpha": a, "beta": b, "phi": phi, "sigma": float(np.sqrt(s2)),
                "last_residual": st["last_residual"],
                "level": float(np.exp(st["level"])), "trend_per_step": st["trend"],
                "cum_phi": cum_phi, "median": float(np.exp(y_hat)), "bias_factor": float(np.exp(var_h / 2)),
                "forecast": res.values[-1], "band": [res.lower_bound[-1], res.upper_bound[-1]],
                "actual": future[h - 1].value if len(future) >= h else None,
                "x_index": explosion_index([p.value for p in train], res.values[-1], h),
            })
    return rows


def scan_cutoffs(pts) -> list:
    dates = [p.timestamp for p in pts]
    vals = np.array([p.value for p in pts], dtype=float)
    out = set()
    for lo, hi in EVENT_WINDOWS:
        out |= {d for d in dates if lo <= d <= hi}
    lr = np.diff(np.log(vals)) if np.all(vals > 0) else np.diff(vals)
    for i in np.argsort(-np.abs(lr))[:N_TOP_JUMPS]:
        out.add(dates[i + 1])                    # training ends WITH the jump
        if i + 2 < len(dates):
            out.add(dates[i + 2])                # one observation later
    return sorted(out)


def scan(sid, entry):
    from backend.services.seasonality import infer_frequency
    pts = _points(entry)
    freq_name = infer_frequency([p.timestamp for p in pts])
    freq = "M" if freq_name == "monthly" else "D"
    canonical = 12 if freq == "M" else 60
    rows = []
    for c in scan_cutoffs(pts):
        train = [p for p in pts if p.timestamp <= c]
        if len(train) < 30:
            continue
        future = [p for p in pts if p.timestamp > c]
        for h in sorted({canonical, 30}):
            _, res = run_holt(train, h, freq)
            rows.append({
                "cutoff": c, "h": h, "last": train[-1].value, "forecast": res.values[-1],
                "band": [res.lower_bound[-1], res.upper_bound[-1]],
                "actual": future[h - 1].value if len(future) >= h else None,
                "ratio": res.values[-1] / train[-1].value if train[-1].value else None,
                "x_index": explosion_index([p.value for p in train], res.values[-1], h),
            })
    return {"frequency": freq_name, "rows": rows}


def options(sid, entry):
    """Variants A/C vs current Holt, and the X > 2 mark, on the 24-cutoff grid
    (canonical horizon and 30): error, coverage, marks, regret."""
    import random
    from decision_stability import _Evaluator
    from horizon_variants import N_GRID, N_RANDOM_SUBSETS, _decide, holdout_regret
    from backend.schemas.models import TimeSeriesData
    from backend.services import auto_discovery as ad
    from backend.services.seasonality import detect_seasonality, infer_frequency
    is_macro = entry["category"] == "fred"
    pts = _points(entry)
    dates = [p.timestamp for p in pts]
    vals = [p.value for p in pts]
    series = TimeSeriesData(id=sid, name=sid, type="macro" if is_macro else "equity", unit="", points=pts, source="live")
    freq_name = infer_frequency(dates)
    window = ad.RECENT_WINDOW.get(freq_name, ad.RECENT_WINDOW_DEFAULT)
    seasonal = detect_seasonality(pts).is_seasonal
    baseline, metric = ("holt_winters", "mase_seasonal") if seasonal else ("holt", "mase")
    bases = [baseline] if seasonal else ["holt", "holt_A", "holt_C"]
    canonical = 12 if freq_name == "monthly" else 60
    out = {"category": entry["category"], "baseline": baseline, "horizons": {}}
    for h in sorted({canonical, 30}):
        ev = _Evaluator(sid, series, is_macro, horizon=h,
                        extra_engines={"holt_A": make_robust_holt("both"), "holt_C": make_robust_holt("trend")})
        grid = ad.recent_cutoff_indices(len(pts), N_GRID, window, horizon=h)
        jump = {i: is_jump_cutoff(vals[: i + 1]) for i in grid}
        per_engine, errors = {}, {}
        for eng in bases + ["timesfm"]:
            rows = []
            for i in grid:
                r = ev.run(i, eng)
                err = None if r.get("refused") or r.get("fallback") or r.get(metric) is None else r[metric]
                x = explosion_index(vals[: i + 1], r["pred_end"], h) if r.get("pred_end") else None
                rows.append({"date": dates[i], "jump": jump[i], "err": err, "cov": r.get("cov"), "x": x,
                             "flag": bool(x is not None and x > FLAG_X)})
            errors[eng] = {i: row["err"] for i, row in zip(grid, rows)}
            per_engine[eng] = rows
        rng = random.Random(f"{sid}-2.3b-{h}")
        subsets = [tuple(sorted(rng.sample(grid, ad.DECISION_N_CUTOFFS))) for _ in range(N_RANDOM_SUBSETS)]
        regrets = {}
        for b in bases:
            decisions = [_decide(ev, list(sub), b, metric) for sub in subsets]
            regrets[b] = [holdout_regret(errors[b], errors["timesfm"], grid, sub, d, b)
                          for sub, d in zip(subsets, decisions)]
        out["horizons"][str(h)] = {"cutoffs": per_engine, "regrets": regrets}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--options", action="store_true", help="mide las variantes A/C y la marca (necesita TimesFM)")
    args = ap.parse_args()
    if args.options:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from backend.services.forecast_engine import TimesFMForecastEngine
        if not TimesFMForecastEngine.is_available():
            print("ERROR: TimesFM no disponible; no se simula.", file=sys.stderr)
            sys.exit(2)
        raw = Path(args.replay).read_bytes()
        snap = json.loads(raw)
        res = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "flag_x": FLAG_X, "huber_k": HUBER_K,
               "jump_sigmas": JUMP_SIGMAS, "series": {}}
        for sid, e in snap["series"].items():
            res["series"][sid] = options(sid, e)
            print(sid, flush=True)
        Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print("escrito", args.out)
        return
    raw = Path(args.replay).read_bytes()
    snap = json.loads(raw)
    res = {
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "mechanism_unrate": mechanism(snap["series"]["UNRATE"],
                                      ["2020-02-01", "2020-03-01", "2020-04-01", "2020-05-01", "2020-06-01"], [12, 30]),
        "scan": {sid: scan(sid, e) for sid, e in snap["series"].items()},
    }
    Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("escrito", args.out)


if __name__ == "__main__":
    main()
