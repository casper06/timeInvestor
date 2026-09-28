"""
What the copilot receives (fix/copilot-context): one context text for every
LLM client (Gemini, Gemini CLI, Claude CLI, OpenAI, Ollama), so none of them
gets less than the others.

- Today's date, and the period of every figure: the last observation of the
  active series, the date the projection points at, the fiscal year of each
  fundamental ("capex: último ejercicio cerrado 2025"), the last observation
  of each FRED series.
- The evidence for or against the thesis comes from indicators of the world
  (FRED): their last value and their 12-month change, fetched here, server
  side.
- The companies are the ones the LLM picked when translating the thesis: they
  are labeled as such ("no una muestra representativa"), never as
  confirmation. Tickers with no fundamentals are listed as missing.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

from backend.schemas.models import FundamentalsMetric, InterpretationContext, MacroEvidence
from backend.services.horizons import format_horizon

logger = logging.getLogger(__name__)

# Appended to both interpretation system prompts (the JSON-example one and
# Claude CLI's --json-schema one), so every variant gets the same rules.
COPILOT_RULES = """
Reglas obligatorias:
1. Afirmá solo lo que está en los datos recibidos. No agregues cifras, hechos, tendencias ni noticias que no estén en el contexto; si algo no está, decí que no está.
2. Si faltan datos de algún activo o serie (líneas "Sin fundamentales" o "sin datos"), decilo explícitamente.
3. La evidencia a favor o en contra de la tesis sale de los indicadores del mundo (series de FRED y similares). El capex y los ingresos de las empresas listadas son de empresas seleccionadas por el LLM, no una muestra representativa: presentalos así, nunca como confirmación de la tesis.
4. Todo dato tiene fecha: usá la fecha de hoy y el período de cada dato (por ejemplo, "capex: último ejercicio cerrado 2025"). La proyección es la salida de un modelo estadístico, no un dato observado.
"""


def _fetch_series(series_id: str):
    """FRED series for the evidence block (separate so tests can fake it)."""
    from backend.services.data_fetcher import FREDDataFetcher
    return FREDDataFetcher().get_series(series_id)


def _fetch_metadata(series_id: str) -> dict:
    """FRED's own title and units (/fred/series). A series outside the catalog
    otherwise arrives named "FRED Series X" with the unit "Index" filled in
    by default: a guess, which the copilot must not state as data."""
    from backend.services.data_fetcher import FREDDataFetcher
    try:
        return FREDDataFetcher().get_series_metadata(series_id)
    except ValueError:
        return {}


def is_percent_unit(unit: Optional[str]) -> bool:
    """Rates and shares (DGS10, UNRATE): their change reads in points, not in %."""
    return bool(unit) and unit.strip().lower().startswith("percent")


def build_macro_evidence(series_ids: List[str]) -> List[MacroEvidence]:
    """Last value and 12-month change of each FRED series; a series that
    can't be fetched stays in the list with the reason."""
    from backend.services.seasonality import infer_frequency
    out: List[MacroEvidence] = []
    for sid in dict.fromkeys(s.strip().upper() for s in series_ids if s and s.strip()):
        try:
            data = _fetch_series(sid)
        except ValueError as e:
            out.append(MacroEvidence(series_id=sid, missing_reason=str(e)))
            continue
        from backend.services.data_fetcher import FREDDataFetcher
        meta = _fetch_metadata(sid)
        in_catalog = sid in FREDDataFetcher.SERIES_CATALOG
        name = meta.get("title") or (data.name if in_catalog else None)
        unit = meta.get("units") or (data.unit if in_catalog else None)
        pts = sorted(data.points, key=lambda p: p.timestamp)
        if not pts:
            out.append(MacroEvidence(series_id=sid, missing_reason="la serie no trajo observaciones"))
            continue
        last = pts[-1]
        a_year_before = (date.fromisoformat(last.timestamp[:10]) - timedelta(days=365)).isoformat()
        prior = next((p for p in reversed(pts) if p.timestamp[:10] <= a_year_before), None)
        ev = MacroEvidence(
            series_id=sid, name=name, unit=unit,
            frequency=infer_frequency([p.timestamp for p in pts]) if len(pts) > 2 else None,
            last_date=last.timestamp[:10], last_value=last.value,
        )
        if prior is not None:
            ev.prior_date, ev.prior_value = prior.timestamp[:10], prior.value
            ev.change_abs = last.value - prior.value
            ev.change_pct = (last.value / prior.value - 1.0) * 100.0 if prior.value != 0 else None
        out.append(ev)
    return out


def _fundamentals_by_ticker(ctx: InterpretationContext) -> Dict[str, List[FundamentalsMetric]]:
    rows: List[FundamentalsMetric] = list(ctx.fundamentals or [])
    if not rows and ctx.capex_summary:
        # Older clients send {"TICKER_PERIOD": value} with capex only.
        for key, value in ctx.capex_summary.items():
            ticker, _, period = key.rpartition("_")
            rows.append(FundamentalsMetric(ticker=ticker or key, metric="Capex (Billions USD)", period=period, value=value))
    by: Dict[str, List[FundamentalsMetric]] = {}
    for r in rows:
        by.setdefault(r.ticker.upper(), []).append(r)
    return by


