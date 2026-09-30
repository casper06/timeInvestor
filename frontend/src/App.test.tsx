import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Charts don't draw in jsdom (no canvas); what matters here is the state.
vi.mock('react-chartjs-2', () => ({ Line: () => null, Bar: () => null, Doughnut: () => null }));

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
    // 4.4: fundamentals now carry the backend's warnings alongside the metrics.
    fetchFundamentals: vi.fn().mockResolvedValue({ metrics: [], warnings: [] }),
    fetchFredMetadata: vi.fn(),
    fetchLLMProviders: vi.fn().mockResolvedValue({ active: 'mock', providers: [] }),
  };
});

import * as api from './services/api';
import type { ForecastResponse, TimeSeriesData } from './services/api';
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
    fireEvent.click(screen.getByRole('button', { name: 'Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.' }));
    expect((screen.getByLabelText('Tesis de inversión') as HTMLInputElement).value).toBe(
      'Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.'
    );
    expect(api.analyzeThesis).not.toHaveBeenCalled();
  });

  it('there is nothing to export yet', () => {
    render(<App />);
    expect(screen.getByRole('button', { name: /Exportar Informe/ })).toBeDisabled();
  });
});

// ---- 4.16: FRED IDs added by hand, and overlapping loads ----

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const series = (id: string, name: string, type = 'equity'): TimeSeriesData => ({
  id,
  name,
  type,
  unit: 'USD',
  points: [1, 2, 3, 4].map((v, i) => ({ timestamp: `2026-01-0${i + 1}`, value: 100 + v })),
  source: 'live',
  from_cache: false,
  frequency: 'daily',
});

const forecastFor = (model: string): ForecastResponse => ({
  timestamps: ['2026-01-05'],
  values: [110],
  lower_bound: [100],
  upper_bound: [120],
  model_name: model,
  horizon: 1,
});

const addFred = (id: string) => {
  const input = screen.getByPlaceholderText('+ FRED ID');
  fireEvent.change(input, { target: { value: id } });
  fireEvent.submit(input.closest('form')!);
};

const addTicker = (symbol: string) => {
  const input = screen.getByPlaceholderText('+ Ticker (ej. AMD)');
  fireEvent.change(input, { target: { value: symbol } });
  fireEvent.submit(input.closest('form')!);
};

describe('FRED ID added by hand (4.16)', () => {
  it('is loaded as a macro series, never through yfinance', async () => {
    vi.mocked(api.fetchFredMetadata).mockResolvedValue({ series_id: 'IPG2211A2N', title: 'Industrial Production', notes: '' });
    vi.mocked(api.fetchMacroData).mockResolvedValue(series('IPG2211A2N', 'FRED Series IPG2211A2N', 'macro'));
    vi.mocked(api.fetchForecast).mockResolvedValue(forecastFor('holt-winters'));
    render(<App />);
    addFred('ipg2211a2n');
    await waitFor(() => expect(api.fetchMacroData).toHaveBeenCalledWith('IPG2211A2N'));
    expect(api.fetchFredMetadata).toHaveBeenCalledWith('IPG2211A2N');
    expect(api.fetchMarketData).not.toHaveBeenCalled();
    expect(await screen.findByText('FRED Series IPG2211A2N')).toBeInTheDocument();
    expect(screen.queryByText(/No se pudo cargar/)).toBeNull();
  });

  it('an ID that does not exist on FRED says so and is not added', async () => {
    const msg = "La serie 'NOEXISTE1' no existe en FRED (la API de FRED respondió \"The series does not exist\").";
    vi.mocked(api.fetchFredMetadata).mockRejectedValue(new api.ApiError(msg, 404, 'fred_series_not_found'));
    render(<App />);
    addFred('noexiste1');
    expect(await screen.findByTestId('macro-add-error')).toHaveTextContent("La serie 'NOEXISTE1' no existe en FRED");
    expect(api.fetchMacroData).not.toHaveBeenCalled();
    expect(api.fetchMarketData).not.toHaveBeenCalled();
    expect(screen.getByText('Indicadores FRED Macro (0)')).toBeInTheDocument();
  });

  it('when FRED cannot be asked (no key), it is still added and loaded as macro', async () => {
    vi.mocked(api.fetchFredMetadata).mockRejectedValue(new api.ApiError('clave FRED_API_KEY no configurada', 404));
    vi.mocked(api.fetchMacroData).mockResolvedValue(series('IPG2211A2N', 'FRED Series IPG2211A2N', 'macro'));
    vi.mocked(api.fetchForecast).mockResolvedValue(forecastFor('holt'));
    render(<App />);
    addFred('IPG2211A2N');
    await waitFor(() => expect(api.fetchMacroData).toHaveBeenCalledWith('IPG2211A2N'));
    expect(api.fetchMarketData).not.toHaveBeenCalled();
    expect(screen.queryByTestId('macro-add-error')).toBeNull();
  });
});

