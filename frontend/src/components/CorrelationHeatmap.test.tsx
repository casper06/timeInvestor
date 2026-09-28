import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, waitFor, cleanup } from '@testing-library/react';
import { CorrelationHeatmap } from './CorrelationHeatmap';
import * as api from '../services/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CorrelationHeatmap routing (4.11, partial)', () => {
  it("sends each series' type, so a FRED ID is never looked up in yfinance", async () => {
    const spy = vi.spyOn(api, 'fetchCorrelations').mockRejectedValue(new Error('not under test'));
    render(
      <CorrelationHeatmap
        activeTickers={[{ symbol: 'NVDA', name: 'NVIDIA', sector: 'Tech', weight: 1, thesis_role: 'x' }]}
        activeMacro={[
          { series_id: 'PCU221110221110', name: 'FRED PCU221110221110', category: 'Macro', expected_correlation: 'Positive' },
          { series_id: 'DGS10', name: 'FRED DGS10', category: 'Macro', expected_correlation: 'Positive' },
        ]}
      />
    );
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const [ids, , , types] = spy.mock.calls[0];
    expect(ids).toEqual(['NVDA', 'PCU221110221110', 'DGS10']);
    expect(types).toEqual({ NVDA: 'equity', PCU221110221110: 'macro', DGS10: 'macro' });
  });
});
