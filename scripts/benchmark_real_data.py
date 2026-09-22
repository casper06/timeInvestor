#!/usr/bin/env python3
"""
TimeInvestor - Real-Data Walk-Forward Benchmark: TimesFM vs Damped Holt vs Naive RW
====================================================================================
Extends the synthetic-series benchmark in `download_and_benchmark_timesfm.py` with
walk-forward backtests over REAL market/macro data, across four categories used to
decide the per-series engine selection rules (see EngineSelector):

  1. Seasonal FRED macro series (real annual cycle, NSA/not-seasonally-adjusted)
  2. Diversified index/sector ETFs (SPY, QQQ, XLE, XLK)
  3. Cold-start series (individual equities with context truncated to 30/60/90 days)
  4. Individual equity baseline (full history) — for comparison against categories 1-3

REGLA DE INTEGRIDAD (same as download_and_benchmark_timesfm.py):
Never fabricates data. If FRED_API_KEY is missing or ALLOW_SYNTHETIC_DATA silently
substitutes a synthetic series, this script detects `TimeSeriesData.source` and
reports the series as excluded rather than benchmarking synthetic data as if real.
"""

import sys
import os
import argparse
from pathlib import Path
from typing import List, Optional, Dict, Tuple
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.models import TimeSeriesPoint
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher
from backend.services.forecast_engine import DampedHoltForecastEngine

# ---------------------------------------------------------------------------
# Series catalogs for this benchmark run
# ---------------------------------------------------------------------------

# Seasonal FRED series: all NSA (not seasonally adjusted, i.e. the raw cycle is
# still in the data — an SA series has had its annual seasonality removed by the
# statistical agency, which would make "does the model catch the seasonal cycle"
# unanswerable). Verified against FRED's own `/fred/series` metadata endpoint
# (seasonal_adjustment_short == "NSA") before inclusion, not assumed from the name.
SEASONAL_FRED_SERIES = {
    "IPG2211A2N": "Producción eléctrica/gas (NAICS 2211,2) — ciclo de demanda de calefacción/refrigeración anual, ya en el catálogo base de FREDDataFetcher.",
    "RSAFSNA": "Ventas minoristas + food services (NSA) — pico navideño de diciembre, uno de los ciclos estacionales más documentados en macro de EE.UU.",
    "HOUSTNSA": "Inicios de construcción de vivienda (NSA) — estacionalidad climática fuerte (mínimos en invierno, máximos en primavera/verano).",
    "MRTSSM4451USN": "Ventas de supermercados (NSA) — estacionalidad de fin de año/festividades, ciclo distinto al retail general (RSAFSNA).",
}

# Diversified index/sector ETFs — broad baskets, not single-company idiosyncratic risk.
DIVERSIFIED_ETFS = ["SPY", "QQQ", "XLE", "XLK"]

# Individual equities used as (a) the cold-start source series and (b) the
# full-history baseline for comparison. Chosen for sector diversity, not cherry-picked
# for a particular result: mega-cap growth tech, mega-cap "value" tech, high-volatility
# tech, and a non-tech defensive/healthcare name.
INDIVIDUAL_EQUITIES = ["AAPL", "MSFT", "NVDA", "JNJ"]

COLD_START_WINDOWS = [30, 60, 90]

# Multiple walk-forward cutoffs per series, so results aren't an artifact of one
# lucky/unlucky split (the existing BacktestEngine.run_backtest API only takes one
# cutoff at a time — this script drives it with several).
N_CUTOFFS = 5


def get_real_timesfm_engine():
    """Same probing logic as download_and_benchmark_timesfm.py's get_real_timesfm_engine."""
    try:
        from backend.services.forecast_engine import TimesFMForecastEngine
        engine = TimesFMForecastEngine()
        if engine._model is None:
            engine._load_model()
        if engine._model is not None:
            return engine
        return None
    except Exception:
        return None


def compute_mase(y_train: np.ndarray, y_test: np.ndarray, y_pred: np.ndarray) -> float:
    naive_diff = np.abs(np.diff(y_train))
    scale = np.mean(naive_diff)
    if scale < 1e-8:
        scale = 1e-8
    mae = np.mean(np.abs(y_test - y_pred))
    return float(mae / scale)


