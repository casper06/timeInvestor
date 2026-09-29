import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ThesisBar } from './ThesisBar';

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
