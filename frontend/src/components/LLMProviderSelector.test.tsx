import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { LLMProviderSelector } from './LLMProviderSelector';
import * as api from '../services/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const providers: api.LLMProvidersResponse = {
  active: 'mock',
  env_default: 'mock',
  persisted: false,
  notice: 'Válido hasta el próximo reinicio del server.',
  providers: [
    { id: 'gemini', label: 'Gemini API', available: false, reason: 'Sin GEMINI_API_KEY configurada' },
    { id: 'claude_cli', label: 'Claude CLI', available: true, note: 'Comparte cupo con tu uso de Claude Code' },
    { id: 'mock', label: 'Mock local', available: true, note: 'Motor semántico local, sin red ni cuota' },
  ],
};

describe('LLMProviderSelector', () => {
  it('shows unavailable providers disabled with their reason, and never switches to them', async () => {
    vi.spyOn(api, 'fetchLLMProviders').mockResolvedValue(providers);
    const switchSpy = vi.spyOn(api, 'switchLLMProvider');

    render(<LLMProviderSelector />);
    fireEvent.click(await screen.findByRole('button', { name: /LLM: Mock local/ }));

    const gemini = await screen.findByRole('option', { name: /Gemini API/ });
    expect(gemini).toHaveAttribute('aria-disabled', 'true');
    expect(gemini).toHaveAttribute('title', 'No disponible: Sin GEMINI_API_KEY configurada');
    expect(screen.getByText('Sin GEMINI_API_KEY configurada')).toBeInTheDocument();
    expect(screen.getByText('Comparte cupo con tu uso de Claude Code')).toBeInTheDocument();
    expect(screen.getByText(/Válido hasta el próximo reinicio/)).toBeInTheDocument();

    fireEvent.click(gemini);
    expect(switchSpy).not.toHaveBeenCalled();
  });

  it('switches to an available provider and updates the active label without reloading', async () => {
    vi.spyOn(api, 'fetchLLMProviders').mockResolvedValue(providers);
    vi.spyOn(api, 'switchLLMProvider').mockResolvedValue({
      active: 'claude_cli',
      previous: 'mock',
      persisted: false,
      notice: '',
    });
    const onChanged = vi.fn();

    render(<LLMProviderSelector onProviderChanged={onChanged} />);
    fireEvent.click(await screen.findByRole('button', { name: /LLM: Mock local/ }));
    fireEvent.click(await screen.findByRole('option', { name: /Claude CLI/ }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('claude_cli'));
    expect(api.switchLLMProvider).toHaveBeenCalledWith('claude_cli');
    expect(screen.getByRole('button', { name: /LLM: Claude CLI/ })).toBeInTheDocument();
  });
});
