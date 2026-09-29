import React, { useEffect, useState } from 'react';
import { X, Sparkles, Tag, ArrowRight } from 'lucide-react';
import type { TickerSuggestion, MacroSuggestion, FredCandidate } from '../services/api';

interface ThesisBarProps {
  onAnalyze: (thesis: string) => void;
  loading: boolean;
  tickers: TickerSuggestion[];
  macroSeries: MacroSuggestion[];
  /** The user picked a real FRED series to replace an ID that doesn't exist (4.11). */
  onChooseCandidate?: (missingId: string, candidate: FredCandidate) => void;
  onAddTicker: (ticker: string) => void;
  onRemoveTicker: (symbol: string) => void;
  onAddMacro: (seriesId: string) => void;
  onRemoveMacro: (seriesId: string) => void;
  /** Why the last "+ FRED ID" wasn't added (e.g. it doesn't exist on FRED). */
  macroAddError?: string | null;
  /** Who translates the thesis, shown while it runs (4.10: a translation takes 30-190 s). */
  providerLabel?: string;
}

// Examples from different sectors (4.10): they used to be all technology,
// AI and electricity.
const PRESET_THESES = [
  'Demanda eléctrica por centros de datos de IA',
  'Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.',
  'La desaceleración del consumo golpea al comercio minorista',
  'La sequía encarece los granos y favorece a los productores agrícolas',
];

/** Seconds since the translation started (median 30-90 s depending on the
 * model, docs/results/thesis_prompt_v2_2026-09-28.md): said, not a spinner
 * alone. Mounted only while translating, so each run starts at 0. */
const TranslatingIndicator: React.FC<{ providerLabel?: string }> = ({ providerLabel }) => {
  const [startedAt] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  return (
    <p data-testid="translating-indicator" role="status" className="text-xs text-cyan-300 font-mono">
      Traduciendo la tesis con {providerLabel || 'el proveedor configurado'}… {elapsed} s
    </p>
  );
};

/**
 * 4.11: a FRED ID is shown for what it is. A verified one looks like it always
 * did; a searched-for replacement and a discarded one are visibly different, so
 * an ID the LLM invented can never pass as one FRED confirmed.
 */
function groundingChipClass(m: MacroSuggestion): string {
  if (m.grounding === 'descartado') return 'bg-rose-500/10 text-rose-300 border-rose-500/30 line-through';
  if (m.grounding === 'sugerido_por_busqueda') {
    return m.chosen_by_user
      ? 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20'
      : 'bg-amber-500/10 text-amber-200 border-amber-500/30';
  }
  if (!m.grounding) return 'bg-slate-500/10 text-slate-300 border-slate-500/30';
  return 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20';
}

export const ThesisBar: React.FC<ThesisBarProps> = ({
  onAnalyze,
  loading,
  tickers,
  macroSeries,
  onChooseCandidate,
  onAddTicker,
  onRemoveTicker,
  onAddMacro,
  onRemoveMacro,
  macroAddError = null,
  providerLabel,
}) => {
  const [thesisText, setThesisText] = useState('');

  const [newTicker, setNewTicker] = useState('');
  const [newMacro, setNewMacro] = useState('');
  // 4.11: IDs that don't exist on FRED and still have no replacement chosen.
  const pendingMacro = macroSeries.filter(
    (m) => m.grounding === 'sugerido_por_busqueda' && !m.chosen_by_user && (m.candidates?.length ?? 0) > 0,
  );

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
            placeholder="Escribí tu tesis de inversión en lenguaje natural…"
            aria-label="Tesis de inversión"
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
      {loading && <TranslatingIndicator providerLabel={providerLabel} />}

      {/* Preset Suggestions */}
      <div className="flex items-center flex-wrap gap-2 text-xs">
        <span className="text-slate-500 flex items-center gap-1 font-medium">
          <Tag className="h-3.5 w-3.5" /> Ejemplos:
        </span>
        {PRESET_THESES.map((preset, idx) => (
          <button
            key={idx}
            type="button"
            // Only fills the box: analyzing is an explicit action ("Analizar Tesis").
            onClick={() => setThesisText(preset)}
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
                data-testid={`macro-chip-${m.series_id}`}
                data-grounding={m.grounding ?? 'sin_verificar'}
                title={m.grounding_note ?? m.fred_title ?? undefined}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-mono font-medium shadow-sm ${groundingChipClass(m)}`}
              >
                {m.grounding === 'sugerido_por_busqueda' && !m.chosen_by_user
                  ? m.proposed_series_id || m.series_id
                  : m.series_id}
                {m.grounding === 'sugerido_por_busqueda' && !m.chosen_by_user && (
                  <span data-testid={`macro-pending-${m.proposed_series_id || m.series_id}`} className="font-sans text-[10px] font-semibold">
                    sin reemplazo elegido
                  </span>
                )}
                {m.grounding === 'sugerido_por_busqueda' && m.chosen_by_user && (
                  <span data-testid={`macro-chosen-${m.series_id}`} className="font-sans text-[10px] font-semibold">
                    elegida por vos
                  </span>
                )}
                {m.grounding === 'descartado' && (
                  <span data-testid={`macro-discarded-${m.series_id}`} className="font-sans text-[10px] font-semibold">
                    no existe en FRED
                  </span>
                )}
                {!m.grounding && (
                  <span data-testid={`macro-unverified-${m.series_id}`} className="font-sans text-[10px] font-semibold">
                    sin verificar
                  </span>
                )}
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
            {macroAddError && (
              <span data-testid="macro-add-error" role="alert" className="basis-full text-[11px] text-rose-400">
                {macroAddError}
              </span>
            )}
          </div>

          {/*
            4.11: an ID the LLM invented is NOT replaced automatically. FRED's
            own candidates are offered with the metadata needed to tell them
            apart (title, frequency, SA/NSA, date range), and the user picks —
            or leaves the series out. Until then it stays out of the analysis.
          */}
          {pendingMacro.map((m) => {
            const missingId = m.proposed_series_id || m.series_id;
            return (
              <div
                key={`pending-${missingId}`}
                data-testid={`macro-candidates-${missingId}`}
                className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5 space-y-2"
              >
                <p role="alert" className="text-[11px] text-amber-200">
                  <span className="font-mono font-semibold">'{missingId}'</span> no existe en FRED; elegí un
                  reemplazo o seguí sin esta serie.
                  {m.searched_concept && (
                    <span className="text-amber-200/70"> Buscado en FRED: "{m.searched_concept}".</span>
                  )}
                </p>
                <ul className="space-y-1">
                  {(m.candidates ?? []).map((c) => (
                    <li key={c.series_id} className="flex items-start justify-between gap-2">
                      <span className="text-[11px] text-slate-300">
                        <span className="font-mono font-semibold text-slate-100">{c.series_id}</span>{' '}
                        {c.title}
                        <span className="block text-[10px] text-slate-400">
                          {[
                            c.frequency,
                            c.seasonal_adjustment,
                            c.observation_start && c.observation_end
                              ? `${c.observation_start} → ${c.observation_end}`
                              : null,
                            c.units,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <button
                        type="button"
                        data-testid={`macro-choose-${missingId}-${c.series_id}`}
                        onClick={() => onChooseCandidate?.(missingId, c)}
                        className="shrink-0 px-2 py-0.5 rounded-md bg-amber-500/20 text-amber-100 border border-amber-500/40 text-[11px] font-semibold hover:bg-amber-500/30 transition-colors"
                      >
                        Agregar
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
