import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
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

  const pending = (): MacroSuggestion => macro({
    series_id: 'TOTALSI',
    name: 'Ventas totales de viviendas nuevas',
    grounding: 'sugerido_por_busqueda',
    proposed_series_id: 'TOTALSI',
    searched_concept: 'new home sales',
    grounding_note: "'TOTALSI' no existe en FRED; elegí un reemplazo o seguí sin esta serie.",
    candidates: [
      { series_id: 'MSPUS', title: 'Median Sales Price of New Houses Sold for the United States', frequency: 'Q', seasonal_adjustment: 'NSA', observation_start: '1963-01-01', observation_end: '2026-04-01', units: '$' },
      { series_id: 'ASPUS', title: 'Average Sales Price of Houses Sold for the United States', frequency: 'Q', seasonal_adjustment: 'NSA', observation_start: '1963-01-01', observation_end: '2026-04-01', units: '$' },
      { series_id: 'EXHOSLUSM495S', title: 'Existing Home Sales', frequency: 'M', seasonal_adjustment: 'SAAR', observation_start: '2025-08-01', observation_end: '2026-08-01', units: 'Number of Units' },
    ],
  });

  it('offers the candidates with the metadata to tell them apart, without substituting the ID', () => {
    render(<ThesisBar {...props} loading={false} macroSeries={[pending()]} />);

    // The chip still shows the ID the LLM invented, marked as unresolved.
    expect(screen.getByTestId('macro-pending-TOTALSI')).toHaveTextContent('sin reemplazo elegido');

    const box = screen.getByTestId('macro-candidates-TOTALSI');
    expect(box).toHaveTextContent("'TOTALSI' no existe en FRED");
    expect(box).toHaveTextContent('elegí un reemplazo o seguí sin esta serie');
    expect(box).toHaveTextContent('new home sales');
    // FRED's metadata for each candidate.
    expect(box).toHaveTextContent('MSPUS');
    expect(box).toHaveTextContent('Median Sales Price of New Houses Sold for the United States');
    expect(box).toHaveTextContent('Q');
    expect(box).toHaveTextContent('NSA');
    expect(box).toHaveTextContent('1963-01-01 → 2026-04-01');
    expect(screen.getByTestId('macro-choose-TOTALSI-MSPUS')).toBeInTheDocument();
    expect(screen.getByTestId('macro-choose-TOTALSI-ASPUS')).toBeInTheDocument();
    expect(screen.getByTestId('macro-choose-TOTALSI-EXHOSLUSM495S')).toBeInTheDocument();
  });

  it('reports the chosen candidate to the caller', async () => {
    const onChooseCandidate = vi.fn();
    render(<ThesisBar {...props} loading={false} macroSeries={[pending()]} onChooseCandidate={onChooseCandidate} />);

    fireEvent.click(screen.getByTestId('macro-choose-TOTALSI-EXHOSLUSM495S'));

    expect(onChooseCandidate).toHaveBeenCalledTimes(1);
    expect(onChooseCandidate.mock.calls[0][0]).toBe('TOTALSI');
    expect(onChooseCandidate.mock.calls[0][1].series_id).toBe('EXHOSLUSM495S');
  });

  it('once chosen, shows it as the pick of the user and drops the picker', () => {
    const chosen = { ...pending(), series_id: 'MSPUS', chosen_by_user: true, grounding_note: null };
    render(<ThesisBar {...props} loading={false} macroSeries={[chosen]} />);

    expect(screen.getByTestId('macro-chosen-MSPUS')).toHaveTextContent('elegida por vos');
    expect(screen.queryByTestId('macro-candidates-TOTALSI')).not.toBeInTheDocument();
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
