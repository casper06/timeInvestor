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
import { KeyRound } from 'lucide-react';
import type { TimeSeriesData, ForecastResponse } from '../services/api';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface ForecastChartProps {
  seriesData: TimeSeriesData | null;
  seriesError?: string | null;
  forecast: ForecastResponse | null;
  selectedSeriesId: string;
  allSeriesList: { id: string; name: string; type: string }[];
  onSelectSeries: (id: string) => void;
  horizon: number;
  onChangeHorizon: (h: number) => void;
  confidence: number;
  onChangeConfidence: (c: number) => void;
  period: string;
  onChangePeriod: (p: string) => void;
  isNormalized: boolean;
  onToggleNormalized: () => void;
  loading: boolean;
  /** When false, every 'macro' series tab shows a small key-required badge —
   * all macro series in this app come from FRED, so a missing key means every
   * one of them will fail to load, not just the one the user happens to click. */
  hasFredKey?: boolean;
}

/**
 * Translates a known technical backend error into user-facing copy, when the
 * cause is recognizably a missing configuration key. Falls back to the raw
 * message for anything else (yfinance down, invalid ticker, ...) — that's
 * still more useful than a generic "no data" string. Exported so App.tsx's
 * top-of-page error banner shows the same friendly text as the chart's own
 * inline message, instead of the raw technical string in one place and the
 * humanized one in the other.
 */
export const humanizeSeriesError = (rawError: string): string => {
  if (/FRED_API_KEY|FRED API no disponible/i.test(rawError)) {
    return 'Esta serie requiere una clave de API de FRED que no está configurada. Podés agregarla en tu .env (FRED_API_KEY).';
  }
  if (/GEMINI_API_KEY/i.test(rawError)) {
    return 'Esta acción requiere una clave de API de Gemini que no está configurada. Podés agregarla en tu .env (GEMINI_API_KEY).';
  }
  return rawError;
};

