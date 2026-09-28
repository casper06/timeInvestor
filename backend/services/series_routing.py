"""
Where a series lives: FRED or yfinance (4.11, partial).

One rule for every route that has to choose (correlation, backtest, the
forecast's auto-discovery), instead of each one checking the fixed catalog
(FREDDataFetcher.SERIES_CATALOG) and sending everything else to yfinance —
which is how a FRED ID outside the catalog (PCU221110221110) ended up asked
to yfinance.

1. The caller's type decides when there is one: the UI always knows it
   (tickers are 'equity', the "+ FRED ID" chips are 'macro').
2. Without a type: the catalog, then FRED itself (/fred/series, the check
   #48 added): an ID FRED knows is FRED's, never a yfinance ticker.
3. Only if FRED can't be asked (no key, no network) and the ID isn't in the
   catalog does an untyped ID go to yfinance, as before. Nothing proves it's
   a FRED series then, and the error says what was tried.
"""
import logging
import threading
from typing import Dict, Optional

from backend.services.data_fetcher import FREDDataFetcher, FredSeriesNotFoundError

logger = logging.getLogger(__name__)

# Definite answers from FRED only (exists / doesn't exist); "couldn't ask" is
# never remembered. Per process, like the data cache.
_known: Dict[str, bool] = {}
_lock = threading.Lock()


def _fred_knows(series_id: str) -> Optional[bool]:
    """True/False when FRED answered; None when it couldn't be asked."""
    with _lock:
        if series_id in _known:
            return _known[series_id]
    try:
        FREDDataFetcher().get_series_metadata(series_id)
        answer = True
    except FredSeriesNotFoundError:
        answer = False
    except ValueError as e:   # no key, HTTP error, network
        logger.info(f"No se pudo consultar FRED para rutear {series_id}: {e}")
        return None
    with _lock:
        _known[series_id] = answer
    return answer


def is_fred_series(series_id: str, series_type: Optional[str] = None) -> bool:
    """Whether `series_id` has to be fetched from FRED (else yfinance)."""
    if series_type == "macro":
        return True
    if series_type == "equity":
        return False
    clean = series_id.strip().upper()
    if clean in FREDDataFetcher.SERIES_CATALOG:
        return True
    return _fred_knows(clean) is True


def clear_routing_cache() -> None:
    with _lock:
        _known.clear()