def _fundamentals_line(ticker: str, rows: List[FundamentalsMetric]) -> str:
    parts = []
    for label, key in (("capex", "capex"), ("ingresos", "revenue")):
        metric_rows = sorted((r for r in rows if key in r.metric.lower()), key=lambda r: r.period, reverse=True)
        if not metric_rows:
            continue
        latest = metric_rows[0]
        text = f"{label}: último ejercicio cerrado {latest.period}: {latest.value:,.2f} B USD"
        if len(metric_rows) > 1:
            prev = metric_rows[1]
            text += f" ({prev.period}: {prev.value:,.2f})"
        parts.append(text)
    return f"  - {ticker}: " + "; ".join(parts) if parts else f"  - {ticker}: sin capex ni ingresos"


def _macro_line(ev: MacroEvidence) -> str:
    if ev.missing_reason:
        return f"- {ev.series_id}: sin datos ({ev.missing_reason})"
    unit = f" {ev.unit}" if ev.unit else " (unidad no informada)"
    freq = f", {ev.frequency}" if ev.frequency else ""
    name = ev.name or "título no informado"
    line = f"- {ev.series_id} ({name}): último dato {ev.last_value:,.4g}{unit} ({ev.last_date}{freq})"
    if ev.prior_value is not None:
        if is_percent_unit(ev.unit):
            change = f"cambio {ev.change_abs:+,.2f} puntos porcentuales"
        else:
            change = f"cambio {ev.change_abs:+,.4g}" + (f", {ev.change_pct:+.1f}%" if ev.change_pct is not None else "")
        line += f"; hace 12 meses {ev.prior_value:,.4g} ({ev.prior_date}): {change}"

    else:
        line += "; sin dato de hace 12 meses para comparar"
    return line


def interpretation_context_text(ctx: InterpretationContext, today: Optional[date] = None) -> str:
    """The context block every client sends to its LLM."""
    today = today or date.today()
    macro_series = ctx.series_type == "macro"
    value_word = "valor" if macro_series else "precio"
    horizon = format_horizon(ctx.horizon, ctx.frequency or "daily")
    lines = [
        f"Fecha de hoy: {today.isoformat()}.",
        "",
        f"Tesis: {ctx.thesis}",
        f"Serie activa: {ctx.active_series_id} ({ctx.active_series_name or ctx.active_series_id})"
        + (f", {'serie macro' if macro_series else 'acción'}" if ctx.series_type else ""),
        f"- Último {value_word} real: {ctx.last_price:,.4f}"
        + (f" (dato del {ctx.last_observation_date})" if ctx.last_observation_date else " (fecha del dato no informada)"),
        f"- Proyección del modelo estadístico (no es un dato) a +{horizon}"
        + (f", al {ctx.target_date}" if ctx.target_date else "")
        + f": {ctx.projected_target:,.4f} (CAGR implícito {ctx.cagr:.1f}%)",
        f"- Banda {int(ctx.confidence * 100)}%: [{ctx.lower_bound:,.4f} - {ctx.upper_bound:,.4f}]",
    ]
    if ctx.reliability_warning:
        lines.append(f"- ADVERTENCIA DEL SISTEMA: {ctx.reliability_warning} No interpretes el objetivo ni el CAGR "
                     f"como una proyección válida; decilo explícitamente.")

    lines += ["", "Evidencia de indicadores del mundo (FRED):"]
    if ctx.macro_evidence:
        lines += [_macro_line(ev) for ev in ctx.macro_evidence]
    elif ctx.macro_series:
        lines.append(f"- Series en la tesis: {', '.join(ctx.macro_series)} (sin valores recibidos)")
    else:
        lines.append("- Ninguna serie macro en la tesis: no hay evidencia de indicadores del mundo.")

    tickers = list(dict.fromkeys(
        ([ctx.active_series_id.upper()] if ctx.series_type == "equity" else []) + [t.upper() for t in ctx.other_tickers]
    ))
    by_ticker = _fundamentals_by_ticker(ctx)
    lines += ["", "Empresas seleccionadas por el LLM al traducir la tesis (no una muestra representativa; "
                  "sus números no confirman la tesis):"]
    lines.append(f"- Activos: {', '.join(tickers) if tickers else 'ninguno'}")
    with_data = [t for t in tickers if t in by_ticker] + [t for t in by_ticker if t not in tickers]
    if with_data:
        lines.append("- Fundamentales recibidos (dólares, ejercicios fiscales):")
        lines += [_fundamentals_line(t, by_ticker[t]) for t in with_data]
    missing = [t for t in tickers if t not in by_ticker]
    if missing:
        lines.append(f"- Sin fundamentales: {', '.join(missing)} (no se recibieron datos).")
    return "\n".join(lines) + "\n"
