import { describe, it, expect, vi, afterEach } from 'vitest';
import { runBacktest } from './api';

afterEach(() => vi.restoreAllMocks());

function mockFetch() {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }));
}

function sentBody(spy: ReturnType<typeof mockFetch>) {
  const init = spy.mock.calls[0][1] as RequestInit;
  return JSON.parse(init.body as string);
}

describe('runBacktest series_type (2.7)', () => {
  it("sends series_type='macro' so a FRED series outside the server's catalog goes to FRED", async () => {
    const spy = mockFetch();
    await runBacktest('UNRATE', '2024-06-01', 12, 0.95, undefined, 'macro');
    expect(sentBody(spy)).toEqual({ series_id: 'UNRATE', cutoff_date: '2024-06-01', horizon: 12, confidence: 0.95, series_type: 'macro' });
  });

  it('sends equity too, and nothing for an unknown or missing type', async () => {
    let spy = mockFetch();
    await runBacktest('NVDA', '2026-06-02', 60, 0.95, undefined, 'equity');
    expect(sentBody(spy).series_type).toBe('equity');
    vi.restoreAllMocks();
    spy = mockFetch();
    await runBacktest('NVDA', '2026-06-02', 60, 0.95);
    expect(sentBody(spy)).not.toHaveProperty('series_type');
    vi.restoreAllMocks();
    spy = mockFetch();
    await runBacktest('X', '2026-06-02', 60, 0.95, undefined, 'fundamental');
    expect(sentBody(spy)).not.toHaveProperty('series_type');
  });
});
