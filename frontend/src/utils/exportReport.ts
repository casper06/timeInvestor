import type {
  ThesisResponse,
  TimeSeriesData,
  ForecastResponse,
  FundamentalsMetric,
  InterpretationResponse,
} from '../services/api';

export interface ReportData {
  thesis: ThesisResponse | null;
  seriesData: TimeSeriesData | null;
  forecast: ForecastResponse | null;
  fundamentals: FundamentalsMetric[];
  interpretation: InterpretationResponse | null;
  horizon: number;
  confidence: number;
}

export function exportMarkdownReport(data: ReportData) {
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

  md += `## 1. Resumen de la Tesis Cuantitativa\n`;
  md += `**Hipótesis:** "${data.thesis?.thesis || ''}"\n\n`;
  md += `**Síntesis:**\n${data.thesis?.summary || 'N/A'}\n\n`;

  md += `## 2. Asignación de Activos y Ponderaciones\n`;
  md += `| Ticker | Empresa | Sector | Ponderación | Rol en la Tesis |\n`;
  md += `| :--- | :--- | :--- | :--- | :--- |\n`;
  (data.thesis?.tickers || []).forEach((t) => {
    md += `| **${t.symbol}** | ${t.name} | ${t.sector} | ${Math.round(t.weight * 100)}% | ${t.thesis_role} |\n`;
  });
  md += `\n`;

  md += `## 3. Telemetría y Proyección Temporal (${data.seriesData?.id || 'Activo Central'})\n`;
  md += `- **Último Precio Real:** $${lastPrice.toFixed(2)} ${data.seriesData?.unit || 'USD'}\n`;
  md += `- **Precio Objetivo Proyectado (+${data.horizon} días):** $${target.toFixed(2)} (${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%)\n`;
  md += `- **Banda de Confianza (${Math.round(data.confidence * 100)}% CI):** [$${lb.toFixed(2)} — $${ub.toFixed(2)}]\n`;
  md += `- **Modelo Predictivo:** ${data.forecast?.model_name || 'TimesFM'}\n\n`;

  if (data.interpretation) {
    md += `## 4. Diagnóstico del Copiloto Cuantitativo\n`;
    md += `### a) Qué dicen los datos\n${data.interpretation.what_data_says}\n\n`;
    md += `### b) Alineación con la tesis\n${data.interpretation.thesis_alignment}\n\n`;
    md += `### c) Qué serie mirar a continuación\n${data.interpretation.next_series_suggestion}\n\n`;
  }

  if (data.fundamentals.length > 0) {
    md += `## 5. Fundamentales Clave (Capex e Ingresos)\n`;
    md += `| Ticker | Métrica | Periodo | Valor ($B USD) |\n`;
    md += `| :--- | :--- | :--- | :--- |\n`;
    data.fundamentals.slice(0, 15).forEach((f) => {
      md += `| ${f.ticker} | ${f.metric} | ${f.period} | $${f.value.toFixed(2)}B |\n`;
    });
    md += `\n`;
  }

  md += `---\n`;
  md += `*Documento emitido para fines de análisis cuantitativo e investigación interna.*`;

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
