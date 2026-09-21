import React from 'react';
import {
  Activity,
  Cpu,
  Database,
  FolderArchive,
  Download,
  LineChart,
  Rewind,
  Network,
  GitCompare,
} from 'lucide-react';
import type { HealthResponse } from '../services/api';

export type DashboardView = 'forecast' | 'backtest' | 'correlation' | 'dual';

interface HeaderProps {
  health: HealthResponse | null;
  loading: boolean;
  currentView: DashboardView;
  onChangeView: (view: DashboardView) => void;
  onOpenThesesDrawer: () => void;
  onExportReport: () => void;
  isSyntheticActive?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  loading,
  currentView,
  onChangeView,
  onOpenThesesDrawer,
  onExportReport,
  isSyntheticActive = false,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center space-x-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Activity className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                TimeInvestor
              </h1>
              <span className="text-[10px] uppercase font-mono tracking-widest px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                v2.0 Advanced Core
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Análisis, Monitoreo y Proyección de Tesis Cuantitativas
            </p>
          </div>
        </div>

        {/* Global Actions: Mis Tesis & Exportar */}
        <div className="flex items-center space-x-2">
          <button
            onClick={onOpenThesesDrawer}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800/90 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium transition-colors shadow-sm cursor-pointer"
          >
            <FolderArchive className="h-4 w-4 text-cyan-400" />
            <span>Mis Tesis</span>
          </button>

          <button
            onClick={onExportReport}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-600/90 hover:bg-indigo-500 text-white text-xs font-medium transition-colors shadow-md shadow-indigo-600/20 cursor-pointer"
          >
            <Download className="h-4 w-4" />
            <span>Exportar Informe</span>
          </button>

          {/* Connection Indicator */}
          <div className="flex items-center space-x-1 pl-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                loading ? 'bg-amber-400 animate-ping' : 'bg-emerald-500 animate-pulse'
              }`}
            />
            <span className="text-[11px] text-slate-400 font-mono">
              {loading ? 'Calculando' : 'Online'}
            </span>
          </div>
        </div>
      </div>

      {/* View Switcher Tabs Sub-bar */}
      <div className="border-t border-slate-800/80 bg-slate-950/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between overflow-x-auto">
          <div className="flex space-x-1 py-1 text-xs">
            <button
              onClick={() => onChangeView('forecast')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium cursor-pointer ${
                currentView === 'forecast'
                  ? 'bg-slate-800 text-cyan-400 font-bold border border-slate-700'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <LineChart className="h-3.5 w-3.5" />
              <span>Dashboard & Proyección</span>
            </button>

            <button
              onClick={() => !isSyntheticActive && onChangeView('backtest')}
              disabled={isSyntheticActive}
              title={
                isSyntheticActive
                  ? 'Deshabilitado: no se puede validar una tesis sobre datos generados'
                  : 'Auditar fidelidad empírica frente al historial real'
              }
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium ${
                isSyntheticActive
                  ? 'opacity-40 cursor-not-allowed text-slate-500'
                  : currentView === 'backtest'
                  ? 'bg-slate-800 text-amber-400 font-bold border border-slate-700 cursor-pointer'
                  : 'text-slate-400 hover:text-slate-200 cursor-pointer'
              }`}
            >
              <Rewind className="h-3.5 w-3.5" />
              <span>Reality Check (Backtest)</span>
            </button>

            <button
              onClick={() => !isSyntheticActive && onChangeView('correlation')}
              disabled={isSyntheticActive}
              title={
                isSyntheticActive
                  ? 'Deshabilitado: no se puede validar una tesis sobre datos generados'
                  : 'Calcular matriz de correlación Pearson / Spearman'
              }
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium ${
                isSyntheticActive
                  ? 'opacity-40 cursor-not-allowed text-slate-500'
                  : currentView === 'correlation'
                  ? 'bg-slate-800 text-indigo-400 font-bold border border-slate-700 cursor-pointer'
                  : 'text-slate-400 hover:text-slate-200 cursor-pointer'
              }`}
            >
              <Network className="h-3.5 w-3.5" />
              <span>Correlaciones & Heatmap</span>
            </button>

            <button
              onClick={() => onChangeView('dual')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium cursor-pointer ${
                currentView === 'dual'
                  ? 'bg-slate-800 text-purple-400 font-bold border border-slate-700'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <GitCompare className="h-3.5 w-3.5" />
              <span>Gráfico Dual-Axis</span>
            </button>
          </div>

          {/* Quick Engine Badges on the right of tabs */}
          <div className="hidden lg:flex items-center space-x-2 text-[11px] text-slate-400 py-1">
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3 text-cyan-400" />
              TimesFM {health?.use_real_timesfm ? 'PyTorch Real' : 'Mock v1'}
            </span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <Database className="h-3 w-3 text-emerald-400" />
              SQLite Activo
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
