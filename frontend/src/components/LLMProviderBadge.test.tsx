import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LLMProviderBadge, formatLLMProvider } from './LLMProviderBadge';

describe('LLMProviderBadge', () => {
  it('reflects an arbitrary provider_used string instead of a fixed name table', () => {
    // "gemini-99-nightly" is not — and will never be — a real model. If the badge
    // used a hardcoded per-model lookup table, this would fall through to some
    // stale default. It must instead derive the label directly from the string
    // the backend actually reported.
    const arbitraryProvider = 'gemini-99-nightly';
    render(<LLMProviderBadge providerUsed={arbitraryProvider} />);

    // The rendered label must contain the real version/model tokens verbatim.
    expect(screen.getByText(/99/)).toBeInTheDocument();
    expect(screen.getByText(/Nightly/i)).toBeInTheDocument();
  });

  it('formats a real provider_used string generically, without special-casing it', () => {
    const { label, isMock } = formatLLMProvider('gemini-3.6-flash');
    expect(isMock).toBe(false);
    expect(label).toContain('3.6');
    expect(label.toLowerCase()).toContain('gemini');
    expect(label.toLowerCase()).toContain('flash');
  });

  it('still recognizes mock-semantic-engine as the no-LLM case', () => {
    const { isMock, label } = formatLLMProvider('mock-semantic-engine');
    expect(isMock).toBe(true);
    expect(label).toMatch(/sin LLM/i);
  });

  it('handles an unset provider gracefully', () => {
    const { isMock, label } = formatLLMProvider(undefined);
    expect(isMock).toBe(true);
    expect(label).toBeTruthy();
  });
});
