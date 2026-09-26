export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
}

export interface TimeSeriesData {
  id: string;
  name: string;
  type: string;
  unit: string;
  points: TimeSeriesPoint[];
  source?: 'live' | 'synthetic';
  from_cache?: boolean;
  cached_at?: string | null;
  source_detail?: string;
}

export interface TickerSuggestion {
  symbol: string;
  name: string;
  sector: string;
  weight: number;
  thesis_role: string;
}

export interface MacroSuggestion {
  series_id: string;
  name: string;
  category: string;
  expected_correlation: string;
}

export type FallbackCategory = 'rate_limit' | 'transient' | 'auth_or_config' | 'content_filtered' | 'unknown';

export interface ThesisResponse {
  thesis: string;
  summary: string;
  tickers: TickerSuggestion[];
  macro_series: MacroSuggestion[];
  rationales: Record<string, string>;
  provider_used: string;
  fallback_reason?: string | null;
  fallback_category?: FallbackCategory | null;
}

export interface ForecastResponse {
  timestamps: string[];
  values: number[];
  lower_bound: number[];
  upper_bound: number[];
  model_name: string;
  is_fallback?: boolean;
  fitted_params?: Record<string, number>;
  engine_selection_reason?: string;
}

export interface FundamentalsMetric {
  ticker: string;
  metric: string;
  period: string;
  value: number;
  source?: 'live' | 'synthetic';
  from_cache?: boolean;
  cached_at?: string | null;
  source_detail?: string;
}

export interface InterpretationContext {
  thesis: string;
  active_series_id: string;
  active_series_name?: string;
  last_price: number;
  projected_target: number;
  horizon: number;
  confidence: number;
  lower_bound: number;
  upper_bound: number;
  cagr: number;
  other_tickers: string[];
  macro_series: string[];
  capex_summary?: Record<string, number>;
}

export interface InterpretationResponse {
  what_data_says: string;
  thesis_alignment: string;
  next_series_suggestion: string;
  suggested_series_id?: string;
  provider_used: string;
  fallback_reason?: string | null;
  fallback_category?: FallbackCategory | null;
}

export interface HealthResponse {
  status: string;
  llm_provider: string;
  /** Always per-series: EngineSelector picks Holt or TimesFM for each series. */
  engine_mode: 'per_series_auto_selection';
  /** Legacy field — no longer names an engine; see each forecast's model_name. */
  forecast_engine: string;
  /** TimesFM is enabled as an option for EngineSelector (not "in use for this series"). */
  use_real_timesfm?: boolean;
  has_gemini_key: boolean;
  has_fred_key: boolean;
  has_openai_key: boolean;
}

const API_BASE = '/api';

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export interface LLMProviderOption {
  id: string;
  label: string;
  available: boolean;
  reason?: string | null;
  note?: string | null;
}

export interface LLMProvidersResponse {
  active: string;
  env_default: string;
  persisted: boolean;
  notice: string;
  providers: LLMProviderOption[];
}

export interface LLMProviderSwitchResponse {
  active: string;
  previous: string;
  persisted: boolean;
  notice: string;
}

export async function fetchLLMProviders(): Promise<LLMProvidersResponse> {
  const res = await fetch(`${API_BASE}/config/llm-providers`);
  if (!res.ok) throw new Error(`No se pudo obtener la lista de proveedores LLM: ${res.statusText}`);
  return res.json();
}

/** Switches the active LLM provider in the server's memory only — never written to .env. */
export async function switchLLMProvider(provider: string): Promise<LLMProviderSwitchResponse> {
  const res = await fetch(`${API_BASE}/config/llm-provider`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'No se pudo cambiar el proveedor LLM');
  }
  return res.json();
}

