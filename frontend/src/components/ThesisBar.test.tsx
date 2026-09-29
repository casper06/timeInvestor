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

  it('marks a series found by concept search, keeping the ID the LLM invented', () => {
    render(
      <ThesisBar
        {...props}
        loading={false}
        macroSeries={[macro({
          series_id: 'TOTALSA',
          grounding: 'sugerido_por_busqueda',
          proposed_series_id: 'TOTALSI',
          fred_title: 'Total Vehicle Sales',
          grounding_note: "'TOTALSI' no existe en FRED. Se sugiere 'TOTALSA' (Total Vehicle Sales).",
        })]}
      />,
    );
    expect(screen.getByTestId('macro-suggested-TOTALSA')).toHaveTextContent('sugerido por búsqueda');
    expect(screen.getByTestId('macro-chip-TOTALSA')).toHaveAttribute('title', expect.stringContaining('TOTALSI'));
  });

  it('marks a discarded ID visibly, so it cannot pass as verified', () => {
    render(
      <ThesisBar
        {...props}
        loading={false}
        macroSeries={[macro({
          series_id: 'IPGD',
          grounding: 'descartado',
          proposed_series_id: 'IPGD',
          grounding_note: "'IPGD' no existe en FRED y la búsqueda no encontró ninguna serie real.",
        })]}
      />,
    );
    expect(screen.getByTestId('macro-discarded-IPGD')).toHaveTextContent('no existe en FRED');
    expect(screen.getByTestId('macro-chip-IPGD').className).toContain('line-through');
  });

  it('says "sin verificar" when FRED could not be reached', () => {
    render(<ThesisBar {...props} loading={false} macroSeries={[macro({ grounding: null })]} />);
    expect(screen.getByTestId('macro-unverified-UMCSENT')).toHaveTextContent('sin verificar');
  });
});
