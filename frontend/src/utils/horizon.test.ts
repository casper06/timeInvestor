import { describe, it, expect } from 'vitest';
import {
  annualizedGrowth,
  CANONICAL_HORIZON,
  horizonButton,
  horizonLabel,
  horizonTag,
  projectionYears,
  seriesFrequency,
} from './horizon';

describe('horizon labels (4.14)', () => {
  it('uses the unit of the series', () => {
    expect(horizonLabel(60, 'daily')).toBe('60 días hábiles');
    expect(horizonLabel(12, 'monthly')).toBe('12 meses');
    expect(horizonLabel(1, 'monthly')).toBe('1 mes');
    expect(horizonLabel(13, 'weekly')).toBe('13 semanas');
    expect(horizonLabel(4, 'quarterly')).toBe('4 trimestres');
  });

  it('says "pasos" when the unit was not recorded (snapshots before 4.14)', () => {
    expect(horizonLabel(60, null)).toBe('60 pasos');
    expect(horizonTag(60, undefined)).toBe('60 pasos');
  });

  it('keeps the compact "+60d" tag for daily series and spells out the rest', () => {
    expect(horizonTag(60, 'daily')).toBe('60d');
    expect(horizonTag(12, 'monthly')).toBe('12 meses');
    expect(horizonButton(12, 'monthly')).toBe('12m');
    expect(horizonButton(60, 'daily')).toBe('60d');
  });

  it('falls back to daily for unknown frequencies, and the canonical horizons match the backend', () => {
    expect(seriesFrequency(undefined)).toBe('daily');
    expect(seriesFrequency('irregular')).toBe('daily');
    // backend/services/horizons.py CANONICAL_HORIZON
    expect(CANONICAL_HORIZON).toEqual({ daily: 60, weekly: 13, monthly: 12, quarterly: 4, annual: 2 });
  });
});

describe('annualized growth over the real span of the projection', () => {
  it('monthly: 12 months are one year, so the CAGR equals the change', () => {
    const ts = Array.from({ length: 12 }, (_, i) => `2026-${String(i + 1).padStart(2, '0')}-01`);
    const years = projectionYears('2025-12-01', ts, 12, 'monthly');
    expect(years).toBeCloseTo(1, 2);
    expect(annualizedGrowth(100, 110, years)).toBeCloseTo(10, 0);
  });

  it('daily: 60 business days span ~84 calendar days, not 60', () => {
    // 60 business days after Friday 2026-05-29 end on Friday 2026-08-21.
    const years = projectionYears('2026-05-29', ['2026-06-01', '2026-08-21'], 60, 'daily');
    expect(years * 365.25).toBeCloseTo(84, 5);
    // 5% in 84 days annualizes to ~23.6%, not the ~34.6% of 60/365.25 years.
    expect(annualizedGrowth(100, 105, years)).toBeCloseTo(23.6, 1);
  });

  it('without dates, uses steps / periods per year', () => {
    expect(projectionYears(undefined, undefined, 12, 'monthly')).toBe(1);
    expect(projectionYears(undefined, [], 252, 'daily')).toBe(1);
  });
});
