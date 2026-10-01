import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ForecastChart, humanizeSeriesError } from './ForecastChart';
import type { TimeSeriesData } from '../services/api';

const baseProps = {
  forecast: null,
  onSelectSeries: vi.fn(),
  horizon: 60,
  onChangeHorizon: vi.fn(),
  confidence: 0.95,
  onChangeConfidence: vi.fn(),
  period: '1y',
  onChangePeriod: vi.fn(),
  isNormalized: false,
  onToggleNormalized: vi.fn(),
  loading: false,
};

const allSeriesList = [
  { id: 'CEG', name: 'Constellation Energy', type: 'equity' },
  { id: 'IPG2211N', name: 'Electric Power Generation', type: 'macro' },
];

const cegSeriesData: TimeSeriesData = {
  id: 'CEG',
  name: 'Constellation Energy Corporation',
  type: 'equity',
  unit: 'USD',
  points: [
    { timestamp: '2026-01-01', value: 250 },
    { timestamp: '2026-01-02', value: 255 },
    { timestamp: '2026-01-03', value: 254.71 },
  ],
  source: 'live',
  from_cache: false,
};

describe('ForecastChart — "Serie Activa" selector', () => {
  it('renders the series tab row and calls onSelectSeries when a tab is clicked', () => {
    const onSelectSeries = vi.fn();
    render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
        onSelectSeries={onSelectSeries}
      />
    );

    expect(screen.getByText('SERIE ACTIVA:', { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'IPG2211N' }));
    expect(onSelectSeries).toHaveBeenCalledWith('IPG2211N');
  });

  it('keeps the series tab row visible and does not crash when seriesData is null (failed fetch)', () => {
    // Regression test: seriesData becomes null when the selected series' fetch fails
    // (e.g. a FRED macro series with no FRED_API_KEY configured). The tab row must
    // stay on screen so the user can click back to a working series — it must not
    // disappear, and computing chart data from an empty series must not throw
    // (a prior version threw `RangeError: Invalid array length` here).
    expect(() =>
      render(
        <ForecastChart
          {...baseProps}
          seriesData={null}
          selectedSeriesId="IPG2211N"
          allSeriesList={allSeriesList}
          onSelectSeries={vi.fn()}
        />
      )
    ).not.toThrow();

    expect(screen.getByText('SERIE ACTIVA:', { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'CEG' })).toBeInTheDocument();
    expect(screen.getByText(/No hay datos de series temporales disponibles/i)).toBeInTheDocument();
  });

  it('shows the real backend error message instead of the generic string when seriesError is set', () => {
    // A yfinance-side failure (not a missing-key case) — must render verbatim,
    // not the generic "No hay datos..." placeholder.
    const specificError = 'No se pudo obtener el histórico para XYZ123: ticker no encontrado en yfinance.';
    render(
      <ForecastChart
        {...baseProps}
        seriesData={null}
        seriesError={specificError}
        selectedSeriesId="XYZ123"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
      />
    );

    expect(screen.getByText(specificError)).toBeInTheDocument();
    expect(screen.queryByText(/^No hay datos de series temporales disponibles\.$/i)).not.toBeInTheDocument();
  });

  it('humanizes a missing-FRED-key error into user-facing copy', () => {
    const technicalError = "No se pudieron obtener datos de FRED para 'IPG2211N' (FRED API no disponible (FRED_API_KEY no configurada)) y ALLOW_SYNTHETIC_DATA=false";
    render(
      <ForecastChart
        {...baseProps}
        seriesData={null}
        seriesError={technicalError}
        selectedSeriesId="IPG2211N"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
      />
    );

    // The raw technical string (mentioning ALLOW_SYNTHETIC_DATA) must NOT be
    // shown verbatim — it should be translated to friendly copy naming FRED_API_KEY.
    expect(screen.queryByText(technicalError)).not.toBeInTheDocument();
    expect(screen.getByText(/FRED_API_KEY/)).toBeInTheDocument();
    expect(humanizeSeriesError(technicalError)).toMatch(/FRED_API_KEY/);
  });

  it('tells apart a rejected FRED key, a missing one and FRED being down', () => {
    const rejected = 'FRED rechazó la clave (HTTP 400): Bad Request.  The value for variable api_key is not registered. Revisá que la hayas copiado completa en el .env (FRED_API_KEY).';
    const missing = "No se pudieron obtener datos de FRED para 'UNRATE' (FRED API no disponible (FRED_API_KEY no configurada)) y ALLOW_SYNTHETIC_DATA=false";
    const down = "No se pudieron obtener datos de FRED para 'UNRATE' (FRED API no disponible (HTTP 503)) y ALLOW_SYNTHETIC_DATA=false";

    expect(humanizeSeriesError(rejected)).toBe('FRED rechazó tu clave: revisá que la hayas copiado completa en el .env (FRED_API_KEY).');
    expect(humanizeSeriesError(rejected)).not.toMatch(/no está configurada/);
    expect(humanizeSeriesError(missing)).toMatch(/no está configurada/);
    expect(humanizeSeriesError(down)).toMatch(/no está respondiendo/);
    expect(humanizeSeriesError(down)).not.toMatch(/clave/);
  });

  it('highlights the currently selected series tab', () => {
    render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
      />
    );
    const cegTab = screen.getByRole('button', { name: 'CEG' });
    const ipgTab = screen.getByRole('button', { name: 'IPG2211N' });
    expect(cegTab.className).toContain('bg-cyan-500');
    expect(ipgTab.className).not.toContain('bg-cyan-500');
  });

  it('shows the real active engine name in the loading spinner, not a hardcoded "TimesFM"', () => {
    // The forecast for the PREVIOUS series can still be in state while a new one
    // loads — its model_name is what's actually active (damped-holt-mle in the
    // common case here, unless real TimesFM weights are installed).
    const holtForecast = {
      timestamps: [],
      values: [],
      lower_bound: [],
      upper_bound: [],
      model_name: 'damped-holt-mle',
    };
    render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        forecast={holtForecast}
        loading={true}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
      />
    );

    expect(screen.getByText(/Calculando proyección damped-holt-mle\.\.\./)).toBeInTheDocument();
    expect(screen.queryByText(/Calculando proyección TimesFM\.\.\./)).not.toBeInTheDocument();
  });

  it('flags a macro series tab as requiring FRED_API_KEY when hasFredKey is false', () => {
    render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
        hasFredKey={false}
      />
    );
    const ipgTab = screen.getByRole('button', { name: /IPG2211N/ });
    expect(ipgTab.title).toMatch(/FRED_API_KEY/);
    // The equity tab (CEG) never needs a FRED key — must not be flagged.
    const cegTab = screen.getByRole('button', { name: /CEG/ });
    expect(cegTab.title).toBe('');
  });

  it('does not flag macro series tabs when hasFredKey is true', () => {
    render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
        onSelectSeries={vi.fn()}
        hasFredKey={true}
      />
    );
    // Exact match: with hasFredKey=true, FredInfoTooltip also renders a button
    // whose aria-label contains "IPG2211N" ("Información de la serie FRED
    // IPG2211N") — the tab button's accessible name is the ticker alone.
    const ipgTab = screen.getByRole('button', { name: 'IPG2211N' });
    expect(ipgTab.title).toBe('');
  });
});

