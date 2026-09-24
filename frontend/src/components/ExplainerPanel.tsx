import React, { useState } from 'react';
import { HelpCircle, ChevronDown, ChevronUp } from 'lucide-react';

interface ExplainerPanelProps {
  title?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

/**
 * Collapsible "¿Qué estoy viendo?" panel — real explanatory content about what
 * a tab's metrics ARE and how to read them, not a one-line generic tooltip.
 * Deliberately never tells the user what conclusion to draw from a specific
 * number (that's the same "decide for the user" line this whole project
 * avoids elsewhere) — only explains the metric itself and how it's computed.
 */
export const ExplainerPanel: React.FC<ExplainerPanelProps> = ({
  title = '¿Qué estoy viendo?',
  children,
  defaultOpen = false,
}) => {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-slate-950/50 border border-slate-800 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-4 py-2.5 text-xs font-semibold text-slate-300 hover:bg-slate-900/40 transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-2">
          <HelpCircle className="h-4 w-4 text-cyan-400" />
          {title}
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5 text-slate-500" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-500" />}
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 text-xs text-slate-400 leading-relaxed space-y-3 border-t border-slate-800/60">
          {children}
        </div>
      )}
    </div>
  );
};
