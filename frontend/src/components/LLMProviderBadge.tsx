import React from 'react';
import { AlertTriangle, Sparkles } from 'lucide-react';
import type { FallbackCategory } from '../services/api';

interface LLMProviderBadgeProps {
  providerUsed?: string | null;
  fallbackReason?: string | null;
  fallbackCategory?: FallbackCategory | null;
  className?: string;
}

/**
 * Turns fallback_category into an ACTIONABLE explanation — whether waiting
 * helps or the user needs to go fix something — instead of leaving them to
 * guess from the raw fallback_reason string alone. 'unknown' intentionally
 * falls through to the raw reason rather than inventing a category that
 * doesn't apply.
 */
const describeFallbackCategory = (category: FallbackCategory | null | undefined, rawReason: string): string => {
  switch (category) {
    case 'rate_limit':
      return 'Se alcanzó el límite de uso de tu cuenta de Gemini. Probá de nuevo en unos minutos, o revisá la facturación en Google AI Studio.';
    case 'transient':
      return 'Falla temporal del servicio. Reintentá la consulta.';
    case 'auth_or_config':
      return 'Problema de configuración (clave inválida o modelo no disponible). Esto no se arregla esperando — revisá tu .env o los logs del servidor.';
    case 'content_filtered':
      return 'Gemini bloqueó esta respuesta por su filtro de contenido. Probá reformular la tesis; esto no es un problema de cuota ni de configuración.';
    default:
      return rawReason;
  }
};

/**
 * Turns a raw `provider_used` string (e.g. "gemini-3.6-flash", "openai-gpt-4o-mini",
 * "ollama-llama3.2") into a human-readable label — WITHOUT a hardcoded per-model name
 * table. Whatever model string the backend reports is what gets shown, so a model
 * bump (e.g. gemini-3.6-flash -> gemini-4.0-flash) never requires a frontend change:
 * each hyphen-separated word is capitalized as-is (numbers/versions pass through
 * untouched, e.g. "3.6" stays "3.6").
 */
const humanizeProviderString = (provider: string): string =>
  provider
    .split('-')
    .map((word) => (/^[a-z]/i.test(word) ? word.charAt(0).toUpperCase() + word.slice(1) : word))
    .join(' ');

export const formatLLMProvider = (provider?: string | null): { label: string; isMock: boolean } => {
  if (!provider) {
    return { label: 'Motor no especificado', isMock: true };
  }
  const p = provider.toLowerCase();
  if (p.startsWith('mock')) {
    return { label: 'Motor heurístico local — sin LLM', isMock: true };
  }
  return { label: humanizeProviderString(provider), isMock: false };
};

export const LLMProviderBadge: React.FC<LLMProviderBadgeProps> = ({
  providerUsed,
  fallbackReason,
  fallbackCategory,
  className = '',
}) => {
  const { label, isMock } = formatLLMProvider(providerUsed);

  if (isMock) {
    // fallback_reason is only set when mock was reached because a real provider
    // threw (auth, model retired, network, ...) — not when mock was configured on purpose.
    const title = fallbackReason
      ? `Se usó el motor heurístico local porque el proveedor real falló: ${describeFallbackCategory(fallbackCategory, fallbackReason)}`
      : 'Generado mediante el parser semántico heurístico local determinístico (sin LLM externo)';

    return (
      <span
        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30 shadow-sm cursor-help ${className}`}
        title={title}
      >
        <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
        <span>{label}</span>
        {fallbackReason && <span className="sr-only">{title}</span>}
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
