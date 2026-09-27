import React from 'react';
import { Sparkles } from 'lucide-react';

/** What the dashboard and every tab show before there is a thesis or an asset
 * to analyze: nothing is loaded or analyzed on its own when the app opens. */
export const EmptyState: React.FC<{ view?: string }> = ({ view }) => (
  <div
    role="status"
    data-testid="empty-state"
    data-view={view}
    className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-10 text-center space-y-3"
  >
    <Sparkles className="h-8 w-8 text-cyan-400 mx-auto" />
    <p className="text-sm font-medium text-slate-200">Escribí una tesis o elegí un ejemplo para empezar</p>
    <p className="text-xs text-slate-500">
      También podés agregar un activo o una serie de FRED a mano, o abrir una tesis guardada desde "Mis Tesis".
    </p>
  </div>
);
