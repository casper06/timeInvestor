import type { TimeSeriesData } from '../services/api';

/**
 * Price wording ("$", "Precio", "cierre") only for equities. A macro series
 * (FRED) is a value in its own unit — an index, a percentage, thousands of
 * people — never a price in dollars.
 */
export const isPriceSeries = (series?: Pick<TimeSeriesData, 'type'> | null): boolean => series?.type === 'equity';

/** "Último precio" for an equity, "Último valor" for anything else. */
export const lastValueLabel = (series?: Pick<TimeSeriesData, 'type'> | null): string =>
  isPriceSeries(series) ? 'Último precio' : 'Último valor';

/** `$123.45` for an equity; `123.45 Index 2017=100` (the series' unit) otherwise. */
export function formatValue(
  value: number,
  series?: Pick<TimeSeriesData, 'type' | 'unit'> | null,
  digits = 2
): string {
  if (isPriceSeries(series)) return `$${value.toFixed(digits)}`;
  const unit = series?.unit?.trim();
  return unit ? `${value.toFixed(digits)} ${unit}` : value.toFixed(digits);
}
