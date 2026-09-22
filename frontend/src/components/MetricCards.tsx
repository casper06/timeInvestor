import React, { useState } from 'react';
import { TrendingUp, ShieldAlert, Target, ChevronDown, ChevronUp, BookOpen, Sparkles } from 'lucide-react';
import type { ThesisResponse, ForecastResponse, TimeSeriesData } from '../services/api';
import { LLMProviderBadge } from './LLMProviderBadge';

interface MetricCardsProps {
  thesisData: ThesisResponse | null;
  forecast: ForecastResponse | null;
  seriesData: TimeSeriesData | null;
  horizon: number;
  confidence: number;
}

export const MetricCards: React.FC<MetricCardsProps> = ({
  thesisData,
  forecast,
  seriesData,
  horizon,
  confidence,
}) => {
  const [showAllRationales, setShowAllRationales] = useState(false);

  // Compute quantitative stats from series and forecast
  const lastHist = seriesData?.points[seriesData.points.length - 1]?.value || 0;
  const targetVal = forecast?.values[forecast.values.length - 1] || lastHist;
  const delta = targetVal - lastHist;
  const pctChange = lastHist > 0 ? (delta / lastHist) * 100 : 0;
  const lowerTarget = forecast?.lower_bound[forecast.lower_bound.length - 1] || 0;
  const upperTarget = forecast?.upper_bound[forecast.upper_bound.length - 1] || 0;

  // Annualized CAGR projection
  const years = horizon / 365.25;
  const cagr = years > 0 && lastHist > 0 && targetVal > 0
    ? ((Math.pow(targetVal / lastHist, 1 / years) - 1) * 100)
    : 0;

  return (
    <div className="space-y-4">
      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Card 1: Target Projection */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-md">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs font-medium uppercase tracking-wider">Objetivo +{horizon}d</span>
            <Target className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="text-xl font-bold font-mono text-slate-100">
            {targetVal.toFixed(2)}
          </div>
          <div className={`text-xs font-mono font-medium mt-1 flex items-center gap-1 ${delta >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            <span>{delta >= 0 ? '▲ +' : '▼ '}{delta.toFixed(2)}</span>
            <span>({pctChange >= 0 ? '+' : ''}{pctChange.toFixed(1)}%)</span>
          </div>
        </div>

        {/* Card 2: Projected CAGR */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-md">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs font-medium uppercase tracking-wider">CAGR Anualizado</span>
            <TrendingUp className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-xl font-bold font-mono text-emerald-400">
            {cagr >= 0 ? '+' : ''}{cagr.toFixed(1)}%
          </div>
          <div className="text-[11px] text-slate-500 font-mono mt-1">
            Horizonte proyectivo {horizon} días
          </div>
        </div>

        {/* Card 3: Prediction Interval */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-md">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs font-medium uppercase tracking-wider">Rango {Math.round(confidence * 100)}% CI</span>
            <ShieldAlert className="h-4 w-4 text-amber-400" />
          </div>
          <div className="text-sm font-bold font-mono text-slate-200 mt-1">
            [{lowerTarget.toFixed(1)} — {upperTarget.toFixed(1)}]
          </div>
          <div className="text-[11px] text-slate-500 font-mono mt-1">
            Amplitud: ±{((upperTarget - lowerTarget) / 2).toFixed(1)}
          </div>
        </div>

        {/* Card 4: Model Info */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-md">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-xs font-medium uppercase tracking-wider">Motor Predictivo</span>
            <Sparkles className="h-4 w-4 text-indigo-400" />
          </div>
          <div className="text-sm font-bold font-mono text-indigo-300 truncate mt-1">
            {forecast?.model_name || 'TimesFM'}
          </div>
          <div
            className="text-[11px] text-slate-500 font-mono mt-1 line-clamp-2"
            title={forecast?.engine_selection_reason || undefined}
          >
            {forecast?.engine_selection_reason || 'Residuos estocásticos'}
          </div>
        </div>
      </div>

      {/* Thesis Synthesis & Rationale Accordion */}
      {thesisData && (
        <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start space-x-3">
              <div className="h-8 w-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                <BookOpen className="h-4 w-4 text-cyan-400" />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-slate-200">
                    Síntesis Cuantitativa de la Tesis
                  </h3>
                  <LLMProviderBadge providerUsed={thesisData.provider_used} fallbackReason={thesisData.fallback_reason} fallbackCategory={thesisData.fallback_category} />
                </div>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  {thesisData.summary}
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowAllRationales(!showAllRationales)}
              className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 font-medium flex-shrink-0 cursor-pointer"
            >
              <span>{showAllRationales ? 'Ocultar detalles' : 'Ver justificación por activo'}</span>
              {showAllRationales ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {/* Rationale Cards per Asset */}
          {showAllRationales && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3 border-t border-slate-800/80">
              {thesisData.tickers.map((t) => (
                <div
                  key={t.symbol}
                  className="bg-slate-950/70 border border-slate-800 rounded-xl p-3.5 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <span className="font-mono font-bold text-cyan-400 text-sm">
                        {t.symbol}
                      </span>
                      <span className="text-xs text-slate-300 font-medium">{t.name}</span>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                      {t.sector}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    <strong className="text-slate-300 font-medium">Rol: </strong>
                    {t.thesis_role}
                  </p>
                  {thesisData.rationales[t.symbol] && (
                    <p className="text-[11px] text-slate-500 italic border-l-2 border-cyan-500/30 pl-2">
                      {thesisData.rationales[t.symbol]}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
