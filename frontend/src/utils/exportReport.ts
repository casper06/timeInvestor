import type {
  ThesisResponse,
  TimeSeriesData,
  ForecastResponse,
  FundamentalsMetric,
  InterpretationResponse,
  BacktestResponse,
  CorrelationMatrixResponse,
  PortfolioOptimizeResponse,
} from '../services/api';
import { horizonLabel, seriesFrequency } from './horizon';
import { formatValue, isPriceSeries } from './valueFormat';

const SKILL_TEXT = {
  aporta: 'aporta sobre el naive',
  no_aporta: 'no aporta más que el naive',
  no_evaluado: 'no evaluado',
} as const;

export interface ReportData {
  thesis: ThesisResponse | null;
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  fundamentals: FundamentalsMetric[];
  interpretation: InterpretationResponse | null;
  horizon: number;
  confidence: number;
  /** Last Reality Check result the user actually ran, if any — undefined
   * (not just absent data) means "never ran it", vs. a genuinely empty result. */
  lastBacktest?: BacktestResponse | null;
  lastCorrelation?: CorrelationMatrixResponse | null;
  lastPortfolioOptimization?: PortfolioOptimizeResponse | null;
}

/** Pure markdown generation, split out from exportMarkdownReport's DOM/download
 * side effect so the section numbering and content logic can be unit tested
 * without a browser environment. */
