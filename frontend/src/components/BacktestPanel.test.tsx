import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { BacktestPanel } from './BacktestPanel';
import * as api from '../services/api';

// The chart isn't under test here, and jsdom has no canvas.
vi.mock('react-chartjs-2', () => ({ Line: () => <div data-testid="chart" /> }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const seriesData: api.TimeSeriesData = {
  id: 'NVDA',
  name: 'NVIDIA',
  type: 'equity',
  unit: 'USD',
  source: 'live',
  points: Array.from({ length: 120 }, (_, i) => ({
    timestamp: `2025-${String(Math.floor(i / 28) + 1).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}`,
    value: 100 + i,
  })),
};

const metrics: api.BacktestMetrics = {
  mae: 1.5,
  mape: 2.1,
  smape: 2.0,
  mase: 1.2,
  directional_accuracy: 55,
  observations_evaluated: 30,
};

function backtestResult(overrides: Partial<api.BacktestResponse> = {}): api.BacktestResponse {
  return {
    series_id: 'NVDA',
    cutoff_date: '2025-03-01',
    horizon: 30,
    historical_dates: ['2025-02-28'],
    historical_values: [150],
    future_actual_dates: ['2025-03-02'],
    future_actual_values: [151],
    future_predicted_values: [150.5],
    future_lower_bound: [149],
    future_upper_bound: [152],
    metrics,
    verdict: 'El modelo supera al benchmark naive.',
    warnings: [],
    model_name: 'timesfm-2.5-200m (cpu)',
    is_fallback: false,
    ...overrides,
  };
}

async function runWith(result: api.BacktestResponse) {
  vi.spyOn(api, 'runBacktest').mockResolvedValue(result);
  render(<BacktestPanel seriesData={seriesData} activeSeriesId="NVDA" />);
  fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
  await screen.findByText(/El modelo supera al benchmark naive/);
}

describe('BacktestPanel', () => {
  it('says the metrics are Holt\'s, why, and to retry on a one-off inference error', async () => {
    await runWith(backtestResult({
      is_fallback: true,
      model_name: 'damped-holt-mle (fallback: TimesFM no disponible)',
      fallback_kind: 'inference_error',
      fallback_reason: 'La inferencia de TimesFM falló: RuntimeError: out of memory',
    }));

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Estas métricas son de Holt, no de TimesFM');
    expect(alert).toHaveTextContent('Causa: La inferencia de TimesFM falló: RuntimeError: out of memory');
    expect(alert).toHaveTextContent('reintentá');
  });

  it('says waiting does not help when TimesFM is not loaded', async () => {
    await runWith(backtestResult({
      is_fallback: true,
      fallback_kind: 'not_loaded',
      fallback_reason: 'TimesFM no está cargado en el servidor.',
    }));

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Esperar no lo arregla');
    expect(alert).toHaveTextContent('USE_REAL_TIMESFM=true');
    expect(alert).not.toHaveTextContent('reintentá');
  });

  it('asks for a shorter horizon when it exceeds TimesFM\'s maximum', async () => {
    await runWith(backtestResult({ is_fallback: true, fallback_kind: 'horizon_exceeded' }));
    expect(screen.getByRole('alert')).toHaveTextContent('horizonte de 128 pasos de la serie o menos');
  });

  it('shows no fallback notice when TimesFM really ran, and lists backend warnings', async () => {
    await runWith(backtestResult({
      warnings: ['Subcobertura del intervalo: La cobertura empírica observada (43.3%) está por debajo del nominal.'],
    }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Advertencias del backtest' });
    expect(list).toHaveTextContent('Subcobertura del intervalo');
  });
});

describe('BacktestPanel engine choice', () => {
  it('sends engine=holt_winters when chosen and shows the engine that actually ran', async () => {
    const spy = vi.spyOn(api, 'runBacktest').mockResolvedValue(
      backtestResult({ model_name: 'holt-winters-ets(A,Ad,A) m=12' }),
    );
    render(<BacktestPanel seriesData={seriesData} activeSeriesId="IPG2211A2N" />);

    fireEvent.click(screen.getByRole('checkbox', { name: /Holt-Winters/ }));
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
    await screen.findByText(/El modelo supera al benchmark naive/);

    expect(spy.mock.calls[0][4]).toBe('holt_winters');
    expect(screen.getByTestId('backtest-engine-badge')).toHaveTextContent('holt-winters-ets(A,Ad,A) m=12');
  });

  it('does not send an engine by default', async () => {
    const spy = vi.spyOn(api, 'runBacktest').mockResolvedValue(backtestResult());
    render(<BacktestPanel seriesData={seriesData} activeSeriesId="NVDA" />);
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
    await screen.findByText(/El modelo supera al benchmark naive/);

    expect(spy.mock.calls[0][4]).toBeUndefined();
    expect(screen.getByTestId('backtest-engine-badge')).toHaveTextContent('timesfm-2.5-200m (cpu)');
  });
});

describe('BacktestPanel horizon in the series unit (4.14)', () => {
  const monthly: api.TimeSeriesData = {
    id: 'INDPRO',
    name: 'Industrial Production',
    type: 'macro',
    unit: 'Index',
    source: 'live',
    frequency: 'monthly',
    points: Array.from({ length: 120 }, (_, i) => ({
      timestamp: `${2016 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
      value: 100 + i,
    })),
  };

  it('evaluates a monthly series in months, 12 by default', async () => {
    const spy = vi.spyOn(api, 'runBacktest').mockResolvedValue(backtestResult({ series_id: 'INDPRO', frequency: 'monthly' }));
    render(<BacktestPanel seriesData={monthly} activeSeriesId="INDPRO" />);
    for (const label of ['3m', '6m', '12m', '24m']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    // Default cutoff leaves the 12 months to evaluate.
    expect(screen.getByText(/Futuro a evaluar: 12 meses/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Ejecutar Reality Check/ }));
    await screen.findByText(/El modelo supera al benchmark naive/);
    expect(spy).toHaveBeenCalledWith('INDPRO', '2024-12-01', 12, 0.95, undefined, 'macro');
  });
});

describe('BacktestPanel undefined metrics (2.10)', () => {
  it('shows "no definido" with the reason instead of a number', async () => {
    await runWith(
      backtestResult({
        metrics: { ...metrics, mape: null, undefined: { mape: 'MAPE no definido: algún valor real del período evaluado es 0' } },
      })
    );
    expect(screen.getByTestId('mape-undefined')).toHaveTextContent('no definido');
    expect(screen.getByText(/algún valor real del período evaluado es 0/)).toBeInTheDocument();
  });
});
