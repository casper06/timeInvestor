"""4.21 — instruments checked against yfinance, and repaired by the LLM itself.

Same shape as the FRED grounding of ADR-0033: the model corrects its own
mistakes inside the single translation step, and the user is never asked
anything.

The 4.10 evaluation caught Haiku describing "PSQ: inverso 3x Nasdaq-100 de
Direxion". PSQ is real, but it's ProShares and −1x, not Direxion and not 3x.
Everything about that sentence reads as fact, and nothing downstream could tell
it from a true one. The same run used the ETF "IPO" (Renaissance IPO ETF) as
semiconductor exposure.

For every ticker the LLM proposes:

  1. yfinance is asked what it really is: official name, quoteType
     (EQUITY/ETF), and for funds the issuer (`fundFamily`) and category;
  2. the LLM's own `thesis_role` / `name` text is compared against those facts
     with EXPLICIT rules (see `find_contradictions`) — never a judgement call;
  3. tickers that don't exist, or whose description contradicts the data, go in
     ONE repair call to the same provider, which rewrites the description,
     replaces the ticker with a real one (re-verified), or discards it.

What is NOT checked stays labelled as the LLM's own claim: yfinance can confirm
an issuer, not whether a company "leads the market".

### Leverage and inverse: what yfinance actually gives

There is no leverage field. Verified against the live API on 2026-09-30, PSQ
reports `category: "Trading--Inverse Equity"`, `fundFamily: "ProShares"`,
`legalType: "Exchange Traded Fund"` — and nothing numeric. So:

- **inverse** is read from yfinance's own `category`/name ("Inverse", "Short"),
  never inferred;
- **leverage** is only ever contradicted when the LLM claims a multiplier and
  yfinance's name/category shows a DIFFERENT one (ProShares and Direxion both
  put "2x"/"3x"/"Ultra" in the fund name). When yfinance says nothing about a
  multiplier, the claim is left alone and flagged as unverifiable rather than
  called false — absence of evidence is not evidence of absence.
"""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VERIFIED = "verificado"
REPAIRED = "reparado"
DISCARDED = "descartado"

# Issuers whose name appearing in a description is a checkable claim. Only
# well-known fund families, so a passing mention doesn't get treated as one.
KNOWN_ISSUERS = [
    "ProShares", "Direxion", "iShares", "Vanguard", "SPDR", "State Street",
    "Invesco", "ARK", "Schwab", "VanEck", "Global X", "First Trust",
    "WisdomTree", "Renaissance Capital", "JPMorgan", "Fidelity",
]

_LEVERAGE_RE = re.compile(r"(?<![\w.])(-?\d+(?:[.,]\d+)?)\s*[xX](?![\w])")
_INVERSE_WORDS = ("inverso", "inversa", "inverse", "short ", "corto", "bajista")

REPAIR_SYSTEM_PROMPT = "Corregís descripciones de instrumentos financieros. Respondés solo el JSON del schema."

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "decisiones": {
            "type": "array",
            "description": "Una decisión por CADA ticker problemático recibido, sin excepción.",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "El ticker problemático, copiado tal cual del pedido",
                    },
                    "accion": {
                        "type": "string",
                        "enum": ["corregir_descripcion", "reemplazar_ticker", "descartar"],
                        "description": "corregir_descripcion: el ticker sirve para la tesis pero tu texto "
                                       "decía algo falso; reescribilo con los datos reales. "
                                       "reemplazar_ticker: este instrumento no da la exposición que buscabas "
                                       "(o no existe); proponé otro ticker real que sí la dé, con la misma "
                                       "dirección y sin más apalancamiento que el original. "
                                       "descartar: ningún instrumento razonable cubre ese rol.",
                    },
                    "nuevo_symbol": {
                        "type": "string",
                        "description": "Solo si accion=reemplazar_ticker: un ticker REAL que cotice en un "
                                       "mercado de EE.UU. Se verifica contra yfinance y, si no existe, se "
                                       "descarta el instrumento. OBLIGATORIO: el reemplazo tiene que "
                                       "mantener la MISMA DIRECCIÓN que el instrumento original (largo → "
                                       "largo, inverso → inverso) y un apalancamiento que NO SUPERE al del "
                                       "original (1x si el original no tenía). Si el instrumento correcto "
                                       "exigiría cambiar la dirección o apalancar, usá accion=descartar con "
                                       "ese motivo: una corrección no puede cambiar la apuesta.",
                    },
                    "thesis_role": {
                        "type": "string",
                        "description": "La descripción corregida del rol en la tesis. No repitas datos que "
                                       "no podés sostener: el emisor, el tipo y el apalancamiento tienen que "
                                       "coincidir con los datos reales que te paso. Si no sabés el "
                                       "apalancamiento, no lo menciones.",
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Una línea: qué estaba mal y qué cambiaste",
                    },
                },
                "required": ["symbol", "accion", "justificacion"],
            },
        }
    },
    "required": ["decisiones"],
}


