import React, { useState } from 'react';
import {
  Chart as ChartJS,
  ArcElement,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Doughnut, Bar } from 'react-chartjs-2';
import {
  PieChart,
  ShieldAlert,
  AlertTriangle,
  Play,
  RotateCcw,
  CheckCircle2,
  Sliders,
  DollarSign,
  Activity,
  Layers,
  Info,
} from 'lucide-react';
import {
  optimizePortfolio,
  evaluatePortfolioRisk,
  type PortfolioOptimizeResponse,
  type PortfolioRiskResponse,
  type TickerSuggestion,
  type ThesisDetailResponse,
  updateThesis,
} from '../services/api';

ChartJS.register(ArcElement, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

interface PortfolioRiskViewProps {
  activeThesis: ThesisDetailResponse | null;
  suggestedTickers: TickerSuggestion[];
  isSyntheticActive?: boolean;
  onRefreshThesis?: () => void;
}

export const PortfolioRiskView: React.FC<PortfolioRiskViewProps> = ({
  activeThesis,
  suggestedTickers,
  isSyntheticActive = false,
  onRefreshThesis,
}) => {
  // Initial tickers from active thesis or suggestions
  const initialTickers =
    activeThesis && activeThesis.tickers.length >= 2
      ? activeThesis.tickers.map((t) => t.symbol)
      : suggestedTickers.length >= 2
      ? suggestedTickers.map((t) => t.symbol)
      : ['NVDA', 'MSFT', 'GOOGL', 'AMZN'];

  const initialWeightsMap: Record<string, number> = {};
  if (activeThesis && activeThesis.tickers.length > 0) {
    activeThesis.tickers.forEach((t) => {
      initialWeightsMap[t.symbol] = t.weight;
    });
  } else if (suggestedTickers.length > 0) {
    suggestedTickers.forEach((t) => {
      initialWeightsMap[t.symbol] = t.weight;
    });
  } else {
    initialTickers.forEach((t) => {
      initialWeightsMap[t] = 1.0 / initialTickers.length;
    });
  }

  // State
  const [tickers, setTickers] = useState<string[]>(initialTickers);
  const [tickerInput, setTickerInput] = useState('');
  const [period, setPeriod] = useState<string>('2y');
  const [maxWeight, setMaxWeight] = useState<number>(0.35);
  const [riskFreeRate, setRiskFreeRate] = useState<number>(0.045);
  const [muMethod, setMuMethod] = useState<'historical_shrunk' | 'equal' | 'forecast'>('historical_shrunk');
  const [covMethod, setCovMethod] = useState<'ledoit_wolf' | 'sample'>('ledoit_wolf');
  const [selectedStrategy, setSelectedStrategy] = useState<'max_sharpe' | 'risk_parity' | 'equal_weight' | 'current'>('max_sharpe');

  // Optimization output state
  const [optimizing, setOptimizing] = useState(false);
  const [optResult, setOptResult] = useState<PortfolioOptimizeResponse | null>(null);
  const [optError, setOptError] = useState<string | null>(null);

  // Risk state
  const [riskHorizon, setRiskHorizon] = useState<number>(30);
  const [initialCapital, setInitialCapital] = useState<number>(100000);
  const [simMethod, setSimMethod] = useState<'bootstrap' | 'student_t' | 'gaussian'>('bootstrap');
  const [simulating, setSimulating] = useState(false);
  const [riskResult, setRiskResult] = useState<PortfolioRiskResponse | null>(null);
  const [riskError, setRiskError] = useState<string | null>(null);

  // Success message when weights are applied
  const [applySuccess, setApplySuccess] = useState<string | null>(null);

  // Palette
  const palette = ['#06b6d4', '#6366f1', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#3b82f6', '#14b8a6'];

  // Add / remove ticker
  const handleAddTicker = () => {
    const sym = tickerInput.trim().toUpperCase();
    if (sym && !tickers.includes(sym)) {
      setTickers([...tickers, sym]);
      setTickerInput('');
    }
  };

  const handleRemoveTicker = (sym: string) => {
    if (tickers.length > 2) {
      setTickers(tickers.filter((t) => t !== sym));
    }
  };

  // Run Optimization
  const handleOptimize = async () => {
    if (tickers.length < 2) {
      setOptError('Se requieren al menos 2 activos para optimizar.');
      return;
    }
    setOptimizing(true);
    setOptError(null);
    setApplySuccess(null);

    try {
      const res = await optimizePortfolio({
        tickers,
        current_weights: initialWeightsMap,
        period,
        cov_method: covMethod,
        mu_method: muMethod,
        max_weight: maxWeight,
        risk_free_rate: riskFreeRate,
      });
      setOptResult(res);
      // If no risk run yet, auto-simulate risk on the optimal portfolio
      handleSimulateRisk(res.portfolios.max_sharpe.weights);
    } catch (err: any) {
      setOptError(err.message || 'Error en la optimización.');
    } finally {
      setOptimizing(false);
    }
  };

  // Run Risk Simulation
  const handleSimulateRisk = async (weightsToUse?: Record<string, number>) => {
    const weights =
      weightsToUse ||
      (optResult
        ? optResult.portfolios[selectedStrategy].weights
        : initialWeightsMap);

    setSimulating(true);
    setRiskError(null);

    try {
      const res = await evaluatePortfolioRisk({
        tickers,
        weights,
        horizon_days: riskHorizon,
        initial_capital: initialCapital,
        method: simMethod,
        n_simulations: 10000,
      });
      setRiskResult(res);
    } catch (err: any) {
      setRiskError(err.message || 'Error en la simulación de riesgo.');
    } finally {
      setSimulating(false);
    }
  };

  // Apply weights to active thesis in SQLite
  const handleApplyToThesis = async () => {
    if (!activeThesis || !optResult) return;
    const selectedWeights = optResult.portfolios[selectedStrategy].weights;

    try {
      const updatedTickers: TickerSuggestion[] = Object.entries(selectedWeights).map(([sym, w]) => {
        const existing = activeThesis.tickers.find((t) => t.symbol === sym);
        return {
          symbol: sym,
          name: existing?.name || sym,
          weight: w,
          sector: existing?.sector || 'General',
          thesis_role: existing?.thesis_role || 'Core asset',
        };
      });

      await updateThesis(activeThesis.id, {
        tickers: updatedTickers,
      });

      setApplySuccess(`Pesos de ${optResult.portfolios[selectedStrategy].name} aplicados a la tesis.`);
      if (onRefreshThesis) onRefreshThesis();
      setTimeout(() => setApplySuccess(null), 4000);
    } catch (err: any) {
      setOptError(`Error al sincronizar con SQLite: ${err.message}`);
    }
  };

  // Active portfolio summary to display
  const currentSummary = optResult ? optResult.portfolios[selectedStrategy] : null;

  // Doughnut chart data
  const doughnutData = currentSummary
    ? {
        labels: Object.keys(currentSummary.weights),
        datasets: [
          {
            data: Object.values(currentSummary.weights).map((w) => Math.round(w * 100)),
            backgroundColor: palette.slice(0, tickers.length),
            borderColor: '#0f172a',
            borderWidth: 2,
          },
        ],
      }
    : null;

  // Risk contribution chart data
  const rcData = currentSummary
    ? {
        labels: Object.keys(currentSummary.risk_contribution_pct),
        datasets: [
          {
            label: '% Contribución al Riesgo',
            data: Object.values(currentSummary.risk_contribution_pct),
            backgroundColor: palette.slice(0, tickers.length).map((c) => c + 'cc'),
            borderColor: palette.slice(0, tickers.length),
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      }
    : null;

  // Histogram chart data
  const histogramData = riskResult
    ? {
        labels: riskResult.histogram.bin_edges.slice(0, -1).map((e, idx) => {
          const next = riskResult.histogram.bin_edges[idx + 1];
          return `${(e * 100).toFixed(1)}% a ${(next * 100).toFixed(1)}%`;
        }),
        datasets: [
          {
            label: 'Frecuencia (Caminos simulados)',
            data: riskResult.histogram.frequencies,
            backgroundColor: riskResult.histogram.bin_edges.slice(0, -1).map((e) => {
              const var95 = riskResult.metrics['95%']?.var_pct || 0;
              // If return is worse than -VaR_95, flag in crimson/red
              return e < -var95 ? '#ef4444' : '#06b6d4';
            }),
            borderRadius: 4,
          },
        ],
      }
    : null;

  return (
    <div className="space-y-6 animate-fadeIn pb-12">
      {/* Header Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-6 backdrop-blur-md shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <PieChart className="h-5 w-5" />
            </span>
            <h2 className="text-xl font-bold text-white tracking-tight">
              Asignación Óptima y Gestión Cuantitativa de Riesgo
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Optimización convexa Markowitz (Máx. Sharpe), Paridad de Riesgo (Spinu ERC) y simulación Monte Carlo con colas empíricas.
          </p>
        </div>

        {/* Tickers Pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          {tickers.map((sym, idx) => (
            <span
              key={sym}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono font-medium border"
              style={{
                backgroundColor: `${palette[idx % palette.length]}15`,
                borderColor: `${palette[idx % palette.length]}40`,
                color: palette[idx % palette.length],
              }}
            >
              {sym}
              {tickers.length > 2 && (
                <button
                  onClick={() => handleRemoveTicker(sym)}
                  className="hover:text-red-400 text-[10px] ml-0.5 cursor-pointer"
                  title="Eliminar activo"
                >
                  ×
                </button>
              )}
            </span>
          ))}

          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="+ Ticker"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddTicker()}
              className="w-20 px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded-lg text-white font-mono placeholder:text-slate-500 focus:outline-none focus:border-cyan-500"
            />
            <button
              onClick={handleAddTicker}
              className="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 cursor-pointer"
            >
              +
            </button>
          </div>
        </div>
      </div>

      {/* Synthetic Block Warning */}
      {isSyntheticActive && (
        <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span>
            <strong>Modo Sintético Activo:</strong> La optimización de cartera y el cálculo de VaR/CVaR están deshabilitados porque requieren observaciones empíricas reales.
          </span>
        </div>
      )}

      {/* Grid: 2 Columns (Left: Allocation, Right: Risk Simulation) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* ========================================================================= */}
        {/* LEFT COLUMN: ALLOCATION & OPTIMIZATION (Col 7) */}
        {/* ========================================================================= */}
        <div className="lg:col-span-7 space-y-6">
          {/* Controls Card */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Sliders className="h-4 w-4 text-cyan-400" />
                <span>Parámetros de Optimización</span>
              </div>
              <button
                onClick={handleOptimize}
                disabled={optimizing || isSyntheticActive}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/20 disabled:opacity-50 cursor-pointer transition-all"
              >
                {optimizing ? (
                  <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                <span>{optimizing ? 'Optimizando...' : 'Optimizar Cartera'}</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
              {/* Historical Period */}
              <div>
                <label className="block text-slate-400 mb-1">Período Histórico</label>
                <select
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="1y">1 año (252d)</option>
                  <option value="2y">2 años (504d)</option>
                  <option value="5y">5 años (1260d)</option>
                </select>
              </div>

              {/* Covariance Method */}
              <div>
                <label className="block text-slate-400 mb-1">Matriz Covarianza</label>
                <select
                  value={covMethod}
                  onChange={(e) => setCovMethod(e.target.value as any)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="ledoit_wolf">Ledoit-Wolf (Shrinkage)</option>
                  <option value="sample">Muestral Clásica</option>
                </select>
              </div>

              {/* Expected Returns Method */}
              <div>
                <label className="block text-slate-400 mb-1">Retorno Esperado (μ)</label>
                <select
                  value={muMethod}
                  onChange={(e) => setMuMethod(e.target.value as any)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="historical_shrunk">James-Stein (Shrunk)</option>
                  <option value="equal">Mínima Varianza (Igual)</option>
                  <option value="forecast">Proyección TimesFM</option>
                </select>
              </div>

              {/* Max Weight Slider */}
              <div>
                <div className="flex justify-between text-slate-400 mb-1">
                  <span>Peso Máx. (w_max)</span>
                  <span className="font-mono text-cyan-400">{Math.round(maxWeight * 100)}%</span>
                </div>
                <input
                  type="range"
                  min="0.15"
                  max="0.80"
                  step="0.05"
                  value={maxWeight}
                  onChange={(e) => setMaxWeight(parseFloat(e.target.value))}
                  className="w-full accent-cyan-500 cursor-pointer"
                />
              </div>

              {/* Risk Free Rate */}
              <div>
                <label className="block text-slate-400 mb-1">Tasa Libre Riesgo (Rf)</label>
                <div className="flex items-center bg-slate-800 border border-slate-700 rounded-xl px-2 py-1.5">
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="15"
                    value={riskFreeRate * 100}
                    onChange={(e) => setRiskFreeRate(parseFloat(e.target.value || '0') / 100.0)}
                    className="w-full bg-transparent text-slate-200 font-mono text-xs focus:outline-none"
                  />
                  <span className="text-slate-500 text-[10px]">%</span>
                </div>
              </div>
            </div>

            {/* Warning if forecast mu */}
            {muMethod === 'forecast' && (
              <div className="text-[11px] p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 flex items-center gap-2">
                <Info className="h-4 w-4 shrink-0" />
                <span>Michaud (1989): Proyectar retornos mediante series temporales como μ en Markowitz amplifica significativamente el error de estimación.</span>
              </div>
            )}
          </div>

          {optError && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-2xl text-red-400 text-xs">
              {optError}
            </div>
          )}

          {/* Allocation Results Tabs & Visualization */}
          {optResult ? (
            <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
                <div className="flex space-x-1 bg-slate-950/60 p-1 rounded-xl border border-slate-800 text-xs">
                  <button
                    onClick={() => setSelectedStrategy('max_sharpe')}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                      selectedStrategy === 'max_sharpe'
                        ? 'bg-cyan-600 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Máx. Sharpe
                  </button>
                  <button
                    onClick={() => setSelectedStrategy('risk_parity')}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                      selectedStrategy === 'risk_parity'
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Risk Parity (ERC)
                  </button>
                  <button
                    onClick={() => setSelectedStrategy('equal_weight')}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                      selectedStrategy === 'equal_weight'
                        ? 'bg-emerald-600 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    1/K Equiponderada
                  </button>
                  <button
                    onClick={() => setSelectedStrategy('current')}
                    className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                      selectedStrategy === 'current'
                        ? 'bg-slate-700 text-white shadow-sm'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Actual
                  </button>
                </div>

                {/* Ledoit-Wolf Shrinkage Telemetry Badge */}
                <div className="flex items-center gap-2 text-[11px] text-slate-400">
                  <span className="px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700 font-mono">
                    Shrinkage δ*: <span className="text-cyan-400 font-bold">{optResult.shrinkage_intensity}</span>
                  </span>
                  <span className="px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700 font-mono">
                    Cond #: <span className="text-amber-400 font-bold">{optResult.condition_number}</span>
                  </span>
                </div>
              </div>

              {/* Chart & Weights Breakdown */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-center">
                <div className="h-[220px] flex items-center justify-center">
                  {doughnutData && (
                    <Doughnut
                      data={doughnutData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: { position: 'bottom', labels: { color: '#94a3b8', boxWidth: 10, font: { size: 10 } } },
                        },
                      }}
                    />
                  )}
                </div>

                {/* Weights table */}
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-slate-300">Ponderaciones Asignadas:</span>
                  <div className="space-y-1.5">
                    {currentSummary &&
                      Object.entries(currentSummary.weights).map(([sym, w], idx) => (
                        <div key={sym} className="flex items-center justify-between text-xs p-1.5 rounded-lg bg-slate-800/40">
                          <span className="font-mono font-semibold" style={{ color: palette[idx % palette.length] }}>
                            {sym}
                          </span>
                          <div className="flex items-center gap-3">
                            <span className="text-slate-400 font-mono">{(w * 100).toFixed(1)}%</span>
                            <div className="w-20 bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.min(w * 100, 100)}%`,
                                  backgroundColor: palette[idx % palette.length],
                                }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>

              {/* Comparative Metrics Table across Portfolios */}
              <div className="overflow-x-auto border-t border-slate-800 pt-4">
                <span className="text-xs font-semibold text-slate-300 mb-2 block">Comparativa de Estrategias:</span>
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="pb-2">Estrategia</th>
                      <th className="pb-2">Ret. Anual</th>
                      <th className="pb-2">Volatilidad</th>
                      <th className="pb-2">Sharpe</th>
                      <th className="pb-2">Max Drawdown</th>
                      <th className="pb-2">Diversif.</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {Object.entries(optResult.portfolios).map(([key, p]) => {
                      const isSelected = key === selectedStrategy;
                      return (
                        <tr
                          key={key}
                          onClick={() => setSelectedStrategy(key as any)}
                          className={`hover:bg-slate-800/30 cursor-pointer transition-colors ${
                            isSelected ? 'bg-cyan-500/10 text-cyan-300 font-semibold' : 'text-slate-300'
                          }`}
                        >
                          <td className="py-2.5 font-sans flex items-center gap-1.5">
                            {isSelected && <CheckCircle2 className="h-3 w-3 text-cyan-400" />}
                            <span>{p.name}</span>
                          </td>
                          <td className="py-2.5">{(p.expected_return * 100).toFixed(1)}%</td>
                          <td className="py-2.5">{(p.volatility * 100).toFixed(1)}%</td>
                          <td className="py-2.5 text-emerald-400">{p.sharpe_ratio.toFixed(2)}</td>
                          <td className="py-2.5 text-red-400">{(p.max_drawdown * 100).toFixed(1)}%</td>
                          <td className="py-2.5">{p.diversification_ratio?.toFixed(2) || '1.00'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Risk Contribution Chart */}
              <div className="border-t border-slate-800 pt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-300">
                    Contribución Marginal al Riesgo Total (% RC_i):
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {selectedStrategy === 'risk_parity'
                      ? 'Paridad perfecta: cada activo aporta exactamente 1/K al riesgo'
                      : 'Revela si algún activo domina desproporcionadamente la varianza'}
                  </span>
                </div>
                <div className="h-[140px]">
                  {rcData && (
                    <Bar
                      data={rcData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                          y: {
                            ticks: { color: '#94a3b8', font: { size: 10 } },
                            grid: { color: '#1e293b' },
                          },
                          x: {
                            ticks: { color: '#94a3b8', font: { size: 10 } },
                            grid: { display: false },
                          },
                        },
                      }}
                    />
                  )}
                </div>
              </div>

              {/* Action: Apply weights to Thesis */}
              {activeThesis && (
                <div className="flex items-center justify-between pt-2 border-t border-slate-800">
                  <span className="text-xs text-slate-400">
                    ¿Desea aplicar la cartera seleccionada a su tesis activa?
                  </span>
                  <button
                    onClick={handleApplyToThesis}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors shadow-sm cursor-pointer"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span>Aplicar pesos a la tesis</span>
                  </button>
                </div>
              )}

              {applySuccess && (
                <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>{applySuccess}</span>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-3xl p-12 text-center text-slate-500 text-xs space-y-2">
              <Layers className="h-8 w-8 text-slate-600 mx-auto" />
              <p>Presione "Optimizar Cartera" para calcular asignaciones eficientes y shrinkage de Ledoit-Wolf.</p>
            </div>
          )}
        </div>

        {/* ========================================================================= */}
        {/* RIGHT COLUMN: RISK EVALUATION & MONTE CARLO (Col 5) */}
        {/* ========================================================================= */}
        <div className="lg:col-span-5 space-y-6">
          {/* Simulation Controls Card */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <ShieldAlert className="h-4 w-4 text-emerald-400" />
                <span>Simulación de Riesgo Multivariable</span>
              </div>
              <button
                onClick={() => handleSimulateRisk()}
                disabled={simulating || isSyntheticActive}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-600/20 disabled:opacity-50 cursor-pointer transition-all"
              >
                {simulating ? (
                  <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Activity className="h-3.5 w-3.5" />
                )}
                <span>{simulating ? 'Simulando...' : 'Simular 10k Caminos'}</span>
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              {/* Method */}
              <div>
                <label className="block text-slate-400 mb-1">Método de Simulación</label>
                <select
                  value={simMethod}
                  onChange={(e) => setSimMethod(e.target.value as any)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="bootstrap">Block Bootstrap (Colas Empíricas)</option>
                  <option value="student_t">Student-t (Leptocúrtico)</option>
                  <option value="gaussian">Gaussiano Paramétrico</option>
                </select>
              </div>

              {/* Horizon */}
              <div>
                <label className="block text-slate-400 mb-1">Horizonte (Días H)</label>
                <input
                  type="number"
                  min="5"
                  max="365"
                  value={riskHorizon}
                  onChange={(e) => setRiskHorizon(parseInt(e.target.value || '30', 10))}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 font-mono focus:outline-none"
                />
              </div>

              {/* Initial Capital */}
              <div className="col-span-2">
                <label className="block text-slate-400 mb-1">Capital Inicial (USD)</label>
                <div className="flex items-center bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5">
                  <DollarSign className="h-3.5 w-3.5 text-slate-500" />
                  <input
                    type="number"
                    step="1000"
                    min="1000"
                    value={initialCapital}
                    onChange={(e) => setInitialCapital(parseFloat(e.target.value || '100000'))}
                    className="w-full bg-transparent text-slate-200 font-mono text-xs focus:outline-none pl-1"
                  />
                </div>
              </div>
            </div>

            {/* Warning if Gaussian */}
            {simMethod === 'gaussian' && (
              <div className="text-[11px] p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Advertencia: El método gaussiano asume colas normales y subestima sistemáticamente el riesgo de eventos extremos.</span>
              </div>
            )}
          </div>

          {riskError && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-2xl text-red-400 text-xs">
              {riskError}
            </div>
          )}

          {/* Risk Metrics Cards */}
          {riskResult ? (
            <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-5">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="text-xs font-semibold text-slate-300">
                  Métricas a {riskResult.horizon_days} días (Capital: ${riskResult.initial_capital.toLocaleString()})
                </span>
                <span className="text-[10px] text-slate-400 font-mono">
                  10,000 caminos • {riskResult.method_used}
                </span>
              </div>

              {/* VaR and CVaR Badges */}
              <div className="grid grid-cols-2 gap-3">
                {/* 95% Confidence */}
                <div className="p-3.5 rounded-2xl bg-slate-800/50 border border-slate-700/60 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">VaR (95%)</span>
                    <span className="text-[10px] font-mono text-slate-500">
                      ±{(riskResult.metrics['95%'].var_std_error * 100).toFixed(2)}% SE
                    </span>
                  </div>
                  <div className="text-lg font-mono font-bold text-amber-400">
                    {(riskResult.metrics['95%'].var_pct * 100).toFixed(2)}%
                  </div>
                  <div className="text-xs font-mono text-slate-400">
                    -${riskResult.metrics['95%'].var_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className="pt-2 border-t border-slate-700/50 text-[11px] text-slate-400 flex justify-between">
                    <span>CVaR (95%):</span>
                    <span className="font-mono text-red-400 font-semibold">
                      {(riskResult.metrics['95%'].cvar_pct * 100).toFixed(2)}% (-${riskResult.metrics['95%'].cvar_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })})
                    </span>
                  </div>
                </div>

                {/* 99% Confidence */}
                <div className="p-3.5 rounded-2xl bg-slate-800/50 border border-slate-700/60 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">VaR (99%)</span>
                    <span className="text-[10px] font-mono text-slate-500">
                      ±{(riskResult.metrics['99%'].var_std_error * 100).toFixed(2)}% SE
                    </span>
                  </div>
                  <div className="text-lg font-mono font-bold text-red-400">
                    {(riskResult.metrics['99%'].var_pct * 100).toFixed(2)}%
                  </div>
                  <div className="text-xs font-mono text-slate-400">
                    -${riskResult.metrics['99%'].var_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className="pt-2 border-t border-slate-700/50 text-[11px] text-slate-400 flex justify-between">
                    <span>CVaR (99%):</span>
                    <span className="font-mono text-red-500 font-semibold">
                      {(riskResult.metrics['99%'].cvar_pct * 100).toFixed(2)}% (-${riskResult.metrics['99%'].cvar_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })})
                    </span>
                  </div>
                </div>
              </div>

              {/* Tail Exceedance Probabilities */}
              <div className="p-3 rounded-2xl bg-slate-950/50 border border-slate-800 text-xs space-y-2">
                <span className="text-slate-400 font-medium block">Probabilidad de Pérdida en el Horizonte:</span>
                <div className="grid grid-cols-3 gap-2 text-center font-mono">
                  <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                    <span className="text-slate-400 text-[10px] block">&gt; 10%</span>
                    <span className="text-sm font-bold text-slate-200">
                      {(riskResult.prob_loss_10pct * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                    <span className="text-slate-400 text-[10px] block">&gt; 20%</span>
                    <span className="text-sm font-bold text-amber-400">
                      {(riskResult.prob_loss_20pct * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                    <span className="text-slate-400 text-[10px] block">&gt; 30%</span>
                    <span className="text-sm font-bold text-red-400">
                      {(riskResult.prob_loss_30pct * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Simulated Distribution Histogram */}
              <div className="space-y-2 border-t border-slate-800 pt-4">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-300">Distribución de Retornos a {riskHorizon} Días:</span>
                  <div className="flex items-center gap-2 text-[10px] font-mono">
                    <span className="flex items-center gap-1 text-slate-400">
                      <span className="h-2 w-2 rounded-full bg-cyan-400" />
                      Normal
                    </span>
                    <span className="flex items-center gap-1 text-red-400">
                      <span className="h-2 w-2 rounded-full bg-red-500" />
                      Cola &lt; VaR 95%
                    </span>
                  </div>
                </div>

                <div className="h-[180px]">
                  {histogramData && (
                    <Bar
                      data={histogramData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: { display: false },
                          tooltip: {
                            callbacks: {
                              title: (items) => `Rango: ${items[0].label}`,
                              label: (item) => `${item.raw} caminos simulados`,
                            },
                          },
                        },
                        scales: {
                          y: {
                            ticks: { color: '#94a3b8', font: { size: 9 } },
                            grid: { color: '#1e293b' },
                          },
                          x: {
                            ticks: { display: false },
                            grid: { display: false },
                          },
                        },
                      }}
                    />
                  )}
                </div>
                <div className="flex justify-between text-[10px] font-mono text-slate-500 px-1">
                  <span>← Mayor Pérdida</span>
                  <span>Mediana: {(riskResult.histogram.median * 100).toFixed(1)}%</span>
                  <span>Mayor Ganancia →</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-3xl p-12 text-center text-slate-500 text-xs space-y-2">
              <ShieldAlert className="h-8 w-8 text-slate-600 mx-auto" />
              <p>Haga clic en "Simular 10k Caminos" para proyectar el cono de riesgo, VaR y Expected Shortfall.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
