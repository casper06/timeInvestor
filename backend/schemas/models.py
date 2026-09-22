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
    source: Literal["live", "synthetic"] = Field(default="live", description="Data provenance: where the data came from originally")
    from_cache: bool = Field(default=False, description="Whether the series was served from local in-memory cache")
    cached_at: Optional[str] = Field(default=None, description="ISO timestamp of when the series was cached")
    source_detail: Optional[str] = Field(default=None, description="Diagnostic detail if synthetic")

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
    fallback_reason: Optional[str] = Field(default=None, description="Motivo real por el que se cayó a mock-semantic-engine (excepción del proveedor real), None si mock fue elegido explícitamente")

class ForecastRequest(BaseModel):
    points: List[TimeSeriesPoint] = Field(..., min_length=2, max_length=10_000, description="Historical time series")
    horizon: int = Field(default=30, ge=1, le=365, description="Projection horizon in steps (max 365)")
    confidence: float = Field(default=0.95, ge=0.5, le=0.99, description="Confidence interval level")
    freq: Optional[str] = Field(default="D", description="Frequency: 'D' for daily, 'M' for monthly")
    series_id: Optional[str] = Field(default=None, description="Series identifier (ticker or FRED series ID), used by EngineSelector to look up its category. None falls back to the default individual-equity selection path.")
    series_type: Optional[str] = Field(default=None, description="'equity' or 'macro', as in TimeSeriesData.type — used by EngineSelector alongside series_id")

class ForecastResponse(BaseModel):
    timestamps: List[str] = Field(..., description="Projected future timestamps")
    values: List[float] = Field(..., description="Point forecasts")
    lower_bound: List[float] = Field(..., description="Lower prediction interval bound")
    upper_bound: List[float] = Field(..., description="Upper prediction interval bound")
    model_name: str = Field(default="damped-holt-mle", description="Name of the forecasting model")
    is_fallback: bool = Field(default=False, description="True if model fell back from primary engine")
    fitted_params: Optional[Dict[str, float]] = Field(default=None, description="Fitted smoothing and damping parameters")
    engine_selection_reason: str = Field(default="", description="Human-readable explanation of why this specific engine was chosen for this series (category, history length, or fallback)")

class FundamentalsMetric(BaseModel):
    ticker: str
    metric: str
    period: str
    value: float
    source: Literal["live", "synthetic"] = Field(default="live", description="Data provenance: where the data came from originally")
    from_cache: bool = Field(default=False, description="Whether the metric was served from local in-memory cache")
    cached_at: Optional[str] = Field(default=None, description="ISO timestamp of when the metric was cached")
    source_detail: Optional[str] = Field(default=None, description="Diagnostic detail if synthetic")

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
    provider_used: str = Field(..., description="Proveedor real que generó esta interpretación: gemini-3.6-flash, openai-gpt-4o-mini, ollama-<model>, o mock-semantic-engine")
    fallback_reason: Optional[str] = Field(default=None, description="Motivo real por el que se cayó a mock-semantic-engine (excepción del proveedor real), None si mock fue elegido explícitamente")

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
    tickers: Optional[List[TickerSuggestion]] = None

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


# Portfolio Optimization Schemas
class PortfolioOptimizeRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=2, max_length=20, description="List of at least 2 tickers")
    current_weights: Optional[Dict[str, float]] = Field(default=None, description="Optional current portfolio weights")
    period: str = Field(default="2y", description="Historical period, e.g. 2y")
    cov_method: Literal["ledoit_wolf", "sample"] = Field(default="ledoit_wolf", description="Covariance estimation method")
    mu_method: Literal["historical_shrunk", "equal", "forecast"] = Field(default="historical_shrunk", description="Expected return estimation method")
    forecast_horizon: int = Field(default=30, ge=5, le=365, description="Horizon in days for forecast-based expected return")
    max_weight: float = Field(default=0.35, ge=0.05, le=1.0, description="Maximum allocation per asset")
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20, description="Annual risk-free rate")


class PortfolioAllocationSummary(BaseModel):
    name: str
    weights: Dict[str, float]
    expected_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    risk_contributions: Dict[str, float]
    risk_contribution_pct: Dict[str, float]
    diversification_ratio: Optional[float] = None


class PortfolioOptimizeResponse(BaseModel):
    tickers: List[str]
    shrinkage_intensity: float = Field(..., description="Ledoit-Wolf shrinkage intensity delta* in [0, 1]")
    condition_number: float = Field(..., description="Condition number of covariance matrix")
    mu_method_used: str
    cov_method_used: str
    portfolios: Dict[str, PortfolioAllocationSummary]
    warnings: List[str] = Field(default_factory=list)


