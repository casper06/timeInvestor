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
} from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { GitCompare } from 'lucide-react';
import { fetchMarketData, fetchMacroData } from '../services/api';
import type { TimeSeriesData } from '../services/api';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

interface DualAxisChartProps {
  primarySeriesData: TimeSeriesData | null;
  allAvailableSeries: { id: string; name: string; type: string }[];
}

export const DualAxisChart: React.FC<DualAxisChartProps> = ({
  primarySeriesData,
  allAvailableSeries,
}) => {
  const [secondaryId, setSecondaryId] = useState<string>('');
  const [secondaryData, setSecondaryData] = useState<TimeSeriesData | null>(null);
  const [loadingSecondary, setLoadingSecondary] = useState<boolean>(false);
  const [isNormalized, setIsNormalized] = useState<boolean>(false);

  // Default secondary to something different from primary
  useEffect(() => {
    if (primarySeriesData && allAvailableSeries.length > 1) {
      const candidate = allAvailableSeries.find((s) => s.id !== primarySeriesData.id);
      if (candidate) {
        setSecondaryId(candidate.id);
      }
    }
  }, [primarySeriesData, allAvailableSeries]);

  // Fetch secondary series data
  useEffect(() => {
    if (!secondaryId) return;
    const item = allAvailableSeries.find((s) => s.id === secondaryId);
    const isMacro = item?.type === 'macro';

    setLoadingSecondary(true);
    const fetcher = isMacro ? fetchMacroData(secondaryId) : fetchMarketData(secondaryId, '2y');
    fetcher
      .then((res) => setSecondaryData(res))
      .catch((err) => console.error(err))
      .finally(() => setLoadingSecondary(false));
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

  const chartData = {
    labels: recentDates,
    datasets: [
      {
        label: `${primarySeriesData.id} (${isNormalized ? 'Base 100' : primarySeriesData.unit})`,
        data: pValues,
        borderColor: '#38bdf8', // Cyan
        backgroundColor: '#38bdf8',
        yAxisID: isNormalized ? 'y' : 'yPrimary',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.1,
      },
      ...(secondaryData
        ? [
            {
              label: `${secondaryData.id} (${isNormalized ? 'Base 100' : secondaryData.unit})`,
              data: sValues,
              borderColor: '#f59e0b', // Amber
              backgroundColor: '#f59e0b',
              yAxisID: isNormalized ? 'y' : 'ySecondary',
              borderWidth: 2,
              pointRadius: 0,
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
            title: { display: true, text: `${primarySeriesData.id} (${primarySeriesData.unit})`, color: '#38bdf8' },
          },
          ySecondary: {
            type: 'linear',
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: { color: '#f59e0b', font: { size: 10, family: 'monospace' } },
            title: { display: true, text: `${secondaryData?.id || ''} (${secondaryData?.unit || ''})`, color: '#f59e0b' },
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
                    {s.id} ({s.name})
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

      {/* Chart Area */}
      <div className="relative h-[380px] w-full">
        {loadingSecondary && (
          <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px] z-10 flex items-center justify-center text-xs text-amber-400 font-mono">
            Cargando serie secundaria ({secondaryId})...
          </div>
        )}
        <Line data={chartData} options={options} />
      </div>

      {/* Footer Info */}
      <div className="flex justify-between items-center text-[11px] text-slate-500 font-mono pt-1">
        <span>Eje Izquierdo (Cyan): {primarySeriesData.name}</span>
        <span>Eje Derecho (Ámbar): {secondaryData?.name || 'Selecciona una serie'}</span>
      </div>
    </div>
  );
};
