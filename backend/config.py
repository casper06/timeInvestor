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
    HOST: str = os.getenv("HOST", "127.0.0.1")
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
    # Options: "auto", "gemini", "openai", "ollama", "mock"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")

    # Forecast Engine configuration
    # Options: "mock", "timesfm"
    FORECAST_ENGINE: str = os.getenv("FORECAST_ENGINE", "mock")
    USE_REAL_TIMESFM: bool = os.getenv("USE_REAL_TIMESFM", "false").lower() in ("true", "1", "t")

    # Data cache TTL (seconds)
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