def fetch_instrument_facts(symbol: str) -> Optional[Dict[str, Any]]:
    """What yfinance really says about a ticker, or None if it doesn't exist.

    Separate from the rules so tests can fake it without touching the network.
    """
    import yfinance as yf

    info = yf.Ticker(symbol.strip().upper()).info or {}
    quote_type = info.get("quoteType")
    if not quote_type:
        return None
    name = info.get("longName") or info.get("shortName")
    if not name:
        return None
    return {
        "symbol": symbol.strip().upper(),
        "name": name,
        "quote_type": quote_type,          # EQUITY, ETF, INDEX, ...
        "issuer": info.get("fundFamily"),  # only funds
        "category": info.get("category"),
        "legal_type": info.get("legalType"),
    }


def _claimed_leverage(text: str) -> Optional[str]:
    """The multiplier the LLM claims ("3x"), or None."""
    match = _LEVERAGE_RE.search(text or "")
    return match.group(1).replace(",", ".") if match else None


def _real_leverage(facts: Dict[str, Any]) -> Optional[str]:
    """The multiplier yfinance's own name/category shows, or None when it says
    nothing (which is NOT the same as 1x)."""
    haystack = " ".join(str(facts.get(k) or "") for k in ("name", "category"))
    match = _LEVERAGE_RE.search(haystack)
    if match:
        return match.group(1).replace(",", ".")
    # ProShares' "Ultra" family and Direxion's "Bull/Bear 3X" put it in words.
    if re.search(r"\bultrapro\b", haystack, re.I):
        return "3"
    if re.search(r"\bultra\b", haystack, re.I):
        return "2"
    # A plain inverse fund with no multiplier anywhere in its name or category
    # is -1x: ProShares' "Short QQQ" (PSQ) next to its "UltraPro Short QQQ"
    # (SQQQ, -3x). That IS something yfinance states, so a claimed 3x on it is
    # checkable rather than merely unverifiable.
    if _says_inverse(haystack):
        return "1"
    return None


def _says_inverse(text: str) -> bool:
    return any(w in (text or "").lower() for w in _INVERSE_WORDS)


