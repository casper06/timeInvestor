import { describe, it, expect } from 'vitest';
import { generateMarkdownReport, type ReportData } from './exportReport';

const baseData: ReportData = {
  thesis: {
    thesis: 'Demanda eléctrica por centros de datos de IA',
    summary: 'Resumen de prueba',
    tickers: [
      { symbol: 'CEG', name: 'Constellation Energy', sector: 'Utilities', weight: 1.0, thesis_role: 'Primary' },
    ],
    macro_series: [],
    rationales: {},
    provider_used: 'mock-semantic-engine',
  },
  seriesData: {
    id: 'CEG',
    name: 'Constellation Energy',
    type: 'equity',
    unit: 'USD',
    points: [
      { timestamp: '2026-01-01', value: 200 },
      { timestamp: '2026-02-01', value: 220 },
    ],
    source: 'live',
  },
  forecast: {
    timestamps: ['2026-03-01'],
    values: [230],
    lower_bound: [200],
    upper_bound: [260],
    model_name: 'damped-holt-mle',
    engine_selection_reason: 'Acción individual, historia suficiente — Holt (default).',
  },
  fundamentals: [],
  interpretation: null,
  horizon: 60,
  confidence: 0.95,
};

function extractSectionNumbers(md: string): number[] {
  return [...md.matchAll(/^## (\d+)\./gm)].map((m) => parseInt(m[1], 10));
}

describe('generateMarkdownReport section numbering', () => {
  it('numbers sections sequentially with no gaps when optional sections are skipped', () => {
    // Regression test for the reported bug: numbering used to hardcode "## 4."
    // for Copiloto and "## 5." for Fundamentales, both conditional sections —
    // skipping Copiloto (interpretation === null, as here) previously left the
    // report jumping straight from "## 3." to "## 5." with no "## 4." at all.
    const md = generateMarkdownReport({ ...baseData, interpretation: null, fundamentals: [] });
    const numbers = extractSectionNumbers(md);

    expect(numbers).toEqual([1, 2, 3]);
    for (let i = 1; i < numbers.length; i++) {
      expect(numbers[i]).toBe(numbers[i - 1] + 1);
    }
  });

  it('still numbers sequentially with no gaps when all optional sections are present', () => {
    const md = generateMarkdownReport({
      ...baseData,
      interpretation: {
        what_data_says: 'x',
        thesis_alignment: 'y',
        next_series_suggestion: 'z',
        provider_used: 'mock-semantic-engine',
      },
      fundamentals: [{ ticker: 'CEG', metric: 'Capex (Billions USD)', period: '2025', value: 2.5 }],
      lastBacktest: {
        series_id: 'CEG',
        cutoff_date: '2026-01-01',
        horizon: 60,
        historical_dates: [],
        historical_values: [],
        future_actual_dates: [],
        future_actual_values: [],
        future_predicted_values: [],
        future_lower_bound: [],
        future_upper_bound: [],
        metrics: { mae: 1, mape: 2, smape: 3, mase: 0.9, directional_accuracy: 55, observations_evaluated: 30 },
        interval_coverage: 90,
        verdict: 'El modelo supera al benchmark naive.',
      },
      lastCorrelation: {
        series_ids: ['CEG', 'VST'],
        series_names: { CEG: 'Constellation', VST: 'Vistra' },
        pearson_matrix: [
          [1, 0.5],
          [0.5, 1],
        ],
        spearman_matrix: [
          [1, 0.5],
          [0.5, 1],
        ],
        common_observations: 100,
        start_date: '2025-01-01',
        end_date: '2026-01-01',
      },
      lastPortfolioOptimization: {
        tickers: ['CEG', 'VST'],
        shrinkage_intensity: 0.05,
        condition_number: 12.3,
        mu_method_used: 'historical_shrunk',
        cov_method_used: 'ledoit_wolf',
        portfolios: {
          max_sharpe: {
            name: 'Máx. Sharpe',
            weights: { CEG: 0.5, VST: 0.5 },
            expected_return: 0.2,
            volatility: 0.3,
            sharpe_ratio: 0.6,
            max_drawdown: -0.25,
            risk_contributions: { CEG: 0.5, VST: 0.5 },
            risk_contribution_pct: { CEG: 50, VST: 50 },
          },
        },
        warnings: [],
      },
    });

    const numbers = extractSectionNumbers(md);
    // thesis, allocation, telemetry, copiloto, fundamentales, backtest, correlation, portfolio
    expect(numbers.length).toBe(8);
    for (let i = 1; i < numbers.length; i++) {
      expect(numbers[i]).toBe(numbers[i - 1] + 1);
    }
  });

  it('only includes Reality Check / Correlations / Portfolio sections when the user actually ran them', () => {
    const md = generateMarkdownReport(baseData); // no lastBacktest/lastCorrelation/lastPortfolioOptimization
    expect(md).not.toContain('Reality Check');
    expect(md).not.toContain('Correlaciones Cruzadas');
    expect(md).not.toContain('Asignación Óptima de Cartera');
  });

  it('includes the engine_selection_reason in the telemetry section when present', () => {
    const md = generateMarkdownReport(baseData);
    expect(md).toContain('Acción individual, historia suficiente — Holt (default).');
  });
});

describe('generateMarkdownReport — unreliable forecast (2.6)', () => {
  it('carries the warning next to the projection', () => {
    const md = generateMarkdownReport({
      ...baseData,
      forecast: {
        timestamps: ['2026-01-01'],
        values: [20855.32],
        lower_bound: [2107.73],
        upper_bound: [84853.43],
        model_name: 'damped-holt-mle',
        reliable: false,
        reliability_warning: 'Pronóstico no confiable: a 12 meses proyecta 20,855.32.',
      },
    });
    expect(md).toContain('⚠ Pronóstico no confiable: a 12 meses proyecta 20,855.32.');
  });
});

describe('generateMarkdownReport — undefined MAPE (2.10)', () => {
  it('writes "no definido" with the reason, never a number', () => {
    const md = generateMarkdownReport({
      ...baseData,
      lastBacktest: {
        series_id: 'DFEDTARU', cutoff_date: '2025-08-01', horizon: 60, frequency: 'daily',
        historical_dates: [], historical_values: [], future_actual_dates: [], future_actual_values: [],
        future_predicted_values: [], future_lower_bound: [], future_upper_bound: [],
        metrics: { mae: 0.1, mape: null, directional_accuracy: 50, observations_evaluated: 60,
                   undefined: { mape: 'MAPE no definido: algún valor real del período evaluado es 0' } },
        verdict: 'v', warnings: [],
      },
    });
    expect(md).toContain('**MAPE:** no definido (MAPE no definido: algún valor real del período evaluado es 0)');
  });
});

describe('generateMarkdownReport — macro wording and forecast skill', () => {
  const macro: ReportData = {
    ...baseData,
    seriesData: {
      id: 'IPG2211A2N', name: 'Electric Power', type: 'macro', unit: 'Index 2017=100', frequency: 'monthly',
      points: [{ timestamp: '2026-07-01', value: 125.47 }], source: 'live',
    },
    forecast: {
      timestamps: ['2027-07-01'], values: [122.54], lower_bound: [117.4], upper_bound: [127.9],
      model_name: 'timesfm-2.5-200m (cpu)',
      skill: { state: 'aporta', reason: 'Le gana al naive estacional en 18 de 24 cutoffs', naive: 'naive_estacional' },
    },
    horizon: 12,
    confidence: 0.8,
  };

  it('a macro series has no "$" nor "Precio": last value and its unit', () => {
    const md = generateMarkdownReport(macro);
    const telemetry = md.split('## 3.')[1].split('## 4.')[0];
    expect(telemetry).toContain('**Último valor:** 125.47 Index 2017=100');
    expect(telemetry).toContain('**Valor proyectado (+12 meses):** 122.54 Index 2017=100');
    expect(telemetry).not.toMatch(/\$|Precio|precio/);
    expect(telemetry).toContain(
      '**Capacidad de pronóstico:** aporta sobre el naive — Le gana al naive estacional en 18 de 24 cutoffs'
    );
  });

  it('a stock keeps its price in dollars', () => {
    const md = generateMarkdownReport(baseData);
    expect(md).toContain('**Último precio real:** $220.00');
    expect(md).toContain('**Precio objetivo proyectado');
  });

  it('"no aporta": the range goes first and the point is secondary', () => {
    const md = generateMarkdownReport({
      ...macro,
      forecast: { ...macro.forecast!, skill: { state: 'no_aporta', reason: 'x', naive: 'random_walk' } },
    });
    const rangeAt = md.indexOf(
      '**Rango proyectado (+12 meses, 80% CI):** [117.40 Index 2017=100 — 127.90 Index 2017=100]'
    );
    const pointAt = md.indexOf(
      "**Punto central (secundario):** 122.54 Index 2017=100 (-2.3%). El pronóstico puntual no supera a 'igual que el último dato'."
    );
    expect(rangeAt).toBeGreaterThan(-1);
    expect(pointAt).toBeGreaterThan(rangeAt);
    expect(md).not.toContain('Valor proyectado');
  });
});

describe('generateMarkdownReport — Reality Check of another series', () => {
  it("names the backtest's series and writes its MAE in its own unit, not the on-screen series'", () => {
    const md = generateMarkdownReport({
      ...baseData,
      seriesData: {
        id: 'IPG2211A2N', name: 'Electric Power', type: 'macro', unit: 'Index 2017=100',
        points: [{ timestamp: '2026-07-01', value: 125.47 }], source: 'live',
      },
      lastBacktest: {
        series_id: 'NVDA', cutoff_date: '2026-06-03', horizon: 60, frequency: 'daily', unit: 'USD',
        historical_dates: [], historical_values: [], future_actual_dates: [], future_actual_values: [],
        future_predicted_values: [], future_lower_bound: [], future_upper_bound: [],
        metrics: { mae: 8.31, mape: 4.01, directional_accuracy: 55.9, observations_evaluated: 60 },
        verdict: 'v', warnings: [],
      },
    });
    expect(md).toContain('Reality Check (Backtest Histórico, NVDA)');
    expect(md).toContain('**MAE:** 8.31 USD');
    expect(md).not.toContain('8.31 Index');
  });
});

describe('generateMarkdownReport — fundamentals of every company', () => {
  it('lists all five companies (a fixed 15-row cut used to keep only CEG and ETN) and labels them', () => {
    const tickers = ['CEG', 'ETN', 'VST', 'GEV', 'PWR'];
    const fundamentals = tickers.flatMap((t, i) =>
      ['2025', '2024', '2023', '2022'].flatMap((y) => [
        { ticker: t, metric: 'Capex (Billions USD)', period: y, value: i + 1 },
        { ticker: t, metric: 'Revenue (Billions USD)', period: y, value: 10 * (i + 1) },
      ])
    );
    const md = generateMarkdownReport({
      ...baseData,
      thesis: {
        ...baseData.thesis!,
        tickers: [...tickers, 'NEE'].map((symbol) => ({ symbol, name: symbol, sector: 'x', weight: 1 / 6, thesis_role: 'x' })),
      },
      fundamentals,
    });
    const section = md.split('Fundamentales de las empresas seleccionadas')[1].split('\n---\n')[0];
    for (const t of tickers) expect(section).toContain(`| ${t} | $`);
    expect(section).toContain('| VST | $3.00B (ej. 2025) · $3.00B (2024) | $30.00B (ej. 2025) · $30.00B (2024) |');
    expect(section).toContain('no una muestra representativa');
    expect(section).toContain('Sin fundamentales: NEE.');
  });
});