export async function analyzeThesis(thesis: string, options?: { forceMock?: boolean }): Promise<ThesisResponse> {
  const query = options?.forceMock ? '?force_mock=true' : '';
  const res = await fetch(`${API_BASE}/thesis${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thesis }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Error al analizar la tesis de inversión');
  }
  return res.json();
}

export async function fetchMarketData(ticker: string, period = '2y'): Promise<TimeSeriesData> {
  const res = await fetch(`${API_BASE}/data/market?ticker=${encodeURIComponent(ticker)}&period=${encodeURIComponent(period)}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Error obteniendo precios de ${ticker}`);
  }
  return res.json();
}

export async function fetchMacroData(seriesId: string): Promise<TimeSeriesData> {
  const res = await fetch(`${API_BASE}/data/macro?series_id=${encodeURIComponent(seriesId)}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Error obteniendo serie macro ${seriesId}`);
  }
  return res.json();
}

export interface FredSeriesMetadata {
  series_id: string;
  title: string;
  notes: string;
}

export async function fetchFredMetadata(seriesId: string): Promise<FredSeriesMetadata> {
  const res = await fetch(`${API_BASE}/catalog/fred-metadata?series_id=${encodeURIComponent(seriesId)}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Error obteniendo metadata FRED para ${seriesId}`);
  }
  return res.json();
}

export async function fetchFundamentals(tickers: string[]): Promise<FundamentalsMetric[]> {
  if (tickers.length === 0) return [];
  const res = await fetch(`${API_BASE}/data/fundamentals?tickers=${encodeURIComponent(tickers.join(','))}`);
  if (!res.ok) throw new Error('Error obteniendo fundamentales');
  const data = await res.json();
  return data.metrics;
}

export async function fetchForecast(
  points: TimeSeriesPoint[],
  horizon = 60,
  confidence = 0.95,
  freq = 'D',
  seriesId?: string,
  seriesType?: string
): Promise<ForecastResponse> {
  const res = await fetch(`${API_BASE}/forecast`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      points,
      horizon,
      confidence,
      freq,
      series_id: seriesId,
      series_type: seriesType,
    }),
  });
  if (!res.ok) throw new Error('Error generando proyección temporal');
  return res.json();
}

export async function interpretSituation(
  ctx: InterpretationContext
): Promise<InterpretationResponse> {
  const res = await fetch(`${API_BASE}/interpret`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ctx),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Error al interpretar la situación');
  }
  return res.json();
}

// ----------------- FASE 2: PERSISTENCIA, BACKTEST Y CORRELACIÓN -----------------

export interface ResearchNoteResponse {
  id: number;
  note_text: string;
  author: string;
  created_at: string;
}

export interface ForecastSnapshotResponse {
  id: number;
  thesis_id: string;
  series_id: string;
  cutoff_date: string;
  horizon: number;
  confidence: number;
  timestamps: string[];
  projected_values: number[];
  lower_bound: number[];
  upper_bound: number[];
  model_name: string;
  created_at: string;
}

export interface ThesisSummaryItem {
  id: string;
  title: string;
  prompt: string;
  summary: string;
  status: string;
  ticker_symbols: string[];
  macro_ids: string[];
  created_at: string;
  updated_at: string;
  snapshot_count: number;
  note_count: number;
}

export interface ThesisDetailResponse {
  id: string;
  title: string;
  prompt: string;
  summary: string;
  status: string;
  tickers: TickerSuggestion[];
  macro_series: MacroSuggestion[];
  rationales: Record<string, string>;
  created_at: string;
  updated_at: string;
  snapshots: ForecastSnapshotResponse[];
  notes: ResearchNoteResponse[];
}

export interface ThesisCreateRequest {
  title: string;
  prompt: string;
  summary?: string;
  status?: string;
  tickers: TickerSuggestion[];
  macro_series: MacroSuggestion[];
  rationales?: Record<string, string>;
}

export interface BacktestMetrics {
  mae: number;
  mape: number;
  smape?: number;
  mase?: number;
  /** MASE scaled by the in-sample seasonal naive; only for seasonal series. */
  mase_seasonal?: number | null;
  directional_accuracy: number;
  observations_evaluated: number;
}

export interface SeasonalityInfo {
  frequency: string;
  period?: number | null;
  is_seasonal: boolean;
  acf_at_period?: number | null;
  threshold?: number | null;
  n_obs: number;
  reason: string;
}

export interface BacktestResponse {
  series_id: string;
  cutoff_date: string;
  horizon: number;
  historical_dates: string[];
  historical_values: number[];
  future_actual_dates: string[];
  future_actual_values: number[];
  future_predicted_values: number[];
  future_lower_bound: number[];
  future_upper_bound: number[];
  metrics: BacktestMetrics;
  naive_metrics?: BacktestMetrics;
  /** Seasonal naive benchmark, alongside the random walk; only for seasonal series. */
  seasonal_naive_metrics?: BacktestMetrics | null;
  seasonality?: SeasonalityInfo | null;
  interval_coverage?: number;
  aggregate_direction_correct?: boolean;
  verdict: string;
  warnings?: string[];
  /** Engine that actually produced the evaluated prediction. */
  model_name?: string;
  /** True when TimesFM failed and Holt answered instead: the metrics are Holt's. */
  is_fallback?: boolean;
  fallback_kind?: 'not_loaded' | 'horizon_exceeded' | 'inference_error' | null;
  fallback_reason?: string | null;
}

export interface CorrelationMatrixResponse {
  series_ids: string[];
  series_names: Record<string, string>;
  pearson_matrix: number[][];
  spearman_matrix: number[][];
  p_values_pearson?: number[][];
  p_values_spearman?: number[][];
  common_observations: number;
  start_date: string;
  end_date: string;
  mode?: string;
  warning?: string;
}

export async function fetchTheses(): Promise<ThesisSummaryItem[]> {
  const res = await fetch(`${API_BASE}/theses`);
  if (!res.ok) throw new Error('Error al listar las tesis guardadas');
  return res.json();
}

export async function createThesis(data: ThesisCreateRequest): Promise<ThesisDetailResponse> {
  const res = await fetch(`${API_BASE}/theses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Error al guardar la tesis');
  return res.json();
}

export async function fetchThesisDetail(id: string): Promise<ThesisDetailResponse> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error('Error al obtener el detalle de la tesis');
  return res.json();
}

