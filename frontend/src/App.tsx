import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import type { DashboardView } from './components/Header';
import { ThesisBar } from './components/ThesisBar';
import { ForecastChart, humanizeSeriesError } from './components/ForecastChart';
import { FundBarChart } from './components/FundBarChart';
import { ExposureDonut } from './components/ExposureDonut';
import { MetricCards } from './components/MetricCards';
import { StatisticalTelemetry } from './components/StatisticalTelemetry';
import { ThesisCopilot } from './components/ThesisCopilot';
import { ThesesDrawer } from './components/ThesesDrawer';
import { BacktestPanel } from './components/BacktestPanel';
import { CorrelationHeatmap } from './components/CorrelationHeatmap';
import { DualAxisChart } from './components/DualAxisChart';
import { ThesisAlertBanner } from './components/ThesisAlertBanner';
import { PortfolioRiskView } from './components/PortfolioRiskView';
import { exportMarkdownReport } from './utils/exportReport';
import { CANONICAL_HORIZON, seriesFrequency } from './utils/horizon';
import { AlertTriangle } from 'lucide-react';
import { EmptyState } from './components/EmptyState';

import {
  checkHealth,
  analyzeThesis,
  fetchMarketData,
  fetchMacroData,
  fetchFundamentals,
  fetchForecast,
  fetchFredMetadata,
  ApiError,
} from './services/api';
import type {
  HealthResponse,
  ThesisResponse,
  TimeSeriesData,
  ForecastResponse,
  FundamentalsMetric,
  TickerSuggestion,
  MacroSuggestion,
  ThesisDetailResponse,
  InterpretationResponse,
  BacktestResponse,
  CorrelationMatrixResponse,
  PortfolioOptimizeResponse,
} from './services/api';

