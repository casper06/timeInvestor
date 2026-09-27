/**
 * Forecast horizons in the series' own unit (item 4.14 of docs/PLAN.md).
 *
 * A horizon is a number of STEPS of the series: 12 on a monthly series is 12
 * months, 60 on a daily one is 60 business days. The frequency comes from the
 * backend (TimeSeriesData.frequency, inferred from the dates).
 *
 * Mirrors backend/services/horizons.py (options, canonical horizon, labels):
 * keep both in sync.
 */

export type Frequency = 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual';

export const HORIZON_OPTIONS: Record<Frequency, number[]> = {
  daily: [30, 60, 90, 180],
  weekly: [4, 13, 26],
  monthly: [3, 6, 12, 24],
  quarterly: [2, 4, 8],
  annual: [1, 2, 3],
};

/** The UI default per frequency. */
export const CANONICAL_HORIZON: Record<Frequency, number> = {
  daily: 60,
  weekly: 13,
  monthly: 12,
  quarterly: 4,
  annual: 2,
};

const UNITS: Record<Frequency, [string, string]> = {
  daily: ['día hábil', 'días hábiles'],
  weekly: ['semana', 'semanas'],
  monthly: ['mes', 'meses'],
  quarterly: ['trimestre', 'trimestres'],
  annual: ['año', 'años'],
};

const BUTTON_SUFFIX: Record<Frequency, string> = {
  daily: 'd',
  weekly: 's',
  monthly: 'm',
  quarterly: 'T',
  annual: 'a',
};

// Used only when the dates of the projection are missing.
const PERIODS_PER_YEAR: Record<Frequency, number> = {
  daily: 252,
  weekly: 52,
  monthly: 12,
  quarterly: 4,
  annual: 1,
};

/** A known frequency, or 'daily' (what the app assumed before 4.14). */
export function seriesFrequency(f?: string | null): Frequency {
  return f && f in UNITS ? (f as Frequency) : 'daily';
}

/** '60 días hábiles', '12 meses'. No known unit -> 'N pasos' (e.g. snapshots
 * saved before 4.14, whose unit wasn't recorded). */
export function horizonLabel(n: number, f?: string | null): string {
  if (!f || !(f in UNITS)) return `${n} ${n === 1 ? 'paso' : 'pasos'}`;
  const [singular, plural] = UNITS[f as Frequency];
  return `${n} ${n === 1 ? singular : plural}`;
}

/** Compact tag after a '+': '60d' for daily series (as before 4.14), the full
 * unit otherwise ('12 meses'). */
export function horizonTag(n: number, f?: string | null): string {
  return f === 'daily' ? `${n}d` : horizonLabel(n, f);
}

/** Selector button text: '60d', '12m', '13s', '4T', '2a'. */
export function horizonButton(n: number, f: Frequency): string {
  return `${n}${BUTTON_SUFFIX[f]}`;
}

/** Years between the last observation and the end of the projection, from
 * the actual dates (60 business days are ~84 calendar days, not 60). Falls
 * back to the steps / periods per year when dates are missing. */
export function projectionYears(
  lastTimestamp: string | undefined,
  forecastTimestamps: string[] | undefined,
  horizon: number,
  f: Frequency
): number {
  const end = forecastTimestamps?.[forecastTimestamps.length - 1];
  if (lastTimestamp && end) {
    const ms = Date.parse(end.slice(0, 10)) - Date.parse(lastTimestamp.slice(0, 10));
    if (Number.isFinite(ms) && ms > 0) return ms / (365.25 * 24 * 3600 * 1000);
  }
  return horizon / PERIODS_PER_YEAR[f];
}

/** Annualized growth (%) from `last` to `target` over `years`. */
export function annualizedGrowth(last: number, target: number, years: number): number {
  return years > 0 && last > 0 && target > 0 ? (Math.pow(target / last, 1 / years) - 1) * 100 : 0;
}
