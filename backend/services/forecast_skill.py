"""
Forecast skill per series (item 4.13 of docs/PLAN.md): does the forecast
beat the naive it should beat? Criterion pre-registered in docs/PLAN.md 4.13
(commit 4c94bea) before implementing:

- naive: the seasonal naive if the 3.0a detector marks the whole series
  seasonal, else the random walk;
- evidence: the decision's mini-backtest cutoffs (MAE of the chosen engine vs
  the naive's on the same points), or, for the seasonal catalog, the 24 3.0d
  cutoffs (seasonal MASE; same order as MAE within a cutoff);
- rule: >= MIN_PAIRS paired cutoffs; "aporta" if the engine wins a majority
  and its mean error is at least MARGIN lower; else "no_aporta";
  anything else is "no_evaluado" with the reason.
"""
import json
from typing import Optional, Sequence

import numpy as np

from backend.schemas.models import ForecastSkill

MIN_PAIRS = 7
MARGIN = 0.10

NAIVE_LABEL = {"random_walk": "random walk (igual que el último dato)",
               "naive_estacional": "naive estacional (igual que el mismo período del ciclo anterior)"}

# Seasonal FRED catalog (engine_selector.SEASONAL_FRED_CATALOG): the 3.0d
# evidence of the catalog engine vs the seasonal naive, computed from
# docs/results/seasonal_benchmark_2026-09-26.json (a test recomputes it).
# id: (engine, wins, losses, pairs, mean MASE_s engine, mean MASE_s naive)
CATALOG_SKILL_EVIDENCE = {
    "IPG2211A2N": ("timesfm", 18, 6, 24, 0.956295, 1.145514),
    "HOUSTNSA": ("timesfm", 17, 7, 24, 0.693146, 0.925911),
    "RSAFSNA": ("timesfm", 22, 2, 24, 0.749150, 1.497038),
    "MRTSSM4451USN": ("holt_winters", 20, 4, 24, 1.034462, 1.651254),
}
CATALOG_SOURCE = "benchmark estacional 3.0d (24 cutoffs, docs/results/seasonal_benchmark_2026-09-26.json)"


def not_evaluated(reason: str, naive: Optional[str] = None) -> ForecastSkill:
    return ForecastSkill(state="no_evaluado", reason=reason, naive=naive)


def _verdict(wins: int, losses: int, n_pairs: int, mean_model: float, mean_naive: float,
             naive: str, source: str) -> ForecastSkill:
    if n_pairs < MIN_PAIRS:
        return not_evaluated(f"solo {n_pairs} cutoffs con los dos errores definidos (< {MIN_PAIRS})", naive)
    gap = (mean_model / mean_naive - 1.0) if mean_naive > 0 else None
    aporta = wins > losses and mean_naive > 0 and mean_model <= (1.0 - MARGIN) * mean_naive
    common = dict(naive=naive, wins=wins, losses=losses, n_pairs=n_pairs, rel_gap=gap, source=source)
    gap_txt = f"{abs(gap) * 100:.0f}% {'menor' if gap < 0 else 'mayor'}" if gap is not None else "no comparable"
    if aporta:
        return ForecastSkill(state="aporta", reason=(
            f"Le gana al {NAIVE_LABEL[naive]} en {wins} de {n_pairs} cutoffs, con un error medio {gap_txt} "
            f"(fuente: {source})."), **common)
    return ForecastSkill(state="no_aporta", reason=(
        f"No aporta más que el {NAIVE_LABEL[naive]}: le gana en {wins} de {n_pairs} cutoffs y su error medio es "
        f"{gap_txt}; hace falta ganar la mayoría con al menos un {int(MARGIN * 100)}% menos de error "
        f"(fuente: {source})."), **common)


def skill_from_pairs(model_errors: Sequence[Optional[float]], naive_errors: Sequence[Optional[float]],
                     naive: str, source: str) -> ForecastSkill:
    pairs = [(m, n) for m, n in zip(model_errors, naive_errors) if m is not None and n is not None]
    if not pairs:
        return not_evaluated("no hay cutoffs con el error del motor y del naive definidos", naive)
    wins = sum(m < n for m, n in pairs)
    losses = sum(m > n for m, n in pairs)
    return _verdict(wins, losses, len(pairs), float(np.mean([m for m, _ in pairs])),
                    float(np.mean([n for _, n in pairs])), naive, source)


def skill_for_decision(decision) -> ForecastSkill:
    """From an auto-discovery decision's stored per-cutoff errors."""
    raw = getattr(decision, "cutoff_errors_json", None)
    if not raw:
        return not_evaluated("la decisión es de una versión anterior y no guardó la evidencia contra el naive; "
                             "se completa en la próxima re-evaluación")
    data = json.loads(raw)
    naive = data["naive"]
    key = "tfm" if decision.engine_choice == "timesfm" else "base"
    rows = data["cutoffs"]
    return skill_from_pairs([r.get(key) for r in rows], [r.get("naive") for r in rows], naive,
                            f"mini-backtest de esta serie, {len(rows)} cutoffs a {decision.horizon or '?'} pasos")


def skill_for_catalog(series_id: str, served_engine: str) -> ForecastSkill:
    ev = CATALOG_SKILL_EVIDENCE.get(series_id)
    if ev is None:
        return not_evaluated("serie del catálogo sin evidencia registrada contra el naive")
    engine, wins, losses, n, mm, mn = ev
    if engine != served_engine:
        return not_evaluated(f"la evidencia del catálogo es de {engine} y respondió {served_engine}",
                             "naive_estacional")
    return _verdict(wins, losses, n, mm, mn, "naive_estacional", CATALOG_SOURCE)


def served_engine(model_name: str) -> str:
    name = (model_name or "").lower()
    if name.startswith("timesfm"):
        return "timesfm"
    if name.startswith("holt-winters"):
        return "holt_winters"
    return "holt"