def find_contradictions(item: Any, facts: Dict[str, Any]) -> List[str]:
    """Explicit rules. Each returned string is one contradiction, in words the
    repair prompt can act on. Nothing here is a judgement call: if a claim
    can't be checked against yfinance, it is NOT a contradiction.
    """
    problems: List[str] = []
    text = " ".join(str(getattr(item, f, "") or "") for f in ("thesis_role", "name", "sector"))
    lower = text.lower()
    real_type = (facts.get("quote_type") or "").upper()

    # R1. Instrument type: the LLM's own instrument_type field vs yfinance.
    declared = (getattr(item, "instrument_type", None) or "").lower()
    if declared == "etf" and real_type == "EQUITY":
        problems.append(f"lo declarás como ETF y yfinance dice que es una acción (quoteType=EQUITY)")
    elif declared == "stock" and real_type == "ETF":
        problems.append(f"lo declarás como acción y yfinance dice que es un ETF")

    # R2. The description calls it an ETF/fund but it's a stock, or vice versa.
    if real_type == "EQUITY" and re.search(r"\b(etf|fondo cotizado)\b", lower):
        problems.append("tu texto lo llama ETF y es una acción (quoteType=EQUITY)")
    if real_type == "ETF" and re.search(r"\b(la empresa|la compañía|la compania)\b", lower):
        problems.append("tu texto habla de la empresa y es un ETF, no una acción")

    # R3. Issuer: only when the text names a KNOWN issuer and yfinance reports
    # a different one. An unnamed issuer is not a contradiction.
    real_issuer = facts.get("issuer")
    if real_issuer:
        for issuer in KNOWN_ISSUERS:
            if issuer.lower() in lower and issuer.lower() not in str(real_issuer).lower():
                problems.append(f"decís que el emisor es {issuer} y yfinance dice {real_issuer}")
                break

    # R4. Leverage: only when BOTH sides state a multiplier and they differ.
    claimed = _claimed_leverage(text)
    real = _real_leverage(facts)
    if claimed and real and claimed.lstrip("-") != real.lstrip("-"):
        problems.append(f"afirmás un apalancamiento de {claimed}x y los datos indican {real}x")

    # R5. Inverse: yfinance's category is explicit about it, both ways.
    category_text = f"{facts.get('category') or ''} {facts.get('name') or ''}"
    really_inverse = _says_inverse(category_text)
    claims_inverse = _says_inverse(text)
    if really_inverse and not claims_inverse:
        problems.append(f"es un instrumento inverso (categoría de yfinance: {facts.get('category')}) y tu texto no lo dice")
    if claims_inverse and not really_inverse and real_type == "ETF" and facts.get("category"):
        problems.append(f"lo describís como inverso y la categoría de yfinance es {facts.get('category')}")

    # R6. The claimed exposure vs the fund's own category. Deliberately narrow:
    # only a handful of themes whose absence from the category is meaningful
    # (the "IPO as semiconductor exposure" case from 4.10).
    if real_type == "ETF" and facts.get("category"):
        cat = str(facts["category"]).lower()
        fund_name = str(facts.get("name") or "").lower()
        for theme, words in (
            ("semiconductores", ("semiconductor", "chip")),
            ("energía", ("energy", "utilities", "oil", "gas")),
            ("vivienda", ("real estate", "home", "construction", "housing")),
            ("oro", ("gold", "precious metals")),
        ):
            if theme in lower and not any(w in cat or w in fund_name for w in words):
                problems.append(
                    f"decís que da exposición a {theme} y yfinance lo clasifica como "
                    f"'{facts['category']}' ({facts.get('name')})"
                )
                break

    return problems


def _direction_and_leverage(item: Any, facts: Optional[Dict[str, Any]]) -> tuple:
    """The (inverse?, leverage) profile of what the LLM originally asked for.

    Read from the instrument's real data when there is any, and from the LLM's
    own words when the ticker doesn't exist — for an invented ticker its
    description is all the intent there is.
    """
    text = " ".join(str(getattr(item, f, "") or "") for f in ("thesis_role", "name", "sector"))
    if facts:
        inverse = _says_inverse(f"{facts.get('category') or ''} {facts.get('name') or ''}")
        leverage = _real_leverage(facts)
    else:
        inverse = _says_inverse(text)
        leverage = _claimed_leverage(text)
    return inverse, float(str(leverage).lstrip("-")) if leverage else 1.0


def _breaks_risk_profile(
    item: Any, original_facts: Optional[Dict[str, Any]], new_facts: Dict[str, Any]
) -> Optional[str]:
    """Why this replacement is not allowed, or None if it is.

    Two rules, both one-directional:
      - the direction must match (long -> long, inverse -> inverse);
      - the leverage must not EXCEED the original's (1x when it had none).
    Going down in leverage is fine: that is less risk, not a different bet.
    """
    was_inverse, was_leverage = _direction_and_leverage(item, original_facts)
    now_inverse, now_leverage = _direction_and_leverage(item, new_facts)

    if was_inverse != now_inverse:
        return (
            f"el original es {'inverso' if was_inverse else 'largo'} y el reemplazo es "
            f"{'inverso' if now_inverse else 'largo'}"
        )
    if now_leverage > was_leverage:
        return f"el original es {was_leverage:g}x y el reemplazo es {now_leverage:g}x"
    return None


