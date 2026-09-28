import React, { useState, useEffect, useRef } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { GitCompare } from 'lucide-react';
import { fetchMarketData, fetchMacroData } from '../services/api';
import { seriesMetaText } from '../utils/valueFormat';
import type { TimeSeriesData } from '../services/api';
import { ExplainerPanel } from './ExplainerPanel';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

interface DualAxisChartProps {
  primarySeriesData: TimeSeriesData | null;
  /** nameFromLLM: the name is what the LLM wrote, not FRED's or the market's title. */
  allAvailableSeries: { id: string; name: string; type: string; nameFromLLM?: boolean }[];
}

export const DualAxisChart: React.FC<DualAxisChartProps> = ({
  primarySeriesData,
  allAvailableSeries,
}) => {
  const [secondaryId, setSecondaryId] = useState<string>('');
  const [secondaryData, setSecondaryData] = useState<TimeSeriesData | null>(null);
  const [loadingSecondary, setLoadingSecondary] = useState<boolean>(false);
  const [secondaryError, setSecondaryError] = useState<string | null>(null);
  const [isNormalized, setIsNormalized] = useState<boolean>(false);
  // Only the latest request's answer is shown: the chart never draws a
  // series other than the one in the selector.
  const requestSeq = useRef(0);

  // Default secondary: only when there's none yet, or it left the list. (It
  // used to be reset on every parent render, since the list is a new array
  // each time, overwriting the user's choice.)
  const candidateIds = allAvailableSeries.map((s) => s.id).join(',');
  useEffect(() => {
    if (!primarySeriesData) return;
    const others = allAvailableSeries.filter((s) => s.id !== primarySeriesData.id);
    if (!others.some((s) => s.id === secondaryId)) {
      setSecondaryId(others[0]?.id ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primarySeriesData?.id, candidateIds]);

  // Fetch secondary series data
  useEffect(() => {
    if (!secondaryId) return;
    const item = allAvailableSeries.find((s) => s.id === secondaryId);
    const isMacro = item?.type === 'macro';
    const req = ++requestSeq.current;

    setLoadingSecondary(true);
    setSecondaryData(null);
    setSecondaryError(null);
    const fetcher = isMacro ? fetchMacroData(secondaryId) : fetchMarketData(secondaryId, '2y');
    fetcher
      .then((res) => {
        if (req === requestSeq.current) setSecondaryData(res);
      })
      .catch((err) => {
        if (req === requestSeq.current) {
          setSecondaryError(err instanceof Error ? err.message : `No se pudo cargar ${secondaryId}`);
        }
      })
      .finally(() => {
        if (req === requestSeq.current) setLoadingSecondary(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secondaryId]);

  if (!primarySeriesData || primarySeriesData.points.length === 0) {
    return null;
  }

  // Align timestamps
  const pPoints = primarySeriesData.points;
  const sPoints = secondaryData?.points || [];

  const pMap = new Map(pPoints.map((p) => [p.timestamp, p.value]));
  const sMap = new Map(sPoints.map((s) => [s.timestamp, s.value]));

  // Intersection or union of dates (take union sorted)
  const allDates = Array.from(new Set([...pMap.keys(), ...sMap.keys()])).sort();
  // Filter dates where at least one has data (keep last 250 points for clarity)
  const recentDates = allDates.slice(-250);

  // Normalization logic Base 100 on first available point
  const pBase = pPoints[0]?.value || 1.0;
  const sBase = sPoints[0]?.value || 1.0;

  const pValues = recentDates.map((d) => {
    const val = pMap.get(d);
    if (val === undefined) return null;
    return isNormalized ? (val / pBase) * 100 : val;
  });

  const sValues = recentDates.map((d) => {
    const val = sMap.get(d);
    if (val === undefined) return null;
    return isNormalized ? (val / sBase) * 100 : val;
  });

  // Each series keeps its own frequency (4.14): on the union of dates a
  // monthly series only has values on its own dates. spanGaps joins a series'
  // consecutive observations without creating points in between, and
  // non-daily series show a marker on each real observation.
  const markerRadius = (d: TimeSeriesData | null) => (d?.frequency && d.frequency !== 'daily' ? 2.5 : 0);

  const chartData = {
    labels: recentDates,
    datasets: [
      {
        label: `${primarySeriesData.id} (${isNormalized ? 'Base 100' : seriesMetaText(primarySeriesData)})`,
        data: pValues,
        borderColor: '#38bdf8', // Cyan
        backgroundColor: '#38bdf8',
        yAxisID: isNormalized ? 'y' : 'yPrimary',
        borderWidth: 2,
        spanGaps: true,
        pointRadius: markerRadius(primarySeriesData),
        pointHoverRadius: 4,
        tension: 0.1,
      },
      ...(secondaryData
        ? [
            {
              label: `${secondaryData.id} (${isNormalized ? 'Base 100' : seriesMetaText(secondaryData)})`,
              data: sValues,
              borderColor: '#f59e0b', // Amber
              backgroundColor: '#f59e0b',
              yAxisID: isNormalized ? 'y' : 'ySecondary',
              borderWidth: 2,
              spanGaps: true,
              pointRadius: markerRadius(secondaryData),
              pointHoverRadius: 4,
              tension: 0.1,
            },
          ]
        : []),
    ],
  };

  const options: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          color: '#94a3b8',
          font: { size: 11, family: 'monospace' },
          boxWidth: 12,
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        borderWidth: 1,
      },
    },
    scales: isNormalized
      ? {
          x: {
            grid: { color: 'rgba(51, 65, 85, 0.25)' },
            ticks: { color: '#64748b', font: { size: 10, family: 'monospace' }, maxTicksLimit: 10 },
          },
          y: {
            grid: { color: 'rgba(51, 65, 85, 0.25)' },
            ticks: { color: '#64748b', font: { size: 10, family: 'monospace' } },
            title: { display: true, text: 'Índice Base 100 (T0 = 100)', color: '#64748b', font: { size: 11 } },
          },
        }
      : {
          x: {
            grid: { color: 'rgba(51, 65, 85, 0.25)' },
            ticks: { color: '#64748b', font: { size: 10, family: 'monospace' }, maxTicksLimit: 10 },
          },
          yPrimary: {
            type: 'linear',
            position: 'left',
            grid: { color: 'rgba(51, 65, 85, 0.25)' },
            ticks: { color: '#38bdf8', font: { size: 10, family: 'monospace' } },
            title: { display: true, text: `${primarySeriesData.id} (${seriesMetaText(primarySeriesData)})`, color: '#38bdf8' },
          },
          ySecondary: {
            type: 'linear',
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { color: '#f59e0b', font: { size: 10, family: 'monospace' } },
            // No right axis without a loaded series (never an empty or stale title).
            display: !!secondaryData,
            title: { display: true, text: `${secondaryData?.id || ''} (${seriesMetaText(secondaryData)})`, color: '#f59e0b' },
          },
        },
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-5">
      {/* Controls Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-2.5">
          <GitCompare className="h-5 w-5 text-cyan-400" />
          <div>
            <h3 className="text-base font-bold text-white">
              Gráfico Comparativo Dual-Axis & Multi-Escala
            </h3>
            <p className="text-xs text-slate-400">
              Superposición directa entre activos y series macro con doble eje Y independiente
            </p>
          </div>
        </div>

        <div className="flex items-center flex-wrap gap-3 text-xs">
          {/* Secondary Series Selector */}
          <div className="flex items-center space-x-2 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1">
            <span className="text-slate-400 font-medium">Comparar con:</span>
            <select
              value={secondaryId}
              onChange={(e) => setSecondaryId(e.target.value)}
              className="bg-transparent text-amber-300 font-mono font-bold focus:outline-none cursor-pointer"
            >
              {allAvailableSeries
                .filter((s) => s.id !== primarySeriesData.id)
                .map((s) => (
                  <option key={s.id} value={s.id} className="bg-slate-900 text-white">
                    {s.id} ({s.name}{s.nameFromLLM ? ', nombre según el LLM' : ''})
                  </option>
                ))}
            </select>
          </div>

          {/* Normalization Toggle */}
          <button
            onClick={() => setIsNormalized(!isNormalized)}
            className={`px-3 py-1 rounded-lg border text-xs font-medium transition-colors cursor-pointer ${
              isNormalized
                ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300 font-bold'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-white'
            }`}
          >
            {isNormalized ? '✓ Base 100 Sincronizada' : 'Doble Eje Y Independiente'}
          </button>
        </div>
      </div>

      <ExplainerPanel>
        <p>
          <strong className="text-slate-200">¿Para qué sirve comparar dos series con escalas distintas?</strong> Un
          ticker que cotiza en cientos de dólares y un índice macro que se mueve en unidades completamente distintas
          (por ejemplo, un índice de producción industrial) no se pueden poner en el mismo eje sin que uno aplaste
          visualmente al otro. Con un eje Y independiente para cada serie (o normalizando ambas a "Base 100" desde el
          mismo punto de partida), podés comparar la <em>forma</em> de sus movimientos — sus tendencias, giros y
          velocidad relativa — sin que la diferencia de escala numérica te distraiga.
        </p>
        <p>
          <strong className="text-slate-200">Qué buscar visualmente:</strong> ¿las dos curvas suben y bajan juntas
          (co-movimiento), o se despegan en algún tramo — una sigue subiendo mientras la otra se aplana o cae? Un
          despegue sostenido puede señalar que la relación que asumías entre esa acción y ese indicador macro se está
          debilitando o cambiando de régimen; una divergencia puntual y breve puede ser solo ruido de corto plazo. La
          vista "Base 100 Sincronizada" es la más útil para este tipo de comparación visual directa; el modo de doble
          eje independiente conserva las unidades originales de cada serie, útil cuando te importa el nivel absoluto y
          no solo la forma relativa.
        </p>
      </ExplainerPanel>

      {/* Chart Area */}
      <div className="relative h-[380px] w-full">
        {loadingSecondary && (
          <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px] z-10 flex items-center justify-center text-xs text-amber-400 font-mono">
            Cargando serie secundaria ({secondaryId})...
          </div>
        )}
        {secondaryError && (
          <div
            data-testid="dual-secondary-error"
            role="alert"
            className="absolute top-2 right-2 left-2 z-10 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/40 text-xs text-rose-200"
          >
            No se pudo cargar {secondaryId}: {secondaryError.replace(/\.+$/, '')}. El gráfico muestra solo{' '}
            {primarySeriesData.id}.
          </div>
        )}
        <Line data={chartData} options={options} />
      </div>

      {/* Footer Info */}
      <div className="flex justify-between items-center text-[11px] text-slate-500 font-mono pt-1">
        <span data-testid="dual-left">
          Eje Izquierdo (Cyan): {primarySeriesData.name} — {seriesMetaText(primarySeriesData)}
        </span>
        <span data-testid="dual-right">
          Eje Derecho (Ámbar):{' '}
          {secondaryData
            ? `${secondaryData.name} — ${seriesMetaText(secondaryData)}`
            : secondaryError
            ? `${secondaryId} — no se pudo cargar`
            : loadingSecondary
            ? `${secondaryId} — cargando…`
            : 'Selecciona una serie'}
        </span>
      </div>
    </div>
  );
};
