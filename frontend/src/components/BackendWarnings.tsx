import React from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * 4.4: the backend's own warnings, shown instead of dropped.
 *
 * Every quantitative endpoint can return `warnings` — a ticker with no
 * fundamentals, a covariance matrix that needed heavy shrinkage, a simulation
 * whose history was too short. They explain why a number looks the way it
 * does, and until now Fundamentals, portfolio optimization and risk threw them
 * away silently, which is the one thing a tool like this must not do.
 */
interface BackendWarningsProps {
  warnings?: string[] | null;
  /** Identifies the panel in tests and gives each list a stable test id. */
  testId: string;
  className?: string;
}

export const BackendWarnings: React.FC<BackendWarningsProps> = ({ warnings, testId, className = '' }) => {
  if (!warnings || warnings.length === 0) return null;

  return (
    <div
      data-testid={testId}
      role="status"
      className={`rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5 space-y-1 ${className}`}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-300">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        <span>
          {warnings.length === 1 ? 'Advertencia del cálculo' : `Advertencias del cálculo (${warnings.length})`}
        </span>
      </div>
      <ul className="space-y-0.5 pl-5 list-disc marker:text-amber-500/60">
        {warnings.map((w, i) => (
          <li key={i} className="text-[11px] text-amber-100/80 leading-relaxed">
            {w}
          </li>
        ))}
      </ul>
    </div>
  );
};
