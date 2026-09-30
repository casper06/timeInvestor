import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CorrelationHeatmap } from './CorrelationHeatmap';

// The component imports fetchCorrelations directly, so the module itself is
// mocked rather than spied on its namespace object.
const fetchCorrelations = vi.hoisted(() => vi.fn());
vi.mock('../services/api', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  fetchCorrelations,
}));

/**
 * Overlapping loads (ADR-0024's request number, extended to the rest of the
 * panels). A slower EARLIER answer must never land on top of a newer one:
 * otherwise the screen shows one request's numbers under another request's
 * parameters, and nothing says so.
 */
describe('CorrelationHeatmap: only the latest request may write', () => {
  beforeEach(() => fetchCorrelations.mockReset());
  afterEach(() => fetchCorrelations.mockReset());

  // The panel needs at least 2 assets before it renders its controls.
  const two = [
    { symbol: 'NVDA', name: 'NVIDIA', sector: 'T', weight: 0.5, thesis_role: 'r' },
    { symbol: 'MSFT', name: 'Microsoft', sector: 'T', weight: 0.5, thesis_role: 'r' },
  ];

  const matrix = (ids: string[]) => ({
    series_ids: ids,
    matrix: ids.map((_, i) => ids.map((__, j) => (i === j ? 1 : 0.5))),
    period: '1y',
    method: 'returns' as const,
    observations: 250,
  });

  it('discards a stale answer that arrives after a newer one', async () => {
    let resolveFirst: (v: unknown) => void = () => {};
    const first = new Promise((r) => { resolveFirst = r; });

    const spy = fetchCorrelations
      // The first load (mount) hangs...
      .mockImplementationOnce(() => first)
      // ...the second resolves immediately.
      .mockImplementationOnce(async () => matrix(['NVDA', 'MSFT']));

    render(<CorrelationHeatmap activeTickers={two} activeMacro={[]} />);

    // Force a second load while the first is still in flight.
    fireEvent.click(screen.getByTitle('Recalcular matriz'));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    // The header counts the ids of whatever answer is on screen.
    await screen.findByText(/2 activos/);

    // Now the FIRST request finally answers, with a DIFFERENT shape.
    resolveFirst(matrix(['STALE']));
    await new Promise((r) => setTimeout(r, 30));

    expect(screen.getByText(/2 activos/)).toBeInTheDocument();
    expect(screen.queryByText(/1 activos/)).not.toBeInTheDocument();
  });

  it('a stale error does not overwrite a good newer result', async () => {
    let rejectFirst: (e: unknown) => void = () => {};
    const first = new Promise((_r, rej) => { rejectFirst = rej; });

    const spy = fetchCorrelations
      .mockImplementationOnce(() => first)
      .mockImplementationOnce(async () => matrix(['NVDA', 'MSFT']));

    render(<CorrelationHeatmap activeTickers={two} activeMacro={[]} />);
    fireEvent.click(screen.getByTitle('Recalcular matriz'));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    await screen.findByText(/2 activos/);

    rejectFirst(new Error('la vieja fallo'));
    await new Promise((r) => setTimeout(r, 30));

    expect(screen.queryByText(/la vieja fallo/)).not.toBeInTheDocument();
    expect(screen.getByText(/2 activos/)).toBeInTheDocument();
  });
});
