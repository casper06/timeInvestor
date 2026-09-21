from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal

class TimeSeriesPoint(BaseModel):
    timestamp: str = Field(..., description="Timestamp in ISO-8601 or YYYY-MM-DD format")
    value: float = Field(..., description="Numerical value of the observation")

class TimeSeriesData(BaseModel):
    id: str = Field(..., description="Identifier for the series (e.g. NVDA, IPG2211A2N)")
    name: str = Field(..., description="Human-readable title or label")
    type: str = Field(..., description="Type of series: equity, macro, or fundamental")
    unit: str = Field(default="USD", description="Unit of measurement")
    points: List[TimeSeriesPoint] = Field(default_factory=list)
    source: Literal["live", "synthetic", "cached"] = Field(default="live", description="Data provenance")
    source_detail: Optional[str] = Field(default=None, description="Diagnostic detail if synthetic or cached")

class TickerSuggestion(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol (e.g. NVDA)")
    name: str = Field(..., description="Company name")
    sector: str = Field(..., description="Industry sector")
    weight: float = Field(default=0.2, description="Suggested allocation weight (0.0 to 1.0)")
    thesis_role: str = Field(..., description="Specific role or angle in the investment thesis")

class MacroSuggestion(BaseModel):
    series_id: str = Field(..., description="FRED or Macro series ID (e.g. IPG2211A2N)")
    name: str = Field(..., description="Series description")
    category: str = Field(..., description="Category (Energy, Tech, Inflation, Rates, etc.)")
    expected_correlation: str = Field(default="Positive", description="Expected correlation with thesis")

class ThesisRequest(BaseModel):
    thesis: str = Field(..., min_length=3, description="Free-text investment thesis")

class ThesisResponse(BaseModel):
    thesis: str
    summary: str
    tickers: List[TickerSuggestion]
    macro_series: List[MacroSuggestion]
    rationales: Dict[str, str]
    provider_used: str

class ForecastRequest(BaseModel):
    points: List[TimeSeriesPoint] = Field(..., min_length=2, max_length=10_000, description="Historical time series")
    horizon: int = Field(default=30, ge=1, le=365, description="Projection horizon in steps (max 365)")
    confidence: float = Field(default=0.95, ge=0.5, le=0.99, description="Confidence interval level")
    freq: Optional[str] = Field(default="D", description="Frequency: 'D' for daily, 'M' for monthly")

class ForecastResponse(BaseModel):
    timestamps: List[str] = Field(..., description="Projected future timestamps")
    values: List[float] = Field(..., description="Point forecasts")
    lower_bound: List[float] = Field(..., description="Lower prediction interval bound")
    upper_bound: List[float] = Field(..., description="Upper prediction interval bound")
    model_name: str = Field(default="damped-holt-mle", description="Name of the forecasting model")
    is_fallback: bool = Field(default=False, description="True if model fell back from primary engine")
    fitted_params: Optional[Dict[str, float]] = Field(default=None, description="Fitted smoothing and damping parameters")

class FundamentalsMetric(BaseModel):
    ticker: str
    metric: str
    period: str
    value: float
    source: Literal["live", "synthetic", "cached"] = Field(default="live", description="Data provenance")
    source_detail: Optional[str] = Field(default=None, description="Diagnostic detail if synthetic or cached")

class FundamentalsResponse(BaseModel):
    metrics: List[FundamentalsMetric] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class InterpretationContext(BaseModel):
    thesis: str = Field(..., description="Tesis original ingresada por el usuario")
    active_series_id: str = Field(..., description="Ticker o ID de serie activa")
    active_series_name: str = Field(default="", description="Nombre de la serie activa")
    last_price: float = Field(..., description="Último precio real registrado")
    projected_target: float = Field(..., description="Valor proyectado al horizonte H")
    horizon: int = Field(default=60, description="Horizonte de días")
    confidence: float = Field(default=0.95, description="Nivel de confianza de las bandas")
    lower_bound: float = Field(..., description="Banda inferior proyectada")
    upper_bound: float = Field(..., description="Banda superior proyectada")
    cagr: float = Field(default=0.0, description="CAGR anualizado proyectado")
    other_tickers: List[str] = Field(default_factory=list, description="Otros tickers en la cartera")
    macro_series: List[str] = Field(default_factory=list, description="Series macro en la tesis")
    capex_summary: Optional[Dict[str, float]] = Field(default=None, description="Resumen de Capex por ticker")

class InterpretationResponse(BaseModel):
    what_data_says: str = Field(..., description="Traducción conceptual de las curvas y tendencia proyectada")
    thesis_alignment: str = Field(..., description="Evaluación de si los datos confirman o contradicen la hipótesis")
    next_series_suggestion: str = Field(..., description="Justificación de qué serie mirar a continuación")
    suggested_series_id: Optional[str] = Field(default=None, description="ID del ticker o serie sugerida para explorar")

class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    forecast_engine: str
    use_real_timesfm: bool = False
    has_gemini_key: bool
    has_fred_key: bool
    has_openai_key: bool

# ----------------- FASE 2: PERSISTENCIA, BACKTEST Y CORRELACIÓN -----------------

class ResearchNoteCreateRequest(BaseModel):
    note_text: str = Field(..., min_length=1)
    author: Optional[str] = Field(default="Analista")

class ResearchNoteResponse(BaseModel):
    id: int
    note_text: str
    author: str
    created_at: str

class ForecastSnapshotCreateRequest(BaseModel):
    series_id: str
    cutoff_date: str
    horizon: int = 60
    confidence: float = 0.95
    timestamps: List[str]
    projected_values: List[float]
    lower_bound: List[float]
    upper_bound: List[float]
    model_name: Optional[str] = "timesfm"

class ForecastSnapshotResponse(BaseModel):
    id: int
    thesis_id: str
    series_id: str
    cutoff_date: str
    horizon: int
    confidence: float
    timestamps: List[str]
    projected_values: List[float]
    lower_bound: List[float]
    upper_bound: List[float]
    model_name: str
    created_at: str

class ThesisCreateRequest(BaseModel):
    title: str = Field(..., min_length=2)
    prompt: str = Field(..., min_length=2)
    summary: Optional[str] = ""
    status: Optional[str] = "Activa"
    tickers: List[TickerSuggestion] = Field(default_factory=list)
    macro_series: List[MacroSuggestion] = Field(default_factory=list)
    rationales: Optional[Dict[str, str]] = Field(default_factory=dict)

class ThesisUpdateRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None

class ThesisSummaryItem(BaseModel):
    id: str
    title: str
    prompt: str
    summary: str
    status: str
    ticker_symbols: List[str]
    macro_ids: List[str]
    created_at: str
    updated_at: str
    snapshot_count: int
    note_count: int

class ThesisDetailResponse(BaseModel):
    id: str
    title: str
    prompt: str
    summary: str
    status: str
    tickers: List[TickerSuggestion]
    macro_series: List[MacroSuggestion]
    rationales: Dict[str, str]
    created_at: str
    updated_at: str
    snapshots: List[ForecastSnapshotResponse] = Field(default_factory=list)
    notes: List[ResearchNoteResponse] = Field(default_factory=list)

# Backtest Schemas
class BacktestRequest(BaseModel):
    series_id: str
    cutoff_date: str
    horizon: int = Field(default=60, ge=5, le=365)
    confidence: float = Field(default=0.95, ge=0.5, le=0.99)

class BacktestMetrics(BaseModel):
    mae: float
    mape: float
    smape: float = Field(default=0.0, description="Symmetric Mean Absolute Percentage Error (%)")
    mase: float = Field(default=0.0, description="Mean Absolute Scaled Error relative to in-sample naive")
    directional_accuracy: float = Field(..., description="Step-by-step directional accuracy (%)")
    observations_evaluated: int

class BacktestResponse(BaseModel):
    series_id: str
    cutoff_date: str
    horizon: int
    historical_dates: List[str]
    historical_values: List[float]
    future_actual_dates: List[str]
    future_actual_values: List[float]
    future_predicted_values: List[float]
    future_lower_bound: List[float]
    future_upper_bound: List[float]
    metrics: BacktestMetrics
    naive_metrics: Optional[BacktestMetrics] = None
    interval_coverage: float = Field(default=0.0, description="Percentage of actuals inside prediction interval (%)")
    aggregate_direction_correct: bool = Field(default=False, description="True if aggregate horizon direction matched")
    verdict: str
    warnings: List[str] = Field(default_factory=list)

# Correlation Schemas
class CorrelationRequest(BaseModel):
    series_ids: List[str] = Field(..., min_length=2)
    period: str = Field(default="2y")
    mode: Literal["returns", "levels"] = Field(default="returns", description="returns (log-diff/pct_change) or levels")

class CorrelationMatrixResponse(BaseModel):
    series_ids: List[str]
    series_names: Dict[str, str]
    pearson_matrix: List[List[float]]
    spearman_matrix: List[List[float]]
    p_values_pearson: List[List[float]] = Field(default_factory=list)
    p_values_spearman: List[List[float]] = Field(default_factory=list)
    common_observations: int
    start_date: str
    end_date: str
    mode: str = "returns"
    warning: Optional[str] = None
