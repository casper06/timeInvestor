"""
Smoke test against REAL data (yfinance + FRED), for comparing dependency sets.

The test suite mocks yfinance and FRED, so it can't tell whether a different
pandas/yfinance version changes the numbers the app computes. This script
downloads real data through the app's own fetchers, cuts it to a FIXED date
window (never "today"), and runs a Damped Holt forecast and a backtest on it.
Run it in two environments and compare the JSON outputs:

    python scripts/smoke_real_data.py --out old.json      # venv A
    python scripts/smoke_real_data.py --out new.json      # venv B
    python scripts/smoke_real_data.py --compare old.json new.json

Needs FRED_API_KEY (from .env or the environment). Without it, or if any
series comes back synthetic, it exits with an error: it never falls back to
generated data. yfinance needs no key.

Comparing prices: Yahoo recomputes adjusted closes between requests, so the
same environment can get values that differ by ~1e-4 USD from one download to
the next (measured 2026-09-26: 0 differences between yfinance 0.2.66 and 1.7.0
fetched back to back, but up to 2e-4 between two fetches a few minutes apart
with the same versions). After the app's round(close, 2), that flips a few
dates by one cent. --compare reports those one-cent flips separately and
doesn't count them as differences; anything above a cent, and any difference
in dates, forecast or backtest metrics, does count.

Exit codes: 0 ok (or no differences on --compare), 1 differences found, 2 setup
or data error.
"""
import argparse
import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Fixed windows: the backtest cutoffs leave HORIZON real points after them
# inside the window, and the window ends in the past so the data is final.
WINDOW_START = "2022-01-03"
WINDOW_END = "2026-06-30"
SERIES = [
    # (series_id, kind, backtest cutoff, backtest horizon, forecast horizon)
    ("JNJ", "equity", "2026-03-31", 30, 30),
    ("SPY", "etf", "2026-03-31", 30, 30),
    ("INDPRO", "macro", "2025-06-01", 12, 12),
]
# Closing values reported one by one; the rest of the window goes into a hash.
SAMPLE_DATES = ["2022-01-03", "2024-01-02", "2026-03-31", "2026-06-30",
                "2022-01-01", "2024-01-01", "2025-06-01", "2026-06-01"]
PACKAGES = ["pandas", "numpy", "yfinance", "scipy", "fastapi", "pydantic", "httpx"]
FLOAT_TOLERANCE = 1e-9
PRICE_NOISE = 0.01  # one cent: Yahoo's request-to-request noise after rounding


def _fail(message: str) -> "NoReturn":
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def _versions() -> dict:
    out = {"python": platform.python_version()}
    for pkg in PACKAGES:
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def _fetch(series_id: str, kind: str):
    from backend.services.data_fetcher import FREDDataFetcher, MarketDataFetcher

    if kind == "macro":
        data = FREDDataFetcher().get_series(series_id)
    else:
        data = MarketDataFetcher.get_history(series_id, period="5y")
    if data.source != "live":
        _fail(f"{series_id} llegó con source={data.source!r}; este smoke test solo acepta datos reales")
    return data


def _window(data):
    points = sorted(
        (p for p in data.points if WINDOW_START <= p.timestamp <= WINDOW_END),
        key=lambda p: p.timestamp,
    )
    if not points:
        _fail(f"{data.id}: ningún punto dentro de {WINDOW_START}..{WINDOW_END}")
    return data.model_copy(update={"points": points})


def _run_one(series_id: str, kind: str, cutoff: str, bt_horizon: int, fc_horizon: int) -> dict:
    from backend.services import backtest_engine
    from backend.services.backtest_engine import BacktestEngine
    from backend.services.forecast_engine import DampedHoltForecastEngine

    windowed = _window(_fetch(series_id, kind))
    points = windowed.points
    by_date = {p.timestamp: p.value for p in points}
    serialized = "\n".join(f"{p.timestamp}:{p.value!r}" for p in points)

    freq = "M" if kind == "macro" else "D"
    forecast = DampedHoltForecastEngine().forecast(points, horizon=fc_horizon, confidence=0.95, freq=freq)

    # run_backtest fetches on its own (period="5y" back from today, so its
    # training start would move every day). Hand it the fixed window instead:
    # same metric code, same real data, stable dates.
    class _FixedMarket:
        @staticmethod
        def get_history(*args, **kwargs):
            return windowed

    class _FixedFred:
        SERIES_CATALOG = backtest_engine.FREDDataFetcher.SERIES_CATALOG

        def get_series(self, *args, **kwargs):
            return windowed

    real_market, real_fred = backtest_engine.MarketDataFetcher, backtest_engine.FREDDataFetcher
    backtest_engine.MarketDataFetcher, backtest_engine.FREDDataFetcher = _FixedMarket, _FixedFred
    try:
        bt = BacktestEngine.run_backtest(
            series_id=series_id, cutoff_date=cutoff, horizon=bt_horizon,
            is_macro=(kind == "macro"), engine_override=DampedHoltForecastEngine(),
        )
    finally:
        backtest_engine.MarketDataFetcher, backtest_engine.FREDDataFetcher = real_market, real_fred

    return {
        "kind": kind,
        "n_points": len(points),
        "first": points[0].timestamp,
        "last": points[-1].timestamp,
        "values_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "values": by_date,
        "samples": {d: by_date[d] for d in SAMPLE_DATES if d in by_date},
        "forecast": {
            "horizon": fc_horizon,
            "first": forecast.values[0],
            "last": forecast.values[-1],
            "lower_last": forecast.lower_bound[-1],
            "upper_last": forecast.upper_bound[-1],
            "fitted_params": forecast.fitted_params,
        },
        "backtest": {
            "cutoff": cutoff,
            "horizon": bt_horizon,
            "observations": bt.metrics.observations_evaluated,
            "mase": bt.metrics.mase,
            "mae": bt.metrics.mae,
            "mape": bt.metrics.mape,
            "coverage": bt.interval_coverage,
        },
    }


