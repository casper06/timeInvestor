import React, { useState } from 'react';
import {
  Chart as ChartJS,
  ArcElement,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Doughnut, Bar, Line } from 'react-chartjs-2';
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
  Repeat,
  TrendingUp,
} from 'lucide-react';
import {
  optimizePortfolio,
  evaluatePortfolioRisk,
  runRebalanceBacktest,
  type PortfolioOptimizeResponse,
  type PortfolioRiskResponse,
  type RebalanceBacktestResponse,
  type TickerSuggestion,
  type ThesisDetailResponse,
  updateThesis,
} from '../services/api';
import { ExplainerPanel } from './ExplainerPanel';

ChartJS.register(ArcElement, CategoryScale, LinearScale, BarElement, PointElement, LineElement, Title, Tooltip, Legend);

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

  // Sub-view switcher
  const [activeSubTab, setActiveSubTab] = useState<'allocation_risk' | 'rebalance'>('allocation_risk');

  // Rebalance Backtest state
  const [rebalanceFreq, setRebalanceFreq] = useState<'monthly' | 'quarterly' | 'none'>('monthly');
  const [rebalanceMethod, setRebalanceMethod] = useState<'max_sharpe' | 'risk_parity'>('max_sharpe');
  const [rebalanceCostBps, setRebalanceCostBps] = useState<number>(10);
  const [rebalanceTaxRate, setRebalanceTaxRate] = useState<number>(0);
  const [rebalancePeriod, setRebalancePeriod] = useState<string>('5y');
  const [rebalanceRunning, setRebalanceRunning] = useState<boolean>(false);
  const [rebalanceResult, setRebalanceResult] = useState<RebalanceBacktestResponse | null>(null);
  const [rebalanceError, setRebalanceError] = useState<string | null>(null);

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

  // Rebalance execution handler
  const handleRunRebalance = async () => {
    if (tickers.length < 2) {
      setRebalanceError('Se requieren al menos 2 activos para el backtest de rebalanceo.');
      return;
    }
    setRebalanceRunning(true);
    setRebalanceError(null);

    try {
      const res = await runRebalanceBacktest({
        tickers,
        method: rebalanceMethod,
        rebalance_frequency: rebalanceFreq,
        cost_bps: rebalanceCostBps,
        capital_gains_tax_rate: rebalanceTaxRate / 100.0,
        period: rebalancePeriod,
        initial_capital: initialCapital,
        risk_free_rate: riskFreeRate,
      });
      setRebalanceResult(res);
    } catch (err: any) {
      setRebalanceError(err.message || 'Error en el backtest de rebalanceo.');
    } finally {
      setRebalanceRunning(false);
    }
  };

  // Rebalance multi-curve chart data
  const rebalanceChartData = rebalanceResult
    ? {
        labels: rebalanceResult.curves.map((c) => c.date),
        datasets: [
          {
            label: 'Rebalanceo Neto (con costos e impuestos)',
            data: rebalanceResult.curves.map((c) => c.rebalance_net),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.04)',
            borderWidth: 2.5,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.1,
          },
          {
            label: 'Rebalanceo Bruto (sin fricciones)',
            data: rebalanceResult.curves.map((c) => c.rebalance_gross),
            borderColor: '#38bdf8',
            borderDash: [5, 5],
            borderWidth: 1.8,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.1,
          },
          {
            label: 'Buy-and-Hold (sin rebalanceo intermedio)',
            data: rebalanceResult.curves.map((c) => c.buy_and_hold),
            borderColor: '#f59e0b',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.1,
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

      {/* Sub-navigation Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
        <button
          onClick={() => setActiveSubTab('allocation_risk')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
            activeSubTab === 'allocation_risk'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
        >
          <PieChart className="h-4 w-4 text-cyan-400" />
          <span>Asignación Óptima & Riesgo Monte Carlo</span>
        </button>

        <button
          onClick={() => setActiveSubTab('rebalance')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
            activeSubTab === 'rebalance'
              ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
        >
          <Repeat className="h-4 w-4 text-emerald-400" />
          <span>Rebalanceo Dinámico & Fricciones (Walk-Forward)</span>
        </button>
      </div>

      {/* ========================================================================= */}
      {/* SUBTAB 1: ALLOCATION & RISK MONTE CARLO                                   */}
      {/* ========================================================================= */}
      {activeSubTab === 'allocation_risk' && (
        <div className="space-y-6">
        <ExplainerPanel>
          <p>
            <strong className="text-slate-200">Sharpe Ratio:</strong> mide cuánto retorno extra (por encima de la tasa
            libre de riesgo) obtenés por cada unidad de volatilidad que asumís. Un Sharpe más alto significa que la
            cartera está siendo más eficiente en convertir riesgo en retorno — no que gane más en términos absolutos,
            sino que gana más <em>por cada unidad de riesgo tomado</em>.
          </p>
          <p>
            <strong className="text-slate-200">Max Drawdown:</strong> la peor caída que hubiera sufrido esta cartera
            desde un pico hasta el valle siguiente, en el período histórico evaluado. Es la forma más directa de
            responder "¿cuánto podría llegar a perder si entro en el peor momento posible?" — a diferencia de la
            volatilidad (que es un promedio), el drawdown captura el escenario doloroso específico.
          </p>
          <p>
            <strong className="text-slate-200">Ratio de Diversificación:</strong> compara el riesgo de la cartera
            combinada contra la suma del riesgo de cada activo por separado. Un ratio alto (bien por encima de 1)
            indica que los activos se compensan entre sí — la diversificación está funcionando de verdad. Un ratio
            cercano a 1 indica que, aunque tengas varios tickers, en la práctica se mueven todos parecido y la
            diversificación real es baja.
          </p>
          <p>
            <strong className="text-slate-200">Shrinkage (δ*) y Número de Condición:</strong> ambos son indicadores de
            qué tan confiable es la matriz de covarianza que se usó para optimizar la cartera (no de la cartera en sí).
            Con pocos datos históricos o activos muy correlacionados entre sí, la matriz de covarianza "cruda" queda
            estadísticamente inestable — el Número de Condición mide justamente eso: valores muy altos son señal de
            datos poco confiables para optimizar sobre ellos tal cual. El Shrinkage (δ*) es la corrección que se le
            aplica a esa matriz para hacerla más estable, "encogiéndola" hacia una versión más simple y menos ruidosa;
            un δ* más alto significa que el ajuste tuvo que ser más agresivo porque los datos originales eran menos
            confiables por sí solos.
          </p>
          <p>
            <strong className="text-slate-200">VaR vs CVaR:</strong> el VaR (Value at Risk) al 95% responde "¿cuál es
            la pérdida que, con 95% de confianza, no debería superarse en este horizonte?" — pero no dice nada sobre
            qué tan mala puede ser esa pérdida en el 5% de casos restante. El CVaR (Conditional VaR, o Expected
            Shortfall) sí lo hace: es el promedio de las pérdidas <em>dentro</em> de ese peor 5% de escenarios. Por eso
            el CVaR siempre es igual o peor que el VaR al mismo nivel de confianza — es la pregunta de seguimiento
            natural a "¿y si sí pasa lo malo, qué tan malo es en promedio?".
          </p>
          <p>
            <strong className="text-slate-200">Block Bootstrap vs Gaussiano:</strong> el método Gaussiano asume que los
            retornos siguen una distribución normal (campana simétrica, sin eventos extremos frecuentes) — es rápido de
            calcular pero subestima sistemáticamente la probabilidad de caídas grandes, porque los mercados reales
            tienen "colas gordas" (crashes más frecuentes de lo que una normal predeciría). El Block Bootstrap en
            cambio remuestrea bloques de retornos históricos reales tal cual ocurrieron, preservando esas colas gordas
            y la estructura de dependencia temporal (los días malos suelen agruparse) — es más lento de calcular pero
            más realista para estimar el riesgo de eventos extremos.
          </p>
        </ExplainerPanel>

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
      )}

      {/* ========================================================================= */}
      {/* SUBTAB 2: DYNAMIC REBALANCING & TRANSACTION COSTS (Walk-Forward Backtest) */}
      {/* ========================================================================= */}
      {activeSubTab === 'rebalance' && (
        <div className="space-y-6">
          {/* Rebalance Controls Card */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Repeat className="h-4 w-4 text-emerald-400" />
                <span>Configuración de Rebalanceo Dinámico (Walk-Forward)</span>
              </div>
              <button
                onClick={handleRunRebalance}
                disabled={rebalanceRunning || isSyntheticActive}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-semibold shadow-md shadow-emerald-600/20 disabled:opacity-50 cursor-pointer transition-all"
              >
                {rebalanceRunning ? (
                  <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                <span>{rebalanceRunning ? 'Simulando Rebalanceos...' : 'Ejecutar Backtest de Rebalanceo'}</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
              {/* Rebalance Frequency */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Frecuencia</label>
                <select
                  value={rebalanceFreq}
                  onChange={(e) => setRebalanceFreq(e.target.value as any)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="monthly">Mensual (~21 ruedas)</option>
                  <option value="quarterly">Trimestral (~63 ruedas)</option>
                  <option value="none">Sin Rebalanceo (Buy & Hold)</option>
                </select>
              </div>

              {/* Rebalance Optimization Method */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Modelo de Asignación</label>
                <select
                  value={rebalanceMethod}
                  onChange={(e) => setRebalanceMethod(e.target.value as any)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="max_sharpe">Máximo Sharpe (SLSQP)</option>
                  <option value="risk_parity">Paridad de Riesgo (Spinu ERC)</option>
                </select>
              </div>

              {/* Cost bps */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">
                  Costo Transacción: <span className="text-cyan-400 font-mono">{rebalanceCostBps} bps</span>
                </label>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={rebalanceCostBps}
                  onChange={(e) => setRebalanceCostBps(Number(e.target.value))}
                  className="w-full accent-cyan-500 cursor-pointer"
                />
                <div className="text-[10px] text-slate-500 text-right font-mono">{(rebalanceCostBps / 100).toFixed(2)}% por rotación</div>
              </div>

              {/* Capital Gains Tax Rate */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">
                  Impuesto Ganancias: <span className="text-amber-400 font-mono">{rebalanceTaxRate}%</span>
                </label>
                <input
                  type="range"
                  min="0"
                  max="35"
                  step="1"
                  value={rebalanceTaxRate}
                  onChange={(e) => setRebalanceTaxRate(Number(e.target.value))}
                  className="w-full accent-amber-500 cursor-pointer"
                />
                <div className="text-[10px] text-slate-500 text-right font-mono">Sobre ventas con ganancia</div>
              </div>

              {/* Historical Window */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Ventana Histórica</label>
                <select
                  value={rebalancePeriod}
                  onChange={(e) => setRebalancePeriod(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-1.5 text-slate-200 focus:outline-none"
                >
                  <option value="3y">3 años de datos</option>
                  <option value="5y">5 años (Recomendado)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Error Alert */}
          {rebalanceError && (
            <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <span>{rebalanceError}</span>
            </div>
          )}

          {/* Results View */}
          {rebalanceResult && (
            <div className="space-y-6 animate-fadeIn">
              {/* Honest Quantitative Verdict Box */}
              <div
                className={`p-5 rounded-3xl border backdrop-blur-md shadow-lg ${
                  rebalanceResult.net_benefit_of_rebalancing >= 0
                    ? 'bg-emerald-950/20 border-emerald-500/40 text-emerald-100'
                    : 'bg-rose-950/20 border-rose-500/40 text-rose-100'
                }`}
              >
                <div className="flex items-start gap-3.5">
                  {rebalanceResult.net_benefit_of_rebalancing >= 0 ? (
                    <CheckCircle2 className="h-6 w-6 text-emerald-400 shrink-0 mt-0.5" />
                  ) : (
                    <AlertTriangle className="h-6 w-6 text-rose-400 shrink-0 mt-0.5" />
                  )}
                  <div className="space-y-1.5">
                    <h3 className="text-sm font-bold tracking-tight">
                      {rebalanceResult.net_benefit_of_rebalancing >= 0
                        ? 'Veredicto Cuantitativo: El rebalanceo periódico aportó valor neto positivo'
                        : 'Veredicto Cuantitativo: El rebalanceo periódico costó más de lo que aportó'}
                    </h3>
                    <p className="text-xs leading-relaxed opacity-90">
                      {rebalanceResult.verdict}
                    </p>
                    {rebalanceResult.warnings && rebalanceResult.warnings.length > 0 && (
                      <div className="pt-2 border-t border-white/10 text-[11px] text-slate-400 flex items-center gap-1.5">
                        <Info className="h-3.5 w-3.5 shrink-0" />
                        <span>{rebalanceResult.warnings.join(' | ')}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Multi-Curve Line Chart */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
                  <div>
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <TrendingUp className="h-4 w-4 text-emerald-400" />
                      <span>Evolución de Patrimonio Comparada (Capital Inicial: ${rebalanceResult.initial_capital.toLocaleString()})</span>
                    </h3>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      Evaluado en {rebalanceResult.trading_days_evaluated} ruedas bursátiles ({rebalanceResult.start_date} al {rebalanceResult.end_date}) con estricto cero sesgo de anticipación.
                    </p>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                      <span className="w-3 h-0.5 bg-emerald-400 inline-block"></span>
                      <span>Neto</span>
                    </span>
                    <span className="flex items-center gap-1.5 text-cyan-400 font-medium">
                      <span className="w-3 h-0.5 bg-cyan-400 border-b border-dashed inline-block"></span>
                      <span>Bruto</span>
                    </span>
                    <span className="flex items-center gap-1.5 text-amber-400 font-medium">
                      <span className="w-3 h-0.5 bg-amber-400 inline-block"></span>
                      <span>Buy & Hold</span>
                    </span>
                  </div>
                </div>

                <div className="h-80 w-full">
                  {rebalanceChartData && (
                    <Line
                      data={rebalanceChartData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: { mode: 'index', intersect: false },
                        plugins: {
                          legend: { display: false },
                          tooltip: {
                            backgroundColor: '#0f172a',
                            borderColor: '#334155',
                            borderWidth: 1,
                            titleFont: { size: 11 },
                            bodyFont: { size: 11 },
                            callbacks: {
                              label: (ctx) => `${ctx.dataset.label}: $${Number(ctx.raw).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                            },
                          },
                        },
                        scales: {
                          x: {
                            ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 10 },
                            grid: { color: '#1e293b' },
                          },
                          y: {
                            ticks: {
                              color: '#64748b',
                              font: { size: 10 },
                              callback: (v) => `$${Number(v).toLocaleString()}`,
                            },
                            grid: { color: '#1e293b' },
                          },
                        },
                      }}
                    />
                  )}
                </div>
              </div>

              {/* Performance Comparison Table & Telemetry */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                <div className="lg:col-span-7 bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md">
                  <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
                    Métricas Comparativas de Rendimiento
                  </h4>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400 font-medium">
                          <th className="py-2.5 pr-4">Métrica</th>
                          <th className="py-2.5 px-3 text-emerald-400 font-semibold">Rebalanceo Neto</th>
                          <th className="py-2.5 px-3 text-cyan-400">Rebalanceo Bruto</th>
                          <th className="py-2.5 pl-3 text-amber-400 font-semibold">Buy-and-Hold</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 font-mono text-slate-200">
                        <tr>
                          <td className="py-2 pr-4 font-sans text-slate-400">Retorno Total</td>
                          <td className="py-2 px-3 text-emerald-400 font-semibold">{(rebalanceResult.net_metrics.total_return * 100).toFixed(2)}%</td>
                          <td className="py-2 px-3 text-cyan-300">{(rebalanceResult.gross_metrics.total_return * 100).toFixed(2)}%</td>
                          <td className="py-2 pl-3 text-amber-400">{(rebalanceResult.buy_and_hold_metrics.total_return * 100).toFixed(2)}%</td>
                        </tr>
                        <tr>
                          <td className="py-2 pr-4 font-sans text-slate-400">Retorno Anualizado (CAGR)</td>
                          <td className="py-2 px-3 text-emerald-400 font-semibold">{(rebalanceResult.net_metrics.annualized_return * 100).toFixed(2)}%</td>
                          <td className="py-2 px-3 text-cyan-300">{(rebalanceResult.gross_metrics.annualized_return * 100).toFixed(2)}%</td>
                          <td className="py-2 pl-3 text-amber-400">{(rebalanceResult.buy_and_hold_metrics.annualized_return * 100).toFixed(2)}%</td>
                        </tr>
                        <tr>
                          <td className="py-2 pr-4 font-sans text-slate-400">Volatilidad Anualizada</td>
                          <td className="py-2 px-3">{(rebalanceResult.net_metrics.annualized_volatility * 100).toFixed(2)}%</td>
                          <td className="py-2 px-3">{(rebalanceResult.gross_metrics.annualized_volatility * 100).toFixed(2)}%</td>
                          <td className="py-2 pl-3">{(rebalanceResult.buy_and_hold_metrics.annualized_volatility * 100).toFixed(2)}%</td>
                        </tr>
                        <tr>
                          <td className="py-2 pr-4 font-sans text-slate-400">Ratio de Sharpe (rf = {(riskFreeRate * 100).toFixed(1)}%)</td>
                          <td className="py-2 px-3 font-semibold text-emerald-400">{rebalanceResult.net_metrics.sharpe_ratio.toFixed(2)}</td>
                          <td className="py-2 px-3 text-cyan-300">{rebalanceResult.gross_metrics.sharpe_ratio.toFixed(2)}</td>
                          <td className="py-2 pl-3 text-amber-400">{rebalanceResult.buy_and_hold_metrics.sharpe_ratio.toFixed(2)}</td>
                        </tr>
                        <tr>
                          <td className="py-2 pr-4 font-sans text-slate-400">Máximo Drawdown</td>
                          <td className="py-2 px-3 text-rose-400">{(rebalanceResult.net_metrics.max_drawdown * 100).toFixed(2)}%</td>
                          <td className="py-2 px-3 text-rose-400">{(rebalanceResult.gross_metrics.max_drawdown * 100).toFixed(2)}%</td>
                          <td className="py-2 pl-3 text-rose-400">{(rebalanceResult.buy_and_hold_metrics.max_drawdown * 100).toFixed(2)}%</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Telemetry of Frictions & Drag */}
                <div className="lg:col-span-5 bg-slate-900/60 border border-slate-800 rounded-3xl p-5 shadow-lg backdrop-blur-md space-y-4">
                  <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Auditoría de Fricciones y Rotación
                  </h4>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="p-3 rounded-2xl bg-slate-800/50 border border-slate-700/60">
                      <span className="text-slate-400 block text-[11px]">Rotación Acumulada</span>
                      <span className="text-base font-bold font-mono text-cyan-400 mt-1 block">
                        {rebalanceResult.total_turnover.toFixed(2)}x
                      </span>
                      <span className="text-[10px] text-slate-500">veces la cartera</span>
                    </div>

                    <div className="p-3 rounded-2xl bg-slate-800/50 border border-slate-700/60">
                      <span className="text-slate-400 block text-[11px]">Rebalanceos Ejecutados</span>
                      <span className="text-base font-bold font-mono text-white mt-1 block">
                        {rebalanceResult.n_rebalances_executed}
                      </span>
                      <span className="text-[10px] text-slate-500">ajustes periódicos</span>
                    </div>

                    <div className="p-3 rounded-2xl bg-slate-800/50 border border-slate-700/60">
                      <span className="text-slate-400 block text-[11px]">Costos de Corretaje</span>
                      <span className="text-base font-bold font-mono text-rose-400 mt-1 block">
                        ${rebalanceResult.total_transaction_costs.toLocaleString()}
                      </span>
                      <span className="text-[10px] text-slate-500">comisiones acumuladas</span>
                    </div>

                    <div className="p-3 rounded-2xl bg-slate-800/50 border border-slate-700/60">
                      <span className="text-slate-400 block text-[11px]">Impuestos Devengados</span>
                      <span className="text-base font-bold font-mono text-amber-400 mt-1 block">
                        ${rebalanceResult.total_tax_paid.toLocaleString()}
                      </span>
                      <span className="text-[10px] text-slate-500">ganancias de capital</span>
                    </div>
                  </div>

                  <div className="p-3.5 rounded-2xl bg-slate-800/70 border border-slate-700 text-xs flex items-center justify-between">
                    <div>
                      <span className="text-slate-300 font-semibold block">Arrastre Total por Fricciones (Drag)</span>
                      <span className="text-[11px] text-slate-400">Pérdida anualizada directa respecto a rebalanceo bruto</span>
                    </div>
                    <span className="text-base font-bold font-mono text-rose-400">
                      -{(rebalanceResult.cost_drag * 100).toFixed(2)}% / año
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {!rebalanceResult && !rebalanceRunning && (
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-3xl p-12 text-center text-slate-500 text-xs space-y-2">
              <Repeat className="h-8 w-8 text-slate-600 mx-auto" />
              <p className="max-w-md mx-auto">
                Haga clic en <strong>"Ejecutar Backtest de Rebalanceo"</strong> para evaluar empíricamente el impacto del rebalanceo periódico ({rebalanceFreq}) deduciendo costos reales de corretaje e impuestos frente a una estrategia pasiva de Buy-and-Hold.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
