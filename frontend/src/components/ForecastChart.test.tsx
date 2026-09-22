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
    const technicalError = "No se pudieron obtener datos de FRED para 'IPG2211N' (FRED API no disponible (clave no configurada o error de conexión)) y ALLOW_SYNTHETIC_DATA=false";
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
    const ipgTab = screen.getByRole('button', { name: /IPG2211N/ });
    expect(ipgTab.title).toBe('');
  });
});