export async function updateThesisStatus(id: string, status: string): Promise<ThesisDetailResponse> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error('Error al actualizar el estado de la tesis');
  return res.json();
}

export async function updateThesis(
  id: string,
  data: {
    title?: string;
    status?: string;
    summary?: string;
    tickers?: TickerSuggestion[];
  }
): Promise<ThesisDetailResponse> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Error al actualizar la tesis');
  return res.json();
}

export async function deleteThesis(id: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Error al eliminar la tesis');
  return res.json();
}

export async function addSnapshot(
  thesisId: string,
  data: {
    series_id: string;
    cutoff_date: string;
    horizon: number;
    confidence: number;
    timestamps: string[];
    projected_values: number[];
    lower_bound: number[];
    upper_bound: number[];
    model_name?: string;
  }
): Promise<ForecastSnapshotResponse> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(thesisId)}/snapshots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Error al registrar el snapshot');
  return res.json();
}

export async function addResearchNote(
  thesisId: string,
  noteText: string,
  author = 'Analista'
): Promise<ResearchNoteResponse> {
  const res = await fetch(`${API_BASE}/theses/${encodeURIComponent(thesisId)}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note_text: noteText, author }),
  });
  if (!res.ok) throw new Error('Error al agregar la nota');
  return res.json();
}

export async function runBacktest(
  seriesId: string,
  cutoffDate: string,
  horizon = 60,
  confidence = 0.95,
  /** Explicit engine; undefined = the server's default. 'holt_winters' only
   * works for seasonal series (the server answers 422 otherwise). */
  engine?: 'holt_winters'
): Promise<BacktestResponse> {
  const res = await fetch(`${API_BASE}/backtest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      series_id: seriesId,
      cutoff_date: cutoffDate,
      horizon,
      confidence,
      ...(engine ? { engine } : {}),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Error al ejecutar backtest');
  }
  return res.json();
}

