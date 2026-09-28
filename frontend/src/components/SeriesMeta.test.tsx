import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import * as api from '../services/api';
import type { ForecastResponse, TimeSeriesData } from '../services/api';
import { seriesMetaText } from '../utils/valueFormat';
import { generateMarkdownReport } from '../utils/exportReport';
import { ForecastChart } from './ForecastChart';
import { DualAxisChart } from './DualAxisChart';
import { MetricCards } from './MetricCards';
import { StatisticalTelemetry } from './StatisticalTelemetry';

// Charts don't draw in jsdom; the labels are checked through the DOM text.
vi.mock('react-chartjs-2', () => ({ Line: () => null, Bar: () => null, Doughnut: () => null }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const points = Array.from({ length: 30 }, (_, i) => ({
  timestamp: `${2024 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
  value: 100 + i,
}));

const withMeta: TimeSeriesData = {
  id: 'DGS10',
  name: 'Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity',
  type: 'macro',
  unit: 'Percent',
  frequency: 'monthly',
  metadata_source: 'fred',
  source_frequency: 'Daily',
  seasonal_adjustment: 'Not Seasonally Adjusted',
  seasonal_adjustment_short: 'NSA',
  points,
  source: 'live',
};

const noMeta: TimeSeriesData = {
  id: 'PCU221110221110',
  name: 'PCU221110221110',
  type: 'macro',
  unit: null,
  frequency: 'monthly',
  metadata_source: 'unavailable',
  metadata_note: 'metadatos no disponibles: HTTP 500',
  points,
  source: 'live',
};

const fc: ForecastResponse = {
  timestamps: ['2026-07-01'],
  values: [131],
  lower_bound: [120],
  upper_bound: [140],
  model_name: 'damped-holt-mle',
};

const chartProps = {
  forecast: fc,
  onSelectSeries: vi.fn(),
  horizon: 12,
  onChangeHorizon: vi.fn(),
  confidence: 0.95,
  onChangeConfidence: vi.fn(),
  period: 'max',
  onChangePeriod: vi.fn(),
  isNormalized: false,
  onToggleNormalized: vi.fn(),
  loading: false,
};

describe('FRED metadata shown (fix/fred-metadata)', () => {
  it('seriesMetaText: unit · FRED frequency · SA/NSA, or "metadatos no disponibles"', () => {
    expect(seriesMetaText(withMeta)).toBe('Percent · Daily · NSA');
    expect(seriesMetaText(noMeta)).toBe('metadatos no disponibles');
    expect(seriesMetaText({ type: 'equity', unit: 'USD' })).toBe('USD');
  });

  it('chart footer', () => {
    render(<ForecastChart {...chartProps} seriesData={withMeta} selectedSeriesId="DGS10" allSeriesList={[]} />);
    expect(screen.getByTestId('series-meta')).toHaveTextContent('Percent · Daily · NSA');
    cleanup();
    render(<ForecastChart {...chartProps} seriesData={noMeta} selectedSeriesId="PCU221110221110" allSeriesList={[]} />);
    expect(screen.getByTestId('series-meta')).toHaveTextContent('metadatos no disponibles');
    expect(document.body.textContent).not.toContain('Index');
  });

  it('target card and telemetry', () => {
    render(<MetricCards thesisData={null} forecast={fc} seriesData={withMeta} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('card-series-meta')).toHaveTextContent('Percent · Daily · NSA');
    cleanup();
    render(<StatisticalTelemetry seriesData={noMeta} forecast={fc} horizon={12} confidence={0.95} />);
    expect(screen.getByTestId('telemetry-series-meta')).toHaveTextContent('metadatos no disponibles');
  });

  it('dual-axis chart names both series with their metadata', async () => {
    vi.spyOn(api, 'fetchMacroData').mockResolvedValue(noMeta);
    render(
      <DualAxisChart
        primarySeriesData={withMeta}
        allAvailableSeries={[
          { id: 'DGS10', name: 'x', type: 'macro' },
          { id: 'PCU221110221110', name: 'y', type: 'macro' },
        ]}
      />
    );
    expect(screen.getByTestId('dual-left')).toHaveTextContent(`${withMeta.name} — Percent · Daily · NSA`);
    await waitFor(() => expect(screen.getByTestId('dual-right')).toHaveTextContent('PCU221110221110 — metadatos no disponibles'));
  });

  it('report', () => {
    const md = generateMarkdownReport({
      thesis: null,
      seriesData: withMeta,
      forecast: fc,
      fundamentals: [],
      interpretation: null,
      horizon: 12,
      confidence: 0.95,
    });
    expect(md).toContain(`- **Serie:** ${withMeta.name} (Percent · Daily · NSA)`);
    const md2 = generateMarkdownReport({
      thesis: null, seriesData: noMeta, forecast: fc, fundamentals: [], interpretation: null, horizon: 12, confidence: 0.95,
    });
    expect(md2).toContain('- **Serie:** PCU221110221110 (metadatos no disponibles)');
  });
});
