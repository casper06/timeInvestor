import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ForecastChart } from './ForecastChart';
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
});
