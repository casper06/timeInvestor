import { describe, it, expect } from 'vitest';
import { entersAnalysis } from './api';
import type { MacroSuggestion } from './api';

/**
 * 4.11: the gate that decides what reaches forecasts, correlations and the
 * copilot. App.tsx derives `analysisMacro` from this, so everything downstream
 * (series pills, CorrelationHeatmap, ThesisCopilot) inherits it from one place.
 *
 * After the repair pass nothing should be left in a limbo state, so this is a
 * defensive check: only what FRED confirmed gets through.
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

  it('lets a repaired series through: the LLM chose it and FRED confirmed it', () => {
    expect(entersAnalysis(base({
      series_id: 'HSN1F',
      grounding: 'reparado',
      proposed_series_id: 'TOTALSI',
      repair_justification: 'Mide cantidad, no precio.',
    }))).toBe(true);
  });

  it('never lets a discarded or unverifiable one through', () => {
    expect(entersAnalysis(base({ grounding: 'descartado' }))).toBe(false);
    expect(entersAnalysis(base({ grounding: null }))).toBe(false);
    expect(entersAnalysis(base({}))).toBe(false);
  });

  it('filters a mixed list down to what may be analyzed', () => {
    const list = [
      base({ series_id: 'UMCSENT', grounding: 'verificado' }),
      base({ series_id: 'HSN1F', grounding: 'reparado', proposed_series_id: 'TOTALSI' }),
      base({ series_id: 'IPGD', grounding: 'descartado', proposed_series_id: 'IPGD' }),
      base({ series_id: 'DGS10', grounding: null }),
    ];
    expect(list.filter(entersAnalysis).map((m) => m.series_id)).toEqual(['UMCSENT', 'HSN1F']);
  });
});
