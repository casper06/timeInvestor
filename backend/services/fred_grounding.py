"""4.11 — FRED IDs grounded in real data, with the LLM repairing its own.

The LLM invents plausible-looking FRED IDs (TOTALSI, IPGD). They look exactly
like real ones, so nothing downstream can tell them apart: the app used to show
them, and the user only found out when a chart came back empty.

Grounding runs inside the single translation step, with no question asked of
the user:

  1. every proposed ID is checked against FRED itself (`/fred/series`);
  2. the invalid ones go to `fred/series/search` with the concept the LLM gave
     in English (`search_concept_en`), which returns up to `SEARCH_LIMIT` real
     candidates WITH their metadata (title, frequency, SA/NSA, date range,
     unit);
  3. ONE extra call to the same provider hands it the thesis' mechanism, the
     invalid IDs and their candidates. For each one the model answers with an
     ID **from that list** plus a one-line justification, or "descartar" with a
     reason. It may ask for ONE search reformulation per series; after that it
     chooses or discards. No open loops.
  4. whatever it chose is verified against FRED again, and an ID that was not
     in the candidate list is rejected.

Why the app never picks for the model: FRED's first hit is a guess at the
*concept*, not the series the thesis needs. Searching "new home sales" for
`TOTALSI` (a thesis about *how many* houses get built) ranks MSPUS first — the
median *price* of houses sold. Real, on topic, and the wrong magnitude. So the
top hit is never adopted automatically: either the model justifies a choice
from the real list, or the series is discarded.

With no LLM able to answer (the mock, or a repair pass that fails), the invalid
IDs are simply discarded with a visible note. When FRED itself can't be reached
(no key, HTTP error), the series is left as the LLM proposed it with
`grounding=None` — degrading to "unverified" beats dropping real series because
the key is missing.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings
from backend.schemas.models import FredCandidate
from backend.services.data_fetcher import FREDDataFetcher, FredSeriesNotFoundError
from backend.services.redaction import redact_secrets

logger = logging.getLogger(__name__)

VERIFIED = "verificado"
REPAIRED = "reparado"
DISCARDED = "descartado"

SEARCH_URL = "https://api.stlouisfed.org/fred/series/search"
SEARCH_LIMIT = 5  # candidates offered to the model
MAX_REFORMULATIONS = 1  # per series; then it chooses or discards

# ADR-0030's lesson, hit again here: with a long numbered system prompt, Claude
# CLI ignores --json-schema and answers in free Markdown (observed 3/3 attempts
# on 2026-09-29, with good reasoning that no parser could read). The rules live
# in the schema's field descriptions instead, and the system prompt is one line.
REPAIR_SYSTEM_PROMPT = "Corregís IDs de series de FRED. Respondés solo el JSON del schema."

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "decisiones": {
            "type": "array",
            "description": "Una decisión por CADA id inválido recibido, sin excepción.",
            "items": {
                "type": "object",
                "properties": {
                    "id_invalido": {
                        "type": "string",
                        "description": "El ID que no existe en FRED, copiado tal cual del pedido",
                    },
                    "accion": {
                        "type": "string",
                        "enum": ["elegir", "reformular", "descartar"],
                        "description": "elegir: un candidato de la lista de ESE id mide el eslabón del "
                                       "mecanismo. reformular: ninguno sirve y querés otra búsqueda (una "
                                       "sola vez por serie). descartar: el eslabón no se puede medir con "
                                       "lo que hay. Ante la duda, descartar antes que elegir una serie que "
                                       "mide otra cosa: una que mide un PRECIO no reemplaza a una que mide "
                                       "una CANTIDAD, aunque hablen del mismo tema.",
                    },
                    "series_id": {
                        "type": "string",
                        "description": "Solo si accion=elegir: un series_id que esté EXACTAMENTE en la "
                                       "lista de candidatos de ese id inválido. Nunca inventes uno: "
                                       "cualquier ID fuera de la lista se rechaza. Mirá la metadata "
                                       "(frecuencia, SA/NSA, rango, unidad), no solo el título.",
                    },
                    "nueva_busqueda": {
                        "type": "string",
                        "description": "Solo si accion=reformular: el concepto nuevo a buscar, EN INGLÉS",
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Una línea: por qué elegiste, reformulaste o descartaste",
                    },
                },
                "required": ["id_invalido", "accion", "justificacion"],
            },
        }
    },
    "required": ["decisiones"],
}


def search_fred_concept(concept: str, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Up to `SEARCH_LIMIT` real FRED series for a free-text concept.

    Returns FRED's own ranking (`order_by=search_rank`, its default) untouched,
    with each hit's metadata verbatim. Nothing here picks a winner: the list is
    what the repair pass gets to choose from.
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
        logger.warning(f"FRED search failed for {concept!r}: {redact_secrets(e, key)}")
        return []


def _search_concept(item: Any) -> str:
    """The text to search FRED with, best first.

    FRED's search index is English-only: `search_text` in Spanish returns
    `count: 0` (verified against the live API on 2026-09-29 — "new home sales"
    → 2986 hits, "Ventas totales de viviendas nuevas" → 0). The prompt returns
    `name` in Spanish, so searching with it would find nothing to repair from.
    Hence `search_concept_en`, which the prompt asks for in English; `name` and
    `category` stay as fallbacks for a provider that doesn't fill it.
    """
    for attr in ("search_concept_en", "name", "category"):
        value = (getattr(item, attr, "") or "").strip()
        if value:
            return value
    return ""


def _exists(series_id: str) -> Optional[Dict[str, Any]]:
    """FRED's metadata for series_id; raises FredSeriesNotFoundError if it
    doesn't exist, and other exceptions when FRED can't be reached."""
    return FREDDataFetcher().get_series_metadata(series_id)


def _mark_discarded(item: Any, reason: str) -> None:
    item.grounding = DISCARDED
    item.grounding_note = reason
    item.candidates = []


def _candidates_block(item: Any) -> str:
    lines = [f'ID inválido: "{item.proposed_series_id}" (mide, según el LLM: "{item.name}")',
             f'  Buscado en FRED: "{item.searched_concept}"']
    for c in item.candidates:
        meta = " · ".join(x for x in [c.frequency, c.seasonal_adjustment,
                                      f"{c.observation_start} → {c.observation_end}"
                                      if c.observation_start and c.observation_end else None,
                                      c.units] if x)
        lines.append(f"  - {c.series_id}: {c.title} [{meta}]")
    return "\n".join(lines)


async def _ask_repair(client: Any, mechanism: str, pending: List[Any]) -> Dict[str, Dict[str, Any]]:
    """One structured call; returns {id_invalido: decision}."""
    blocks = "\n\n".join(_candidates_block(i) for i in pending)
    user_prompt = (
        f"Mecanismo de la tesis:\n{mechanism or '(no declarado)'}\n\n"
        f"IDs inválidos y sus candidatos reales de FRED:\n\n{blocks}"
    )
    data = await client.complete_json(REPAIR_SYSTEM_PROMPT, user_prompt, REPAIR_SCHEMA)
    out: Dict[str, Dict[str, Any]] = {}
    for d in (data or {}).get("decisiones", []) or []:
        key = (d.get("id_invalido") or "").strip()
        if key:
            out[key] = d
    return out


def _apply_choice(item: Any, decision: Dict[str, Any]) -> bool:
    """Applies an 'elegir' decision. Returns False (and discards) when the ID
    isn't in the candidate list or FRED no longer confirms it."""
    chosen = (decision.get("series_id") or "").strip()
    allowed = {c.series_id for c in item.candidates}
    justification = (decision.get("justificacion") or "").strip()

    if chosen not in allowed:
        # The model invented an ID again, or named one outside its own list.
        logger.warning(f"Repair proposed {chosen!r}, not among candidates {sorted(allowed)}")
        _mark_discarded(
            item,
            f"'{item.proposed_series_id}' no existe en FRED. La reparación propuso "
            f"'{chosen or '(vacío)'}', que no estaba entre los candidatos reales: se rechaza y se descarta la serie.",
        )
        return False

    # Re-verify against FRED: the candidate came from FRED, but the choice is
    # only trusted after FRED confirms it again.
    try:
        meta = _exists(chosen)
    except FredSeriesNotFoundError:
        meta = None
    except Exception as e:
        logger.warning(f"No se pudo re-verificar '{chosen}': {e}")
        meta = None

    if not meta:
        _mark_discarded(
            item,
            f"'{item.proposed_series_id}' no existe en FRED y el reemplazo '{chosen}' "
            f"no pudo verificarse: se descarta la serie.",
        )
        return False

    item.series_id = chosen
    item.fred_title = meta.get("title") or None
    item.grounding = REPAIRED
    item.repair_justification = justification or None
    item.grounding_note = (
        f"'{item.proposed_series_id}' no existe en FRED. Se reemplazó por '{chosen}' "
        f"({item.fred_title}). {justification}".strip()
    )
    item.candidates = []
    return True


