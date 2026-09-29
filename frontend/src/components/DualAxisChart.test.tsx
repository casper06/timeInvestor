import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { DualAxisChart } from './DualAxisChart';
import * as api from '../services/api';

// jsdom has no canvas: the chart renders its dataset labels.
vi.mock('react-chartjs-2', () => ({
  Line: ({ data }: { data: { datasets: { label: string }[] } }) => (
    <div data-testid="chart">{data.datasets.map((d) => d.label).join(' | ')}</div>
  ),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function series(id: string, name: string, type: 'equity' | 'macro' = 'macro'): api.TimeSeriesData {
  return {
    id,
    name,
    type,
    unit: type === 'macro' ? 'Index' : 'USD',
    source: 'live',
    metadata_source: 'fred',
    points: Array.from({ length: 24 }, (_, i) => ({
      timestamp: `${2024 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
      value: 50 + i,
    })),
  };
}

// The thesis from the screenshots: TOTALSI and IPGD don't exist in FRED.
const thesisSeries = [
  { id: 'NVDA', name: 'NVIDIA', type: 'equity', nameFromLLM: true },
  { id: 'TOTALSI', name: 'Total Business Inventories to Sales', type: 'macro', nameFromLLM: true },
  { id: 'IPGD', name: 'Industrial Production: Durable Goods', type: 'macro', nameFromLLM: true },
  { id: 'UMCSENT', name: 'Consumer Sentiment', type: 'macro', nameFromLLM: true },
];

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('DualAxisChart with a series that does not exist (fix/missing-series-resilience)', () => {
  it("shows the selected series' error, not another series' chart", async () => {
    vi.spyOn(api, 'fetchMacroData').mockImplementation(async (id: string) => {
      if (id === 'UMCSENT') return series('UMCSENT', 'University of Michigan: Consumer Sentiment');
      throw new Error(`La serie ${id} no existe en FRED`);
    });
    render(<DualAxisChart primarySeriesData={series('NVDA', 'NVIDIA', 'equity')} allAvailableSeries={thesisSeries} />);

    // Default: the first other series, TOTALSI, which fails.
    const err = await screen.findByTestId('dual-secondary-error');
    expect(err).toHaveTextContent('TOTALSI');
    expect(err).toHaveTextContent('no existe en FRED. El gráfico muestra solo NVDA.');
    expect(screen.getByTestId('chart')).not.toHaveTextContent('TOTALSI');
    expect(screen.getByTestId('dual-right')).toHaveTextContent('TOTALSI — no se pudo cargar');

    // A series that loads, then back to a failing one: the old chart doesn't stay.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'UMCSENT' } });
    await waitFor(() => expect(screen.getByTestId('chart')).toHaveTextContent('UMCSENT'));
    expect(screen.queryByTestId('dual-secondary-error')).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'IPGD' } });
    expect(await screen.findByTestId('dual-secondary-error')).toHaveTextContent('IPGD');
    expect(screen.getByTestId('chart')).not.toHaveTextContent('UMCSENT');
    expect(screen.getByTestId('dual-right')).not.toHaveTextContent('Consumer Sentiment');
  });

  it('never draws a late answer for a series no longer selected', async () => {
    const slow = deferred<api.TimeSeriesData>();
    vi.spyOn(api, 'fetchMacroData').mockImplementation((id: string) =>
      id === 'TOTALSI' ? slow.promise : Promise.resolve(series(id, `FRED title of ${id}`)),
    );
    render(<DualAxisChart primarySeriesData={series('NVDA', 'NVIDIA', 'equity')} allAvailableSeries={thesisSeries} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'UMCSENT' } });
    await waitFor(() => expect(screen.getByTestId('chart')).toHaveTextContent('UMCSENT'));

    slow.resolve(series('TOTALSI', 'late answer'));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByRole('combobox')).toHaveValue('UMCSENT');
    expect(screen.getByTestId('chart')).not.toHaveTextContent('TOTALSI');
    expect(screen.getByTestId('dual-right')).not.toHaveTextContent('late answer');
  });

  it("keeps the user's choice when the parent re-renders with a new list", async () => {
    vi.spyOn(api, 'fetchMacroData').mockImplementation(async (id: string) => series(id, `FRED ${id}`));
    const primary = series('NVDA', 'NVIDIA', 'equity');
    const { rerender } = render(<DualAxisChart primarySeriesData={primary} allAvailableSeries={[...thesisSeries]} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'UMCSENT' } });
    await waitFor(() => expect(screen.getByTestId('chart')).toHaveTextContent('UMCSENT'));

    // App rebuilds allSeriesList on every render: a new array, same series.
    rerender(<DualAxisChart primarySeriesData={primary} allAvailableSeries={[...thesisSeries]} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByRole('combobox')).toHaveValue('UMCSENT');
    expect(screen.getByTestId('chart')).toHaveTextContent('UMCSENT');
  });

  it("labels the LLM's name as the LLM's, and shows FRED's title once loaded", async () => {
    vi.spyOn(api, 'fetchMacroData').mockImplementation(async (id: string) =>
      series(id, 'University of Michigan: Consumer Sentiment'),
    );
    render(
      <DualAxisChart
        primarySeriesData={series('NVDA', 'NVIDIA', 'equity')}
        allAvailableSeries={[
          ...thesisSeries,
          { id: 'DGS10', name: 'FRED DGS10', type: 'macro', nameFromLLM: false },
        ]}
      />,
    );
    expect(screen.getByRole('option', { name: /TOTALSI/ })).toHaveTextContent(
      'TOTALSI (Total Business Inventories to Sales, nombre según el LLM)',
    );
    expect(screen.getByRole('option', { name: /DGS10/ })).toHaveTextContent('DGS10 (FRED DGS10)');
    expect(screen.getByRole('option', { name: /DGS10/ })).not.toHaveTextContent('LLM');

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'UMCSENT' } });
    await waitFor(() =>
      expect(screen.getByTestId('dual-right')).toHaveTextContent('University of Michigan: Consumer Sentiment'),
    );
  });
});
