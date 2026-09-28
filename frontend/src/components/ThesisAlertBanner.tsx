import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type { TimeSeriesData, ForecastResponse } from '../services/api';
import { formatValue, isPriceSeries } from '../utils/valueFormat';

interface ThesisAlertBannerProps {
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  thesisStatus: string;
}

export const ThesisAlertBanner: React.FC<ThesisAlertBannerProps> = ({
  seriesData,
  forecast,
  thesisStatus,
}) => {
  if (!seriesData || !forecast || seriesData.points.length === 0 || forecast.lower_bound.length === 0) {
    return null;
  }

  const lastPrice = seriesData.points[seriesData.points.length - 1].value;
  const lowerBound = forecast.lower_bound[0]; // Nearest lower bound
  const isBreached = lastPrice < lowerBound * 0.98; // Margin of breach

  const isUnderStress = thesisStatus === 'Bajo estrés' || isBreached;

  if (!isUnderStress) {
    return null;
  }
  // The band's real level (TimesFM only has 80%), never a fixed 95%.
  const level = forecast.interval_level != null ? ` ${Math.round(forecast.interval_level * 100)}%` : '';
  const price = isPriceSeries(seriesData);

  return (
    <div className="rounded-2xl p-4 bg-gradient-to-r from-rose-950/60 via-slate-900 to-slate-900 border border-rose-500/40 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
      <div className="flex items-start space-x-3">
        <div className="h-8 w-8 rounded-xl bg-rose-500/20 border border-rose-500/40 flex items-center justify-center flex-shrink-0 mt-0.5">
          <AlertTriangle className="h-4 w-4 text-rose-400 animate-pulse" />
        </div>
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            <span className="font-bold text-rose-300 uppercase tracking-wide">
              Alerta Cuantitativa • Tesis Bajo Estrés
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-500/20 text-rose-200 border border-rose-500/30">
              Desvío de Soporte{level}
            </span>
          </div>
          <p className="text-slate-300 leading-relaxed text-[11px]">
            {price ? 'El activo' : 'La serie'} <strong className="text-white font-mono">{seriesData.id}</strong> registra un{' '}
            {price ? 'último cierre' : 'último valor'} de{' '}
            <strong className="text-rose-300 font-mono">{formatValue(lastPrice, seriesData)}</strong>, perforando la banda
            inferior proyectada por {forecast.model_name} (
            <strong className="text-slate-200 font-mono">{formatValue(lowerBound, seriesData)}</strong>). Las premisas
            fundamentales pueden haber cambiado.
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-2 flex-shrink-0 pl-11 md:pl-0">
        <span className="text-[11px] text-rose-300/80 font-medium">
          Acción recomendada: Auditar cuellos de botella macro o rebalancear ponderación.
        </span>
      </div>
    </div>
  );
};