def _facts_block(item: Any, facts: Optional[Dict[str, Any]], problems: List[str]) -> str:
    lines = [f'Ticker: {item.symbol}', f'  Tu descripción: "{item.thesis_role}"']
    if facts:
        lines.append(
            f"  Datos reales (yfinance): nombre={facts.get('name')!r}, tipo={facts.get('quote_type')}"
            + (f", emisor={facts.get('issuer')}" if facts.get("issuer") else "")
            + (f", categoría={facts.get('category')}" if facts.get("category") else "")
        )
        lines.append("  Contradicciones detectadas:")
        lines += [f"    - {p}" for p in problems]
    else:
        lines.append("  Datos reales (yfinance): EL TICKER NO EXISTE.")
    return "\n".join(lines)


async def _ask_repair(client: Any, thesis: str, pending: List[tuple]) -> Dict[str, Dict[str, Any]]:
    blocks = "\n\n".join(_facts_block(item, facts, problems) for item, facts, problems in pending)
    user_prompt = (
        f"Tesis: {thesis or '(no declarada)'}\n\n"
        f"Instrumentos con problemas:\n\n{blocks}"
    )
    data = await client.complete_json(REPAIR_SYSTEM_PROMPT, user_prompt, REPAIR_SCHEMA)
    out: Dict[str, Dict[str, Any]] = {}
    for d in (data or {}).get("decisiones", []) or []:
        key = (d.get("symbol") or "").strip().upper()
        if key:
            out[key] = d
    return out


def _mark_discarded(item: Any, reason: str) -> None:
    item.grounding = DISCARDED
    item.grounding_note = reason


def _apply(item: Any, decision: Dict[str, Any], fetch, original_facts: Optional[Dict[str, Any]] = None) -> None:
    """Applies one repair decision."""
    action = (decision.get("accion") or "").strip().lower()
    justification = (decision.get("justificacion") or "").strip()
    new_role = (decision.get("thesis_role") or "").strip()

    if action == "corregir_descripcion":
        if not new_role:
            _mark_discarded(item, f"'{item.symbol}': la corrección llegó sin descripción nueva, se descarta.")
            return
        item.original_thesis_role = item.thesis_role
        item.thesis_role = new_role
        item.grounding = REPAIRED
        item.repair_justification = justification or None
        item.grounding_note = f"Descripción corregida: {justification}".strip()

        # Same check on a rewritten description: if the new text still
        # contradicts the data, say so instead of calling it repaired and done.
        leftover = find_contradictions(item, original_facts) if original_facts else []
        if leftover:
            item.contradictions = leftover
            item.grounding_note += (
                f" Atención: el texto corregido todavía no coincide con los datos "
                f"({'; '.join(leftover)})."
            )
        else:
            item.contradictions = []
        return

    if action == "reemplazar_ticker":
        new_symbol = (decision.get("nuevo_symbol") or "").strip().upper()
        if not new_symbol:
            _mark_discarded(item, f"'{item.symbol}': el reemplazo llegó sin ticker, se descarta.")
            return
        try:
            facts = fetch(new_symbol)
        except Exception as e:
            logger.warning(f"No se pudo verificar el reemplazo '{new_symbol}': {e}")
            facts = None
        if not facts:
            _mark_discarded(
                item,
                f"'{item.symbol}' se iba a reemplazar por '{new_symbol}', que tampoco existe "
                f"en yfinance: se descarta.",
            )
            return
        # A repair fixes a description; it must not change the BET. A
        # replacement that flips long -> inverse, or adds leverage, is a
        # different position from the one the thesis asked for, and nobody
        # approved it. Enforced here and not only in the prompt.
        refusal = _breaks_risk_profile(item, original_facts, facts)
        if refusal:
            _mark_discarded(
                item,
                f"'{item.symbol}' se descartó: el reemplazo coherente cambiaría la dirección "
                f"de la apuesta o su apalancamiento ({refusal}). Propuesto: '{new_symbol}' "
                f"({facts.get('name')}).",
            )
            return

        item.original_symbol = item.symbol
        item.original_thesis_role = item.thesis_role
        item.symbol = new_symbol
        item.name = facts.get("name") or item.name
        item.verified_name = facts.get("name")
        item.verified_type = facts.get("quote_type")
        item.verified_issuer = facts.get("issuer")
        item.verified_category = facts.get("category")
        if new_role:
            item.thesis_role = new_role
        item.grounding = REPAIRED
        item.repair_justification = justification or None
        item.grounding_note = (
            f"'{item.original_symbol}' se reemplazó por '{new_symbol}' ({facts.get('name')}). {justification}"
        ).strip()

        # The replacement's OWN description is checked too: the repair is not
        # trusted just because it came from the model. A second round would be
        # a loop, so a still-contradictory text is recorded and the claim is
        # left visible rather than silently accepted.
        leftover = find_contradictions(item, facts)
        if leftover:
            item.contradictions = leftover
            item.grounding_note += (
                f" Atención: la descripción del reemplazo todavía no coincide con los datos "
                f"({'; '.join(leftover)})."
            )
        else:
            item.contradictions = []
        return

    reason = justification or "el LLM no encontró un instrumento adecuado"
    _mark_discarded(item, f"'{item.symbol}' se descartó: {reason}")


