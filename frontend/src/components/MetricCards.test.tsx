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
