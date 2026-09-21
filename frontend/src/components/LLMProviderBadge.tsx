import React from 'react';
import { AlertTriangle, Sparkles } from 'lucide-react';

interface LLMProviderBadgeProps {
  providerUsed?: string | null;
  className?: string;
}

export const formatLLMProvider = (provider?: string | null): { label: string; isMock: boolean } => {
  if (!provider) {
    return { label: 'Motor no especificado', isMock: true };
  }
  const p = provider.toLowerCase();
  if (p.startsWith('mock')) {
    return { label: 'Motor heurístico local — sin LLM', isMock: true };
  }
  if (p.includes('gemini')) {
    return { label: 'Gemini 2.5 Flash', isMock: false };
  }
  if (p.includes('openai') || p.includes('gpt')) {
    return { label: 'OpenAI GPT-4o Mini', isMock: false };
  }
  if (p.startsWith('ollama')) {
    const model = provider.replace(/^ollama-?/i, '') || 'local';
    return { label: `Ollama (${model})`, isMock: false };
  }
  return { label: provider, isMock: false };
};

export const LLMProviderBadge: React.FC<LLMProviderBadgeProps> = ({
  providerUsed,
  className = '',
}) => {
  const { label, isMock } = formatLLMProvider(providerUsed);

  if (isMock) {
    return (
      <span
        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 shadow-sm ${className}`}
        title="Generado mediante el parser semántico heurístico local determinístico (sin LLM externo)"
      >
        <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
        <span>{label}</span>
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shadow-sm ${className}`}
      title={`Generado con el modelo fundacional ${label}`}
    >
      <Sparkles className="h-3 w-3 text-emerald-400 shrink-0" />
      <span>{label}</span>
    </span>
  );
};
