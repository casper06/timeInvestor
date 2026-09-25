"""
Runtime availability of each LLM provider, for the Header's provider selector
(GET/POST /api/config/llm-provider[s]).

Same criterion as the FRED series without FRED_API_KEY: never offer an option
we already know is going to fail without saying why. Each provider reports
`available` plus, when False, the specific reason — "Sin GEMINI_API_KEY
configurada", "gemini CLI no instalado", "claude CLI no autenticado", etc.

None of these checks ever calls a model (no quota is spent just to render a
dropdown):
- API-key providers: the key is present in settings. Instant, never cached,
  so it always reflects the current settings.
- gemini_cli: binary in PATH + the OAuth credentials file Gemini CLI writes
  after "Sign in with Google" (~/.gemini/oauth_creds.json, or
  ~/.gemini/gemini-credentials.json when GEMINI_FORCE_ENCRYPTED_FILE_STORAGE
  is set — both paths confirmed in the installed @google/gemini-cli 0.61.0
  bundle, not guessed). Gemini CLI has no `auth status` subcommand.
- claude_cli: binary in PATH + `claude auth status --json`, which reports
  {"loggedIn": true/false, ...} locally in ~0.5s without a model turn
  (verified against Claude Code 2.1.281).
- ollama: GET {OLLAMA_BASE_URL}/api/tags with a short timeout — lists local
  models, never generates.

The CLI and Ollama checks spawn a process / hit the network, so their results
are cached for AVAILABILITY_CACHE_TTL_SECONDS instead of re-running on every
render of the dropdown.

What these checks can NOT see: an account Google refuses outright
(IneligibleTierError / UNSUPPORTED_CLIENT) still has a valid credentials file.
That is only learned from a real call, so the CLI client reports it back via
mark_account_rejected(), which pins the provider as unavailable for
ACCOUNT_REJECTION_TTL_SECONDS — or until the process restarts.
"""
import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Order is the order shown in the dropdown. "auto" is deliberately NOT here:
# it's a .env-level convenience (resolved by Settings.effective_llm_provider),
# not a concrete provider the user would pick at runtime.
KNOWN_PROVIDERS: List[str] = ["gemini", "gemini_cli", "claude_cli", "openai", "ollama", "mock"]

PROVIDER_LABELS: Dict[str, str] = {
    "gemini": "Gemini API",
    "gemini_cli": "Gemini CLI",
    "claude_cli": "Claude CLI",
    "openai": "OpenAI API",
    "ollama": "Ollama (local)",
    "mock": "Mock local",
}

# One-line reminders shown next to the option in the dropdown, so the choice
# is informed at the moment it's made (see README "Diferencia importante de
# cuota") — not a paragraph, just the one thing that bites if forgotten.
PROVIDER_NOTES: Dict[str, str] = {
    "gemini_cli": "Cuota propia, separada del resto de tu uso de Gemini",
    "claude_cli": "Comparte cupo con tu uso de Claude Code",
    "mock": "Motor semántico local, sin red ni cuota",
}

AVAILABILITY_CACHE_TTL_SECONDS = 60
# An account-level rejection doesn't fix itself in 60 s, and re-checking it
# would mean offering again an option we already saw fail for good.
ACCOUNT_REJECTION_TTL_SECONDS = 24 * 60 * 60
CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS = 10
OLLAMA_PROBE_TIMEOUT_SECONDS = 1.5

Availability = Tuple[bool, Optional[str]]


@dataclass
class ProviderAvailability:
    id: str
    label: str
    available: bool
    reason: Optional[str] = None
    note: Optional[str] = None


# provider -> (expires_at monotonic, result, survives_refresh). survives_refresh
# is set only for account rejections: ?refresh=true re-runs the cheap check,
# which would just find the credentials file again and wrongly say available.
_cache: Dict[str, Tuple[float, Availability, bool]] = {}
_cache_lock = threading.Lock()


def clear_availability_cache() -> None:
    with _cache_lock:
        _cache.clear()


def mark_account_rejected(provider: str, reason: str) -> None:
    """Record that a real call proved `provider` unusable at the account level.
    Stored in the same cache as the regular checks, with a longer TTL."""
    expires_at = time.monotonic() + ACCOUNT_REJECTION_TTL_SECONDS
    with _cache_lock:
        _cache[provider] = (expires_at, (False, reason), True)
    logger.warning(f"{provider} marked unavailable for {ACCOUNT_REJECTION_TTL_SECONDS}s: {reason}")


def _cached(provider: str, check: Callable[[], Availability], force_refresh: bool) -> Availability:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(provider)
        if hit and now < hit[0] and (not force_refresh or hit[2]):
            return hit[1]
    result = check()
    with _cache_lock:
        _cache[provider] = (now + AVAILABILITY_CACHE_TTL_SECONDS, result, False)
    return result


def _has_value(value: Optional[str]) -> bool:
    return bool(value and value.strip())


def _check_gemini_cli() -> Availability:
    if shutil.which("gemini") is None:
        return False, "gemini CLI no instalado (npm install -g @google/gemini-cli)"
    gemini_dir = Path.home() / ".gemini"
    if (gemini_dir / "oauth_creds.json").is_file() or (gemini_dir / "gemini-credentials.json").is_file():
        return True, None
    return False, "gemini CLI no autenticado (corré `gemini` una vez y elegí \"Sign in with Google\")"


def _check_claude_cli() -> Availability:
    binary_path = shutil.which("claude")
    if binary_path is None:
        return False, "claude CLI no instalado (npm install -g @anthropic-ai/claude-code)"
    try:
        result = subprocess.run(
            [binary_path, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=CLAUDE_AUTH_STATUS_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
        status = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return False, "claude CLI no respondió al verificar la sesión (`claude auth status`)"
    except (json.JSONDecodeError, OSError) as e:
        # Older Claude Code versions without `auth status`: we can't confirm a
        # session, and "never offer what we can't vouch for" wins here.
        logger.warning(f"Could not verify Claude CLI session: {e}")
        return False, "No se pudo verificar la sesión de claude CLI (actualizá Claude Code)"
    if status.get("loggedIn"):
        return True, None
    return False, "claude CLI no autenticado (corré `claude` una vez para iniciar sesión)"


def _check_ollama() -> Availability:
    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True, None
    except Exception:
        return False, f"Ollama no responde en {base_url}"


def check_provider(provider: str, force_refresh: bool = False) -> Availability:
    """(available, reason) for one provider id; reason is None when available."""
    if provider == "gemini":
        if _has_value(settings.GEMINI_API_KEY):
            return True, None
        return False, "Sin GEMINI_API_KEY configurada"
    if provider == "openai":
        if _has_value(settings.OPENAI_API_KEY):
            return True, None
        return False, "Sin OPENAI_API_KEY configurada"
    if provider == "gemini_cli":
        return _cached(provider, _check_gemini_cli, force_refresh)
    if provider == "claude_cli":
        return _cached(provider, _check_claude_cli, force_refresh)
    if provider == "ollama":
        return _cached(provider, _check_ollama, force_refresh)
    if provider == "mock":
        return True, None
    return False, f"Proveedor desconocido: '{provider}'"


def get_provider_availability(force_refresh: bool = False) -> List[ProviderAvailability]:
    items = []
    for pid in KNOWN_PROVIDERS:
        available, reason = check_provider(pid, force_refresh=force_refresh)
        items.append(ProviderAvailability(
            id=pid,
            label=PROVIDER_LABELS[pid],
            available=available,
            reason=reason,
            note=PROVIDER_NOTES.get(pid),
        ))
    return items