async def ground_macro_series(macro_series: List[Any], client: Any = None, mechanism: str = "") -> List[Any]:
    """Validates every proposed series against FRED and lets the LLM repair its
    own invalid IDs, in one extra call. Mutates and returns the same objects;
    order is preserved, and discarded series stay in the list (marked) so the
    UI can say what was dropped and why instead of silently showing fewer.
    """
    pending: List[Any] = []

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

        concept = _search_concept(item)
        candidates = search_fred_concept(concept)
        item.proposed_series_id = proposed
        item.searched_concept = concept
        item.candidates = [FredCandidate(**c) for c in candidates]

        if not candidates:
            _mark_discarded(
                item,
                f"'{proposed}' no existe en FRED y la búsqueda de \"{concept}\" "
                f"no encontró ninguna serie real. Se descarta.",
            )
            continue

        pending.append(item)

    if not pending:
        return macro_series

    # No provider able to answer: discard. The search's first hit is NEVER
    # adopted on its own (see the module docstring).
    if client is None or not getattr(client, "supports_json_completion", False):
        for item in pending:
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y no hay un LLM disponible "
                f"para elegir un reemplazo: se descarta.",
            )
        return macro_series

    await _repair_pass(client, mechanism, pending)
    return macro_series


async def _repair_pass(client: Any, mechanism: str, pending: List[Any]) -> None:
    """The extra call, plus at most one reformulation round."""
    try:
        decisions = await _ask_repair(client, mechanism, pending)
    except Exception as e:
        logger.warning(f"La pasada de reparación falló: {e}")
        for item in pending:
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y la reparación automática "
                f"falló ({e}): se descarta.",
            )
        return

    reformulate: List[Any] = []

    for item in pending:
        decision = decisions.get(item.proposed_series_id)
        if not decision:
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y la reparación no se "
                f"pronunció sobre él: se descarta.",
            )
            continue

        action = (decision.get("accion") or "").strip().lower()
        justification = (decision.get("justificacion") or "").strip()

        if action == "elegir":
            _apply_choice(item, decision)
        elif action == "reformular" and item.reformulations < MAX_REFORMULATIONS:
            new_query = (decision.get("nueva_busqueda") or "").strip()
            new_candidates = search_fred_concept(new_query) if new_query else []
            item.reformulations += 1
            if not new_candidates:
                _mark_discarded(
                    item,
                    f"'{item.proposed_series_id}' no existe en FRED; la búsqueda reformulada "
                    f"(\"{new_query}\") tampoco encontró candidatos. Se descarta.",
                )
                continue
            item.searched_concept = new_query
            item.candidates = [FredCandidate(**c) for c in new_candidates]
            reformulate.append(item)
        else:
            # "descartar", an unknown action, or a second reformulation
            # request: the budget is one, so this is the end of the line.
            reason = justification or "el LLM no encontró una serie que mida ese eslabón"
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y se descartó: {reason}",
            )

    if not reformulate:
        return

    # Second and final round, only for the series that asked for it.
    try:
        decisions = await _ask_repair(client, mechanism, reformulate)
    except Exception as e:
        logger.warning(f"La segunda vuelta de reparación falló: {e}")
        for item in reformulate:
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y la reparación automática "
                f"falló ({e}): se descarta.",
            )
        return

    for item in reformulate:
        decision = decisions.get(item.proposed_series_id) or {}
        if (decision.get("accion") or "").strip().lower() == "elegir":
            _apply_choice(item, decision)
        else:
            reason = (decision.get("justificacion") or "").strip() or (
                "tras reformular la búsqueda, ningún candidato mide ese eslabón"
            )
            _mark_discarded(
                item,
                f"'{item.proposed_series_id}' no existe en FRED y se descartó: {reason}",
            )
