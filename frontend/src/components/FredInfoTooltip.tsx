import React, { useState } from 'react';
import { Info, Loader2 } from 'lucide-react';
import { fetchFredMetadata, type FredSeriesMetadata } from '../services/api';

interface FredInfoTooltipProps {
  seriesId: string;
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: FredSeriesMetadata }
  | { status: 'error'; message: string };

/**
 * Small (ⓘ) affordance next to a FRED-backed series tab. Fetches FRED's own
 * official title/notes for that series_id on first hover/click — never a
 * hand-written description — and shows the real failure reason (no key
 * configured, series_id not found on FRED, ...) if the lookup fails, same
 * humanized-error spirit as the rest of this app's FRED-dependent UI.
 */
export const FredInfoTooltip: React.FC<FredInfoTooltipProps> = ({ seriesId }) => {
  const [state, setState] = useState<LoadState>({ status: 'idle' });

  const load = () => {
    if (state.status === 'loading' || state.status === 'loaded') return;
    setState({ status: 'loading' });
    fetchFredMetadata(seriesId)
      .then((data) => setState({ status: 'loaded', data }))
      .catch((err) =>
        setState({ status: 'error', message: err instanceof Error ? err.message : 'Error desconocido' })
      );
  };

  return (
    <span
      className="relative inline-flex items-center group/fredinfo"
      onMouseEnter={load}
      onClick={(e) => {
        e.stopPropagation();
        load();
      }}
    >
      {state.status === 'loading' ? (
        <Loader2 className="h-3 w-3 text-slate-400 animate-spin" />
      ) : (
        <Info className="h-3 w-3 text-slate-400 hover:text-cyan-300 cursor-help" />
      )}

      <span className="pointer-events-none absolute z-20 hidden group-hover/fredinfo:block bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-64 rounded-lg border border-slate-700 bg-slate-950 p-2.5 text-left shadow-xl">
        {state.status === 'idle' && (
          <span className="text-[11px] text-slate-500">Pasá el mouse para cargar la descripción oficial de FRED...</span>
        )}
        {state.status === 'loading' && (
          <span className="text-[11px] text-slate-500">Consultando metadata de FRED...</span>
        )}
        {state.status === 'error' && (
          <span className="text-[11px] text-rose-400">{state.message}</span>
        )}
        {state.status === 'loaded' && (
          <>
            <span className="block text-[11px] font-semibold text-slate-200 mb-1">{state.data.title || seriesId}</span>
            {state.data.notes ? (
              <span className="block text-[10.5px] text-slate-400 leading-relaxed max-h-40 overflow-y-auto">
                {state.data.notes}
              </span>
            ) : (
              <span className="block text-[10.5px] text-slate-500 italic">FRED no publicó notas descriptivas para esta serie.</span>
            )}
          </>
        )}
      </span>
    </span>
  );
};
