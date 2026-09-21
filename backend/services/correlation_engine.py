import logging
from typing import List, Dict
import numpy as np
import pandas as pd
from scipy import stats

from backend.schemas.models import CorrelationMatrixResponse
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

logger = logging.getLogger(__name__)

class CorrelationEngine:
    """
    Computes cross-asset and macro time series correlation matrices (Pearson and Spearman).
    Aligns heterogeneous time series along common observation dates.
    """

    @staticmethod
    def calculate_correlations(series_ids: List[str], period: str = "2y") -> CorrelationMatrixResponse:
        clean_ids = [s.strip().upper() for s in series_ids if s.strip()]
        if len(clean_ids) < 2:
            raise ValueError("Se requieren al menos 2 series para calcular matrices de correlación")

        fred = FREDDataFetcher()
        series_dict: Dict[str, pd.Series] = {}
        names_dict: Dict[str, str] = {}

        for sid in clean_ids:
            if sid in FREDDataFetcher.SERIES_CATALOG:
                data = fred.get_series(sid)
            else:
                data = MarketDataFetcher.get_history(sid, period=period)

            names_dict[sid] = data.name
            
            # Build Pandas Series indexed by date string (YYYY-MM-DD)
            date_val_map = {p.timestamp: p.value for p in data.points}
            series_dict[sid] = pd.Series(date_val_map, name=sid)

        # Combine into DataFrame
        df = pd.DataFrame(series_dict)

        # Sort index chronologically
        df = df.sort_index()

        # Resample / forward-fill daily or monthly gaps so macro and equity can correlate
        # Forward fill up to 5 days, then drop remaining NaNs for alignment
        df_filled = df.ffill(limit=7).dropna()

        if len(df_filled) < 10:
            # Fallback: if inner intersection is too small, interpolate linearly
            df_filled = df.interpolate(method="linear").dropna()

        if len(df_filled) < 5:
            raise ValueError("No se encontraron suficientes fechas coincidentes entre las series seleccionadas")

        valid_ids = list(df_filled.columns)
        n = len(valid_ids)

        # Pearson correlation
        pearson_df = df_filled.corr(method="pearson")
        pearson_mat = [[round(float(pearson_df.iloc[i, j]), 3) for j in range(n)] for i in range(n)]

        # Spearman rank correlation
        spearman_mat = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    row.append(1.0)
                else:
                    corr, _ = stats.spearmanr(df_filled.iloc[:, i], df_filled.iloc[:, j])
                    row.append(round(float(corr) if not np.isnan(corr) else 0.0, 3))
            spearman_mat.append(row)

        start_date = str(df_filled.index[0])
        end_date = str(df_filled.index[-1])

        return CorrelationMatrixResponse(
            series_ids=valid_ids,
            series_names=names_dict,
            pearson_matrix=pearson_mat,
            spearman_matrix=spearman_mat,
            common_observations=len(df_filled),
            start_date=start_date,
            end_date=end_date
        )