describe('ForecastChart interval level', () => {
  it('says so when the engine delivered a different level than requested', () => {
    render(<ForecastChart {...baseProps} confidence={0.95} intervalLevel={0.8} allSeriesList={allSeriesList} selectedSeriesId="CEG" seriesData={cegSeriesData} />);
    expect(screen.getByTestId('interval-level-note')).toHaveTextContent('este motor da 80%');
  });

  it('shows no note when the levels match', () => {
    render(<ForecastChart {...baseProps} confidence={0.95} intervalLevel={0.95} allSeriesList={allSeriesList} selectedSeriesId="CEG" seriesData={cegSeriesData} />);
    expect(screen.queryByTestId('interval-level-note')).not.toBeInTheDocument();
  });
});

describe('ForecastChart horizon in the series unit (4.14)', () => {
  const monthly: TimeSeriesData = {
    id: 'INDPRO',
    name: 'Industrial Production',
    type: 'macro',
    unit: 'Index',
    frequency: 'monthly',
    points: Array.from({ length: 36 }, (_, i) => ({
      timestamp: `${2023 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}-01`,
      value: 100 + i,
    })),
    source: 'live',
  };
  const forecast = {
    timestamps: Array.from({ length: 12 }, (_, i) => `2026-${String(i + 1).padStart(2, '0')}-01`),
    values: Array.from({ length: 12 }, (_, i) => 136 + i),
    lower_bound: Array.from({ length: 12 }, (_, i) => 130 + i),
    upper_bound: Array.from({ length: 12 }, (_, i) => 142 + i),
    model_name: 'damped-holt-mle',
    frequency: 'monthly',
    horizon: 12,
  };

  it('offers monthly horizons and labels the projection in months', () => {
    const onChangeHorizon = vi.fn();
    render(
      <ForecastChart
        {...baseProps}
        horizon={12}
        onChangeHorizon={onChangeHorizon}
        forecast={forecast}
        seriesData={monthly}
        selectedSeriesId="INDPRO"
        allSeriesList={allSeriesList}
      />
    );
    for (const label of ['3m', '6m', '12m', '24m']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: '60d' })).not.toBeInTheDocument();
    expect(screen.getByText(/Proyección \+12 meses/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '6m' }));
    expect(onChangeHorizon).toHaveBeenCalledWith(6);
  });

  it('keeps the daily horizons for daily series', () => {
    render(
      <ForecastChart {...baseProps} seriesData={{ ...cegSeriesData, frequency: 'daily' }} selectedSeriesId="CEG" allSeriesList={allSeriesList} />
    );
    for (const label of ['30d', '60d', '90d', '180d']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });
});

