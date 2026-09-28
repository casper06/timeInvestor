import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { BacktestPanel } from './BacktestPanel';
import { CorrelationHeatmap } from './CorrelationHeatmap';
import { ThesisCopilot } from './ThesisCopilot';
import * as api from '../services/api';

vi.mock('react-chartjs-2', () => ({
  Line: () => <div data-testid="chart" />,
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const monthly: api.TimeSeriesData = {
  id: 'UMCSENT',
  name: 'University of Michigan: Consumer Sentiment',
  type: 'macro',
  unit: 'Index 1966:Q1=100',
  source: 'live',
  frequency: 'monthly',
  points: Array.from({ length: 120 }, (_, i) => ({
    timestamp: `${2016 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
    value: 80 + (i % 7),
  })),
};

const notSeasonal: api.SeasonalityInfo = {
  frequency: 'monthly',
  period: 12,
  is_seasonal: false,
  acf_at_period: 0.1234,
  threshold: 0.3,
  n_obs: 120,
  reason: 'ACF en el lag 12 = 0.123, por debajo del umbral 0.300.',
};

describe('Reality Check: Holt-Winters when the detector already knows', () => {
  it('disables the checkbox and shows the ACF and the threshold', () => {
    render(<BacktestPanel seriesData={monthly} activeSeriesId="UMCSENT" seasonality={notSeasonal} />);
    const box = screen.getByRole('checkbox', { name: /Holt-Winters/ });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
    const why = screen.getByTestId('hw-blocked-reason');
    expect(why).toHaveTextContent('ACF en el lag 12 = 0.123 ≤ umbral 0.300');
  });

  it('never sends holt_winters for a series marked not seasonal', async () => {
    const spy = vi.spyOn(api, 'runBacktest').mockRejectedValue(new Error('not under test'));
    render(<BacktestPanel seriesData={monthly} activeSeriesId="UMCSENT" seasonality={notSeasonal} />);
    fireEvent.click(screen.getByRole('checkbox', { name: /Holt-Winters/ }));
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][4]).toBeUndefined();
  });

  it('keeps it enabled when seasonal or when there is no detector answer yet', () => {
    render(
      <BacktestPanel seriesData={monthly} activeSeriesId="UMCSENT" seasonality={{ ...notSeasonal, is_seasonal: true, acf_at_period: 0.6 }} />,
    );
    expect(screen.getByRole('checkbox', { name: /Holt-Winters/ })).toBeEnabled();
    cleanup();
    render(<BacktestPanel seriesData={monthly} activeSeriesId="UMCSENT" />);
    expect(screen.getByRole('checkbox', { name: /Holt-Winters/ })).toBeEnabled();
    expect(screen.queryByTestId('hw-blocked-reason')).not.toBeInTheDocument();
  });

  it("uses the detector's reason when there is no ACF (too few observations)", () => {
    render(
      <BacktestPanel
        seriesData={monthly}
        activeSeriesId="UMCSENT"
        seasonality={{ ...notSeasonal, acf_at_period: null, reason: 'Pocas observaciones: 20 < 36.' }}
      />,
    );
    expect(screen.getByTestId('hw-blocked-reason')).toHaveTextContent('Pocas observaciones: 20 < 36.');
  });
});

describe('No browser dialogs: errors in the page', () => {
  it('Reality Check says why it cannot run when the series did not load', () => {
    render(<BacktestPanel seriesData={null} activeSeriesId="TOTALSI" />);
    expect(screen.getByRole('button', { name: /Ejecutar Reality Check/ })).toBeDisabled();
    expect(screen.getByTestId('backtest-no-data')).toHaveTextContent('No hay datos de TOTALSI para evaluar');
  });

  it('Reality Check shows its error inline', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(api, 'runBacktest').mockRejectedValue(new Error('La serie TOTALSI no existe en FRED'));
    render(<BacktestPanel seriesData={{ ...monthly, id: 'TOTALSI' }} activeSeriesId="TOTALSI" />);
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
    expect(await screen.findByTestId('backtest-error')).toHaveTextContent('TOTALSI no existe en FRED');
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('the copilot shows its error inline', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(api, 'interpretSituation').mockRejectedValue(new Error('Proveedor no disponible'));
    render(
      <ThesisCopilot
        thesis="x"
        activeSeriesId="UMCSENT"
        seriesData={monthly}
        forecast={null}
        horizon={12}
        confidence={0.95}
        activeTickers={[]}
        activeMacro={[]}
        fundamentals={[]}
        onSelectSeries={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Interpretar Situación/ }));
    expect(await screen.findByTestId('copilot-error')).toHaveTextContent('Proveedor no disponible');
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('no alert() or confirm() calls are left in the source', () => {
    const files = import.meta.glob(['../**/*.tsx', '../**/*.ts', '!../**/*.test.*'], {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(files).length).toBeGreaterThan(10);
    const offenders = Object.entries(files)
      .filter(([, src]) =>
        src
          .split('\n')
          .filter((l) => !l.trim().startsWith('//'))
          .some((l) => /(^|[^\w.])(window\.)?(alert|confirm)\(/.test(l)),
      )
      .map(([f]) => f);
    expect(offenders).toEqual([]);
  });
});

describe('Correlation with a series that does not exist', () => {
  it('lists the excluded series and why, next to the matrix of the rest', async () => {
    vi.spyOn(api, 'fetchCorrelations').mockResolvedValue({
      series_ids: ['NVDA', 'UMCSENT'],
      series_names: { NVDA: 'NVIDIA', UMCSENT: 'University of Michigan: Consumer Sentiment' },
      pearson_matrix: [[1, 0.2], [0.2, 1]],
      spearman_matrix: [[1, 0.1], [0.1, 1]],
      p_values_pearson: [[0, 0.3], [0.3, 0]],
      p_values_spearman: [[0, 0.4], [0.4, 0]],
      common_observations: 24,
      start_date: '2024-10-31',
      end_date: '2026-08-31',
      mode: 'returns',
      excluded: [
        { series_id: 'TOTALSI', reason: 'La serie TOTALSI no existe en FRED' },
        { series_id: 'IPGD', reason: 'La serie IPGD no existe en FRED' },
      ],
    } as api.CorrelationMatrixResponse);
    render(
      <CorrelationHeatmap
        activeTickers={[{ symbol: 'NVDA', name: 'NVIDIA', sector: 'Tech', weight: 1, thesis_role: 'x' }]}
        activeMacro={['TOTALSI', 'IPGD', 'UMCSENT'].map((id) => ({
          series_id: id, name: id, category: 'Macro', expected_correlation: 'Positive' as const,
        }))}
      />,
    );
    const notice = await screen.findByTestId('correlation-excluded');
    expect(notice).toHaveTextContent('TOTALSI: La serie TOTALSI no existe en FRED');
    expect(notice).toHaveTextContent('IPGD: La serie IPGD no existe en FRED');
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});
