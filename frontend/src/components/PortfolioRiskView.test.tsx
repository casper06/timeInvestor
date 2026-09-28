import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { PortfolioRiskView } from './PortfolioRiskView';
import * as api from '../services/api';

// Charts don't draw in jsdom; the state is what's under test.
vi.mock('react-chartjs-2', () => ({ Bar: () => null, Line: () => null, Doughnut: () => null, Pie: () => null }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const riskResult = (over: Partial<api.PortfolioRiskResponse> = {}): api.PortfolioRiskResponse => ({
  method_used: 'bootstrap',
  horizon_days: 30,
  initial_capital: 100000,
  n_simulations: 10000,
  metrics: {
    '95%': { confidence_level: 0.95, var_pct: 0.188, var_usd: 18800, var_std_error: 0.003, cvar_pct: 0.233, cvar_usd: 23300 },
    '99%': { confidence_level: 0.99, var_pct: 0.261, var_usd: 26100, var_std_error: 0.005, cvar_pct: 0.3, cvar_usd: 30000 },
  },
  prob_loss_10pct: 0.194,
  prob_loss_20pct: 0.04,
  prob_loss_30pct: 0.003,
  histogram: { bin_edges: [-0.3, 0, 0.3], frequencies: [5000, 5000], densities: [1, 1], median: 0, percentile_5: -0.18, percentile_1: -0.26 },
  warnings: [],
  seed_used: 3141592653,
  drift_used: 'centered',
  historical_drift_annual: 0.2693,
  ...over,
});

const renderView = () =>
  render(
    <PortfolioRiskView
      activeThesis={null}
      suggestedTickers={[
        { symbol: 'CEG', name: 'CEG', sector: 'x', weight: 0.5, thesis_role: 'x' },
        { symbol: 'VST', name: 'VST', sector: 'x', weight: 0.5, thesis_role: 'x' },
      ]}
    />
  );

describe('PortfolioRiskView risk simulation (fix/risk-simulation)', () => {
  it('each click asks for a new seed, centered by default, and shows the seed and the trend label', async () => {
    const spy = vi.spyOn(api, 'evaluatePortfolioRisk').mockResolvedValue(riskResult());
    renderView();
    fireEvent.click(screen.getByRole('button', { name: /Simular 10k Caminos/ }));
    await screen.findByTestId('risk-seed');
    expect(spy.mock.calls[0][0].seed).toBeUndefined();
    expect(spy.mock.calls[0][0].drift).toBe('centered');
    expect(screen.getByTestId('risk-seed')).toHaveTextContent('semilla 3141592653');
    expect(screen.getByTestId('risk-drift-label')).toHaveTextContent('Sin tendencia');
    expect(screen.getByTestId('risk-drift-label')).toHaveTextContent('26.9% anual');

    fireEvent.click(screen.getByRole('button', { name: /Simular 10k Caminos/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][0].seed).toBeUndefined();
  });

  it('"reproducir" fixes the seed shown, so the next run repeats it', async () => {
    const spy = vi.spyOn(api, 'evaluatePortfolioRisk').mockResolvedValue(riskResult());
    renderView();
    fireEvent.click(screen.getByRole('button', { name: /Simular 10k Caminos/ }));
    await screen.findByTestId('risk-seed');
    fireEvent.click(screen.getByRole('button', { name: 'reproducir' }));
    expect((screen.getByTestId('risk-seed-input') as HTMLInputElement).value).toBe('3141592653');
    fireEvent.click(screen.getByRole('button', { name: /Simular 10k Caminos/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][0].seed).toBe(3141592653);
  });

  it('the historical option is available and labeled as such', async () => {
    const spy = vi
      .spyOn(api, 'evaluatePortfolioRisk')
      .mockResolvedValue(riskResult({ drift_used: 'historical' }));
    renderView();
    fireEvent.change(screen.getByTestId('risk-drift-select'), { target: { value: 'historical' } });
    fireEvent.click(screen.getByRole('button', { name: /Simular 10k Caminos/ }));
    await screen.findByTestId('risk-drift-label');
    expect(spy.mock.calls[0][0].drift).toBe('historical');
    expect(screen.getByTestId('risk-drift-label')).toHaveTextContent('Con la tendencia histórica');
  });
});