describe('ForecastChart forecast skill badge (4.13, moved next to "Serie activa")', () => {
  const fc = (state: 'aporta' | 'no_aporta', reason: string) => ({
    timestamps: ['2026-01-04'],
    values: [256],
    lower_bound: [240],
    upper_bound: [270],
    model_name: 'damped-holt-mle',
    skill: { state, reason, naive: 'random_walk' as const },
  });

  it('shows the selected series verdict in the chart panel and changes with the series', () => {
    const first = render(
      <ForecastChart
        {...baseProps}
        seriesData={cegSeriesData}
        forecast={fc('no_aporta', 'le gana en 6 de 8 cutoffs, 7% menos')}
        selectedSeriesId="CEG"
        allSeriesList={allSeriesList}
      />
    );
    const badge = screen.getByTestId('skill-badge');
    expect(badge).toHaveAttribute('data-state', 'no_aporta');
    expect(badge).toHaveAttribute('data-series', 'CEG');
    expect(badge).toHaveTextContent('Capacidad de pronóstico (CEG): No aporta más que el naive');
    expect(badge).toHaveTextContent('6 de 8 cutoffs');

    const ipg = { ...cegSeriesData, id: 'IPG2211N', name: 'Electric Power', type: 'macro', unit: 'Index' };
    first.unmount(); // a chart.js re-render doesn't run in jsdom; a fresh render is the same props change
    render(
      <ForecastChart
        {...baseProps}
        seriesData={ipg}
        forecast={fc('aporta', 'le gana en 18 de 24 cutoffs')}
        selectedSeriesId="IPG2211N"
        allSeriesList={allSeriesList}
      />
    );
    expect(screen.getByTestId('skill-badge')).toHaveAttribute('data-state', 'aporta');
    expect(screen.getByTestId('skill-badge')).toHaveTextContent('Capacidad de pronóstico (IPG2211N): Aporta sobre el naive');
  });

  it('shows no badge while the selected series has no forecast yet', () => {
    render(<ForecastChart {...baseProps} seriesData={cegSeriesData} selectedSeriesId="CEG" allSeriesList={allSeriesList} />);
    expect(screen.queryByTestId('skill-badge')).not.toBeInTheDocument();
  });
});