describe('Overlapping loads (4.16)', () => {
  it('a response from an older load arriving last is dropped: only the latest is shown', async () => {
    const slowA = deferred<TimeSeriesData>();
    vi.mocked(api.fetchMarketData).mockImplementation((id: string) =>
      id === 'AAA' ? slowA.promise : Promise.resolve(series('BBB', 'BBB Corp'))
    );
    vi.mocked(api.fetchForecast).mockImplementation((_p, _h, _c, id) => Promise.resolve(forecastFor(`model-${id}`)));
    render(<App />);
    addTicker('AAA');
    addTicker('BBB');
    expect(await screen.findByText('BBB Corp')).toBeInTheDocument();
    await waitFor(() => expect(api.fetchForecast).toHaveBeenCalledTimes(1));

    slowA.resolve(series('AAA', 'AAA Corp'));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText('AAA Corp')).toBeNull();
    expect(screen.getByText('BBB Corp')).toBeInTheDocument();
    // AAA's data never reached the forecast step either.
    expect(api.fetchForecast).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.fetchForecast).mock.calls[0][3]).toBe('BBB');
  });

  it("an older load's error arriving last does not replace the latest series", async () => {
    const slowA = deferred<TimeSeriesData>();
    vi.mocked(api.fetchMarketData).mockImplementation((id: string) =>
      id === 'AAA' ? slowA.promise : Promise.resolve(series('BBB', 'BBB Corp'))
    );
    vi.mocked(api.fetchForecast).mockResolvedValue(forecastFor('holt'));
    render(<App />);
    addTicker('AAA');
    addTicker('BBB');
    expect(await screen.findByText('BBB Corp')).toBeInTheDocument();

    slowA.reject(new Error('No se pudieron obtener datos de mercado para AAA'));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/No se pudieron obtener datos de mercado para AAA/)).toBeNull();
    expect(screen.getByText('BBB Corp')).toBeInTheDocument();
  });

  it("an older load's forecast arriving last does not replace the latest one", async () => {
    const slowFcA = deferred<ForecastResponse>();
    vi.mocked(api.fetchMarketData).mockImplementation((id: string) =>
      Promise.resolve(series(id, `${id} Corp`))
    );
    vi.mocked(api.fetchForecast).mockImplementation((_p, _h, _c, id) =>
      id === 'AAA' ? slowFcA.promise : Promise.resolve(forecastFor('model-BBB'))
    );
    render(<App />);
    addTicker('AAA');
    await waitFor(() => expect(api.fetchForecast).toHaveBeenCalledTimes(1));
    addTicker('BBB');
    expect(await screen.findByText('BBB Corp')).toBeInTheDocument();
    await waitFor(() => expect(api.fetchForecast).toHaveBeenCalledTimes(2));

    slowFcA.resolve(forecastFor('model-AAA'));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/model-AAA/)).toBeNull();
    expect(screen.getAllByText(/model-BBB/).length).toBeGreaterThan(0);
  });

  it('a horizon change while another series is loading re-runs that load, not a forecast of the previous series', async () => {
    const slowB = deferred<TimeSeriesData>();
    vi.mocked(api.fetchMarketData).mockImplementation((id: string) =>
      id === 'BBB' ? slowB.promise : Promise.resolve(series('AAA', 'AAA Corp'))
    );
    vi.mocked(api.fetchForecast).mockImplementation((_p, h, _c, id) => Promise.resolve(forecastFor(`model-${id}-${h}`)));
    render(<App />);
    addTicker('AAA');
    await waitFor(() => expect(api.fetchForecast).toHaveBeenCalledTimes(1));
    addTicker('BBB');
    fireEvent.click(screen.getByRole('button', { name: '90d' }));   // AAA's controls are still on screen
    slowB.resolve(series('BBB', 'BBB Corp'));
    expect(await screen.findByText('BBB Corp')).toBeInTheDocument();
    await waitFor(() => expect(api.fetchForecast).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(api.fetchForecast).mock.calls.map((c) => `${c[3]}@${c[1]}`);
    expect(calls).toEqual(['AAA@60', 'BBB@90']);
  });
});

describe('Example theses (4.10)', () => {
  it('are not all about technology', () => {
    render(<App />);
    const examples = [
      'Demanda eléctrica por centros de datos de IA',
      'Las tasas hipotecarias altas frenan la construcción de viviendas en EE.UU.',
      'La desaceleración del consumo golpea al comercio minorista',
      'La sequía encarece los granos y favorece a los productores agrícolas',
    ];
    for (const e of examples) expect(screen.getByRole('button', { name: e })).toBeInTheDocument();
    const tech = examples.filter((e) => /\b(IA|tecnol|semiconductor|chip)/i.test(e));
    expect(tech.length).toBeLessThanOrEqual(1);
  });
});
