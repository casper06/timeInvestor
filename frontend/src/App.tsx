import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import type { DashboardView } from './components/Header';
import { ThesisBar } from './components/ThesisBar';
import { ForecastChart } from './components/ForecastChart';
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
import { exportMarkdownReport } from './utils/exportReport';

import {
  checkHealth,
  analyzeThesis,
  fetchMarketData,
  fetchMacroData,
  fetchFundamentals,
  fetchForecast,
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
} from './services/api';

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

  // Time Series & Forecast State
  const [selectedSeriesId, setSelectedSeriesId] = useState<string>('NVDA');
  const [seriesData, setSeriesData] = useState<TimeSeriesData | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [fundamentals, setFundamentals] = useState<FundamentalsMetric[]>([]);
  const [lastInterpretation, setLastInterpretation] = useState<InterpretationResponse | null>(null);

  // Forecast & View Controls
  const [horizon, setHorizon] = useState<number>(60);
  const [confidence, setConfidence] = useState<number>(0.95);
  const [period, setPeriod] = useState<string>('1y');
  const [isNormalized, setIsNormalized] = useState<boolean>(false);

  // Load health check and initial default thesis on mount
  useEffect(() => {
    async function init() {
      try {
        const h = await checkHealth();
        setHealth(h);
      } catch (err) {
        console.warn('Backend offline or health check failed', err);
      }
      handleAnalyzeThesis('Demanda eléctrica por centros de datos de IA');
    }
    init();
  }, []);

  // Handler for analyzing a new thesis
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
      await loadSeriesAndForecast(defaultId, 'equity', period, horizon, confidence);
    } catch (err) {
      console.error('Error analyzing thesis:', err);
      alert(err instanceof Error ? err.message : 'Error al analizar la tesis');
    } finally {
      setLoading(false);
    }
  };

  // Helper to load series data and trigger forecast
  const loadSeriesAndForecast = async (
    id: string,
    type: string,
    p: string,
    h: number,
    conf: number
  ) => {
    setChartLoading(true);
    try {
      let data: TimeSeriesData;
      if (type === 'macro' || activeMacro.some((m) => m.series_id === id)) {
        data = await fetchMacroData(id);
      } else {
        data = await fetchMarketData(id, p);
      }
      setSeriesData(data);

      if (data.points.length > 2) {
        const fc = await fetchForecast(data.points, h, conf, 'D');
        setForecast(fc);
      }
    } catch (err) {
      console.error(`Error loading series ${id}:`, err);
    } finally {
      setChartLoading(false);
    }
  };

  // Switch selected series
  const handleSelectSeries = (id: string) => {
    setSelectedSeriesId(id);
    const isMacro = activeMacro.some((m) => m.series_id === id);
    loadSeriesAndForecast(id, isMacro ? 'macro' : 'equity', period, horizon, confidence);
  };

  // Re-forecast on horizon change
  const handleChangeHorizon = (newHorizon: number) => {
    setHorizon(newHorizon);
    if (seriesData && seriesData.points.length > 2) {
      setChartLoading(true);
      fetchForecast(seriesData.points, newHorizon, confidence, 'D')
        .then((fc) => setForecast(fc))
        .catch((e) => console.error(e))
        .finally(() => setChartLoading(false));
    }
  };

  // Re-forecast on confidence change
  const handleChangeConfidence = (newConf: number) => {
    setConfidence(newConf);
    if (seriesData && seriesData.points.length > 2) {
      setChartLoading(true);
      fetchForecast(seriesData.points, horizon, newConf, 'D')
        .then((fc) => setForecast(fc))
        .catch((e) => console.error(e))
        .finally(() => setChartLoading(false));
    }
  };

  // Change historical period
  const handleChangePeriod = (newPeriod: string) => {
    setPeriod(newPeriod);
    const isMacro = activeMacro.some((m) => m.series_id === selectedSeriesId);
    loadSeriesAndForecast(selectedSeriesId, isMacro ? 'macro' : 'equity', newPeriod, horizon, confidence);
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

  // Add macro series manually
  const handleAddMacro = (seriesId: string) => {
    if (activeMacro.some((m) => m.series_id === seriesId)) return;
    const newM: MacroSuggestion = {
      series_id: seriesId,
      name: `FRED ${seriesId}`,
      category: 'Macro Indicator',
      expected_correlation: 'Positive',
    };
    setActiveMacro([...activeMacro, newM]);
    handleSelectSeries(seriesId);
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

  // Restore saved thesis from drawer
  const handleLoadThesisFromDrawer = (detail: ThesisDetailResponse) => {
    setThesisData({
      thesis: detail.prompt,
      summary: detail.summary,
      tickers: detail.tickers,
      macro_series: detail.macro_series,
      rationales: detail.rationales,
      provider_used: 'sqlite-repository',
    });
    setThesisStatus(detail.status);
    setActiveTickers(detail.tickers);
    setActiveMacro(detail.macro_series);

    const tickerSymbols = detail.tickers.map((t) => t.symbol);
    fetchFundamentals(tickerSymbols)
      .then((f) => setFundamentals(f))
      .catch((e) => console.error(e));

    const firstSym = detail.tickers[0]?.symbol || 'NVDA';
    handleSelectSeries(firstSym);
    setCurrentView('forecast');
  };

  // Export executive report
  const handleExport = () => {
    exportMarkdownReport({
      thesis: thesisData,
      seriesData,
      forecast,
      fundamentals,
      interpretation: lastInterpretation,
      horizon,
      confidence,
    });
  };

  // List of all active series for selector pills
  const allSeriesList = [
    ...activeTickers.map((t) => ({ id: t.symbol, name: t.name, type: 'equity' })),
    ...activeMacro.map((m) => ({ id: m.series_id, name: m.name, type: 'macro' })),
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        health={health}
        loading={loading || chartLoading}
        currentView={currentView}
        onChangeView={setCurrentView}
        onOpenThesesDrawer={() => setIsDrawerOpen(true)}
        onExportReport={handleExport}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
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
          onRemoveMacro={handleRemoveMacro}
        />

        {/* ============================================================ */}
        {/* VIEW 1: DASHBOARD PRINCIPAL Y PROYECCIÓN (Default Phase 1) */}
        {/* ============================================================ */}
        {currentView === 'forecast' && (
          <div className="space-y-6">
            {/* Quantitative KPI Metrics & AI Synthesis */}
            <MetricCards
              thesisData={thesisData}
              forecast={forecast}
              seriesData={seriesData}
              horizon={horizon}
              confidence={confidence}
            />

            {/* Main Line & Forecast Chart */}
            <ForecastChart
              seriesData={seriesData}
              forecast={forecast}
              selectedSeriesId={selectedSeriesId}
              allSeriesList={allSeriesList}
              onSelectSeries={handleSelectSeries}
              horizon={horizon}
              onChangeHorizon={handleChangeHorizon}
              confidence={confidence}
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
              confidence={confidence}
            />

            {/* 2. Componente Copiloto / Intérprete de Tesis (Asistente LLM) */}
            <ThesisCopilot
              thesis={thesisData?.thesis || 'Demanda eléctrica por centros de datos de IA'}
              activeSeriesId={selectedSeriesId}
              seriesData={seriesData}
              forecast={forecast}
              horizon={horizon}
              confidence={confidence}
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
        {currentView === 'backtest' && (
          <BacktestPanel
            seriesData={seriesData}
            activeSeriesId={selectedSeriesId}
          />
        )}

        {/* ============================================================ */}
        {/* VIEW 3: MATRIZ DE CORRELACIÓN MULTISERIE & HEATMAP           */}
        {/* ============================================================ */}
        {currentView === 'correlation' && (
          <CorrelationHeatmap
            activeTickers={activeTickers}
            activeMacro={activeMacro}
          />
        )}

        {/* ============================================================ */}
        {/* VIEW 4: GRÁFICO COMPARATIVO DUAL-AXIS                        */}
        {/* ============================================================ */}
        {currentView === 'dual' && (
          <DualAxisChart
            primarySeriesData={seriesData}
            allAvailableSeries={allSeriesList}
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
        activeSeriesId={selectedSeriesId}
        seriesData={seriesData}
        forecast={forecast}
        horizon={horizon}
        confidence={confidence}
        onLoadThesis={handleLoadThesisFromDrawer}
      />

      <footer className="border-t border-slate-900 bg-slate-950/80 py-4 text-center text-xs text-slate-600 font-mono">
        TimeInvestor Quantitative Platform • v2.0 Local Core • TimesFM PyTorch Adapter • SQLite Persistence • Backtesting Engine
      </footer>
    </div>
  );
};

export default App;
