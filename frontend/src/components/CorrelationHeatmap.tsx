import React, { useState, useEffect } from 'react';
import { Network, RefreshCw, Info } from 'lucide-react';
import { fetchCorrelations } from '../services/api';
import type { CorrelationMatrixResponse, TickerSuggestion, MacroSuggestion } from '../services/api';

interface CorrelationHeatmapProps {
  activeTickers: TickerSuggestion[];
  activeMacro: MacroSuggestion[];
}

export const CorrelationHeatmap: React.FC<CorrelationHeatmapProps> = ({
  activeTickers,
  activeMacro,
}) => {
  const [method, setMethod] = useState<'pearson' | 'spearman'>('pearson');
  const [period, setPeriod] = useState<string>('2y');
  const [data, setData] = useState<CorrelationMatrixResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [hoveredCell, setHoveredCell] = useState<{
    row: string;
    col: string;
    val: number;
  } | null>(null);

  const seriesIds = [
    ...activeTickers.map((t) => t.symbol),
    ...activeMacro.map((m) => m.series_id),
  ];

  const loadCorrelations = async () => {
    if (seriesIds.length < 2) return;
    setLoading(true);
    try {
      const res = await fetchCorrelations(seriesIds, period);
      setData(res);
    } catch (err) {
      console.error('Error fetching correlations:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCorrelations();
  }, [activeTickers, activeMacro, period]);

  const getColor = (val: number) => {
    if (val >= 0.75) return 'bg-emerald-500/80 text-white font-bold';
    if (val >= 0.4) return 'bg-emerald-500/40 text-emerald-200 font-semibold';
    if (val >= 0.15) return 'bg-cyan-500/20 text-cyan-300';
    if (val <= -0.75) return 'bg-rose-600/80 text-white font-bold';
    if (val <= -0.4) return 'bg-rose-500/40 text-rose-200 font-semibold';
    if (val <= -0.15) return 'bg-amber-500/20 text-amber-300';
    return 'bg-slate-800/60 text-slate-400';
  };

  if (seriesIds.length < 2) {
    return (
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-8 text-center text-xs text-slate-500">
        Agrega al menos 2 activos o series macro para generar la matriz de correlación cruzada.
      </div>
    );
  }

  const matrix = method === 'pearson' ? data?.pearson_matrix : data?.spearman_matrix;
  const ids = data?.series_ids || [];

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-5">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-2.5">
          <Network className="h-5 w-5 text-indigo-400" />
          <div>
            <h3 className="text-base font-bold text-white">
              Matriz de Correlación Multiserie ({ids.length} activos)
            </h3>
            <p className="text-xs text-slate-400">
              Alineación temporal de series de mercado con indicadores macroeconómicos
            </p>
          </div>
        </div>

        <div className="flex items-center flex-wrap gap-2 text-xs">
          {/* Method Toggle */}
          <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5">
            <button
              onClick={() => setMethod('pearson')}
              className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
                method === 'pearson'
                  ? 'bg-indigo-600 text-white font-bold'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Pearson (Lineal)
            </button>
            <button
              onClick={() => setMethod('spearman')}
              className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
                method === 'spearman'
                  ? 'bg-indigo-600 text-white font-bold'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Spearman (Rangos)
            </button>
          </div>

          {/* Period */}
          <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5">
            {['1y', '2y', '5y'].map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-2 py-1 rounded text-[11px] font-mono ${
                  period === p ? 'bg-slate-800 text-cyan-400 font-bold' : 'text-slate-400 hover:text-white'
                }`}
              >
                {p.toUpperCase()}
              </button>
            ))}
          </div>

          <button
            onClick={loadCorrelations}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Recalcular matriz"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Heatmap Table */}
      <div className="overflow-x-auto">
        {loading && (
          <div className="py-12 text-center text-xs text-indigo-400 font-mono">
            Alineando series temporales y computando coeficientes...
          </div>
        )}

        {!loading && matrix && (
          <table className="w-full text-xs font-mono border-collapse">
            <thead>
              <tr>
                <th className="p-2.5 text-left text-slate-500 border-b border-slate-800">Serie</th>
                {ids.map((id) => (
                  <th
                    key={id}
                    className="p-2.5 text-center text-slate-300 font-bold border-b border-slate-800"
                  >
                    {id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ids.map((rowId, i) => (
                <tr key={rowId} className="border-b border-slate-800/40">
                  <td className="p-2.5 font-bold text-slate-300 text-left bg-slate-950/40">
                    <div className="flex flex-col">
                      <span>{rowId}</span>
                      <span className="text-[10px] text-slate-500 font-sans font-normal truncate max-w-[140px]">
                        {data?.series_names[rowId] || ''}
                      </span>
                    </div>
                  </td>
                  {ids.map((colId, j) => {
                    const val = matrix[i]?.[j] ?? 0;
                    return (
                      <td
                        key={colId}
                        onMouseEnter={() => setHoveredCell({ row: rowId, col: colId, val })}
                        onMouseLeave={() => setHoveredCell(null)}
                        className={`p-2.5 text-center transition-transform hover:scale-105 cursor-pointer rounded-sm ${getColor(
                          val
                        )}`}
                      >
                        {val.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail Tooltip Bar & Legend */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-3 border-t border-slate-800 text-xs text-slate-400">
        <div className="flex items-center space-x-2">
          {hoveredCell ? (
            <span className="font-mono text-cyan-300 bg-slate-950 px-2.5 py-1 rounded-lg border border-slate-800">
              <strong>{hoveredCell.row}</strong> ↔ <strong>{hoveredCell.col}</strong>:{' '}
              {hoveredCell.val > 0 ? '+' : ''}
              {hoveredCell.val.toFixed(3)} (
              {hoveredCell.val > 0.6
                ? 'Fuerte co-movimiento directo'
                : hoveredCell.val < -0.4
                ? 'Relación inversa / Cobertura'
                : 'Correlación débil o desacoplada'}
              )
            </span>
          ) : (
            <span className="text-slate-500 italic text-[11px] flex items-center gap-1">
              <Info className="h-3.5 w-3.5" /> Pasa el cursor sobre una celda para ver la relación de
              paridad.
            </span>
          )}
        </div>

        {/* Legend */}
        <div className="flex items-center space-x-2 text-[10px] font-mono">
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500" /> -1.0
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-700" /> 0.0
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> +1.0
          </span>
          {data && (
            <span className="text-slate-500 pl-2">
              ({data.common_observations} observaciones coincidentes)
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
