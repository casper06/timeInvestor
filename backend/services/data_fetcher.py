import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Tuple
import numpy as np
import httpx
import yfinance as yf

from backend.config import settings
from backend.schemas.models import TimeSeriesPoint, TimeSeriesData, FundamentalsMetric

logger = logging.getLogger(__name__)

class SimpleCache:
    """Thread-safe in-memory cache with TTL."""
    def __init__(self, ttl_seconds: int = 3600):
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._ttl = ttl_seconds
        self._lock = threading.RLock()

    def get_with_time(self, key: str) -> Optional[Tuple[Any, float]]:
        with self._lock:
            if key in self._cache:
                timestamp, data = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    return data, timestamp
                del self._cache[key]
            return None

    def get(self, key: str) -> Optional[Any]:
        res = self.get_with_time(key)
        return res[0] if res else None

    def set(self, key: str, value: Any):
        with self._lock:
            self._cache[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._cache.clear()

cache = SimpleCache(ttl_seconds=settings.CACHE_TTL_SECONDS)


class MarketDataFetcher:
    """Ingests market and financial statement data using yfinance."""

    @staticmethod
    def get_history(ticker: str, period: str = "2y", interval: str = "1d") -> TimeSeriesData:
        clean_ticker = ticker.strip().upper()
        cache_key = f"yf_hist_{clean_ticker}_{period}_{interval}"
        hit = cache.get_with_time(cache_key)
        if hit:
            cached, cached_ts = hit
            cached_at_str = datetime.fromtimestamp(cached_ts, tz=timezone.utc).isoformat()
            # Clone preserving the original source of the cached object and set from_cache=True plus cached_at
            return TimeSeriesData(
                id=cached.id,
                name=cached.name,
                type=cached.type,
                unit=cached.unit,
                points=cached.points,
                source=cached.source,
                from_cache=True,
                cached_at=cached_at_str,
                source_detail=cached.source_detail
            )

        logger.info(f"Fetching yfinance history for {clean_ticker} (period={period}, interval={interval})")
        try:
            t = yf.Ticker(clean_ticker)
            df = t.history(period=period, interval=interval)
            
            if df is None or df.empty:
                detail = f"yfinance devolvió dataframe vacío para {clean_ticker}"
                logger.warning(detail)
                if not settings.ALLOW_SYNTHETIC_DATA:
                    raise ValueError(f"No se pudieron obtener datos de mercado para '{clean_ticker}' ({detail}) y ALLOW_SYNTHETIC_DATA=false")
                return MarketDataFetcher._generate_synthetic_equity(clean_ticker, period, detail=detail)

            points: List[TimeSeriesPoint] = []
            for idx, row in df.iterrows():
                if hasattr(idx, "strftime"):
                    date_str = idx.strftime("%Y-%m-%d")
                else:
                    date_str = str(idx)[:10]

                close_val = row.get("Close")
                if close_val is not None and not np.isnan(close_val):
                    points.append(TimeSeriesPoint(timestamp=date_str, value=round(float(close_val), 2)))

            info = {}
            try:
                info = t.info or {}
            except Exception:
                pass

            name = info.get("shortName") or info.get("longName") or f"{clean_ticker} Stock"
            series_data = TimeSeriesData(
                id=clean_ticker,
                name=name,
                type="equity",
                unit="USD",
                points=points,
                source="live",
                source_detail="Cotizaciones reales obtenidas vía yfinance"
            )
            cache.set(cache_key, series_data)
            return series_data

        except Exception as e:
            detail = f"Error al consultar yfinance para {clean_ticker}: {str(e)}"
            logger.error(detail)
            if not settings.ALLOW_SYNTHETIC_DATA:
                raise ValueError(f"Fallo en la ingesta de datos para '{clean_ticker}': {str(e)} y ALLOW_SYNTHETIC_DATA=false") from e
            return MarketDataFetcher._generate_synthetic_equity(clean_ticker, period, detail=detail)

    @staticmethod
    def get_fundamentals(tickers: List[str]) -> Tuple[List[FundamentalsMetric], List[str]]:
        """
        Fetches official balance sheet and cashflow fundamentals (Capex and Revenue) from yfinance.
        Never fabricates numbers: if unavailable, returns warnings explicitly.
        """
        clean_tickers = sorted(list(set(t.strip().upper() for t in tickers if t.strip())))
        cache_key = f"yf_fund_{'_'.join(clean_tickers)}"
        hit = cache.get_with_time(cache_key)
        if hit:
            (cached_metrics, cached_warnings), cached_ts = hit
            cached_at_str = datetime.fromtimestamp(cached_ts, tz=timezone.utc).isoformat()
            cloned_metrics = [
                FundamentalsMetric(
                    ticker=m.ticker,
                    metric=m.metric,
                    period=m.period,
                    value=m.value,
                    source=m.source,
                    from_cache=True,
                    cached_at=cached_at_str,
                    source_detail=m.source_detail
                )
                for m in cached_metrics
            ]
            return cloned_metrics, cached_warnings

        metrics: List[FundamentalsMetric] = []
        warnings: List[str] = []

        for sym in clean_tickers:
            try:
                t = yf.Ticker(sym)
                cashflow = t.cashflow
                financials = t.financials

                capex_extracted = False
                if cashflow is not None and not cashflow.empty:
                    candidates = [
                        "Capital Expenditure", 
                        "CapitalExpenditure", 
                        "Net PPE Purchase And Sale", 
                        "Purchase Of Property Plant And Equipment"
                    ]
                    for candidate in candidates:
                        if candidate in cashflow.index:
                            row = cashflow.loc[candidate]
                            for date_col, val in row.items():
                                if val is not None and not np.isnan(val):
                                    year = date_col.strftime("%Y") if hasattr(date_col, "strftime") else str(date_col)[:4]
                                    val_abs = abs(float(val)) / 1e9
                                    metrics.append(FundamentalsMetric(
                                        ticker=sym,
                                        metric="Capex (Billions USD)",
                                        period=year,
                                        value=round(val_abs, 2),
                                        source="live",
                                        source_detail="Cashflow statement oficial de yfinance"
                                    ))
                                    capex_extracted = True
                            if capex_extracted:
                                break

                rev_extracted = False
                if financials is not None and not financials.empty:
                    rev_candidates = ["Total Revenue", "Operating Revenue", "TotalRevenue"]
                    for candidate in rev_candidates:
                        if candidate in financials.index:
                            row = financials.loc[candidate]
                            for date_col, val in row.items():
                                if val is not None and not np.isnan(val):
                                    year = date_col.strftime("%Y") if hasattr(date_col, "strftime") else str(date_col)[:4]
                                    val_billions = float(val) / 1e9
                                    metrics.append(FundamentalsMetric(
                                        ticker=sym,
                                        metric="Revenue (Billions USD)",
                                        period=year,
                                        value=round(val_billions, 2),
                                        source="live",
                                        source_detail="Income statement oficial de yfinance"
                                    ))
                                    rev_extracted = True
                            if rev_extracted:
                                break

                if not capex_extracted and not rev_extracted:
                    warnings.append(f"No se obtuvieron estados contables para {sym}")

            except Exception as e:
                logger.warning(f"Error fetching fundamentals for {sym}: {e}")
                warnings.append(f"No se obtuvieron estados contables para {sym}: {str(e)}")

        result = (metrics, warnings)
        cache.set(cache_key, result)
        return result

    @staticmethod
    def _generate_synthetic_equity(ticker: str, period: str, detail: Optional[str] = None) -> TimeSeriesData:
        """Generates synthetic daily equity prices only when ALLOW_SYNTHETIC_DATA=true."""
        days = 365 if period == "1y" else 730
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        seed = sum(ord(c) for c in ticker)
        rng = np.random.default_rng(seed)
        base_price = 50.0 + (seed % 150)
        
        returns = rng.normal(0.0006, 0.015, days)
        prices = base_price * np.cumprod(1 + returns)
        
        points: List[TimeSeriesPoint] = []
        current = start_date
        for i in range(days):
            current += timedelta(days=1)
            if current.weekday() < 5:
                points.append(TimeSeriesPoint(
                    timestamp=current.strftime("%Y-%m-%d"),
                    value=round(float(prices[i]), 2)
                ))

        return TimeSeriesData(
            id=ticker.upper(),
            name=f"{ticker.upper()} (Sintético)",
            type="equity",
            unit="USD",
            points=points,
            source="synthetic",
            source_detail=detail or "Serie sintética generada por falta de datos reales"
        )


class FREDDataFetcher:
    """Ingests macroeconomic and energy time series from FRED API or built-in reference dataset."""

    SERIES_CATALOG = {
        "IPG2211A2N": {
            "name": "Electric Power Generation, Transmission and Distribution Index",
            "category": "Energy / Utilities",
            "unit": "Index 2017=100",
            "base_val": 102.5,
            "trend": 0.002
        },
        "INDPRO": {
            "name": "Industrial Production Total Index",
            "category": "Macroeconomics",
            "unit": "Index 2017=100",
            "base_val": 103.0,
            "trend": 0.001
        },
        "CPIAUCSL": {
            "name": "Consumer Price Index for All Urban Consumers",
            "category": "Inflation",
            "unit": "Index 1982-1984=100",
            "base_val": 314.0,
            "trend": 0.0025
        },
        "DGS10": {
            "name": "10-Year Treasury Constant Maturity Rate",
            "category": "Interest Rates",
            "unit": "Percent",
            "base_val": 4.15,
            "trend": 0.0005
        },
        "PCU33443344": {
            "name": "PPI: Semiconductor and Other Electronic Component Manufacturing",
            "category": "Technology Supply Chain",
            "unit": "Index Dec 2003=100",
            "base_val": 145.0,
            "trend": 0.0015
        }
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.FRED_API_KEY

    def get_series(self, series_id: str, limit: int = 500) -> TimeSeriesData:
        cache_key = f"fred_{series_id}_{limit}"
        hit = cache.get_with_time(cache_key)
        if hit:
            cached, cached_ts = hit
            cached_at_str = datetime.fromtimestamp(cached_ts, tz=timezone.utc).isoformat()
            return TimeSeriesData(
                id=cached.id,
                name=cached.name,
                type=cached.type,
                unit=cached.unit,
                points=cached.points,
                source=cached.source,
                from_cache=True,
                cached_at=cached_at_str,
                source_detail=cached.source_detail
            )

        if self.api_key and self.api_key.strip():
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    # "desc" + limit returns the N MOST RECENT observations. Long-running
                    # series like INDPRO (starts 1919) or DGS10 (starts 1962) would
                    # otherwise return the OLDEST `limit` points with "asc" + limit —
                    # e.g. INDPRO's first 500 observations end in 1960, decades before
                    # any equity series this gets correlated/backtested against, silently
                    # producing zero overlapping dates. Reversed back to ascending order
                    # below, since every caller (correlation alignment, backtest train/test
                    # split) expects chronological order.
                    "sort_order": "desc",
                    "limit": limit
                }
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        points: List[TimeSeriesPoint] = []
                        for obs in data.get("observations", []):
                            val_str = obs.get("value")
                            date_str = obs.get("date")
                            if val_str and val_str != ".":
                                try:
                                    points.append(TimeSeriesPoint(
                                        timestamp=date_str,
                                        value=round(float(val_str), 2)
                                    ))
                                except ValueError:
                                    continue
                        points.reverse()
                        if points:
                            catalog_entry = self.SERIES_CATALOG.get(series_id, {})
                            series_data = TimeSeriesData(
                                id=series_id,
                                name=catalog_entry.get("name", f"FRED Series {series_id}"),
                                type="macro",
                                unit=catalog_entry.get("unit", "Index"),
                                points=points,
                                source="live",
                                source_detail="Datos oficiales de St. Louis Fed FRED API"
                            )
                            cache.set(cache_key, series_data)
                            return series_data
                    else:
                        logger.warning(f"FRED API returned HTTP {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"Failed to query FRED API: {e}")

        # Fallback to reference series only if ALLOW_SYNTHETIC_DATA=true
        detail = "FRED API no disponible (clave no configurada o error de conexión)"
        if not settings.ALLOW_SYNTHETIC_DATA:
            raise ValueError(f"No se pudieron obtener datos de FRED para '{series_id}' ({detail}) y ALLOW_SYNTHETIC_DATA=false")
        
        series_data = self._generate_reference_series(series_id, detail=detail)
        cache.set(cache_key, series_data)
        return series_data

    def get_series_metadata(self, series_id: str) -> Dict[str, str]:
        """Fetches the REAL title and description ('notes') FRED itself publishes
        for a series_id, via FRED's own /fred/series metadata endpoint (distinct
        from /fred/series/observations used by get_series() above). Never
        hand-written: the whole point is to show the user FRED's own official
        description, not a guess at what a cryptic ID like PCU221110221110 means.

        Raises ValueError (same shape as get_series()'s no-key/no-data error) when
        FRED_API_KEY isn't configured or the series_id doesn't exist on FRED —
        callers (routes.py) already know how to turn that into a humanized 404.
        """
        cache_key = f"fred_meta_{series_id}"
        hit = cache.get(cache_key)
        if hit:
            return hit

        if not (self.api_key and self.api_key.strip()):
            raise ValueError(
                f"No se pudo obtener metadata de FRED para '{series_id}' "
                f"(clave FRED_API_KEY no configurada)"
            )

        try:
            url = "https://api.stlouisfed.org/fred/series"
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    series_list = data.get("seriess", [])
                    if series_list:
                        entry = series_list[0]
                        metadata = {
                            "series_id": series_id,
                            "title": entry.get("title", ""),
                            "notes": entry.get("notes", ""),
                        }
                        cache.set(cache_key, metadata)
                        return metadata
                    raise ValueError(f"La serie FRED '{series_id}' no existe (respuesta vacía de la API)")
                else:
                    logger.warning(f"FRED metadata API returned HTTP {resp.status_code}: {resp.text}")
                    raise ValueError(
                        f"No se pudo obtener metadata de FRED para '{series_id}' "
                        f"(HTTP {resp.status_code} de la API de FRED)"
                    )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to query FRED metadata API for {series_id}: {e}")
            raise ValueError(f"No se pudo obtener metadata de FRED para '{series_id}': {str(e)}") from e

    def _generate_reference_series(self, series_id: str, detail: Optional[str] = None) -> TimeSeriesData:
        catalog_entry = self.SERIES_CATALOG.get(series_id, {
            "name": f"Macro Series {series_id}",
            "category": "Economic Indicator",
            "unit": "Index",
            "base_val": 100.0,
            "trend": 0.001
        })

        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 3)
        base_val = catalog_entry["base_val"]
        trend = catalog_entry["trend"]

        seed = sum(ord(c) for c in series_id)
        rng = np.random.default_rng(seed)
        
        points: List[TimeSeriesPoint] = []
        cur_date = datetime(start_date.year, start_date.month, 1)
        cur_val = base_val
        
        while cur_date <= end_date:
            noise = rng.normal(0, base_val * 0.01)
            cur_val = cur_val * (1 + trend) + noise
            points.append(TimeSeriesPoint(
                timestamp=cur_date.strftime("%Y-%m-%d"),
                value=round(float(cur_val), 2)
            ))
            month = cur_date.month + 1
            year = cur_date.year
            if month > 12:
                month = 1
                year += 1
            cur_date = datetime(year, month, 1)

        return TimeSeriesData(
            id=series_id,
            name=f"{catalog_entry['name']} (Referencia Sintética)",
            type="macro",
            unit=catalog_entry["unit"],
            points=points,
            source="synthetic",
            source_detail=detail or "Serie sintética generada por falta de datos reales"
        )
