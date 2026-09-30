import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ThesisBar } from './ThesisBar';
import type { MacroSuggestion } from '../services/api';

afterEach(() => {
  vi.useRealTimers();
});

const props = {
  onAnalyze: vi.fn(),
  tickers: [],
  macroSeries: [],
  onAddTicker: vi.fn(),
  onRemoveTicker: vi.fn(),
  onAddMacro: vi.fn(),
  onRemoveMacro: vi.fn(),
};

describe('ThesisBar translation progress (4.10)', () => {
  it('says who is translating and for how long', () => {
    vi.useFakeTimers();
    render(<ThesisBar {...props} loading providerLabel="Claude CLI" />);
    expect(screen.getByTestId('translating-indicator')).toHaveTextContent('Traduciendo la tesis con Claude CLI… 0 s');
    act(() => {
      vi.advanceTimersByTime(42_000);
    });
    expect(screen.getByTestId('translating-indicator')).toHaveTextContent('Traduciendo la tesis con Claude CLI… 42 s');
  });

  it('shows nothing when not translating', () => {
    render(<ThesisBar {...props} loading={false} providerLabel="Gemini API" />);
    expect(screen.queryByTestId('translating-indicator')).not.toBeInTheDocument();
  });
});

describe('FRED ID grounding in the chips (4.11)', () => {
  const macro = (over: Partial<MacroSuggestion>): MacroSuggestion => ({
    series_id: 'UMCSENT',
    name: 'Confianza del consumidor',
    category: 'Consumo',
    expected_correlation: 'Positive',
    ...over,
  });

  it('shows a verified ID with no warning', () => {
    render(<ThesisBar {...props} loading={false} macroSeries={[macro({ grounding: 'verificado' })]} />);
    const chip = screen.getByTestId('macro-chip-UMCSENT');
    expect(chip).toHaveAttribute('data-grounding', 'verificado');
    expect(screen.queryByTestId('macro-suggested-UMCSENT')).not.toBeInTheDocument();
    expect(screen.queryByTestId('macro-discarded-UMCSENT')).not.toBeInTheDocument();
    expect(screen.queryByTestId('macro-unverified-UMCSENT')).not.toBeInTheDocument();
  });

  it('shows a repaired series as corrected, naming the ID it replaces', () => {
    render(
      <ThesisBar
        {...props}
        loading={false}
        macroSeries={[macro({
          series_id: 'HSN1F',
          grounding: 'reparado',
          proposed_series_id: 'TOTALSI',
          fred_title: 'New One Family Houses Sold: United States',
          repair_justification: 'Mide cantidad de viviendas vendidas, no precio.',
          grounding_note: "'TOTALSI' no existe en FRED. Se reemplazó por 'HSN1F'.",
        })]}
      />,
    );
    const chip = screen.getByTestId('macro-chip-HSN1F');
    expect(chip).toHaveAttribute('data-grounding', 'reparado');
    expect(screen.getByTestId('macro-repaired-HSN1F')).toHaveTextContent('corregida: reemplaza a TOTALSI');
    // The justification is visible to the user, not hidden.
    expect(chip).toHaveAttribute('title', expect.stringContaining('Mide cantidad de viviendas vendidas'));
  });

  it('never asks the user to choose: no candidate picker anywhere', () => {
    render(
      <ThesisBar
        {...props}
        loading={false}
        macroSeries={[
          macro({ series_id: 'HSN1F', grounding: 'reparado', proposed_series_id: 'TOTALSI' }),
          macro({ series_id: 'IPGD', grounding: 'descartado', proposed_series_id: 'IPGD' }),
        ]}
      />,
    );
    expect(screen.queryByTestId('macro-candidates-TOTALSI')).not.toBeInTheDocument();
    expect(screen.queryByTestId('macro-candidates-IPGD')).not.toBeInTheDocument();
    expect(screen.queryByText('Agregar')).not.toBeInTheDocument();
  });

  it('says "sin verificar" when FRED could not be reached', () => {
    render(<ThesisBar {...props} loading={false} macroSeries={[macro({ grounding: null })]} />);
    expect(screen.getByTestId('macro-unverified-UMCSENT')).toHaveTextContent('sin verificar');
  });
});