async def ground_instruments(
    tickers: List[Any],
    client: Any = None,
    thesis: str = "",
    fetch=fetch_instrument_facts,
) -> List[Any]:
    """Checks every proposed instrument against yfinance and lets the LLM
    repair its own mistakes in one extra call. Mutates and returns the same
    objects; order is preserved and discarded instruments stay in the list,
    marked, so the UI can say what was dropped and why.
    """
    pending: List[tuple] = []

    for item in tickers or []:
        symbol = (getattr(item, "symbol", "") or "").strip().upper()
        if not symbol:
            continue

        try:
            facts = fetch(symbol)
        except Exception as e:
            # yfinance unreachable: leave it as proposed and say so. Dropping
            # real instruments because the network blinked would be worse.
            logger.warning(f"No se pudo verificar '{symbol}' en yfinance: {e}")
            item.grounding = None
            item.grounding_note = (
                f"No se pudo verificar '{symbol}' (yfinance no respondió). "
                f"Los datos son los que propuso el LLM."
            )
            continue

        if facts is None:
            item.grounding_note = f"'{symbol}' no existe en yfinance."
            pending.append((item, None, []))
            continue

        item.verified_name = facts.get("name")
        item.verified_type = facts.get("quote_type")
        item.verified_issuer = facts.get("issuer")
        item.verified_category = facts.get("category")

        problems = find_contradictions(item, facts)
        if problems:
            item.contradictions = problems
            pending.append((item, facts, problems))
        else:
            item.grounding = VERIFIED

    if not pending:
        return tickers

    # No provider able to answer: a wrong description is not silently kept.
    if client is None or not getattr(client, "supports_json_completion", False):
        for item, facts, problems in pending:
            if facts is None:
                _mark_discarded(item, f"'{item.symbol}' no existe en yfinance y no hay un LLM disponible para corregirlo: se descarta.")
            else:
                _mark_discarded(
                    item,
                    f"'{item.symbol}': la descripción contradice los datos reales "
                    f"({'; '.join(problems)}) y no hay un LLM disponible para corregirla: se descarta.",
                )
        return tickers

    try:
        decisions = await _ask_repair(client, thesis, pending)
    except Exception as e:
        logger.warning(f"La pasada de corrección de instrumentos falló: {e}")
        for item, _facts, _problems in pending:
            _mark_discarded(item, f"'{item.symbol}': la corrección automática falló ({e}): se descarta.")
        return tickers

    for item, facts, problems in pending:
        decision = decisions.get(item.symbol.upper())
        if not decision:
            _mark_discarded(item, f"'{item.symbol}': la corrección no se pronunció sobre él, se descarta.")
            continue
        if facts is None and (decision.get("accion") or "").strip().lower() == "corregir_descripcion":
            # A ticker that doesn't exist can't be fixed by rewording it.
            _mark_discarded(
                item,
                f"'{item.symbol}' no existe en yfinance y la corrección solo reescribió el texto: se descarta.",
            )
            continue
        _apply(item, decision, fetch, facts)

    return tickers
