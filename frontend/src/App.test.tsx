import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./services/api')>();
  return {
    ...actual,
    checkHealth: vi.fn().mockResolvedValue({ status: 'ok', has_fred_key: true, use_real_timesfm: true, llm_provider: 'mock' }),
    analyzeThesis: vi.fn(),
    fetchTheses: vi.fn().mockResolvedValue([]),
    fetchThesisDetail: vi.fn(),
    fetchMarketData: vi.fn(),
    fetchMacroData: vi.fn(),
    fetchForecast: vi.fn(),
    fetchFundamentals: vi.fn().mockResolvedValue([]),
    fetchLLMProviders: vi.fn().mockResolvedValue({ active: 'mock', providers: [] }),
  };
});

import * as api from './services/api';
import App from './App';

beforeEach(() => vi.clearAllMocks());

describe('Empty start', () => {
  it('only checks health on mount: no thesis analyzed, no saved thesis loaded', async () => {
    render(<App />);
    await waitFor(() => expect(api.checkHealth).toHaveBeenCalledTimes(1));
    expect(api.analyzeThesis).not.toHaveBeenCalled();
    expect(api.fetchTheses).not.toHaveBeenCalled();
    expect(api.fetchThesisDetail).not.toHaveBeenCalled();
    expect(api.fetchForecast).not.toHaveBeenCalled();
    expect(screen.getByTestId('empty-state')).toHaveTextContent('Escribí una tesis o elegí un ejemplo para empezar');
  });

  it('starts with an empty thesis box and a placeholder', () => {
    render(<App />);
    const box = screen.getByLabelText('Tesis de inversión') as HTMLInputElement;
    expect(box.value).toBe('');
    expect(box.placeholder).toContain('Escribí tu tesis');
  });

  it('shows the empty state in every tab, without charts', () => {
    render(<App />);
    for (const tab of ['Reality Check (Backtest)', 'Correlaciones & Heatmap', 'Gráfico Dual-Axis', 'Asignación y Riesgo']) {
      fireEvent.click(screen.getByText(tab));
      expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    }
    expect(document.querySelector('canvas')).toBeNull();
  });

  it('an example only fills the box; it does not analyze', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Superciclo de Capex en semiconductores avanzados y litografía' }));
    expect((screen.getByLabelText('Tesis de inversión') as HTMLInputElement).value).toBe(
      'Superciclo de Capex en semiconductores avanzados y litografía'
    );
    expect(api.analyzeThesis).not.toHaveBeenCalled();
  });

  it('there is nothing to export yet', () => {
    render(<App />);
    expect(screen.getByRole('button', { name: /Exportar Informe/ })).toBeDisabled();
  });
});