def compute_interval_coverage(y_test: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    inside = (y_test >= lower) & (y_test <= upper)
    return float(np.mean(inside) * 100.0)


def get_declared_interval_pct(forecast_response, default: Optional[float] = None) -> Optional[float]:
    """Same rationale as download_and_benchmark_timesfm.py: TimesFM's quantile head
    only exposes an 80% (p10-p90) empirical interval, not a genuine 95% one — read
    the real declared level from fitted_params instead of assuming 95% for every engine."""
    fitted_params = getattr(forecast_response, "fitted_params", None)
    if fitted_params:
        level = fitted_params.get("actual_interval_pct")
        if level is not None:
            return float(level)
    return default


def fetch_series(series_id: str, is_macro: bool, period: str = "5y") -> Optional[Tuple[List[TimeSeriesPoint], str, str]]:
    """Fetches real data for a series. Returns (sorted_points, freq, unit) or None if
    the source turned out to be synthetic (excluded, never silently benchmarked)."""
    try:
        if is_macro:
            data = FREDDataFetcher().get_series(series_id)
        else:
            data = MarketDataFetcher.get_history(series_id, period=period)
    except Exception as e:
        print(f"  [!] {series_id}: fallo al obtener datos ({e}) — excluida del benchmark.")
        return None

    if getattr(data, "source", "live") == "synthetic":
        print(f"  [!] {series_id}: fuente sintética ({data.source_detail}) — excluida del benchmark real.")
        return None

    points = sorted(data.points, key=lambda p: p.timestamp)
    freq = "M" if data.type == "macro" else "D"
    return points, freq, data.unit


def walk_forward_cutoffs(points: List[TimeSeriesPoint], horizon: int, n_cutoffs: int, min_train: int) -> List[int]:
    """Picks n_cutoffs train-set end indices, evenly spaced over the usable range,
    each leaving at least `horizon` points for evaluation."""
    n = len(points)
    last_possible = n - horizon
    if last_possible <= min_train:
        return [min_train] if min_train < n else []
    if n_cutoffs == 1:
        return [last_possible]
    step = (last_possible - min_train) / (n_cutoffs - 1)
    return sorted(set(int(round(min_train + i * step)) for i in range(n_cutoffs)))


def run_engine_at_cutoff(engine, points: List[TimeSeriesPoint], cutoff_idx: int, horizon: int, freq: str):
    """Runs one engine on one train/test split. Returns None on inference failure
    (engine unavailable or errored) rather than fabricating a result."""
    train_points = points[:cutoff_idx]
    test_points = points[cutoff_idx:cutoff_idx + horizon]
    if len(test_points) < horizon:
        return None
    try:
        res = engine.forecast(train_points, horizon=len(test_points), confidence=0.95, freq=freq)
    except Exception as e:
        return None

    y_train = np.array([p.value for p in train_points], dtype=float)
    y_test = np.array([p.value for p in test_points], dtype=float)
    y_pred = np.array(res.values[:len(test_points)], dtype=float)
    lb = np.array(res.lower_bound[:len(test_points)], dtype=float)
    ub = np.array(res.upper_bound[:len(test_points)], dtype=float)

    mase = compute_mase(y_train, y_test, y_pred)
    coverage = compute_interval_coverage(y_test, lb, ub)
    declared_pct = get_declared_interval_pct(res, default=95.0)
    return {"mase": mase, "coverage": coverage, "declared_pct": declared_pct}


def run_naive_rw_at_cutoff(points: List[TimeSeriesPoint], cutoff_idx: int, horizon: int):
    train_points = points[:cutoff_idx]
    test_points = points[cutoff_idx:cutoff_idx + horizon]
    if len(test_points) < horizon:
        return None
    y_train = np.array([p.value for p in train_points], dtype=float)
    y_test = np.array([p.value for p in test_points], dtype=float)
    last_val = y_train[-1]
    y_pred = np.full(len(test_points), last_val)
    daily_vol = np.std(np.diff(y_train)) if len(y_train) > 1 else 0.0
    h_vec = np.arange(1, len(test_points) + 1)
    lb = last_val - 1.96 * daily_vol * np.sqrt(h_vec)
    ub = last_val + 1.96 * daily_vol * np.sqrt(h_vec)
    mase = compute_mase(y_train, y_test, y_pred)
    coverage = compute_interval_coverage(y_test, lb, ub)
    return {"mase": mase, "coverage": coverage, "declared_pct": 95.0}


def aggregate_runs(runs: List[Optional[dict]]) -> Optional[dict]:
    valid = [r for r in runs if r is not None]
    if not valid:
        return None
    return {
        "mase_mean": float(np.mean([r["mase"] for r in valid])),
        "mase_std": float(np.std([r["mase"] for r in valid])),
        "coverage_mean": float(np.mean([r["coverage"] for r in valid])),
        "declared_pct": valid[0]["declared_pct"],
        "n": len(valid),
    }


def format_result(agg: Optional[dict]) -> Tuple[str, str]:
    if agg is None:
        return "No evaluado", "No evaluado"
    mase_str = f"{agg['mase_mean']:.3f} (±{agg['mase_std']:.3f}, n={agg['n']})"
    cov_str = f"Cob. ({agg['declared_pct']:.0f}%): {agg['coverage_mean']:.1f}%"
    return mase_str, cov_str


def benchmark_one_series(
    label: str,
    series_id: str,
    is_macro: bool,
    horizon: int,
    holt_engine,
    tfm_engine,
    context_limit_days: Optional[int] = None,
) -> Optional[Dict]:
    fetched = fetch_series(series_id, is_macro=is_macro)
    if fetched is None:
        return None
    points, freq, unit = fetched

    if context_limit_days is not None:
        min_train = context_limit_days
        # Cold-start: fixed short context per cutoff, not "all history up to cutoff".
        # We slide a context_limit_days-wide training WINDOW (not an expanding one)
        # to genuinely simulate "a company with only N days of trading history",
        # rather than a long-history series merely truncated once.
        n = len(points)
        last_possible = n - horizon
        if last_possible <= context_limit_days:
            print(f"  [!] {series_id}: histórico insuficiente para ventana de {context_limit_days}d + horizonte {horizon}d.")
            return None
        cutoffs = walk_forward_cutoffs(points, horizon, N_CUTOFFS, context_limit_days)
        holt_runs, tfm_runs, rw_runs = [], [], []
        for cutoff_idx in cutoffs:
            window_start = max(0, cutoff_idx - context_limit_days)
            window_points = points[window_start:cutoff_idx]
            test_points = points[cutoff_idx:cutoff_idx + horizon]
            if len(test_points) < horizon or len(window_points) < 5:
                continue
            full_slice = window_points + test_points
            holt_runs.append(run_engine_at_cutoff(holt_engine, full_slice, len(window_points), horizon, freq))
            if tfm_engine is not None:
                tfm_runs.append(run_engine_at_cutoff(tfm_engine, full_slice, len(window_points), horizon, freq))
            rw_runs.append(run_naive_rw_at_cutoff(full_slice, len(window_points), horizon))
    else:
        min_train = max(30, horizon * 2)
        cutoffs = walk_forward_cutoffs(points, horizon, N_CUTOFFS, min_train)
        holt_runs, tfm_runs, rw_runs = [], [], []
        for cutoff_idx in cutoffs:
            holt_runs.append(run_engine_at_cutoff(holt_engine, points, cutoff_idx, horizon, freq))
            if tfm_engine is not None:
                tfm_runs.append(run_engine_at_cutoff(tfm_engine, points, cutoff_idx, horizon, freq))
            rw_runs.append(run_naive_rw_at_cutoff(points, cutoff_idx, horizon))

    if not cutoffs:
        print(f"  [!] {series_id}: sin cutoffs válidos (historia insuficiente).")
        return None

    return {
        "label": label,
        "series_id": series_id,
        "n_points": len(points),
        "n_cutoffs_used": len(cutoffs),
        "holt": aggregate_runs(holt_runs),
        "tfm": aggregate_runs(tfm_runs) if tfm_engine is not None else None,
        "rw": aggregate_runs(rw_runs),
    }


def print_category_table(title: str, results: List[Dict], tfm_available: bool):
    print("\n" + "=" * 115)
    print(f" {title}")
    print("=" * 115)
    tfm_header = "TimesFM (Real 200M)" if tfm_available else "TimesFM (no evaluado)"
    print(f" {'Serie':<20} | {'Métrica':<10} | {tfm_header:<32} | {'Damped Holt MLE':<28} | {'Naive Random Walk':<24}")
    print("-" * 115)
    for r in results:
        tfm_mase, tfm_cov = format_result(r["tfm"])
        holt_mase, holt_cov = format_result(r["holt"])
        rw_mase, rw_cov = format_result(r["rw"])
        print(f" {r['label']:<20} | {'MASE':<10} | {tfm_mase:<32} | {holt_mase:<28} | {rw_mase:<24}")
        print(f" {'(n=' + str(r['n_points']) + ' pts, ' + str(r['n_cutoffs_used']) + ' cutoffs)':<20} | {'Cobertura':<10} | {tfm_cov:<32} | {holt_cov:<28} | {rw_cov:<24}")
        print("-" * 115)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark walk-forward real (FRED + yfinance): TimesFM vs Damped Holt vs Naive RW"
    )
    parser.add_argument("--allow-missing", action="store_true", help="Continuar aunque TimesFM no esté disponible")
    args = parser.parse_args()

    print("=" * 115)
    print(" BENCHMARK DE DATOS REALES — SELECCIÓN DE MOTOR POR CATEGORÍA DE SERIE")
    print("=" * 115)
    print(" Fuente de datos: yfinance (equities/ETFs) y FRED API (macro). Ninguna serie sintética se benchmarkea.")
    print(f" Cutoffs por serie: {N_CUTOFFS} (walk-forward), horizonte fijo por categoría.\n")

    holt_engine = DampedHoltForecastEngine()
    tfm_engine = get_real_timesfm_engine()
    tfm_available = tfm_engine is not None

    if not tfm_available:
        print(" [!] AVISO: TimesFM no disponible (pesos o dependencias ausentes).")
        print("     Todas las categorías reportarán TimesFM como 'No evaluado' — sin datos fabricados.")
        if not args.allow_missing:
            print("     Use --allow-missing para continuar de todos modos.")
            sys.exit(1)

    # ---- Categoría 1: FRED estacional ----
    print("\n[Preparando Categoría 1/4: Series FRED estacionales]")
    for sid, why in SEASONAL_FRED_SERIES.items():
        print(f"  - {sid}: {why}")
    seasonal_results = []
    for sid in SEASONAL_FRED_SERIES:
        res = benchmark_one_series(sid, sid, is_macro=True, horizon=6, holt_engine=holt_engine, tfm_engine=tfm_engine)
        if res:
            seasonal_results.append(res)
    print_category_table("CATEGORÍA 1: SERIES FRED ESTACIONALES (horizonte = 6 meses)", seasonal_results, tfm_available)

    # ---- Categoría 2: Índices/ETF diversificados ----
    print("\n[Preparando Categoría 2/4: Índices/ETF diversificados]")
    etf_results = []
    for tkr in DIVERSIFIED_ETFS:
        res = benchmark_one_series(tkr, tkr, is_macro=False, horizon=30, holt_engine=holt_engine, tfm_engine=tfm_engine)
        if res:
            etf_results.append(res)
    print_category_table("CATEGORÍA 2: ÍNDICES/ETF DIVERSIFICADOS (horizonte = 30 días)", etf_results, tfm_available)

    # ---- Categoría 3: Cold-start (historia corta) ----
    print("\n[Preparando Categoría 3/4: Cold-start (historia corta)]")
    cold_start_results_by_window: Dict[int, List[Dict]] = {}
    for window in COLD_START_WINDOWS:
        window_results = []
        for tkr in INDIVIDUAL_EQUITIES:
            res = benchmark_one_series(
                f"{tkr} ({window}d)", tkr, is_macro=False, horizon=min(14, window // 3),
                holt_engine=holt_engine, tfm_engine=tfm_engine, context_limit_days=window,
            )
            if res:
                window_results.append(res)
        cold_start_results_by_window[window] = window_results
        print_category_table(
            f"CATEGORÍA 3: COLD-START — VENTANA DE CONTEXTO = {window} DÍAS (horizonte = {min(14, window // 3)}d)",
            window_results, tfm_available,
        )

    # ---- Categoría 4: Acciones individuales, historia completa (baseline) ----
    print("\n[Preparando Categoría 4/4: Acciones individuales — baseline historia completa]")
    equity_results = []
    for tkr in INDIVIDUAL_EQUITIES:
        res = benchmark_one_series(tkr, tkr, is_macro=False, horizon=30, holt_engine=holt_engine, tfm_engine=tfm_engine)
        if res:
            equity_results.append(res)
    print_category_table("CATEGORÍA 4: ACCIONES INDIVIDUALES — BASELINE (horizonte = 30 días, historia completa)", equity_results, tfm_available)

    print("\n" + "=" * 115)
    print(" RESUMEN: esta tabla es la evidencia que alimenta EngineSelector — ninguna regla de switching")
    print(" se implementa para una categoría sin que TimesFM le haya ganado a Holt aquí, en datos reales.")
    print(" Nota: MASE < 1.0 = mejor que el naive de un paso. Cobertura se mide contra el nivel que cada")
    print(" motor declara servir (ver fitted_params.actual_interval_pct), no siempre 95% fijo.")
    print("=" * 115)


if __name__ == "__main__":
    main()
