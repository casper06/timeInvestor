import React, { useEffect, useRef, useState } from 'react';
import { Bot, Check, ChevronDown, KeyRound, Loader2 } from 'lucide-react';
import {
  fetchLLMProviders,
  switchLLMProvider,
  type LLMProvidersResponse,
} from '../services/api';

interface LLMProviderSelectorProps {
  onProviderChanged?: (provider: string) => void;
}

/**
 * Header dropdown to switch the active LLM provider at runtime. The switch
 * lives in the server's memory only (never written to .env), so the note
 * under the list says so every time the list is open — a restart goes back
 * to whatever LLM_PROVIDER says in .env.
 *
 * Unavailable providers are listed but disabled, with the backend's reason
 * both inline and as a tooltip — same "this requires X which isn't
 * configured" treatment as FRED series without FRED_API_KEY.
 */
export const LLMProviderSelector: React.FC<LLMProviderSelectorProps> = ({ onProviderChanged }) => {
  const [data, setData] = useState<LLMProvidersResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const load = () => {
    setLoadingList(true);
    fetchLLMProviders()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Error desconocido'))
      .finally(() => setLoadingList(false));
  };

  useEffect(load, []);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const toggle = () => {
    // Re-fetch on open: a CLI may have been installed/logged in since the last
    // look. The backend caches the expensive checks, so this stays cheap.
    if (!open) load();
    setOpen(!open);
  };

  const select = async (provider: string) => {
    if (!data || provider === data.active || switching) return;
    setSwitching(provider);
    setError(null);
    try {
      const res = await switchLLMProvider(provider);
      setData({ ...data, active: res.active });
      onProviderChanged?.(res.active);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido');
    } finally {
      setSwitching(null);
    }
  };

  const active = data?.providers.find((p) => p.id === data.active);
  const activeLabel = active?.label ?? data?.active ?? '…';
  const differsFromEnv = !!data && data.active !== data.env_default;

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={toggle}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={differsFromEnv ? `Cambiado en esta sesión (el .env dice "${data?.env_default}")` : 'Proveedor LLM activo'}
        className="flex items-center gap-1 px-2 py-0.5 rounded-md border border-slate-700 bg-slate-900/80 hover:bg-slate-800 text-slate-300 cursor-pointer transition-colors"
      >
        <Bot className="h-3 w-3 text-violet-400" />
        <span>LLM: {activeLabel}</span>
        {differsFromEnv && <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />}
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 mt-1.5 w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-xl shadow-black/40 z-50 p-1.5 text-xs">
          <div className="flex items-center justify-between px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            <span>Proveedor LLM</span>
            {loadingList && <Loader2 className="h-3 w-3 animate-spin" />}
          </div>

          <ul role="listbox" className="space-y-0.5">
            {data?.providers.map((p) => {
              const isActive = p.id === data.active;
              return (
                <li key={p.id}>
                  <button
                    role="option"
                    aria-selected={isActive}
                    aria-disabled={!p.available}
                    onClick={() => p.available && select(p.id)}
                    title={p.available ? p.note ?? undefined : `No disponible: ${p.reason}`}
                    className={`w-full text-left px-2 py-1.5 rounded-lg flex items-start gap-2 transition-colors ${
                      !p.available
                        ? 'opacity-50 cursor-not-allowed'
                        : isActive
                        ? 'bg-slate-800 cursor-default'
                        : 'hover:bg-slate-800/70 cursor-pointer'
                    }`}
                  >
                    <span className="mt-0.5 w-3.5 shrink-0">
                      {switching === p.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
                      ) : isActive ? (
                        <Check className="h-3.5 w-3.5 text-violet-400" />
                      ) : !p.available ? (
                        <KeyRound className="h-3.5 w-3.5 text-amber-400" />
                      ) : null}
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className={`block font-medium ${isActive ? 'text-violet-300' : 'text-slate-200'}`}>
                        {p.label}
                        <span className="ml-1.5 font-mono text-[10px] text-slate-500">{p.id}</span>
                      </span>
                      {!p.available && p.reason && (
                        <span className="block text-[11px] text-amber-400/90 leading-snug">{p.reason}</span>
                      )}
                      {p.available && p.note && (
                        <span
                          className={`block text-[11px] leading-snug ${
                            p.id === 'claude_cli' ? 'text-amber-300/90' : 'text-slate-500'
                          }`}
                        >
                          {p.note}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          {error && <p className="mx-2 mt-1.5 text-[11px] text-rose-400 leading-snug">{error}</p>}

          <p className="mx-2 mt-1.5 pt-1.5 border-t border-slate-800 text-[11px] text-slate-500 leading-snug">
            Válido hasta el próximo reinicio del server. Para dejarlo fijo, editá <code className="text-slate-400">LLM_PROVIDER</code> en tu <code className="text-slate-400">.env</code>
            {data && (
              <>
                {' '}(hoy: <code className="text-slate-400">{data.env_default}</code>)
              </>
            )}
            .
          </p>
        </div>
      )}

      {!open && error && (
        <span className="absolute right-0 mt-1 w-64 text-[11px] text-rose-400 leading-snug">{error}</span>
      )}
    </div>
  );
};
