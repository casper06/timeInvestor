import React, { useState, useRef, useEffect } from 'react';
import { Info, Loader2, X } from 'lucide-react';
import { fetchFredMetadata, type FredSeriesMetadata } from '../services/api';

interface FredInfoTooltipProps {
  seriesId: string;
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; data: FredSeriesMetadata }
  | { status: 'error'; message: string };

const URL_PATTERN = /(https?:\/\/\S+)/g;

/**
 * Splits text on URLs and renders each URL as a real, clickable <a> — a small
 * hand-rolled linkifier instead of dangerouslySetInnerHTML, since FRED's
 * `notes` field commonly embeds reference links (e.g. to BLS/BEA methodology
 * pages) that were previously flattened into inert plain text.
 *
 * Deliberately regex-based rather than an HTML-injecting approach: this is
 * untrusted third-party text (FRED's API response), and there's no need to
 * parse or render it as HTML to get clickable links out of it.
 */
const linkifyNotes = (text: string): React.ReactNode[] => {
  const parts = text.split(URL_PATTERN);
  return parts.map((part, i) => {
    if (part.match(URL_PATTERN)) {
      // Trim common trailing punctuation that isn't part of the URL itself
      // (FRED's notes often end a sentence with a link followed by a period).
      const trailingMatch = part.match(/[.,;)\]]+$/);
      const trailing = trailingMatch ? trailingMatch[0] : '';
      const url = trailing ? part.slice(0, -trailing.length) : part;
      return (
        <React.Fragment key={i}>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2 break-all"
          >
            {url}
          </a>
          {trailing}
        </React.Fragment>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
};

/**
 * Small (ⓘ) affordance next to a FRED-backed series tab. Fetches FRED's own
 * official title/notes for that series_id on click — never a hand-written
 * description — and shows the real failure reason (no key configured,
 * series_id not found on FRED, ...) if the lookup fails, same humanized-error
 * spirit as the rest of this app's FRED-dependent UI.
 *
 * Popover visibility is explicit React state (`open`), not CSS :hover/
 * group-hover — the content can include a clickable link, and a hover-only
 * popover closes the instant the cursor leaves the icon on the way to that
 * link, before a click can ever land. Closes on click-outside or its own
 * close button, since it can now legitimately stay open while the user reads
 * or clicks through its content.
 */
export const FredInfoTooltip: React.FC<FredInfoTooltipProps> = ({ seriesId }) => {
  const [state, setState] = useState<LoadState>({ status: 'idle' });
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);

  const load = () => {
    if (state.status === 'loading' || state.status === 'loaded') return;
    setState({ status: 'loading' });
    fetchFredMetadata(seriesId)
      .then((data) => setState({ status: 'loaded', data }))
      .catch((err) =>
        setState({ status: 'error', message: err instanceof Error ? err.message : 'Error desconocido' })
      );
  };

  const toggleOpen = (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen((prev) => {
      const next = !prev;
      if (next) load();
      return next;
    });
  };

  // Click-outside closes the popover, now that it's kept open by state rather
  // than by the mouse staying over the icon.
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <span ref={containerRef} className="relative inline-flex items-center">
      <button
        type="button"
        onClick={toggleOpen}
        className="inline-flex items-center cursor-pointer"
        aria-label={`Información de la serie FRED ${seriesId}`}
        aria-expanded={open}
      >
        {state.status === 'loading' ? (
          <Loader2 className="h-3 w-3 text-slate-400 animate-spin" />
        ) : (
          <Info className="h-3 w-3 text-slate-400 hover:text-cyan-300" />
        )}
      </button>

      {open && (
        <span className="absolute z-20 bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-64 rounded-lg border border-slate-700 bg-slate-950 p-2.5 text-left shadow-xl">
          <span className="flex items-start justify-between gap-2 mb-1">
            <span className="block text-[11px] font-semibold text-slate-200">
              {state.status === 'loaded' ? state.data.title || seriesId : seriesId}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
              className="shrink-0 text-slate-500 hover:text-slate-300 cursor-pointer"
              aria-label="Cerrar"
            >
              <X className="h-3 w-3" />
            </button>
          </span>

          {state.status === 'loading' && (
            <span className="block text-[11px] text-slate-500">Consultando metadata de FRED...</span>
          )}
          {state.status === 'error' && (
            <span className="block text-[11px] text-rose-400">{state.message}</span>
          )}
          {state.status === 'loaded' && (
            <>
              {state.data.notes ? (
                <span className="block text-[10.5px] text-slate-400 leading-relaxed max-h-40 overflow-y-auto">
                  {linkifyNotes(state.data.notes)}
                </span>
              ) : (
                <span className="block text-[10.5px] text-slate-500 italic">FRED no publicó notas descriptivas para esta serie.</span>
              )}
            </>
          )}
        </span>
      )}
    </span>
  );
};
