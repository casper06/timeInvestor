import React, { useState, useEffect } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { Play, RotateCcw, Award, CheckCircle, Sliders } from 'lucide-react';
import { runBacktest } from '../services/api';
import type { BacktestResponse, TimeSeriesData } from '../services/api';
import { ExplainerPanel } from './ExplainerPanel';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface BacktestPanelProps {
  seriesData: TimeSeriesData | null;
  activeSeriesId: string;
  /** Notifies the parent of the latest result, so the exported report can
   * include a one-line verdict summary of what the user actually reviewed here. */
  onResult?: (result: BacktestResponse) => void;
}

export const BacktestPanel: React.FC<BacktestPanelProps> = ({ seriesData, activeSeriesId, onResult }) => {
  const [cutoffIndex, setCutoffIndex] = useState<number>(0);
  const [horizon, setHorizon] = useState<number>(60);
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const points = seriesData?.points || [];

  // Default cutoff date to ~4 months before the end
  useEffect(() => {
    if (points.length > 80) {
      const defaultIdx = Math.max(30, points.length - 80);
      setCutoffIndex(defaultIdx);
    } else if (points.length > 30) {
      setCutoffIndex(Math.floor(points.length * 0.7));
    }
  }, [seriesData]);

  const selectedDate = points[cutoffIndex]?.timestamp || '';

  const handleRunBacktest = async () => {
    if (!selectedDate) return;
    setLoading(true);
    try {
      const res = await runBacktest(activeSeriesId, selectedDate, horizon, 0.95);
      setResult(res);
      onResult?.(res);
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Error al ejecutar backtest');
    } finally {
      setLoading(false);
    }
  };

  // Build Chart Data
  let chartData = null;
  if (result) {
    const allLabels = [...result.historical_dates, ...result.future_actual_dates];
    const nHist = result.historical_dates.length;
    const nFuture = result.future_actual_dates.length;

    // Train curve
    const trainData = [...result.historical_values, ...new Array(nFuture).fill(null)];

    // Actual future curve (connected to last train point)
    const lastHistVal = result.historical_values[result.historical_values.length - 1];
    const actualFutureData = [
      ...new Array(nHist - 1).fill(null),
      lastHistVal,
      ...result.future_actual_values,
    ];

    // Predicted curve (connected to last train point)
    const predictedFutureData = [
      ...new Array(nHist - 1).fill(null),
      lastHistVal,
      ...result.future_predicted_values,
    ];

    // Confidence interval
    const upperData = [
      ...new Array(nHist - 1).fill(null),
      lastHistVal,
      ...result.future_upper_bound,
    ];
    const lowerData = [
      ...new Array(nHist - 1).fill(null),
      lastHistVal,
      ...result.future_lower_bound,
    ];

    chartData = {
      labels: allLabels,
      datasets: [
        {
          label: 'Histórico de Entrenamiento (Pasado)',
          data: trainData,
          borderColor: '#38bdf8', // Cyan-400
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.1,
        },
        {
          label: 'Mercado Real Ocurrido (Ground Truth)',
          data: actualFutureData,
          borderColor: '#10b981', // Emerald-500
          backgroundColor: 'rgba(16, 185, 129, 0.05)',
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.1,
        },
        {
          label: 'Proyección Simulada en esa Fecha',
          data: predictedFutureData,
          borderColor: '#f59e0b', // Amber-500
          borderWidth: 2,
          borderDash: [6, 4],
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.15,
        },
        {
          label: 'Banda Superior (95% CI)',
          data: upperData,
          borderColor: 'rgba(245, 158, 11, 0.3)',
          borderWidth: 1,
          borderDash: [2, 2],
          pointRadius: 0,
          fill: false,
        },
        {
          label: 'Banda Inferior (95% CI)',
          data: lowerData,
          borderColor: 'rgba(245, 158, 11, 0.3)',
          borderWidth: 1,
          borderDash: [2, 2],
          pointRadius: 0,
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          fill: '-1',
        },
      ],
    };
  }

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          color: '#94a3b8',
          font: { size: 10, family: 'monospace' },
          boxWidth: 12,
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: { color: '#64748b', font: { size: 10, family: 'monospace' }, maxTicksLimit: 10 },
      },
      y: {
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: { color: '#64748b', font: { size: 10, family: 'monospace' } },
      },
    },
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-5">
      {/* Title and Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div className="flex items-center space-x-2">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Award className="h-5 w-5 text-amber-400" />
              Reality Check • Motor de Backtesting ({activeSeriesId})
            </h3>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
              Validación Histórica
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Corta la serie en una fecha pasada y comprueba si TimesFM habría anticipado lo que ocurrió después.
          </p>
        </div>
      </div>

      <ExplainerPanel>
        <p>
          <strong className="text-slate-200">¿Qué es "cortar la serie en una fecha pasada"?</strong> Elegís un día en el
          pasado (la "fecha de corte") y le mostrás al modelo únicamente los datos anteriores a esa fecha, como si estuvieras
          parado ahí y no supieras qué pasó después. El modelo genera una proyección hacia adelante, y esa proyección se
          compara contra lo que <em>realmente</em> ocurrió (que ya conocemos, porque es historia). Es la única forma
          honesta de medir qué tan bien hubiera funcionado el modelo — a diferencia de una proyección hacia el futuro real,
          acá sabemos la respuesta correcta.
        </p>
        <p>
          <strong className="text-slate-200">Acierto Direccional:</strong> de cada paso hacia adelante, ¿el modelo acertó
          si el precio iba a subir o bajar (sin importar cuánto)? 50% es lo que lograría tirar una moneda al aire; por
          encima de eso, el modelo está capturando algo real sobre la dirección del movimiento.
        </p>
        <p>
          <strong className="text-slate-200">MAPE (Error Porcentual Absoluto Medio):</strong> en promedio, ¿por cuántos
          por ciento se equivocó la proyección respecto al valor real? Un MAPE de 5% significa que, en promedio, la
          proyección estuvo a un 5% de distancia del precio real en cada punto evaluado.
        </p>
        <p>
          <strong className="text-slate-200">MAE (Error Medio Absoluto):</strong> lo mismo que el MAPE pero en las
          unidades de la serie (dólares, puntos de índice) en vez de porcentaje — más fácil de interpretar cuando ya
          conocés la escala típica del activo.
        </p>
        <p>
          <strong className="text-slate-200">¿Qué significa el veredicto ("el modelo supera/no supera al Random
          Walk")?</strong> El Random Walk (paseo aleatorio) es el benchmark más simple posible: "mañana el precio va a
          ser igual al de hoy". Cualquier modelo serio tiene que superar a ese benchmark ingenuo para justificar su uso —
          si no lo supera, la proyección no está agregando información real, y tomarla en serio como base para decidir
          sería sobrestimar lo que el modelo realmente sabe sobre esa serie particular. Que el modelo supere al Random
          Walk en un cutoff no garantiza que lo haga siempre, pero si ni siquiera le gana ahí, es una señal fuerte de que
          conviene desconfiar de sus proyecciones para esa serie específica.
        </p>
      </ExplainerPanel>

      <div className="flex justify-end border-b border-slate-800 pb-4">
        <div className="flex items-center flex-wrap gap-3 text-xs">
          {/* Horizon Selector */}
          <div className="flex items-center space-x-1 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1">
            <span className="text-slate-500">Horizonte H:</span>
            {[30, 60, 90, 120].map((h) => (
              <button
                key={h}
                onClick={() => setHorizon(h)}
                className={`px-1.5 py-0.5 rounded font-mono ${
                  horizon === h ? 'bg-amber-500/20 text-amber-300 font-bold' : 'text-slate-400 hover:text-white'
                }`}
              >
                {h}d
              </button>
            ))}
          </div>

          <button
            onClick={handleRunBacktest}
            disabled={loading || points.length < 30}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-slate-950 font-bold text-xs shadow-md shadow-amber-600/20 transition-all disabled:opacity-50 cursor-pointer"
          >
            {loading ? (
              <div className="w-4 h-4 border-2 border-slate-950 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Play className="h-4 w-4 fill-slate-950" />
            )}
            <span>Ejecutar Reality Check</span>
          </button>
        </div>
      </div>

      {/* Date Slider */}
      {points.length > 30 && (
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
          <div className="flex justify-between items-center text-xs font-mono">
            <span className="text-slate-400 flex items-center gap-1.5">
              <Sliders className="h-3.5 w-3.5 text-cyan-400" />
              Fecha de Corte (T_cutoff): <strong className="text-cyan-300">{selectedDate}</strong>
            </span>
            <span className="text-slate-500">
              Datos previos: {cutoffIndex} • Futuro a evaluar: {points.length - 1 - cutoffIndex} días
            </span>
          </div>

          <input
            type="range"
            min={20}
            max={points.length - 15}
            value={cutoffIndex}
            onChange={(e) => setCutoffIndex(Number(e.target.value))}
            className="w-full accent-amber-500 bg-slate-800 h-1.5 rounded-lg cursor-pointer"
          />

          <div className="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>Inicio: {points[20]?.timestamp}</span>
            <span>Fin: {points[points.length - 15]?.timestamp}</span>
          </div>
        </div>
      )}

      {/* Metrics Row */}
      {result && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5">
            <div className="text-slate-400 text-[11px] uppercase tracking-wider">Acierto Direccional</div>
            <div
              className={`text-xl font-bold font-mono mt-1 ${
                result.metrics.directional_accuracy >= 60 ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {result.metrics.directional_accuracy.toFixed(1)}%
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">Signo alcista/bajista coincidente</div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5">
            <div className="text-slate-400 text-[11px] uppercase tracking-wider">Error MAPE</div>
            <div className="text-xl font-bold font-mono text-cyan-300 mt-1">
              {result.metrics.mape.toFixed(2)}%
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">Porcentaje de error absoluto</div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5">
            <div className="text-slate-400 text-[11px] uppercase tracking-wider">Error Medio (MAE)</div>
            <div className="text-xl font-bold font-mono text-indigo-300 mt-1">
              ${result.metrics.mae.toFixed(2)}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">Desviación media absoluta</div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5">
            <div className="text-slate-400 text-[11px] uppercase tracking-wider">Muestra Evaluada</div>
            <div className="text-xl font-bold font-mono text-white mt-1">
              {result.metrics.observations_evaluated} puntos
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">Ventana de comparación</div>
          </div>
        </div>
      )}

      {/* Chart Area */}
      <div className="relative h-[360px] w-full">
        {chartData ? (
          <Line data={chartData} options={options} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl space-y-2">
            <RotateCcw className="h-6 w-6 text-slate-600" />
            <span>Selecciona una fecha de corte histórica y haz clic en "Ejecutar Reality Check"</span>
          </div>
        )}
      </div>

      {/* Qualitative Verdict */}
      {result && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200 flex items-start gap-2.5">
          <CheckCircle className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <strong className="text-amber-300 font-semibold">Veredicto Cuantitativo: </strong>
            {result.verdict}
          </div>
        </div>
      )}
    </div>
  );
};
