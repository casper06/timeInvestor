import React, { useState } from 'react';
import {
  Sparkles,
  Bot,
  TrendingUp,
  Target,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  Lightbulb,
} from 'lucide-react';
import { interpretSituation } from '../services/api';
import { LLMProviderBadge } from './LLMProviderBadge';
import type {
  InterpretationContext,
  InterpretationResponse,
  TimeSeriesData,
  ForecastResponse,
  FundamentalsMetric,
  TickerSuggestion,
  MacroSuggestion,
} from '../services/api';

interface ThesisCopilotProps {
  thesis: string;
  activeSeriesId: string;
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  horizon: number;
  confidence: number;
  activeTickers: TickerSuggestion[];
  activeMacro: MacroSuggestion[];
  fundamentals: FundamentalsMetric[];
  onSelectSeries: (seriesId: string) => void;
  onInterpretationComplete?: (res: InterpretationResponse) => void;
}

export const ThesisCopilot: React.FC<ThesisCopilotProps> = ({
  thesis,
  activeSeriesId,
  seriesData,
  forecast,
  horizon,
  confidence,
  activeTickers,
  activeMacro,
  fundamentals,
  onSelectSeries,
  onInterpretationComplete,
}) => {
  const [loading, setLoading] = useState(false);
  const [interpretation, setInterpretation] = useState<InterpretationResponse | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  // Compute key stats for context
  const lastPrice = seriesData?.points[seriesData.points.length - 1]?.value || 0;
  const projectedTarget = forecast?.values[forecast.values.length - 1] || lastPrice;
  const lowerBound = forecast?.lower_bound[forecast.lower_bound.length - 1] || 0;
  const upperBound = forecast?.upper_bound[forecast.upper_bound.length - 1] || 0;
  const years = horizon / 365.25;
  const cagr =
    years > 0 && lastPrice > 0 && projectedTarget > 0
      ? (Math.pow(projectedTarget / lastPrice, 1 / years) - 1) * 100
      : 0;

  // Build Capex summary
  const capexSummary: Record<string, number> = {};
  fundamentals
    .filter((m) => m.metric.includes('Capex'))
    .forEach((m) => {
      capexSummary[`${m.ticker}_${m.period}`] = m.value;
    });

  const handleRunInterpretation = async () => {
    setLoading(true);
    try {
      const ctx: InterpretationContext = {
        thesis,
        active_series_id: activeSeriesId,
        active_series_name: seriesData?.name || activeSeriesId,
        last_price: lastPrice,
        projected_target: projectedTarget,
        horizon,
        confidence,
        lower_bound: lowerBound,
        upper_bound: upperBound,
        cagr,
        other_tickers: activeTickers.map((t) => t.symbol).filter((s) => s !== activeSeriesId),
        macro_series: activeMacro.map((m) => m.series_id).filter((s) => s !== activeSeriesId),
        capex_summary: capexSummary,
      };

      const res = await interpretSituation(ctx);
      setInterpretation(res);
      onInterpretationComplete?.(res);
      setCollapsed(false);
    } catch (err) {
      console.error('Error running thesis interpretation:', err);
      alert(err instanceof Error ? err.message : 'Error al interpretar la situación');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950/40 border border-indigo-500/30 rounded-2xl p-5 shadow-2xl shadow-indigo-950/20 space-y-4">
      {/* Header with Callout Action */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-indigo-500/20 pb-3">
        <div className="flex items-center space-x-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Bot className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100 flex items-center gap-1.5">
                Copiloto / Intérprete de Tesis
              </h3>
              {interpretation ? (
                <LLMProviderBadge providerUsed={interpretation.provider_used} fallbackReason={interpretation.fallback_reason} fallbackCategory={interpretation.fallback_category} />
              ) : (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-medium">
                  Asistente LLM
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Traducción conceptual de curvas, alineación con tu hipótesis y detección de cuellos de botella
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          {interpretation && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
              title={collapsed ? 'Expandir interpretación' : 'Colapsar tarjeta'}
            >
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
            </button>
          )}

          <button
            onClick={handleRunInterpretation}
            disabled={loading || !seriesData}
            className="inline-flex items-center justify-center space-x-2 px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-xs font-medium shadow-md shadow-indigo-500/25 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer group"
          >
            {loading ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Interpretando {activeSeriesId}...</span>
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 text-indigo-200 group-hover:rotate-12 transition-transform" />
                <span>Interpretar Situación</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* When no interpretation is generated yet */}
      {!interpretation && !loading && (
        <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
          <HelpCircle className="h-4 w-4 text-indigo-400" />
          <span>
            Haz clic en <strong>"Interpretar Situación"</strong> para que el Copiloto evalúe las proyecciones de{' '}
            <strong className="text-cyan-400">{activeSeriesId}</strong> y Capex en relación a tu tesis.
          </span>
        </div>
      )}

      {/* Loading state indicator */}
      {loading && !interpretation && (
        <div className="p-6 rounded-xl bg-slate-950/40 border border-indigo-500/20 text-center text-xs text-indigo-300 font-mono flex flex-col items-center justify-center space-y-2">
          <div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
          <span>Sintetizando telemetría cuantitativa y validando hipótesis con el modelo...</span>
        </div>
      )}

      {/* Structured Callout Card */}
      {interpretation && !collapsed && (
        <div className="space-y-3 pt-1">
          {/* Section A: Qué dicen los datos */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-1.5 shadow-inner">
            <div className="flex items-center space-x-2 text-cyan-400 text-xs font-semibold uppercase tracking-wider">
              <TrendingUp className="h-4 w-4" />
              <span>a) Qué dicen los datos</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed pl-6">
              {interpretation.what_data_says}
            </p>
          </div>

          {/* Section B: Alineación con tu tesis */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-1.5 shadow-inner">
            <div className="flex items-center space-x-2 text-indigo-400 text-xs font-semibold uppercase tracking-wider">
              <Target className="h-4 w-4" />
              <span>b) Alineación con tu tesis</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed pl-6">
              {interpretation.thesis_alignment}
            </p>
          </div>

          {/* Section C: Qué serie mirar a continuación */}
          <div className="p-4 rounded-xl bg-gradient-to-r from-slate-950/90 to-purple-950/20 border border-purple-500/30 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-purple-400 text-xs font-semibold uppercase tracking-wider">
                <Lightbulb className="h-4 w-4" />
                <span>c) Qué serie mirar a continuación</span>
              </div>
              {interpretation.suggested_series_id && (
                <button
                  onClick={() => onSelectSeries(interpretation.suggested_series_id!)}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 border border-purple-500/40 text-xs font-mono font-bold transition-all cursor-pointer shadow-sm group"
                >
                  <span>Explorar {interpretation.suggested_series_id}</span>
                  <ArrowRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 transition-transform" />
                </button>
              )}
            </div>
            <p className="text-xs text-slate-300 leading-relaxed pl-6">
              {interpretation.next_series_suggestion}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