export async function fetchCorrelations(
  seriesIds: string[],
  period = '2y',
  mode: 'returns' | 'levels' = 'returns'
): Promise<CorrelationMatrixResponse> {
  const res = await fetch(`${API_BASE}/correlation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      series_ids: seriesIds,
      period,
      mode,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Error al calcular matrices de correlación');
  }
  return res.json();
}

// ==========================================
// Portfolio Optimization & Risk Interfaces & Calls
// ==========================================

export interface PortfolioAllocationSummary {
  name: string;
  weights: Record<string, number>;
  expected_return: number;
  volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  risk_contributions: Record<string, number>;
  risk_contribution_pct: Record<string, number>;
  diversification_ratio?: number;
}

export interface PortfolioOptimizeResponse {
  tickers: string[];
  shrinkage_intensity: number;
  condition_number: number;
  mu_method_used: string;
  cov_method_used: string;
  portfolios: Record<string, PortfolioAllocationSummary>;
  warnings: string[];
}

export interface RiskMetricDetail {
  confidence_level: number;
  var_pct: number;
  var_usd: number;
  var_std_error: number;
  cvar_pct: number;
  cvar_usd: number;
}

export interface HistogramData {
  bin_edges: number[];
  frequencies: number[];
  densities: number[];
  median: number;
  percentile_5: number;
  percentile_1: number;
}

export interface PortfolioRiskResponse {
  method_used: string;
  horizon_days: number;
  initial_capital: number;
  n_simulations: number;
  metrics: Record<string, RiskMetricDetail>;
  prob_loss_10pct: number;
  prob_loss_20pct: number;
  prob_loss_30pct: number;
  histogram: HistogramData;
  warnings: string[];
}

export interface RebalanceCurvePoint {
  date: string;
  rebalance_net: number;
  rebalance_gross: number;
  buy_and_hold: number;
}

export interface StrategyPerformanceMetrics {
  total_return: number;
  annualized_return: number;
  annualized_volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
}

export interface RebalanceBacktestResponse {
  tickers: string[];
  method: string;
  rebalance_frequency: string;
  cost_bps: number;
  capital_gains_tax_rate: number;
  initial_capital: number;
  start_date: string;
  end_date: string;
  trading_days_evaluated: number;
  n_rebalances_executed: number;
  total_turnover: number;
  total_transaction_costs: number;
  total_tax_paid: number;
  curves: RebalanceCurvePoint[];
  net_metrics: StrategyPerformanceMetrics;
  gross_metrics: StrategyPerformanceMetrics;
  buy_and_hold_metrics: StrategyPerformanceMetrics;
  net_benefit_of_rebalancing: number;
  cost_drag: number;
  verdict: string;
  warnings: string[];
}

export interface RebalanceBacktestRequest {
  tickers: string[];
  method?: 'max_sharpe' | 'risk_parity';
  mu_method?: 'historical_shrunk' | 'equal';
  rebalance_frequency?: 'monthly' | 'quarterly' | 'none';
  cost_bps?: number;
  capital_gains_tax_rate?: number;
  period?: string;
  burn_in_days?: number;
  max_weight?: number;
  initial_capital?: number;
  risk_free_rate?: number;
}

export async function optimizePortfolio(params: {
  tickers: string[];
  current_weights?: Record<string, number>;
  period?: string;
  cov_method?: 'ledoit_wolf' | 'sample';
  mu_method?: 'historical_shrunk' | 'equal' | 'forecast';
  forecast_horizon?: number;
  max_weight?: number;
  risk_free_rate?: number;
}): Promise<PortfolioOptimizeResponse> {
  const res = await fetch(`${API_BASE}/portfolio/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Error al optimizar la cartera');
  }
  return res.json();
}

export async function evaluatePortfolioRisk(params: {
  tickers: string[];
  weights: Record<string, number>;
  horizon_days?: number;
  confidence_levels?: number[];
  initial_capital?: number;
  method?: 'bootstrap' | 'student_t' | 'gaussian';
  n_simulations?: number;
  block_size?: number;
}): Promise<PortfolioRiskResponse> {
  const res = await fetch(`${API_BASE}/portfolio/risk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Error al evaluar el riesgo de la cartera');
  }
  return res.json();
}

export async function runRebalanceBacktest(
  params: RebalanceBacktestRequest
): Promise<RebalanceBacktestResponse> {
  const res = await fetch(`${API_BASE}/portfolio/rebalance-backtest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Error en el backtest de rebalanceo');
  }
  return res.json();
}

