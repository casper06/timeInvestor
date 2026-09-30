import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SkillBadge } from './SkillBadge';
import type { ForecastSkill } from '../services/api';

const skill = (over: Partial<ForecastSkill>): ForecastSkill => ({
  state: 'aporta',
  reason: 'Le gana al random walk en 17 de 24 cutoffs.',
  ...over,
});

/**
 * 3.4: the badge measures with today's REVISED series. On a revisable SA
 * series that flatters the engine, so the verdict carries a provenance note.
 */
describe('SkillBadge vintage note (3.4)', () => {
  it('shows the note when the capability did not hold with vintage data', () => {
    render(
      <SkillBadge
        seriesId="HOUST"
        skill={skill({
          vintage_note: 'Capacidad medida con datos revisados; con datos de época no se sostuvo (3.4).',
        })}
      />,
    );
    expect(screen.getByTestId('skill-vintage-note')).toHaveTextContent('con datos de época no se sostuvo');
  });

  it('shows the weaker note when 3.4 never measured the series', () => {
    render(
      <SkillBadge
        seriesId="PAYEMS"
        skill={skill({
          vintage_note: 'Capacidad medida con datos revisados; no verificada con datos de época.',
        })}
      />,
    );
    expect(screen.getByTestId('skill-vintage-note')).toHaveTextContent('no verificada con datos de época');
  });

  it('shows no note when there is none', () => {
    render(<SkillBadge seriesId="IPG2211A2N" skill={skill({})} />);
    expect(screen.queryByTestId('skill-vintage-note')).not.toBeInTheDocument();
  });

  it('still shows the verdict and its reason', () => {
    render(<SkillBadge seriesId="HOUST" skill={skill({ vintage_note: 'Nota.' })} />);
    const badge = screen.getByTestId('skill-badge');
    expect(badge).toHaveAttribute('data-state', 'aporta');
    expect(badge).toHaveTextContent('Le gana al random walk en 17 de 24 cutoffs.');
  });
});
