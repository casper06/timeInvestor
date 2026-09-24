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
