import React, { useState } from 'react';
import { X, Sparkles, Tag, ArrowRight } from 'lucide-react';
import type { TickerSuggestion, MacroSuggestion } from '../services/api';

interface ThesisBarProps {
  onAnalyze: (thesis: string) => void;
  loading: boolean;
  tickers: TickerSuggestion[];
  macroSeries: MacroSuggestion[];
  onAddTicker: (ticker: string) => void;
  onRemoveTicker: (symbol: string) => void;
  onAddMacro: (seriesId: string) => void;
  onRemoveMacro: (seriesId: string) => void;
}

const PRESET_THESES = [
  'Demanda eléctrica por centros de datos de IA',
  'Superciclo de Capex en semiconductores avanzados y litografía',
  'Transición y expansión de la red eléctrica con almacenamiento en baterías',
  'Impacto de tasas de interés y curva de rendimientos en múltiplos tecnológicos',
];

export const ThesisBar: React.FC<ThesisBarProps> = ({
  onAnalyze,
  loading,
  tickers,
  macroSeries,
  onAddTicker,
  onRemoveTicker,
  onAddMacro,
  onRemoveMacro,
}) => {
  const [thesisText, setThesisText] = useState('Demanda eléctrica por centros de datos de IA');
  const [newTicker, setNewTicker] = useState('');
  const [newMacro, setNewMacro] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (thesisText.trim()) {
      onAnalyze(thesisText.trim());
    }
  };

  const handleAddTickerSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTicker.trim()) {
      onAddTicker(newTicker.trim().toUpperCase());
      setNewTicker('');
    }
  };

  const handleAddMacroSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newMacro.trim()) {
      onAddMacro(newMacro.trim().toUpperCase());
      setNewMacro('');
    }
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      {/* Search / Thesis Input */}
      <form onSubmit={handleSubmit} className="relative flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
            <Sparkles className="h-5 w-5 text-cyan-400" />
          </div>
          <input
            type="text"
            value={thesisText}
            onChange={(e) => setThesisText(e.target.value)}
            placeholder="Introduce tu tesis de inversión en lenguaje natural (ej. Demanda eléctrica por IA)..."
            className="w-full pl-11 pr-4 py-3 bg-slate-950 border border-slate-700/80 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 text-sm transition-all shadow-inner"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !thesisText.trim()}
          className="inline-flex items-center justify-center px-6 py-3 bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white font-medium rounded-xl text-sm transition-all shadow-lg shadow-cyan-600/25 disabled:opacity-50 disabled:cursor-not-allowed group cursor-pointer"
        >
          {loading ? (
            <div className="flex items-center space-x-2">
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Procesando...</span>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <span>Analizar Tesis</span>
              <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
            </div>
          )}
        </button>
      </form>

      {/* Preset Suggestions */}
      <div className="flex items-center flex-wrap gap-2 text-xs">
        <span className="text-slate-500 flex items-center gap-1 font-medium">
          <Tag className="h-3.5 w-3.5" /> Ejemplos:
        </span>
        {PRESET_THESES.map((preset, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => {
              setThesisText(preset);
              onAnalyze(preset);
            }}
            className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 hover:text-white border border-slate-700/60 transition-colors cursor-pointer"
          >
            {preset}
          </button>
        ))}
      </div>

      {/* Tickers & Macro Series Management */}
      <div className="pt-3 border-t border-slate-800/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Tickers Chips */}
        <div className="space-y-1.5 flex-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Activos en Cartera ({tickers.length})
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {tickers.map((t) => (
              <span
                key={t.symbol}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 text-xs font-mono font-medium shadow-sm"
              >
                {t.symbol}
                <span className="text-[10px] text-cyan-400/70">({Math.round(t.weight * 100)}%)</span>
                <button
                  type="button"
                  onClick={() => onRemoveTicker(t.symbol)}
                  className="hover:bg-cyan-500/20 rounded p-0.5 ml-0.5 text-cyan-400 hover:text-cyan-200 transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}

            {/* Manual Ticker Add */}
            <form onSubmit={handleAddTickerSubmit} className="inline-flex items-center">
              <input
                type="text"
                value={newTicker}
                onChange={(e) => setNewTicker(e.target.value)}
                placeholder="+ Ticker (ej. AMD)"
                className="w-28 px-2 py-0.5 bg-slate-950/60 border border-slate-700 rounded-lg text-xs text-slate-200 uppercase font-mono placeholder:normal-case placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </form>
          </div>
        </div>

        {/* Macro Series Chips */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Indicadores FRED Macro ({macroSeries.length})
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {macroSeries.map((m) => (
              <span
                key={m.series_id}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-xs font-mono font-medium shadow-sm"
              >
                {m.series_id}
                <button
                  type="button"
                  onClick={() => onRemoveMacro(m.series_id)}
                  className="hover:bg-indigo-500/20 rounded p-0.5 ml-0.5 text-indigo-400 hover:text-indigo-200 transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}

            {/* Manual Macro Add */}
            <form onSubmit={handleAddMacroSubmit} className="inline-flex items-center">
              <input
                type="text"
                value={newMacro}
                onChange={(e) => setNewMacro(e.target.value)}
                placeholder="+ FRED ID"
                className="w-24 px-2 py-0.5 bg-slate-950/60 border border-slate-700 rounded-lg text-xs text-slate-200 uppercase font-mono placeholder:normal-case placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
