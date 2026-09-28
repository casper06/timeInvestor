import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatisticalTelemetry } from './StatisticalTelemetry';
import { ThesisAlertBanner } from './ThesisAlertBanner';
import type { ForecastResponse, TimeSeriesData } from '../services/api';

const monthly: TimeSeriesData = {
  id: 'IPG2211A2N',
  name: 'Electric Power',
  type: 'macro',
  unit: 'Index 2017=100',
  frequency: 'monthly',
  points: Array.from({ length: 24 }, (_, i) => ({
    timestamp: `${2024 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
    value: 110 + 15 * Math.sin((2 * Math.PI * i) / 12),
  })),
};

const fc: ForecastResponse = {
  timestamps: ['2026-12-01'],
  values: [122.54],
  lower_bound: [117.4],
  upper_bound: [127.9],
  model_name: 'timesfm-2.5-200m (cpu)',
  interval_level: 0.8,
};

const seasonal = { frequency: 'monthly', period: 12, is_seasonal: true, n_obs: 500, reason: 'ACF 0.4 > 0.1' };

describe('StatisticalTelemetry', () => {
  it('hides "Estado de la inercia" on a seasonal series and says why', () => {
    render(<StatisticalTelemetry seriesData={monthly} forecast={{ ...fc, seasonality: seasonal }} horizon={12} confidence={0.8} />);
    expect(screen.getByTestId('inertia-hidden')).toHaveTextContent('No se muestra en series estacionales');
    expect(screen.getByTestId('inertia-hidden')).toHaveTextContent('m=12');
    for (const label of [
      'Lateralización',
      'Aceleración positiva',
      'Aceleración negativa',
      'Tendencia alcista con desaceleración',
      'Tendencia bajista con atenuación',
    ]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('keeps it on a non-seasonal series', () => {
    render(
      <StatisticalTelemetry
        seriesData={monthly}
        forecast={{ ...fc, seasonality: { ...seasonal, is_seasonal: false } }}
        horizon={12}
        confidence={0.8}
      />
    );
    expect(screen.queryByTestId('inertia-hidden')).not.toBeInTheDocument();
  });

  it('a macro series has no "$" and says "último valor"', () => {
    const { container } = render(<StatisticalTelemetry seriesData={monthly} forecast={fc} horizon={12} confidence={0.8} />);
    expect(container.textContent).not.toContain('$');
    expect(container.textContent).toContain('último valor registrado');
    expect(container.textContent).toContain('Index 2017=100');
  });

  it('"no aporta": the central trend loses its color', () => {
    render(
      <StatisticalTelemetry
        seriesData={monthly}
        forecast={{ ...fc, skill: { state: 'no_aporta', reason: 'x', naive: 'random_walk' } }}
        horizon={12}
        confidence={0.8}
      />
    );
    expect(screen.getByTestId('central-trend-pct').className).not.toMatch(/emerald|rose/);
  });
});

describe('ThesisAlertBanner', () => {
  it('uses the real band level, the engine that answered, and no "$" for a macro series', () => {
    const breached = { ...fc, lower_bound: [140], upper_bound: [160] };
    const { container } = render(<ThesisAlertBanner seriesData={monthly} forecast={breached} thesisStatus="Activa" />);
    expect(container.textContent).toContain('Desvío de Soporte 80%');
    expect(container.textContent).not.toContain('95%');
    expect(container.textContent).toContain('timesfm-2.5-200m (cpu)');
    expect(container.textContent).toContain('La serie IPG2211A2N');
    expect(container.textContent).toContain('último valor');
    expect(container.textContent).not.toContain('$');
  });
});