# Risk Engine Schemas
class PortfolioRiskRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=1, max_length=20)
    weights: Dict[str, float] = Field(..., description="Weights summing to ~1.0")
    horizon_days: int = Field(default=30, ge=1, le=365, description="Risk horizon in days")
    confidence_levels: List[float] = Field(default=[0.95, 0.99], description="Confidence levels for VaR/CVaR")
    initial_capital: float = Field(default=100_000.0, ge=100.0, description="Capital in USD")
    method: Literal["bootstrap", "student_t", "gaussian"] = Field(default="bootstrap", description="Simulation engine method")
    n_simulations: int = Field(default=10_000, ge=1_000, le=100_000, description="Number of Monte Carlo paths")
    block_size: Optional[int] = Field(default=None, ge=2, le=100, description="Block size for bootstrap")


class RiskMetricDetail(BaseModel):
    confidence_level: float
    var_pct: float = Field(..., description="Value at Risk as a POSITIVE percentage loss (e.g. 0.12 = 12% loss)")
    var_usd: float = Field(..., description="Value at Risk in USD")
    var_std_error: float = Field(..., description="Monte Carlo standard error of estimated VaR")
    cvar_pct: float = Field(..., description="Conditional VaR (Expected Shortfall) as a POSITIVE percentage loss")
    cvar_usd: float = Field(..., description="Conditional VaR in USD")


class HistogramData(BaseModel):
    bin_edges: List[float]
    frequencies: List[int]
    densities: List[float]
    median: float
    percentile_5: float
    percentile_1: float


class PortfolioRiskResponse(BaseModel):
    method_used: str
    horizon_days: int
    initial_capital: float
    n_simulations: int
    metrics: Dict[str, RiskMetricDetail]
    prob_loss_10pct: float
    prob_loss_20pct: float
    prob_loss_30pct: float
    histogram: HistogramData
    warnings: List[str] = Field(default_factory=list)


# Dynamic Rebalancing Backtest Schemas
class RebalanceBacktestRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=2, max_length=20, description="List of at least 2 tickers")
    method: Literal["max_sharpe", "risk_parity"] = Field(default="max_sharpe", description="Portfolio rebalancing optimization model")
    mu_method: Literal["historical_shrunk", "equal"] = Field(default="historical_shrunk", description="Expected return method if max_sharpe")
    rebalance_frequency: Literal["monthly", "quarterly", "none"] = Field(default="monthly", description="Rebalancing schedule: monthly (~21d), quarterly (~63d), or none")
    cost_bps: float = Field(default=10.0, ge=0.0, le=500.0, description="Transaction cost in basis points (e.g. 10 bps = 0.10%)")
    capital_gains_tax_rate: float = Field(default=0.0, ge=0.0, le=0.50, description="Capital gains tax rate on realized sales (0.0 to 0.50)")
    period: str = Field(default="5y", description="Historical lookback period (e.g. 3y, 5y)")
    burn_in_days: int = Field(default=252, ge=126, le=756, description="Minimum trading days of history before initial backtest rebalance")
    max_weight: float = Field(default=0.35, ge=0.05, le=1.0, description="Maximum allocation per asset")
    initial_capital: float = Field(default=100_000.0, ge=100.0, description="Initial portfolio capital in USD")
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20, description="Risk-free rate for Sharpe ratio calculation")


class RebalanceCurvePoint(BaseModel):
    date: str
    rebalance_net: float
    rebalance_gross: float
    buy_and_hold: float


class StrategyPerformanceMetrics(BaseModel):
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float


class RebalanceBacktestResponse(BaseModel):
    tickers: List[str]
    method: str
    rebalance_frequency: str
    cost_bps: float
    capital_gains_tax_rate: float
    initial_capital: float
    start_date: str
    end_date: str
    trading_days_evaluated: int
    n_rebalances_executed: int
    total_turnover: float
    total_transaction_costs: float
    total_tax_paid: float
    curves: List[RebalanceCurvePoint]
    net_metrics: StrategyPerformanceMetrics
    gross_metrics: StrategyPerformanceMetrics
    buy_and_hold_metrics: StrategyPerformanceMetrics
    net_benefit_of_rebalancing: float
    cost_drag: float
    verdict: str
    warnings: List[str] = Field(default_factory=list)

