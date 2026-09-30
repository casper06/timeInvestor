import React from 'react';
import type { ForecastSkill } from '../services/api';

const SKILL_LABEL = {
  aporta: 'Aporta sobre el naive',
  no_aporta: 'No aporta más que el naive',
  no_evaluado: 'No evaluado',
} as const;

const SKILL_STYLE = {
  aporta: 'border-emerald-500/40 bg-emerald-950/30 text-emerald-300',
  no_aporta: 'border-amber-500/40 bg-amber-950/30 text-amber-300',
  no_evaluado: 'border-slate-700 bg-slate-900/60 text-slate-400',
} as const;

interface SkillBadgeProps {
  skill: ForecastSkill;
  /** The series the verdict belongs to, shown so it can't be read as another one's. */
  seriesId?: string;
}

/** Does the forecast beat the naive for this series? (4.13; lives next to
 * "Serie activa" in the chart panel so it changes with the selected series.) */
export const SkillBadge: React.FC<SkillBadgeProps> = ({ skill, seriesId }) => (
  <div
    data-testid="skill-badge"
    data-state={skill.state}
    data-series={seriesId}
    className={`flex flex-col sm:flex-row sm:items-center gap-2 rounded-xl border p-3 text-xs ${SKILL_STYLE[skill.state]}`}
  >
    <span className="font-bold uppercase tracking-wide whitespace-nowrap">
      Capacidad de pronóstico{seriesId ? ` (${seriesId})` : ''}: {SKILL_LABEL[skill.state]}
    </span>
    <span className="text-slate-300">{skill.reason}</span>
    {/* 3.4: the badge measures with today's REVISED series. On a revisable SA
        series that flatters the engine, so the verdict says where it comes
        from instead of leaving it implicit. */}
    {skill.vintage_note && (
      <span data-testid="skill-vintage-note" className="text-[11px] text-amber-300/90 sm:basis-full">
        {skill.vintage_note}
      </span>
    )}
  </div>
);