// Readable name of the active LLM provider (health.llm_provider).
const PROVIDER_LABEL: Record<string, string> = {
  gemini: 'Gemini API',
  gemini_cli: 'Gemini CLI',
  claude_cli: 'Claude CLI',
  openai: 'OpenAI',
  ollama: 'Ollama',
  mock: 'el motor local (sin LLM)',
};
const providerLabel = (id?: string | null): string | undefined => (id ? PROVIDER_LABEL[id] ?? id : undefined);

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);

  // Active View State (Phase 1 default is 'forecast')
  const [currentView, setCurrentView] = useState<DashboardView>('forecast');
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Thesis & Assets State
  const [thesisData, setThesisData] = useState<ThesisResponse | null>(null);
  const [thesisStatus, setThesisStatus] = useState<string>('Activa');
  const [activeTickers, setActiveTickers] = useState<TickerSuggestion[]>([]);
  const [activeMacro, setActiveMacro] = useState<MacroSuggestion[]>([]);
  const [activeThesisDetail, setActiveThesisDetail] = useState<ThesisDetailResponse | null>(null);

  // Last-seen results per analysis tab, kept only for the exported report's
  // one-line verdict summaries — never re-fetched or re-rendered here.
  const [lastBacktest, setLastBacktest] = useState<BacktestResponse | null>(null);
  const [lastCorrelation, setLastCorrelation] = useState<CorrelationMatrixResponse | null>(null);
  const [lastPortfolioOptimization, setLastPortfolioOptimization] = useState<PortfolioOptimizeResponse | null>(null);

  // Time Series & Forecast State
  const [selectedSeriesId, setSelectedSeriesId] = useState<string>('NVDA');
  const [seriesData, setSeriesData] = useState<TimeSeriesData | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  // Why a FRED ID typed in "+ FRED ID" was not added (4.16).
  const [macroAddError, setMacroAddError] = useState<string | null>(null);
  // 4.16: every load that writes seriesData / forecast / seriesError takes a
  // number, and its responses are applied only while it is still the latest.
  // A request id and not AbortController: the state is only written in these
  // few places, so one check there covers every kind of request (series,
  // forecast, re-forecast), while aborting would only save the download, not
  // the backend's work (its handlers don't stop when the client goes away).
  const loadSeq = useRef(0);
  // The series load in flight, if any: a re-forecast then re-runs it instead of
  // forecasting the previous series' points.
  const pendingLoad = useRef<{ id: string; type: string; period: string } | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [fundamentals, setFundamentals] = useState<FundamentalsMetric[]>([]);
  const [lastInterpretation, setLastInterpretation] = useState<InterpretationResponse | null>(null);

  // Forecast & View Controls
  // Horizon in steps of the series, one per frequency (4.14): 12 on a monthly
  // series is 12 months. Switching between a daily and a monthly series keeps
  // each one's choice; the default is the canonical horizon of its frequency.
  const [horizonByFreq, setHorizonByFreq] = useState<Record<string, number>>({ ...CANONICAL_HORIZON });
  const frequency = seriesFrequency(seriesData?.frequency);
  const horizon = horizonByFreq[frequency];
  const [confidence, setConfidence] = useState<number>(0.95);
  const [period, setPeriod] = useState<string>('1y');
  const [isNormalized, setIsNormalized] = useState<boolean>(false);

  // On mount: only the health check. Nothing is analyzed or loaded on its own —
  // no thesis, no saved thesis, no LLM call — until the user writes a thesis,
  // picks an example, adds an asset, or opens one from "Mis Tesis".
  useEffect(() => {
    checkHealth()
      .then(setHealth)
      .catch((err) => console.warn('Backend offline or health check failed', err));
  }, []);

  // Handler for analyzing a thesis: only ever called from an explicit user
  // action ("Analizar Tesis" in ThesisBar), with the configured provider.
  const handleAnalyzeThesis = async (thesisText: string) => {
    setLoading(true);
    try {
      const resp = await analyzeThesis(thesisText);
      setThesisData(resp);
      setThesisStatus('Activa');
      setActiveTickers(resp.tickers);
      setActiveMacro(resp.macro_series);

      // Load fundamentals for tickers
      const tickerSymbols = resp.tickers.map((t) => t.symbol);
      fetchFundamentals(tickerSymbols)
        .then((f) => setFundamentals(f))
        .catch((e) => console.error(e));

      // Select first ticker by default
      const defaultId = resp.tickers[0]?.symbol || 'NVDA';
      setSelectedSeriesId(defaultId);
      await loadSeriesAndForecast(defaultId, 'equity', period, confidence);
    } catch (err) {
      console.error('Error analyzing thesis:', err);
      alert(err instanceof Error ? err.message : 'Error al analizar la tesis');
    } finally {
      setLoading(false);
    }
  };

  // Helper to load series data and trigger forecast.
  // IMPORTANT: on failure this must clear the previous seriesData/forecast, not leave
  // them in place. Leaving stale data around after switching to a series whose fetch
  // failed (e.g. a FRED macro ID with no FRED_API_KEY configured) makes the chart and
  // "Serie:" label keep showing the PREVIOUS series while the tab itself highlights as
  // selected — which looks exactly like "clicking the tab does nothing" even though
  // the click handler and state update are both working correctly.
  //
  // 4.16: a response that arrives after a newer load started is dropped, so the
  // series, its error and its forecast always come from the same load.
  const loadSeriesAndForecast = async (
    id: string,
    type: string,
    p: string,
    conf: number,
    horizons: Record<string, number> = horizonByFreq
  ) => {
    const req = ++loadSeq.current;
    pendingLoad.current = { id, type, period: p };
    setChartLoading(true);
    setSeriesError(null);
    try {
      let data: TimeSeriesData;
      if (type === 'macro' || activeMacro.some((m) => m.series_id === id)) {
        data = await fetchMacroData(id);
      } else {
        data = await fetchMarketData(id, p);
      }
      if (req !== loadSeq.current) return;
      setSeriesData(data);
      setForecast(null);

      if (data.points.length > 2) {
        const h = horizons[seriesFrequency(data.frequency)];
        const fc = await fetchForecast(data.points, h, conf, data.id, data.type);
        if (req !== loadSeq.current) return;
        setForecast(fc);
      }
    } catch (err) {
      if (req !== loadSeq.current) return;
      console.error(`Error loading series ${id}:`, err);
      setSeriesData(null);
      setForecast(null);
      setSeriesError(err instanceof Error ? err.message : `No se pudo cargar la serie ${id}`);
    } finally {
      if (req === loadSeq.current) {
        pendingLoad.current = null;
        setChartLoading(false);
      }
    }
  };

  // Switch selected series. `type` when the caller knows it: right after adding
  // a series, `activeMacro` in this closure doesn't have it yet (4.16).
  const handleSelectSeries = (id: string, type?: 'macro' | 'equity') => {
    setSelectedSeriesId(id);
    const isMacro = type ? type === 'macro' : activeMacro.some((m) => m.series_id === id);
    loadSeriesAndForecast(id, isMacro ? 'macro' : 'equity', period, confidence);
  };

  // Re-forecast the loaded series with a new horizon or level. With a series
  // load still in flight, re-run that load instead: forecasting the previous
  // series' points would show them under the newly selected tab (4.16).
  const reforecast = (horizons: Record<string, number>, conf: number) => {
    const pending = pendingLoad.current;
    if (pending) {
      loadSeriesAndForecast(pending.id, pending.type, pending.period, conf, horizons);
      return;
    }
    if (!seriesData || seriesData.points.length <= 2) return;
    const req = ++loadSeq.current;
    setChartLoading(true);
    fetchForecast(seriesData.points, horizons[seriesFrequency(seriesData.frequency)], conf, seriesData.id, seriesData.type)
      .then((fc) => {
        if (req === loadSeq.current) setForecast(fc);
      })
      .catch((e) => console.error(e))
      .finally(() => {
        if (req === loadSeq.current) setChartLoading(false);
      });
  };

  // Re-forecast on horizon change
  const handleChangeHorizon = (newHorizon: number) => {
    const horizons = { ...horizonByFreq, [frequency]: newHorizon };
    setHorizonByFreq(horizons);
    reforecast(horizons, confidence);
  };

  // Re-forecast on confidence change
  const handleChangeConfidence = (newConf: number) => {
    setConfidence(newConf);
    reforecast(horizonByFreq, newConf);
  };

  // Change historical period
  const handleChangePeriod = (newPeriod: string) => {
    setPeriod(newPeriod);
    const isMacro = activeMacro.some((m) => m.series_id === selectedSeriesId);
    loadSeriesAndForecast(selectedSeriesId, isMacro ? 'macro' : 'equity', newPeriod, confidence);
  };

  // Add ticker manually
  const handleAddTicker = (symbol: string) => {
    if (activeTickers.some((t) => t.symbol === symbol)) return;
    const newT: TickerSuggestion = {
      symbol,
      name: `${symbol} Equity`,
      sector: 'Custom Asset',
      weight: 0.1,
      thesis_role: 'Activo agregado manualmente para correlación y proyección',
    };
    const updated = [...activeTickers, newT];
    setActiveTickers(updated);
    fetchFundamentals(updated.map((t) => t.symbol)).then((f) => setFundamentals(f));
    handleSelectSeries(symbol);
  };

  // Remove ticker
  const handleRemoveTicker = (symbol: string) => {
    const updated = activeTickers.filter((t) => t.symbol !== symbol);
    setActiveTickers(updated);
    if (selectedSeriesId === symbol && updated.length > 0) {
      handleSelectSeries(updated[0].symbol);
    }
  };

  // Add a FRED series by hand (4.16). The ID is checked against FRED's own
  // /fred/series first (4.11's FRED search isn't done yet), and the series is
  // always loaded as macro: it never goes to yfinance.
  const handleAddMacro = async (rawId: string) => {
    const seriesId = rawId.trim().toUpperCase();
    setMacroAddError(null);
    if (!seriesId || activeMacro.some((m) => m.series_id === seriesId)) return;
    const seqAtStart = loadSeq.current;
    try {
      await fetchFredMetadata(seriesId);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'fred_series_not_found') {
        setMacroAddError(err.message);
        return;
      }
      // FRED couldn't be asked (no key, network): that doesn't show the ID is
      // wrong. It is added, and loading it says what failed.
    }
    const newM: MacroSuggestion = {
      series_id: seriesId,
      name: `FRED ${seriesId}`,
      category: 'Macro Indicator',
      expected_correlation: 'Positive',
    };
    setActiveMacro((prev) => (prev.some((m) => m.series_id === seriesId) ? prev : [...prev, newM]));
    // If the user started another load while this ID was being checked, that
    // one is the latest and stays on screen.
    if (loadSeq.current === seqAtStart) handleSelectSeries(seriesId, 'macro');
  };

  // Remove macro series
  const handleRemoveMacro = (seriesId: string) => {
    const updated = activeMacro.filter((m) => m.series_id !== seriesId);
    setActiveMacro(updated);
    if (selectedSeriesId === seriesId) {
      const fallbackId = activeTickers[0]?.symbol || 'NVDA';
      handleSelectSeries(fallbackId);
    }
  };

  // Shared hydration for a persisted thesis (SQLite) — used both by the mount-time
  // bootstrap (loading the last saved thesis, no LLM call) and by the drawer's
  // "load saved thesis" action. Never calls a real or mock LLM: the data already
  // exists in the database.
  const loadThesisDetailIntoState = (detail: ThesisDetailResponse) => {
    setThesisData({
      thesis: detail.prompt,
      summary: detail.summary,
      tickers: detail.tickers,
      macro_series: detail.macro_series,
      rationales: detail.rationales,
      mechanism: detail.mechanism,
      falsifiers: detail.falsifiers,
      benchmark: detail.benchmark,
      prompt_version: detail.prompt_version,
      provider_used: 'sqlite-repository',
    });
    setThesisStatus(detail.status);
    setActiveTickers(detail.tickers);
    setActiveMacro(detail.macro_series);
    setActiveThesisDetail(detail);

    const tickerSymbols = detail.tickers.map((t) => t.symbol);
    fetchFundamentals(tickerSymbols)
      .then((f) => setFundamentals(f))
      .catch((e) => console.error(e));

    const firstSym = detail.tickers[0]?.symbol || 'NVDA';
    handleSelectSeries(firstSym);
  };

  // Restore saved thesis from drawer
  const handleLoadThesisFromDrawer = (detail: ThesisDetailResponse) => {
    loadThesisDetailIntoState(detail);
    setCurrentView('forecast');
  };

  // Export executive report
  // The level the engine actually delivered (TimesFM only has an 80% band),
  // which is what gets displayed and recorded; `confidence` stays the request.
  const intervalLevel = forecast?.interval_level ?? confidence;

  const handleExport = () => {
    exportMarkdownReport({
      thesis: thesisData,
      seriesData,
      forecast,
      fundamentals,
      interpretation: lastInterpretation,
      horizon,
      confidence: intervalLevel,
      lastBacktest,
      lastCorrelation,
      lastPortfolioOptimization,
    });
  };

  // List of all active series for selector pills
  const allSeriesList = [
    ...activeTickers.map((t) => ({ id: t.symbol, name: t.name, type: 'equity' })),
    ...activeMacro.map((m) => ({ id: m.series_id, name: m.name, type: 'macro' })),
  ];

  const isSyntheticActive = !!seriesData && seriesData.source === 'synthetic';
  // Nothing to analyze yet: every view shows the empty state instead of
  // components that assume a thesis, a series or a forecast.
  const isEmpty = !thesisData && activeTickers.length === 0 && activeMacro.length === 0;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        health={health}
        loading={loading || chartLoading}
        currentView={currentView}
        onChangeView={setCurrentView}
        onOpenThesesDrawer={() => setIsDrawerOpen(true)}
        onExportReport={handleExport}
        canExport={!isEmpty}
        isSyntheticActive={isSyntheticActive}
        onLLMProviderChanged={(provider) => setHealth((h) => (h ? { ...h, llm_provider: provider } : h))}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Series Fetch Error Banner — shown when switching "Serie Activa" fails
            (e.g. a FRED macro series with no FRED_API_KEY configured) instead of
            silently leaving the previous series' chart on screen. */}
        {seriesError && (
          <div className="rounded-2xl p-4 bg-red-950/40 border border-red-500/40 shadow-xl flex items-start gap-3 text-red-200">
            <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              <span className="font-bold text-red-300 uppercase tracking-wide">
                No se pudo cargar la serie {selectedSeriesId}
              </span>
              <p className="text-slate-300 leading-relaxed text-[11px]">{humanizeSeriesError(seriesError)}</p>
            </div>
          </div>
        )}

        {/* Synthetic Data Transparency Alert Banner */}
        {isSyntheticActive && (
          <div className="rounded-2xl p-4 bg-amber-950/40 border border-amber-500/40 shadow-xl flex items-start gap-3 text-amber-200">
            <AlertTriangle className="h-5 w-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="text-xs space-y-1">
              <div className="flex items-center space-x-2">
                <span className="font-bold text-amber-300 uppercase tracking-wide">
                  Datos Sintéticos / No Verificados
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-200 border border-amber-500/30">
                  Modo Contingencia
                </span>
              </div>
              <p className="text-slate-300 leading-relaxed text-[11px]">
                La serie actual <strong className="text-white font-mono">{seriesData?.id}</strong> proviene de un generador sintético o de referencia ({seriesData?.source_detail || 'sin conexión de datos reales'}). Los módulos de <strong>Reality Check (Backtesting)</strong> y <strong>Matrices de Correlación</strong> han sido inhabilitados para proteger la integridad cuantitativa de la tesis.
              </p>
            </div>
          </div>
        )}

        {/* Quantitative Stress Alert Banner */}
        <ThesisAlertBanner
          seriesData={seriesData}
          forecast={forecast}
          thesisStatus={thesisStatus}
        />

        {/* Thesis Input & Asset Chips Section */}
        <ThesisBar
          onAnalyze={handleAnalyzeThesis}
          loading={loading}
          tickers={activeTickers}
          macroSeries={activeMacro}
          onAddTicker={handleAddTicker}
          onRemoveTicker={handleRemoveTicker}
          onAddMacro={handleAddMacro}
          macroAddError={macroAddError}
          providerLabel={providerLabel(health?.llm_provider)}
          onRemoveMacro={handleRemoveMacro}
        />

        {/* ============================================================ */}
        {/* VIEW 1: DASHBOARD PRINCIPAL Y PROYECCIÓN (Default Phase 1) */}
        {/* ============================================================ */}
        {isEmpty && <EmptyState view={currentView} />}

        {!isEmpty && currentView === 'forecast' && (
          <div className="space-y-6">
            {/* Quantitative KPI Metrics & AI Synthesis */}
            <MetricCards
              thesisData={thesisData}
              forecast={forecast}
              seriesData={seriesData}
              horizon={horizon}
              confidence={intervalLevel}
            />

            {/* Main Line & Forecast Chart */}
            <ForecastChart
              seriesData={seriesData}
              seriesError={seriesError}
              forecast={forecast}
              hasFredKey={health?.has_fred_key ?? true}
              selectedSeriesId={selectedSeriesId}
              allSeriesList={allSeriesList}
              onSelectSeries={handleSelectSeries}
              horizon={horizon}
              onChangeHorizon={handleChangeHorizon}
              confidence={confidence}
              intervalLevel={intervalLevel}
              onChangeConfidence={handleChangeConfidence}
              period={period}
              onChangePeriod={handleChangePeriod}
              isNormalized={isNormalized}
              onToggleNormalized={() => setIsNormalized(!isNormalized)}
              loading={chartLoading}
            />

            {/* 1. Componente Telemetría y Resumen Estadístico (Descriptivo / Puro dato) */}
            <StatisticalTelemetry
              seriesData={seriesData}
              forecast={forecast}
              horizon={horizon}
              confidence={intervalLevel}
            />

            {/* 2. Componente Copiloto / Intérprete de Tesis (Asistente LLM) */}
            <ThesisCopilot
              thesis={thesisData?.thesis || ''}
              activeSeriesId={selectedSeriesId}
              seriesData={seriesData}
              forecast={forecast}
              horizon={horizon}
              confidence={intervalLevel}
              activeTickers={activeTickers}
              activeMacro={activeMacro}
              fundamentals={fundamentals}
              onSelectSeries={handleSelectSeries}
              onInterpretationComplete={setLastInterpretation}
            />

            {/* Multi-Chart Analytics Row: Fundamentals Bar Chart & Sector Donut */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <div className="lg:col-span-7">
                <FundBarChart metrics={fundamentals} loading={loading} />
              </div>
              <div className="lg:col-span-5">
                <ExposureDonut tickers={activeTickers} />
              </div>
            </div>
          </div>
        )}

        {/* ============================================================ */}
        {/* VIEW 2: REALITY CHECK / BACKTESTING                          */}
        {/* ============================================================ */}
        {!isEmpty && currentView === 'backtest' && (
          <BacktestPanel
            seriesData={seriesData}
            activeSeriesId={selectedSeriesId}
            onResult={setLastBacktest}
          />
        )}

        {/* ============================================================ */}
        {/* VIEW 3: MATRIZ DE CORRELACIÓN MULTISERIE & HEATMAP           */}
        {/* ============================================================ */}
        {!isEmpty && currentView === 'correlation' && (
          <CorrelationHeatmap
            activeTickers={activeTickers}
            activeMacro={activeMacro}
            onResult={setLastCorrelation}
          />
        )}

        {/* ============================================================ */}
        {/* VIEW 4: GRÁFICO COMPARATIVO DUAL-AXIS                        */}
        {/* ============================================================ */}
        {!isEmpty && currentView === 'dual' && (
          <DualAxisChart
            primarySeriesData={seriesData}
            allAvailableSeries={allSeriesList}
          />
        )}

        {/* ============================================================ */}
        {/* VIEW 5: ASIGNACIÓN Y RIESGO (Markowitz, ERC & Monte Carlo)    */}
        {/* ============================================================ */}
        {!isEmpty && currentView === 'risk' && (
          <PortfolioRiskView
            activeThesis={activeThesisDetail}
            suggestedTickers={activeTickers}
            isSyntheticActive={isSyntheticActive}
            onOptimizeResult={setLastPortfolioOptimization}
          />
        )}
      </main>

      {/* Persistent Theses Drawer Modal */}
      <ThesesDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        currentPrompt={thesisData?.thesis || ''}
        currentSummary={thesisData?.summary || ''}
        currentTickers={activeTickers}
        currentMacro={activeMacro}
        currentRationales={thesisData?.rationales || {}}
        currentAnalysis={{
          mechanism: thesisData?.mechanism,
          falsifiers: thesisData?.falsifiers,
          benchmark: thesisData?.benchmark,
          prompt_version: thesisData?.prompt_version,
        }}
        activeSeriesId={selectedSeriesId}
        seriesData={seriesData}
        forecast={forecast}
        horizon={horizon}
        confidence={intervalLevel}
        onLoadThesis={handleLoadThesisFromDrawer}
      />

      <footer className="border-t border-slate-900 bg-slate-950/80 py-4 text-center text-xs text-slate-600 font-mono">
        TimeInvestor Quantitative Platform • v2.0 Local Core • TimesFM PyTorch Adapter • SQLite Persistence • Backtesting Engine
      </footer>
    </div>
  );
};

export default App;
