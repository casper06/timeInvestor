import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "frontend" / "dist"

# Load .env file
load_dotenv(BASE_DIR / ".env")

class Settings:
    BASE_DIR: Path = BASE_DIR
    STATIC_DIR: Path = STATIC_DIR

    # Server settings
    RUNNING_IN_DOCKER: bool = os.getenv("RUNNING_IN_DOCKER", "0").lower() in ("true", "1", "t")
    HOST: str = os.getenv("HOST", "0.0.0.0" if os.getenv("RUNNING_IN_DOCKER", "0").lower() in ("true", "1", "t") else "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1", "t")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'backend' / 'database' / 'time_investor.db'}")

    # API Keys
    FRED_API_KEY: str | None = os.getenv("FRED_API_KEY")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # LLM Router configuration
    # Options: "auto", "gemini", "openai", "ollama", "gemini_cli", "claude_cli", "mock"
    # "gemini_cli"/"claude_cli" use the user's subscription session (Google AI
    # Pro / Claude Pro-Max) via the official CLIs instead of a billed API key —
    # see README.md's "Proveedores LLM por suscripción" section for setup,
    # quota differences, and why neither is the default here.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    # LLM_PROVIDER can be switched at runtime from the UI (POST
    # /api/config/llm-provider) — IN MEMORY ONLY, never written back to .env.
    # This keeps the startup value so the UI can show what a restart returns to.
    LLM_PROVIDER_FROM_ENV: str = LLM_PROVIDER

    # Model alias used for `claude -p ... --model <this>` when LLM_PROVIDER=claude_cli.
    # Defaults to the cheapest model to minimize consumption of the user's
    # SHARED 5-hour/weekly Claude usage window (see ClaudeCliLLMClient's own
    # docstring) — override to "sonnet" for better quality at the cost of more
    # of that shared quota per call.
    CLAUDE_CLI_MODEL: str = os.getenv("CLAUDE_CLI_MODEL", "haiku")

    # Forecast Engine configuration
    # Options: "mock", "timesfm"
    FORECAST_ENGINE: str = os.getenv("FORECAST_ENGINE", "mock")
    # Default true: EngineSelector (backend/services/engine_selector.py) already
    # restricts real TimesFM usage to a handful of benchmark-confirmed
    # categories (seasonal FRED series) — this flag no longer means "use the
    # heavy model for everything", just "let EngineSelector use it where the
    # benchmark says it wins, if the weights happen to be available". Leaving
    # it on doesn't trigger broad heavy-model usage; every other category
    # stays on Holt regardless of this flag.
    USE_REAL_TIMESFM: bool = os.getenv("USE_REAL_TIMESFM", "true").lower() in ("true", "1", "t")

    # Data configuration
    ALLOW_SYNTHETIC_DATA: bool = os.getenv("ALLOW_SYNTHETIC_DATA", "false").lower() in ("true", "1", "t")
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

    @property
    def effective_llm_provider(self) -> str:
        provider = self.LLM_PROVIDER.lower()
        if provider == "auto":
            if self.GEMINI_API_KEY and self.GEMINI_API_KEY.strip():
                return "gemini"
            elif self.OPENAI_API_KEY and self.OPENAI_API_KEY.strip():
                return "openai"
            else:
                return "mock"
        return provider

settings = Settings()