export function generateMarkdownReport(data: ReportData): string {
  const dateStr = new Date().toISOString().slice(0, 10);
  const title = data.thesis?.thesis || 'Tesis de Inversión Cuantitativa';

  const lastPrice = data.seriesData?.points[data.seriesData.points.length - 1]?.value || 0;
  const target = data.forecast?.values[data.forecast.values.length - 1] || 0;
  const deltaPct = lastPrice > 0 ? ((target - lastPrice) / lastPrice) * 100 : 0;
  const lb = data.forecast?.lower_bound[data.forecast.lower_bound.length - 1] || 0;
  const ub = data.forecast?.upper_bound[data.forecast.upper_bound.length - 1] || 0;

  let md = `# INFORME EJECUTIVO: ${title.toUpperCase()}\n`;
  md += `*Fecha de emisión: ${dateStr} • Generado por TimeInvestor Local Core*\n\n`;
  md += `---\n\n`;

  // Section numbers are assigned sequentially as each section is actually
  // written, instead of hardcoded literals — a previous version hardcoded
  // "## 4." and "## 5." for the two CONDITIONAL sections (Copiloto,
  // Fundamentales), so whenever either was skipped (e.g. the user never ran
  // the Copiloto), the numbering visibly jumped from "## 3." straight to
  // "## 5." with no "## 4." ever printed.
  let sectionNum = 1;
  const addSection = (heading: string, body: string) => {
    md += `## ${sectionNum}. ${heading}\n${body}`;
    sectionNum += 1;
  };

  addSection(
    'Resumen de la Tesis Cuantitativa',
    `**Hipótesis:** "${data.thesis?.thesis || ''}"\n\n**Síntesis:**\n${data.thesis?.summary || 'N/A'}\n\n`
  );

  let allocationBody = `| Ticker | Empresa | Sector | Ponderación | Rol en la Tesis |\n| :--- | :--- | :--- | :--- | :--- |\n`;
  (data.thesis?.tickers || []).forEach((t) => {
    allocationBody += `| **${t.symbol}** | ${t.name} | ${t.sector} | ${Math.round(t.weight * 100)}% | ${t.thesis_role} |\n`;
  });
  addSection('Asignación de Activos y Ponderaciones', allocationBody + '\n');

  // "$" and "Precio" only for equities; a macro series is a value in its unit.
  const sd = data.seriesData;
  const price = isPriceSeries(sd);
  const fmt = (v: number) => formatValue(v, sd);
  const hLabel = horizonLabel(data.horizon, seriesFrequency(sd?.frequency));
  const pct = `${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%`;
  const band = `[${fmt(lb)} — ${fmt(ub)}]`;
  const skill = data.forecast?.skill;
  const naiveWords =
    skill?.naive === 'naive_estacional' ? 'igual que el mismo período del ciclo anterior' : 'igual que el último dato';
  // When the point forecast doesn't beat the naive, the range goes first (4.13).
  const projection =
    skill?.state === 'no_aporta'
      ? `- **Rango proyectado (+${hLabel}, ${Math.round(data.confidence * 100)}% CI):** ${band}\n` +
        `- **Punto central (secundario):** ${fmt(target)} (${pct}). El pronóstico puntual no supera a '${naiveWords}'.\n`
      : `- **${price ? 'Precio objetivo proyectado' : 'Valor proyectado'} (+${hLabel}):** ${fmt(target)} (${pct})\n` +
        `- **Banda de Confianza (${Math.round(data.confidence * 100)}% CI):** ${band}\n`;

  addSection(
    `Telemetría y Proyección Temporal (${sd?.id || 'Activo Central'})`,
    `- **${price ? 'Último precio real' : 'Último valor'}:** ${fmt(lastPrice)}\n` +
      projection +
      (skill ? `- **Capacidad de pronóstico:** ${SKILL_TEXT[skill.state]} — ${skill.reason}\n` : '') +
      (data.forecast?.reliable === false
        ? `- **⚠ ${data.forecast.reliability_warning || 'Pronóstico no confiable.'}**\n`
        : '') +
      `- **Motor Predictivo:** ${data.forecast?.model_name || 'TimesFM'}` +
      (data.forecast?.engine_selection_reason ? ` — ${data.forecast.engine_selection_reason}` : '') +
      `\n\n`
  );

  if (data.interpretation) {
    addSection(
      'Diagnóstico del Copiloto Cuantitativo',
      `### a) Qué dicen los datos\n${data.interpretation.what_data_says}\n\n` +
        `### b) Alineación con la tesis\n${data.interpretation.thesis_alignment}\n\n` +
        `### c) Qué serie mirar a continuación\n${data.interpretation.next_series_suggestion}\n\n`
    );
  }

  const thesisTickers = (data.thesis?.tickers || []).map((t) => t.symbol);
  if (data.fundamentals.length > 0) {
    // One row per company with its last closed fiscal year (and the one
    // before), for EVERY company: a fixed cut of 15 rows used to leave out all
    // but the first two (8 rows each), e.g. only CEG and ETN of five.
    const byTicker: Record<string, typeof data.fundamentals> = {};
    data.fundamentals.forEach((f) => {
      (byTicker[f.ticker] ||= []).push(f);
    });
    const cell = (rows: typeof data.fundamentals, key: string) => {
      const r = rows.filter((f) => f.metric.toLowerCase().includes(key)).sort((a, b) => b.period.localeCompare(a.period));
      if (r.length === 0) return 'sin datos';
      return `$${r[0].value.toFixed(2)}B (ej. ${r[0].period})` + (r[1] ? ` · $${r[1].value.toFixed(2)}B (${r[1].period})` : '');
    };
    const tickers = [...new Set([...thesisTickers, ...Object.keys(byTicker)])];
    let fundBody =
      `*Empresas que eligió el LLM al traducir la tesis (y las que se agregaron a mano), no una muestra representativa: sus números no confirman la tesis.*\n\n` +
      `| Ticker | Capex (último ejercicio cerrado) | Ingresos (último ejercicio cerrado) |\n| :--- | :--- | :--- |\n`;
    tickers.forEach((t) => {
      const rows = byTicker[t] || [];
      fundBody += `| ${t} | ${cell(rows, 'capex')} | ${cell(rows, 'revenue')} |\n`;
    });
    const missing = tickers.filter((t) => !byTicker[t]);
    if (missing.length > 0) fundBody += `\nSin fundamentales: ${missing.join(', ')}.\n`;
    addSection('Fundamentales de las empresas seleccionadas (Capex e Ingresos)', fundBody + '\n');
  }

  // The three sections below only appear if the user actually ran that
  // analysis in this session — the report mirrors what was actually reviewed
  // on screen (one-line verdict per section, not the full detail already
  // seen there), rather than being silent about analyses the user DID run.
  if (data.lastBacktest) {
    const bt = data.lastBacktest;
    // The last Reality Check may be of another series than the one on screen:
    // named in the title, and its MAE in ITS unit, never the on-screen one's.
    addSection(
      `Reality Check (Backtest Histórico, ${bt.series_id})`,
      `**Veredicto:** ${bt.verdict}\n\n` +
        `- **Fecha de corte evaluada:** ${bt.cutoff_date} (horizonte: ${horizonLabel(bt.horizon, seriesFrequency(bt.frequency))})\n` +
        `- **Acierto direccional:** ${bt.metrics.directional_accuracy.toFixed(1)}%\n` +
        `- **MAPE:** ${
          bt.metrics.mape != null
            ? `${bt.metrics.mape.toFixed(2)}%`
            : `no definido (${bt.metrics.undefined?.mape || 'sin motivo informado'})`
        } • **MAE:** ${bt.metrics.mae.toFixed(2)}${bt.unit ? ` ${bt.unit}` : ''}\n` +
        (bt.interval_coverage !== undefined
          ? `- **Cobertura del intervalo:** ${bt.interval_coverage.toFixed(1)}%` +
            (bt.interval_level != null ? ` (nivel nominal ${Math.round(bt.interval_level * 100)}%)` : '') +
            `\n`
          : '') +
        `\n`
    );
  }

  if (data.lastCorrelation) {
    const corr = data.lastCorrelation;
    const n = corr.series_ids.length;
    let strongPairs = 0;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (Math.abs(corr.pearson_matrix[i]?.[j] ?? 0) >= 0.7) strongPairs += 1;
      }
    }
    const totalPairs = (n * (n - 1)) / 2;
    addSection(
      'Correlaciones Cruzadas',
      `**Veredicto:** ${strongPairs} de ${totalPairs} pares de activos muestran correlación fuerte (|r| ≥ 0.7) ` +
        `sobre ${corr.common_observations} observaciones comunes (${corr.start_date} a ${corr.end_date}).` +
        (strongPairs > totalPairs / 2
          ? ' La cartera está mayormente concentrada — poca diversificación real entre sus componentes.'
          : ' La cartera muestra diversificación razonable entre sus componentes.') +
        `\n\n`
    );
  }

  if (data.lastPortfolioOptimization) {
    const opt = data.lastPortfolioOptimization;
    const sharpe = opt.portfolios.max_sharpe;
    addSection(
      'Asignación Óptima de Cartera',
      `**Veredicto:** la estrategia de Máximo Sharpe proyecta un retorno anualizado de ` +
        `${(sharpe.expected_return * 100).toFixed(1)}% con volatilidad de ${(sharpe.volatility * 100).toFixed(1)}% ` +
        `(Sharpe: ${sharpe.sharpe_ratio.toFixed(2)}, Max Drawdown: ${(sharpe.max_drawdown * 100).toFixed(1)}%).\n\n` +
        `- **Shrinkage (δ*):** ${opt.shrinkage_intensity} • **Número de Condición:** ${opt.condition_number}\n\n`
    );
  }

  md += `---\n`;
  md += `*Documento emitido para fines de análisis cuantitativo e investigación interna.*`;

  return md;
}

export function exportMarkdownReport(data: ReportData) {
  const dateStr = new Date().toISOString().slice(0, 10);
  const md = generateMarkdownReport(data);

  // Trigger download
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', `TimeInvestor_Report_${dateStr}.md`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
