import React from 'react';
import { Gauge, ArrowUpRight, ArrowDownRight, Minus, Activity, ShieldAlert, Compass } from 'lucide-react';
import type { TimeSeriesData, ForecastResponse } from '../services/api';

interface StatisticalTelemetryProps {
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  horizon: number;
  confidence: number;
}

export const StatisticalTelemetry: React.FC<StatisticalTelemetryProps> = ({
  seriesData,
  forecast,
  horizon,
  confidence,
}) => {
  if (!seriesData || seriesData.points.length < 2 || !forecast || forecast.values.length === 0) {
    return null;
  }

  const points = seriesData.points;
  const lastPrice = points[points.length - 1].value;
  const target = forecast.values[forecast.values.length - 1];
  const delta = target - lastPrice;
  const deltaPct = lastPrice > 0 ? (delta / lastPrice) * 100 : 0;

  const lowerBound = forecast.lower_bound[forecast.lower_bound.length - 1];
  const upperBound = forecast.upper_bound[forecast.upper_bound.length - 1];
  const coneWidth = upperBound - lowerBound;
  const conePct = target > 0 ? (coneWidth / target) * 100 : 0;

  // Inercia histórica sobre los últimos N puntos
  const n = Math.min(20, points.length);
  const recent = points.slice(-n).map((p) => p.value);
  const mid = Math.floor(n / 2);
  const slope1 = (recent[mid] - recent[0]) / Math.max(1, mid);
  const slope2 = (recent[n - 1] - recent[mid]) / Math.max(1, n - 1 - mid);
  const accel = slope2 - slope1;
  const totalRet = (recent[n - 1] - recent[0]) / (recent[0] || 1);

  let inertiaLabel = 'Lateralización';
  let inertiaDetail = 'Rango neutral de consolidación sin sesgo direccional dominante en los últimos registros.';
  let inertiaBadge = 'bg-slate-800 text-slate-300 border-slate-700';
  let inertiaIcon = <Minus className="h-4 w-4 text-slate-400" />;

  if (Math.abs(totalRet) < 0.018 && Math.abs(slope2) < 0.15) {
    inertiaLabel = 'Lateralización';
    inertiaDetail = `Consolidación de precio en rango estrecho (±${(Math.abs(totalRet) * 100).toFixed(1)}%) en los últimos ${n} registros.`;
    inertiaBadge = 'bg-amber-500/10 text-amber-300 border-amber-500/20';
    inertiaIcon = <Minus className="h-4 w-4 text-amber-400" />;
  } else if (slope2 > 0 && accel > 0) {
    inertiaLabel = 'Aceleración positiva';
    inertiaDetail = `Impulso alcista creciente con convexidad positiva en el tramo final de los últimos ${n} registros.`;
    inertiaBadge = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20';
    inertiaIcon = <ArrowUpRight className="h-4 w-4 text-emerald-400" />;
  } else if (slope2 > 0 && accel <= 0) {
    inertiaLabel = 'Tendencia alcista con desaceleración';
    inertiaDetail = `Trayectoria positiva sostenida pero con moderación en la pendiente de avance reciente.`;
    inertiaBadge = 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20';
    inertiaIcon = <ArrowUpRight className="h-4 w-4 text-cyan-400" />;
  } else if (slope2 < 0 && accel < 0) {
    inertiaLabel = 'Aceleración negativa';
    inertiaDetail = `Inercia bajista con intensificación de la pendiente de retroceso en los últimos registros.`;
    inertiaBadge = 'bg-rose-500/10 text-rose-300 border-rose-500/20';
    inertiaIcon = <ArrowDownRight className="h-4 w-4 text-rose-400" />;
  } else {
    inertiaLabel = 'Tendencia bajista con atenuación';
    inertiaDetail = `Inclinación correctiva con reducción del ritmo de caída o soporte local.`;
    inertiaBadge = 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20';
    inertiaIcon = <ArrowDownRight className="h-4 w-4 text-indigo-400" />;
  }

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2">
          <Gauge className="h-4 w-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200">
            Telemetría y Resumen Estadístico ({seriesData.id})
          </h3>
        </div>
        <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
          Puro Dato • Sin Sesgo
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        {/* 1. Tendencia Central */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5 space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-400 flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-cyan-400" />
              Tendencia Central
            </span>
            <span className={`font-mono font-bold ${deltaPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {deltaPct >= 0 ? '+' : ''}{deltaPct.toFixed(1)}%
            </span>
          </div>
          <div className="text-slate-300 font-mono text-[13px] font-medium">
            ${lastPrice.toFixed(2)} → ${target.toFixed(2)}
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            Desviación porcentual proyectada a <strong>{horizon} días</strong> frente al último cierre real registrado.
          </p>
        </div>

        {/* 2. Amplitud del Intervalo de Confianza */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5 space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-400 flex items-center gap-1.5">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
              Cono de Confianza ({Math.round(confidence * 100)}%)
            </span>
            <span className="font-mono font-bold text-amber-400">
              {conePct.toFixed(1)}% ancho
            </span>
          </div>
          <div className="text-slate-300 font-mono text-[13px] font-medium">
            ±{(coneWidth / 2).toFixed(2)} ({lowerBound.toFixed(1)} a {upperBound.toFixed(1)})
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            Amplitud del cono relativo al objetivo central, reflejando la dispersión e incertidumbre temporal estocástica.
          </p>
        </div>

        {/* 3. Estado de la Inercia */}
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5 space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span className="font-semibold uppercase tracking-wider text-[11px] text-slate-400 flex items-center gap-1.5">
              <Compass className="h-3.5 w-3.5 text-indigo-400" />
              Estado de la Inercia
            </span>
            <div className="flex items-center gap-1">
              {inertiaIcon}
            </div>
          </div>
          <div className="flex items-center">
            <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border ${inertiaBadge}`}>
              {inertiaLabel}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            {inertiaDetail}
          </p>
        </div>
      </div>
    </div>
  );
};
