import { describe, it, expect } from 'vitest';
import { entersAnalysis } from './api';
import type { MacroSuggestion } from './api';

/**
 * 4.11: the gate that keeps an unchosen suggestion out of forecasts,
 * correlations and the copilot. App.tsx derives `analysisMacro` from this, so
 * everything downstream (series pills, CorrelationHeatmap, ThesisCopilot)
 * inherits it from one place.
 */
const base = (over: Partial<MacroSuggestion>): MacroSuggestion => ({
  series_id: 'TOTALSI',
  name: 'Ventas totales de viviendas nuevas',
  category: 'Vivienda',
  expected_correlation: 'Negative',
  ...over,
});

describe('entersAnalysis (4.11)', () => {
  it('lets a verified series through', () => {
    expect(entersAnalysis(base({ series_id: 'UMCSENT', grounding: 'verificado' }))).toBe(true);
  });

  it('keeps a searched-for suggestion out until the user picks', () => {
    const pending = base({ grounding: 'sugerido_por_busqueda', proposed_series_id: 'TOTALSI' });
    expect(entersAnalysis(pending)).toBe(false);
  });

  it('lets it through once the user picked a candidate', () => {
    const chosen = base({
      series_id: 'MSPUS',
      grounding: 'sugerido_por_busqueda',
      proposed_series_id: 'TOTALSI',
      chosen_by_user: true,
    });
    expect(entersAnalysis(chosen)).toBe(true);
  });

  it('never lets a discarded or unverifiable one through', () => {
    expect(entersAnalysis(base({ grounding: 'descartado' }))).toBe(false);
    expect(entersAnalysis(base({ grounding: null }))).toBe(false);
  });

  it('filters a mixed list down to what may be analyzed', () => {
    const list = [
      base({ series_id: 'UMCSENT', grounding: 'verificado' }),
      base({ series_id: 'TOTALSI', grounding: 'sugerido_por_busqueda', proposed_series_id: 'TOTALSI' }),
      base({ series_id: 'MSPUS', grounding: 'sugerido_por_busqueda', proposed_series_id: 'HSN1X', chosen_by_user: true }),
      base({ series_id: 'IPGD', grounding: 'descartado' }),
    ];
    expect(list.filter(entersAnalysis).map((m) => m.series_id)).toEqual(['UMCSENT', 'MSPUS']);
  });
});