export const ForecastChart: React.FC<ForecastChartProps> = ({
  seriesData,
  seriesError,
  forecast,
  selectedSeriesId,
  allSeriesList,
  onSelectSeries,
  horizon,
  onChangeHorizon,
  confidence,
  onChangeConfidence,
  period,
  onChangePeriod,
  isNormalized,
  onToggleNormalized,
  loading,
  hasFredKey = true,
}) => {
  const hasData = !!seriesData && seriesData.points.length > 0;

  // Slice historical points based on period if desired
  let historicalPoints = hasData ? seriesData.points : [];
  if (period === '1mo') historicalPoints = historicalPoints.slice(-22);
  else if (period === '6mo') historicalPoints = historicalPoints.slice(-130);
  else if (period === '1y') historicalPoints = historicalPoints.slice(-252);
  else if (period === '2y') historicalPoints = historicalPoints.slice(-504);

  // Normalization logic: base = 100 on first visible point
  const baseValue = historicalPoints[0]?.value || 1.0;
  const normalize = (v: number) => (isNormalized ? (v / baseValue) * 100 : v);

  const histTimestamps = historicalPoints.map((p) => p.timestamp);
  const histValues = historicalPoints.map((p) => normalize(p.value));

  const forecastTimestamps = forecast ? forecast.timestamps : [];
  const forecastValues = forecast ? forecast.values.map(normalize) : [];
  const lowerBounds = forecast ? forecast.lower_bound.map(normalize) : [];
  const upperBounds = forecast ? forecast.upper_bound.map(normalize) : [];

  // Unified timeline: historical + forecast
  const allLabels = [...histTimestamps, ...forecastTimestamps];

  // Align datasets along allLabels
  const histDatasetData = [...histValues, ...new Array(forecastTimestamps.length).fill(null)];

  // For continuous transition, forecast begins with the last historical point.
  // Guard against histValues being empty (no data / a failed series fetch) — that
  // would make `histValues.length - 1` negative, and `new Array(negative)` throws
  // a RangeError, crashing the whole component render (not just this chart).
  const lastHistVal = histValues[histValues.length - 1];
  const leadingPadLength = Math.max(histValues.length - 1, 0);

  const forecastDatasetData = [
    ...new Array(leadingPadLength).fill(null),
    lastHistVal,
    ...forecastValues,
  ];

  const lowerBoundData = [
    ...new Array(leadingPadLength).fill(null),
    lastHistVal,
    ...lowerBounds,
  ];

  const upperBoundData = [
    ...new Array(leadingPadLength).fill(null),
    lastHistVal,
    ...upperBounds,
  ];

  const chartData = {
    labels: allLabels,
    datasets: [
      {
        label: `${seriesData?.id ?? ''} Histórico`,
        data: histDatasetData,
        borderColor: '#38bdf8', // Tailwind cyan-400
        backgroundColor: 'rgba(56, 189, 248, 0.1)',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
      },
      {
        label: `Proyección (${forecast?.model_name || 'TimesFM'})`,
        data: forecastDatasetData,
        borderColor: '#f59e0b', // Amber-500
        backgroundColor: 'transparent',
        borderWidth: 2.2,
        borderDash: [6, 4],
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.15,
      },
      {
        label: `Banda Superior (${Math.round(confidence * 100)}%)`,
        data: upperBoundData,
        borderColor: 'rgba(245, 158, 11, 0.4)',
        borderWidth: 1,
        borderDash: [2, 2],
        pointRadius: 0,
        fill: false,
        tension: 0.15,
      },
      {
        label: `Banda Inferior (${Math.round(confidence * 100)}%)`,
        data: lowerBoundData,
        borderColor: 'rgba(245, 158, 11, 0.4)',
        borderWidth: 1,
        borderDash: [2, 2],
        pointRadius: 0,
        backgroundColor: 'rgba(245, 158, 11, 0.12)', // Confidence band shading
        fill: '-1', // Fill to previous dataset (upper bound)
        tension: 0.15,
      },
    ],
  };

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index',
      intersect: false,
    },
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          color: '#94a3b8',
          font: { size: 11, family: 'monospace' },
          boxWidth: 12,
          usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        titleColor: '#e2e8f0',
        bodyColor: '#cbd5e1',
        borderColor: '#334155',
        borderWidth: 1,
        padding: 10,
        callbacks: {
          label: (context) => {
            const val = context.parsed.y;
            if (val === null || val === undefined) return '';
            const unit = isNormalized ? 'pts (Base 100)' : (seriesData?.unit ?? '');
            return ` ${context.dataset.label}: ${val.toFixed(2)} ${unit}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: {
          color: '#64748b',
          font: { size: 10, family: 'monospace' },
          maxTicksLimit: 12,
        },
      },
      y: {
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: {
          color: '#64748b',
          font: { size: 10, family: 'monospace' },
        },
        title: {
          display: true,
          text: isNormalized ? 'Índice (Base 100)' : `${seriesData?.unit ?? ''}`,
          color: '#64748b',
          font: { size: 11 },
        },
      },
    },
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      {/* Top Chart Header & Interactive Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 border-b border-slate-800/80 pb-4">
        {/* Series Selector Pills */}
        <div className="flex items-center flex-wrap gap-1.5">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-1">
            Serie Activa:
          </span>
          {allSeriesList.map((item) => {
            // All macro series in this app are FRED-backed — without a key every
            // one of them will fail to load, not just whichever the user clicks.
            // Flag that up front instead of letting them find out via a failed click.
            const needsFredKey = item.type === 'macro' && !hasFredKey;
            return (
              <button
                key={item.id}
                onClick={() => onSelectSeries(item.id)}
                title={needsFredKey ? 'Esta serie requiere FRED_API_KEY, que no está configurada' : undefined}
                className={`inline-flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-mono font-medium transition-all cursor-pointer ${
                  selectedSeriesId === item.id
                    ? 'bg-cyan-500 text-slate-950 font-bold shadow-md shadow-cyan-500/30'
                    : 'bg-slate-800/90 text-slate-300 hover:bg-slate-700/80'
                }`}
              >
                {item.id}
                {needsFredKey && <KeyRound className="h-3 w-3 text-amber-400" />}
              </button>
            );
          })}
        </div>

        {/* Chart Configuration Controls */}
        <div className="flex items-center flex-wrap gap-2 text-xs">
          {/* Time Range Selector */}
          <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5">
            {['1mo', '6mo', '1y', '2y', 'max'].map((p) => (
              <button
                key={p}
                onClick={() => onChangePeriod(p)}
                className={`px-2.5 py-0.5 rounded text-[11px] font-mono transition-colors uppercase cursor-pointer ${
                  period === p ? 'bg-slate-800 text-cyan-400 font-bold' : 'text-slate-400 hover:text-white'
                }`}
              >
                {p}
              </button>
            ))}
          </div>

          {/* Horizon Selector */}
          <div className="flex items-center space-x-1 bg-slate-950 border border-slate-800 rounded-lg px-2 py-0.5 text-slate-300">
            <span className="text-slate-500 text-[11px]">H:</span>
            {[30, 60, 90, 180].map((h) => (
              <button
                key={h}
                onClick={() => onChangeHorizon(h)}
                className={`px-1.5 py-0.5 rounded text-[11px] font-mono cursor-pointer ${
                  horizon === h ? 'bg-amber-500/20 text-amber-300 font-bold' : 'text-slate-400 hover:text-white'
                }`}
              >
                {h}d
              </button>
            ))}
          </div>

          {/* Confidence Selector */}
          <div className="flex items-center space-x-1 bg-slate-950 border border-slate-800 rounded-lg px-2 py-0.5 text-slate-300">
            <span className="text-slate-500 text-[11px]">CI:</span>
            {[0.8, 0.9, 0.95].map((c) => (
              <button
                key={c}
                onClick={() => onChangeConfidence(c)}
                className={`px-1.5 py-0.5 rounded text-[11px] font-mono cursor-pointer ${
                  confidence === c ? 'bg-indigo-500/20 text-indigo-300 font-bold' : 'text-slate-400 hover:text-white'
                }`}
              >
                {Math.round(c * 100)}%
              </button>
            ))}
          </div>

          {/* Base 100 Normalization Toggle */}
          <button
            onClick={onToggleNormalized}
            className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium transition-colors cursor-pointer ${
              isNormalized
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-white'
            }`}
          >
            {isNormalized ? '✓ Base 100' : 'Normalizar'}
          </button>
        </div>
      </div>

      {/* Main Chart Area */}
      <div className="relative h-[380px] w-full">
        {loading && (
          <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px] z-10 flex items-center justify-center">
            <div className="flex items-center space-x-2 text-cyan-400 font-mono text-xs">
              <div className="w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
              {/* Reflects the actually active engine (forecast?.model_name — the
                  same source MetricCards/the projection line label already use),
                  not a hardcoded "TimesFM" that's wrong whenever the real active
                  engine is the Damped Holt fallback (the common case in this
                  project unless real TimesFM weights are installed). */}
              <span>Calculando proyección {forecast?.model_name || 'TimesFM'}...</span>
            </div>
          </div>
        )}
        {hasData ? (
          <Line data={chartData} options={options} />
        ) : (
          !loading && (
            <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-center px-8 text-sm">
              {seriesError ? humanizeSeriesError(seriesError) : 'No hay datos de series temporales disponibles.'}
            </div>
          )
        )}
      </div>

      {/* Chart Footer Info */}
      {hasData && seriesData && (
        <div className="flex items-center justify-between text-[11px] text-slate-500 pt-1 font-mono">
          <div className="flex items-center gap-2">
            <span>
              Serie: <span className="text-slate-300">{seriesData.name}</span> ({seriesData.type.toUpperCase()})
            </span>
            {seriesData.from_cache && seriesData.source === 'live' && (
              <span
                className="text-[10px] px-2 py-0.5 rounded-md bg-slate-800/80 text-slate-400 border border-slate-700/60 font-mono inline-flex items-center gap-1"
                title={seriesData.cached_at ? `En caché local desde ${new Date(seriesData.cached_at).toLocaleTimeString()}` : 'Servido desde caché local'}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-slate-400"></span>
                datos en caché
              </span>
            )}
          </div>
          <div className="flex items-center space-x-3">
            <span>Último: <strong className="text-cyan-400">{lastHistVal?.toFixed(2)} {isNormalized ? 'pts' : seriesData.unit}</strong></span>
            {forecast && (
              <span>
                Proyección +{horizon}d: <strong className="text-amber-400">{forecast.values[forecast.values.length - 1]?.toFixed(2)}</strong>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
