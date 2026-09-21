import React, { useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Bar } from 'react-chartjs-2';
import type { FundamentalsMetric } from '../services/api';
import { BarChart3 } from 'lucide-react';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

interface FundBarChartProps {
  metrics: FundamentalsMetric[];
  loading: boolean;
}

export const FundBarChart: React.FC<FundBarChartProps> = ({ metrics, loading }) => {
  const [selectedMetricType, setSelectedMetricType] = useState<'Capex' | 'Revenue'>('Capex');

  if (metrics.length === 0) {
    return (
      <div className="h-[280px] bg-slate-900/60 border border-slate-800 rounded-2xl flex items-center justify-center text-slate-500 text-xs">
        No hay datos fundamentales disponibles para los tickers seleccionados.
      </div>
    );
  }

  // Filter metrics based on selected metric type
  const filtered = metrics.filter((m) =>
    selectedMetricType === 'Capex' ? m.metric.includes('Capex') : m.metric.includes('Revenue')
  );

  // Extract unique periods (e.g. 2022, 2023, 2024, 2025) and unique tickers
  const periods = Array.from(new Set(filtered.map((m) => m.period))).sort();
  const tickers = Array.from(new Set(filtered.map((m) => m.ticker))).sort();

  // Color palette for tickers
  const colors = [
    '#38bdf8', // Cyan
    '#818cf8', // Indigo
    '#34d399', // Emerald
    '#fbbf24', // Amber
    '#f472b6', // Pink
    '#a78bfa', // Purple
  ];

  const datasets = tickers.map((ticker, idx) => {
    const color = colors[idx % colors.length];
    const data = periods.map((period) => {
      const match = filtered.find((m) => m.ticker === ticker && m.period === period);
      return match ? match.value : 0;
    });

    return {
      label: ticker,
      data,
      backgroundColor: color,
      borderRadius: 6,
    };
  });

  const chartData = {
    labels: periods,
    datasets,
  };

  const options: ChartOptions<'bar'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          color: '#94a3b8',
          font: { size: 10, family: 'monospace' },
          boxWidth: 10,
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        borderWidth: 1,
        callbacks: {
          label: (context) => {
            const val = context.parsed.y !== null ? context.parsed.y.toFixed(2) : '0.00';
            return ` ${context.dataset.label}: $${val}B USD`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: '#64748b', font: { size: 10, family: 'monospace' } },
      },
      y: {
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: { color: '#64748b', font: { size: 10, family: 'monospace' } },
        title: {
          display: true,
          text: 'Billions USD ($B)',
          color: '#64748b',
          font: { size: 10 },
        },
      },
    },
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2">
          <BarChart3 className="h-4 w-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200">
            Comparativa Fundamental ({selectedMetricType === 'Capex' ? 'Gasto en Capex' : 'Ingresos Totales'})
          </h3>
        </div>

        {/* Toggle Capex vs Revenue */}
        <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5 text-xs">
          <button
            onClick={() => setSelectedMetricType('Capex')}
            className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              selectedMetricType === 'Capex'
                ? 'bg-cyan-500/20 text-cyan-300 font-bold'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Capex
          </button>
          <button
            onClick={() => setSelectedMetricType('Revenue')}
            className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              selectedMetricType === 'Revenue'
                ? 'bg-cyan-500/20 text-cyan-300 font-bold'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            Ingresos
          </button>
        </div>
      </div>

      <div className="relative h-[250px] w-full">
        {loading && (
          <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px] z-10 flex items-center justify-center text-xs text-cyan-400 font-mono">
            Cargando fundamentales...
          </div>
        )}
        <Bar data={chartData} options={options} />
      </div>
      <p className="text-[11px] text-slate-500 italic text-right">
        * Cifras expresadas en miles de millones de USD (Billions).
      </p>
    </div>
  );
};
