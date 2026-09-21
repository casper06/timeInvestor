import React, { useState } from 'react';
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js';
import type { ChartOptions } from 'chart.js';
import { Doughnut } from 'react-chartjs-2';
import type { TickerSuggestion } from '../services/api';
import { PieChart } from 'lucide-react';

ChartJS.register(ArcElement, Tooltip, Legend);

interface ExposureDonutProps {
  tickers: TickerSuggestion[];
}

export const ExposureDonut: React.FC<ExposureDonutProps> = ({ tickers }) => {
  const [viewMode, setViewMode] = useState<'sector' | 'asset'>('sector');

  if (tickers.length === 0) {
    return (
      <div className="h-[280px] bg-slate-900/60 border border-slate-800 rounded-2xl flex items-center justify-center text-slate-500 text-xs">
        Sin activos para calcular exposición.
      </div>
    );
  }

  // Aggregate by sector or asset
  let labels: string[] = [];
  let dataValues: number[] = [];

  if (viewMode === 'sector') {
    const sectorMap: Record<string, number> = {};
    tickers.forEach((t) => {
      sectorMap[t.sector] = (sectorMap[t.sector] || 0) + t.weight;
    });
    labels = Object.keys(sectorMap);
    dataValues = Object.values(sectorMap).map((v) => Math.round(v * 100));
  } else {
    labels = tickers.map((t) => t.symbol);
    dataValues = tickers.map((t) => Math.round(t.weight * 100));
  }

  const backgroundColors = [
    '#06b6d4', // Cyan
    '#6366f1', // Indigo
    '#10b981', // Emerald
    '#f59e0b', // Amber
    '#ec4899', // Pink
    '#8b5cf6', // Purple
    '#3b82f6', // Blue
  ];

  const chartData = {
    labels,
    datasets: [
      {
        data: dataValues,
        backgroundColor: backgroundColors.slice(0, labels.length),
        borderColor: '#0f172a',
        borderWidth: 2,
        hoverOffset: 6,
      },
    ],
  };

  const options: ChartOptions<'doughnut'> = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '70%',
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: '#cbd5e1',
          font: { size: 10, family: 'monospace' },
          boxWidth: 10,
          usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: '#0f172a',
        borderColor: '#334155',
        borderWidth: 1,
        callbacks: {
          label: (context) => ` ${context.label}: ${context.parsed}%`,
        },
      },
    },
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2">
          <PieChart className="h-4 w-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200">
            {viewMode === 'sector' ? 'Distribución Sectorial' : 'Ponderación por Activo'}
          </h3>
        </div>

        {/* Mode Toggle */}
        <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5 text-xs">
          <button
            onClick={() => setViewMode('sector')}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              viewMode === 'sector' ? 'bg-cyan-500/20 text-cyan-300 font-bold' : 'text-slate-400 hover:text-white'
            }`}
          >
            Sector
          </button>
          <button
            onClick={() => setViewMode('asset')}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              viewMode === 'asset' ? 'bg-cyan-500/20 text-cyan-300 font-bold' : 'text-slate-400 hover:text-white'
            }`}
          >
            Activos
          </button>
        </div>
      </div>

      <div className="relative h-[250px] w-full flex items-center justify-center">
        <Doughnut data={chartData} options={options} />
      </div>
      <div className="text-[11px] text-slate-500 text-center font-mono">
        Total Exposición Asignada: 100%
      </div>
    </div>
  );
};
