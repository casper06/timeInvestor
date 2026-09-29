"""4.11 — FRED IDs grounded in real data.

The LLM invents plausible-looking FRED IDs (TOTALSI, IPGD). They look exactly
like real ones, so nothing downstream can tell them apart: the app used to show
them, and the user only found out when a chart came back empty.

Every macro series the LLM proposes goes through `ground_macro_series` before
it reaches the UI:

  1. the ID is checked against FRED itself (`/fred/series`, via
     `get_series_metadata`);
  2. if it doesn't exist, `fred/series/search` looks for the CONCEPT the LLM
     described (its `name`, falling back to `category`), and the best real
     candidate is proposed in its place, marked "sugerido por búsqueda";
  3. if the search finds nothing either, the series is discarded with a visible
     warning.

Nothing here invents an ID or a title: a suggested series always carries FRED's
own `title`. When FRED can't be reached at all (no key, HTTP error), the series
is left as the LLM proposed it with `grounding=None` and a note — degrading to
"unverified" beats dropping real series because the key is missing.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings
from backend.schemas.models import FredCandidate
from backend.services.data_fetcher import FREDDataFetcher, FredSeriesNotFoundError

logger = logging.getLogger(__name__)

VERIFIED = "verificado"
SUGGESTED = "sugerido_por_busqueda"
DISCARDED = "descartado"

SEARCH_URL = "https://api.stlouisfed.org/fred/series/search"
SEARCH_LIMIT = 3  # what the UI offers; the user picks one


def search_fred_concept(concept: str, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Up to `SEARCH_LIMIT` real FRED series for a free-text concept.

    Returns FRED's own ranking (`order_by=search_rank`, its default) untouched,
    with each hit's metadata verbatim: we don't reorder it, because our ranking
    would be one more guess. The CHOICE among them is the user's — the top hit
    is not necessarily the right series (searching "new home sales" ranks MSPUS
    first, a *price*, which says nothing about how many houses are built).
    """
    key = api_key if api_key is not None else settings.FRED_API_KEY
    if not (key and str(key).strip()):
        return []
    if not (concept and concept.strip()):
        return []

    try:
        params = {
            "search_text": concept.strip(),
            "api_key": key,
            "file_type": "json",
            "limit": SEARCH_LIMIT,
            "order_by": "search_rank",
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(SEARCH_URL, params=params)
        if resp.status_code != 200:
            logger.warning(f"FRED search returned HTTP {resp.status_code} for {concept!r}")
            return []
        hits = resp.json().get("seriess", []) or []
        return [
            {
                "series_id": h["id"],
                "title": h.get("title", ""),
                "frequency": h.get("frequency_short") or None,
                "seasonal_adjustment": h.get("seasonal_adjustment_short") or None,
                "observation_start": h.get("observation_start") or None,
                "observation_end": h.get("observation_end") or None,
                "units": h.get("units_short") or None,
            }
            for h in hits[:SEARCH_LIMIT]
            if h.get("id")
        ]
    except Exception as e:
        logger.warning(f"FRED search failed for {concept!r}: {e}")
        return []


def _search_concept(item: Any) -> str:
    """The text to search FRED with, best first.

    FRED's search index is English-only: `search_text` in Spanish returns
    `count: 0` (verified against the live API on 2026-09-29 — "new home sales"
    → 2986 hits, "Ventas totales de viviendas nuevas" → 0). The prompt returns
    `name` in Spanish, so searching with it would discard every invented ID
    instead of repairing it. Hence `search_concept_en`, which the prompt now
    asks for in English; `name` and `category` stay as fallbacks for a provider
    that doesn't fill it (the mock, an older cached thesis).
    """
    for attr in ("search_concept_en", "name", "category"):
        value = (getattr(item, attr, "") or "").strip()
        if value:
            return value
    return ""


def _exists(series_id: str) -> Optional[Dict[str, Any]]:
    """FRED's metadata for series_id; None if it doesn't exist.

    Re-raises nothing: an unreachable FRED is reported as `unknown` by the
    caller, which is different from "does not exist".
    """
    return FREDDataFetcher().get_series_metadata(series_id)


def ground_macro_series(macro_series: List[Any]) -> List[Any]:
    """Validates each proposed series against FRED, in place-ish (returns the
    same list objects, mutated). Order is preserved; discarded series stay in
    the list, marked `descartado`, so the UI can say what was dropped and why
    instead of silently showing fewer series."""
    for item in macro_series or []:
        proposed = (getattr(item, "series_id", "") or "").strip()
        if not proposed:
            continue

        try:
            meta = _exists(proposed)
        except FredSeriesNotFoundError:
            meta = None
        except Exception as e:
            # FRED unreachable or no key: leave the LLM's ID untouched and say so.
            logger.warning(f"No se pudo validar '{proposed}' contra FRED: {e}")
            item.grounding = None
            item.grounding_note = (
                f"No se pudo verificar '{proposed}' contra FRED "
                f"(la API de FRED no respondió). El ID es el que propuso el LLM."
            )
            continue

        if meta:
            item.grounding = VERIFIED
            item.fred_title = meta.get("title") or None
            continue

        # The ID doesn't exist: look for the concept the LLM described and
        # OFFER the candidates. The ID is never substituted automatically: see
        # MacroSuggestion.enters_analysis.
        concept = _search_concept(item)
        candidates = search_fred_concept(concept)

        if candidates:
            item.proposed_series_id = proposed
            item.grounding = SUGGESTED
            item.searched_concept = concept
            item.candidates = [FredCandidate(**c) for c in candidates]
            item.grounding_note = (
                f"'{proposed}' no existe en FRED; elegí un reemplazo o seguí sin esta serie."
            )
        else:
            item.proposed_series_id = proposed
            item.grounding = DISCARDED
            item.grounding_note = (
                f"'{proposed}' no existe en FRED y la búsqueda de \"{concept}\" "
                f"no encontró ninguna serie real. Se descarta."
            )
    return macro_series
