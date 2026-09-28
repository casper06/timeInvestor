import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetricCards } from './MetricCards';
import type { ForecastResponse, TimeSeriesData } from '../services/api';

const monthly: TimeSeriesData = {
  id: 'INDPRO',
  name: 'Industrial Production',
  type: 'macro',
  unit: 'Index',
  frequency: 'monthly',
  points: [
    { timestamp: '2025-11-01', value: 99 },
    { timestamp: '2025-12-01', value: 100 },
  ],
};

const monthlyForecast: ForecastResponse = {
  timestamps: Array.from({ length: 12 }, (_, i) => `2026-${String(i + 1).padStart(2, '0')}-01`),
  values: [...Array(11).fill(101), 110],
  lower_bound: Array(12).fill(95),
  upper_bound: Array(12).fill(120),
  model_name: 'damped-holt-mle',
  frequency: 'monthly',
  horizon: 12,
  decision_horizon: 30,
};

describe('MetricCards in the series unit (4.14)', () => {
  it('labels a monthly target in months and annualizes over one year', () => {
    render(<MetricCards thesisData={null} forecast={monthlyForecast} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.getByText('Objetivo +12 meses')).toBeInTheDocument();
    expect(screen.getByText('Horizonte proyectivo 12 meses')).toBeInTheDocument();
    expect(screen.getByText('+10.0%', { selector: 'div' })).toBeInTheDocument(); // 100 -> 110 in one year
  });

  it('says at which horizon the engine was chosen when it differs from the requested one', () => {
    render(<MetricCards thesisData={null} forecast={monthlyForecast} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('decision-horizon-note')).toHaveTextContent('Motor elegido evaluando a 30 meses');
  });

  it('shows no note when the engine was chosen at the requested horizon', () => {
    render(
      <MetricCards
        thesisData={null}
        forecast={{ ...monthlyForecast, decision_horizon: 12 }}
        seriesData={monthly}
        horizon={12}
        confidence={0.95}
      />
    );
    expect(screen.queryByTestId('decision-horizon-note')).not.toBeInTheDocument();
  });

  it('keeps "+60d" for daily series', () => {
    const daily: TimeSeriesData = { ...monthly, id: 'NVDA', frequency: 'daily', points: [{ timestamp: '2026-05-29', value: 100 }] };
    const fc: ForecastResponse = { ...monthlyForecast, timestamps: ['2026-06-01', '2026-08-21'], values: [101, 105], frequency: 'daily', horizon: 60, decision_horizon: null };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={daily} horizon={60} confidence={0.95} />);
    expect(screen.getByText('Objetivo +60d')).toBeInTheDocument();
    expect(screen.getByText('Horizonte proyectivo 60 días hábiles')).toBeInTheDocument();
  });
});

describe('MetricCards unreliable forecast (2.6)', () => {
  it('shows the warning when the backend marks the forecast unreliable, with the numbers untouched', () => {
    const fc: ForecastResponse = {
      ...monthlyForecast,
      values: [...Array(11).fill(1000), 20855.32],
      reliable: false,
      reliability_warning: 'Pronóstico no confiable: a 12 meses proyecta 20,855.32 (×1,409.1 el último valor).',
    };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('unreliable-forecast')).toHaveTextContent('Pronóstico no confiable');
    expect(screen.getByText('20855.32')).toBeInTheDocument();
  });

  it('shows nothing when the forecast is reliable', () => {
    render(<MetricCards thesisData={null} forecast={{ ...monthlyForecast, reliable: true }} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.queryByTestId('unreliable-forecast')).not.toBeInTheDocument();
  });
});

describe('MetricCards forecast skill (4.13)', () => {
  const base = { ...monthlyForecast, decision_horizon: 12 };

  it('"aporta": the point forecast stays the main figure; the badge is not here (it moved to the chart panel)', () => {
    const fc: ForecastResponse = {
      ...base,
      skill: { state: 'aporta', reason: 'Le gana al naive estacional en 18 de 24 cutoffs, con un error medio 17% menor', naive: 'naive_estacional', wins: 18, n_pairs: 24 },
    };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.queryByTestId('skill-badge')).not.toBeInTheDocument();
    expect(screen.queryByTestId('target-range-first')).not.toBeInTheDocument();
    expect(screen.getByText('110.00')).toBeInTheDocument();
    expect(screen.getByTestId('cagr-value')).toHaveAttribute('data-secondary', 'false');
    expect(screen.getByTestId('cagr-value').className).toContain('text-emerald-400');
  });

  it('"no aporta": the range becomes the main figure and the point is secondary, with the warning', () => {
    const fc: ForecastResponse = {
      ...base,
      skill: { state: 'no_aporta', reason: 'No aporta más que el random walk (igual que el último dato): le gana en 3 de 8 cutoffs', naive: 'random_walk', wins: 3, n_pairs: 8 },
    };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    const card = screen.getByTestId('target-range-first');
    expect(card).toHaveTextContent('[95.00 — 120.00]');
    expect(card).toHaveTextContent('Punto central 110.00');
    expect(card).toHaveTextContent("El pronóstico puntual no supera a 'igual que el último dato'");
    // The CAGR comes from the point: secondary too, without green or emphasis.
    const cagr = screen.getByTestId('cagr-value');
    expect(cagr).toHaveAttribute('data-secondary', 'true');
    expect(cagr.className).not.toContain('emerald');
    expect(cagr.className).not.toContain('font-bold');
    expect(screen.getByText('Sale del punto central, que no supera al naive')).toBeInTheDocument();
  });

  it('"no aporta" against the seasonal naive names that naive', () => {
    const fc: ForecastResponse = { ...base, skill: { state: 'no_aporta', reason: 'x', naive: 'naive_estacional' } };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('target-range-first')).toHaveTextContent("igual que el mismo período del ciclo anterior");
  });

  it('"no evaluado" keeps the normal card', () => {
    const fc: ForecastResponse = { ...base, skill: { state: 'no_evaluado', reason: 'Historia insuficiente para evaluar (150 de 186 puntos)' } };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.queryByTestId('target-range-first')).not.toBeInTheDocument();
    expect(screen.getByTestId('cagr-value')).toHaveAttribute('data-secondary', 'false');
  });
});

describe('MetricCards CAGR color', () => {
  it('a negative CAGR is not shown in green', () => {
    const fc: ForecastResponse = { ...monthlyForecast, values: [...Array(11).fill(99), 90] };
    render(<MetricCards thesisData={null} forecast={fc} seriesData={monthly} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('cagr-value')).toHaveTextContent('-10.0%');
    expect(screen.getByTestId('cagr-value').className).toContain('text-rose-400');
  });
});
