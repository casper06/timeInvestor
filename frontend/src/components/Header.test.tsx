import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Header } from './Header';
import type { HealthResponse } from '../services/api';

vi.mock('./LLMProviderSelector', () => ({ LLMProviderSelector: () => null }));

const baseProps = {
  loading: false,
  currentView: 'forecast' as const,
  onChangeView: vi.fn(),
  onOpenThesesDrawer: vi.fn(),
  onExportReport: vi.fn(),
};

const health = (version?: string): HealthResponse => ({
  status: 'ok',
  llm_provider: 'gemini',
  engine_mode: 'per_series_auto_selection',
  forecast_engine: 'x',
  has_gemini_key: true,
  has_fred_key: true,
  has_openai_key: false,
  version,
});

describe('Header version badge', () => {
  it('shows the version the backend reports, not one typed into the UI', () => {
    render(<Header {...baseProps} health={health('7.8.9')} />);
    expect(screen.getByText('v7.8.9')).toBeInTheDocument();
    expect(screen.queryByText(/v2\.0/)).not.toBeInTheDocument();
  });

  it('shows no badge while the version is unknown', () => {
    render(<Header {...baseProps} health={health(undefined)} />);
    expect(screen.queryByText(/^v\d/)).not.toBeInTheDocument();
  });
});