def run(out_path: str) -> None:
    from backend.config import settings

    if not (settings.FRED_API_KEY and settings.FRED_API_KEY.strip()):
        _fail("falta FRED_API_KEY (en .env o en el entorno). Sin ella no hay serie FRED real que comparar.")
    settings.ALLOW_SYNTHETIC_DATA = False  # never fall back to generated data

    result = {"versions": _versions(), "window": [WINDOW_START, WINDOW_END], "series": {}}
    for series_id, kind, cutoff, bt_h, fc_h in SERIES:
        try:
            result["series"][series_id] = _run_one(series_id, kind, cutoff, bt_h, fc_h)
        except SystemExit:
            raise
        except Exception as e:
            _fail(f"{series_id}: {type(e).__name__}: {e}")
        s = result["series"][series_id]
        print(f"{series_id:7} n={s['n_points']} {s['first']}..{s['last']} "
              f"MASE={s['backtest']['mase']} cobertura={s['backtest']['coverage']}")

    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"versiones: {result['versions']}")
    print(f"escrito {out_path}")


def _diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            yield from _diff(a.get(key), b.get(key), f"{path}.{key}" if path else key)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > FLOAT_TOLERANCE * max(1.0, abs(a), abs(b)):
            yield path, a, b
    elif a != b:
        yield path, a, b


def _price_report(series_id: str, va: dict, vb: dict) -> list:
    """Prints how the two price series differ; returns the differences that
    count (dates missing on one side, or a value off by more than a cent)."""
    counted = []
    for d in sorted(set(va) ^ set(vb)):
        counted.append((f"{series_id}.values[{d}]", va.get(d), vb.get(d)))
    common = sorted(set(va) & set(vb))
    deltas = [(d, va[d], vb[d]) for d in common if va[d] != vb[d]]
    noise = [x for x in deltas if abs(x[2] - x[1]) <= PRICE_NOISE + 1e-9]
    counted += [(f"{series_id}.values[{d}]", x, y) for d, x, y in deltas if (d, x, y) not in noise]
    print(f"  {series_id}: {len(common)} fechas en común, {len(deltas)} con valor distinto "
          f"({len(noise)} de ±1 centavo, ruido de redondeo de Yahoo)")
    for d, x, y in noise[:10]:
        print(f"    {d}: {x} -> {y}")
    return counted


def compare(path_a: str, path_b: str) -> None:
    a = json.loads(Path(path_a).read_text(encoding="utf-8"))
    b = json.loads(Path(path_b).read_text(encoding="utf-8"))
    print("versiones A:", a["versions"])
    print("versiones B:", b["versions"])
    diffs = []
    print("Precios:")
    for sid in sorted(set(a["series"]) | set(b["series"])):
        sa, sb = a["series"].get(sid, {}), b["series"].get(sid, {})
        diffs += _price_report(sid, sa.get("values", {}), sb.get("values", {}))
        # Everything else (dates, counts, forecast, backtest) must match exactly.
        rest_a = {k: v for k, v in sa.items() if k not in ("values", "values_sha256", "samples")}
        rest_b = {k: v for k, v in sb.items() if k not in ("values", "values_sha256", "samples")}
        diffs += [(f"{sid}.{p}", x, y) for p, x, y in _diff(rest_a, rest_b)]
    if not diffs:
        print("Sin diferencias fuera del ruido de redondeo: mismas fechas, forecast y backtest.")
        return
    print(f"{len(diffs)} diferencias:")
    for path, va, vb in diffs:
        print(f"  {path}: {va!r} -> {vb!r}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="corre el smoke test y escribe el JSON acá")
    group.add_argument("--compare", nargs=2, metavar=("A", "B"), help="compara dos JSON")
    args = parser.parse_args()
    if args.out:
        run(args.out)
    else:
        compare(*args.compare)


if __name__ == "__main__":
    main()
