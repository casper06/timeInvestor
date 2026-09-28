import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { ThesisCopilot } from './ThesisCopilot';
import * as api from '../services/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const fundamentals: api.FundamentalsMetric[] = [
  { ticker: 'CEG', metric: 'Capex (Billions USD)', period: '2025', value: 2.949 },
  { ticker: 'CEG', metric: 'Revenue (Billions USD)', period: '2025', value: 25.533 },
];

describe('ThesisCopilot context (fix/copilot-context)', () => {
  it('sends the date of every figure and the fundamentals with their fiscal year', async () => {
    const spy = vi.spyOn(api, 'interpretSituation').mockResolvedValue({
      what_data_says: 'a',
      thesis_alignment: 'b',
      next_series_suggestion: 'c',
      provider_used: 'mock-semantic-engine',
    });
    render(
      <ThesisCopilot
        thesis="Demanda eléctrica por centros de datos de IA"
        activeSeriesId="CEG"
        seriesData={{
          id: 'CEG', name: 'Constellation', type: 'equity', unit: 'USD', frequency: 'daily',
          points: [{ timestamp: '2026-09-24', value: 298 }, { timestamp: '2026-09-25', value: 300 }],
        }}
        forecast={{
          timestamps: ['2026-09-26', '2026-12-18'], values: [301, 310], lower_bound: [290, 250],
          upper_bound: [312, 370], model_name: 'damped-holt-mle',
        }}
        horizon={60}
        confidence={0.95}
        activeTickers={[{ symbol: 'CEG', name: 'CEG', sector: 'x', weight: 0.5, thesis_role: 'x' },
                        { symbol: 'VST', name: 'VST', sector: 'x', weight: 0.5, thesis_role: 'x' },
                        { symbol: 'PWR', name: 'PWR Equity', sector: 'Custom Asset', weight: 0.1, thesis_role: 'Activo agregado manualmente' }]}
        activeMacro={[{ series_id: 'IPG2211A2N', name: 'x', category: 'x', expected_correlation: 'Positive' }]}
        fundamentals={fundamentals}
        onSelectSeries={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Interpretar Situación/ }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const ctx = spy.mock.calls[0][0];
    expect(ctx.series_type).toBe('equity');
    expect(ctx.last_observation_date).toBe('2026-09-25');
    expect(ctx.target_date).toBe('2026-12-18');
    expect(ctx.fundamentals).toEqual(fundamentals);
    expect(ctx.other_tickers).toEqual(['VST', 'PWR']);
    // PWR was added with "+ Ticker": the copilot must not call it an LLM pick.
    expect(ctx.user_added_tickers).toEqual(['PWR']);
    expect(ctx.macro_series).toEqual(['IPG2211A2N']);
  });
});
