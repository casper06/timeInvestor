import logging
from typing import List, Dict, Optional, Literal
import numpy as np
import pandas as pd
from scipy import stats

from backend.schemas.models import CorrelationMatrixResponse
from backend.services.data_fetcher import MarketDataFetcher, FREDDataFetcher

logger = logging.getLogger(__name__)

class CorrelationEngine:
    """
    Computes cross-asset and macro time series correlation matrices (Pearson and Spearman).
    Eliminates spurious regressions by operating on log-returns and percentage changes by default.
    Aligns series using real DatetimeIndex and downsampling to lowest common frequency.
    """

    @staticmethod
    def calculate_correlations(
        series_ids: List[str],
        period: str = "2y",
        mode: Literal["returns", "levels"] = "returns"
    ) -> CorrelationMatrixResponse:
        clean_ids = [s.strip().upper() for s in series_ids if s.strip()]
        if len(clean_ids) < 2:
            raise ValueError("Se requieren al menos 2 series para calcular matrices de correlación")

        fred = FREDDataFetcher()
        series_dict: Dict[str, pd.Series] = {}
        names_dict: Dict[str, str] = {}
        is_monthly_list = []

        for sid in clean_ids:
            if sid in FREDDataFetcher.SERIES_CATALOG:
                data = fred.get_series(sid)
            else:
                data = MarketDataFetcher.get_history(sid, period=period)

            # Reject synthetic data
            if getattr(data, "source", "live") == "synthetic":
                raise ValueError(f"La serie {sid} es sintética: no se puede calcular correlación sobre datos generados")

            names_dict[sid] = data.name

            # Build Pandas Series with DatetimeIndex
            dates = pd.to_datetime([p.timestamp for p in data.points])
            vals = [p.value for p in data.points]
            s = pd.Series(vals, index=dates, name=sid).sort_index()

            # Remove duplicate index timestamps if any
            s = s[~s.index.duplicated(keep="last")]

            # Detect frequency
            if len(s) >= 3:
                median_days = (s.index[1:] - s.index[:-1]).median().days
                is_monthly = median_days > 15
            else:
                is_monthly = False
            is_monthly_list.append(is_monthly)
            series_dict[sid] = s

        # If any series is low-frequency (e.g. monthly macro), resample all series to month-end
        has_monthly = any(is_monthly_list)
        if has_monthly:
            aligned_dict = {}
            for sid, s in series_dict.items():
                try:
                    aligned_dict[sid] = s.resample("ME").last().dropna()
                except ValueError:
                    aligned_dict[sid] = s.resample("M").last().dropna()
            df = pd.DataFrame(aligned_dict).dropna()
        else:
            # Daily series: inner join on exact trading days
            df = pd.DataFrame(series_dict).dropna()

        if len(df) < 5:
            raise ValueError(
                f"No se encontraron suficientes fechas coincidentes entre las series seleccionadas "
                f"({len(df)} observaciones comunes encontradas, mínimo 5 requeridas)"
            )

        warning_msg: Optional[str] = None
        if mode == "levels":
            warning_msg = "Correlación sobre niveles: sujeta a regresión espuria"
            df_calc = df.copy()
        else:
            # Mode "returns": log-returns for strictly positive series, pct_change for others
            df_returns = pd.DataFrame(index=df.index[1:])
            for col in df.columns:
                col_vals = df[col].values
                if np.all(col_vals > 0):
                    df_returns[col] = np.diff(np.log(col_vals))
                else:
                    # Percentage change or simple difference for negative/zero series (e.g. rate spreads)
                    col_s = df[col]
                    df_returns[col] = col_s.pct_change().iloc[1:]
            df_calc = df_returns.dropna()

        if len(df_calc) < 4:
            raise ValueError(f"No hay suficientes observaciones tras el cálculo de retornos ({len(df_calc)})")

        valid_ids = list(df_calc.columns)
        n = len(valid_ids)

        pearson_mat = []
        spearman_mat = []
        p_val_pearson = []
        p_val_spearman = []

        for i in range(n):
            row_p, row_s = [], []
            row_pv_p, row_pv_s = [], []
            for j in range(n):
                if i == j:
                    row_p.append(1.0)
                    row_s.append(1.0)
                    row_pv_p.append(0.0)
                    row_pv_s.append(0.0)
                else:
                    x = df_calc.iloc[:, i].values
                    y = df_calc.iloc[:, j].values
                    # Pearson
                    r_p, p_p = stats.pearsonr(x, y)
                    row_p.append(round(float(r_p) if not np.isnan(r_p) else 0.0, 3))
                    row_pv_p.append(round(float(p_p) if not np.isnan(p_p) else 1.0, 4))
                    # Spearman
                    r_s, p_s = stats.spearmanr(x, y)
                    row_s.append(round(float(r_s) if not np.isnan(r_s) else 0.0, 3))
                    row_pv_s.append(round(float(p_s) if not np.isnan(p_s) else 1.0, 4))
            pearson_mat.append(row_p)
            spearman_mat.append(row_s)
            p_val_pearson.append(row_pv_p)
            p_val_spearman.append(row_pv_s)

        start_date = df_calc.index[0].strftime("%Y-%m-%d")
        end_date = df_calc.index[-1].strftime("%Y-%m-%d")

        return CorrelationMatrixResponse(
            series_ids=valid_ids,
            series_names=names_dict,
            pearson_matrix=pearson_mat,
            spearman_matrix=spearman_mat,
            p_values_pearson=p_val_pearson,
            p_values_spearman=p_val_spearman,
            common_observations=len(df_calc),
            start_date=start_date,
            end_date=end_date,
            mode=mode,
            warning=warning_msg
        )
