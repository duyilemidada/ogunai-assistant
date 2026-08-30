# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    APP_NAME: str = "Ogun AI"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = ""
    DATABASE_URL: str = "sqlite:///./ogun.db"

    # LLM
    LLM_PROVIDER: str = "openai_compatible"
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"

    #TAVILY
    TAVILY_API_KEY: str = ""

    # Auth
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Mono DirectPay
    MONO_SECRET_KEY: str = "test_sk_placeholder"
    MONO_ACCOUNT_ID: str = "placeholder_account_id"

    # USDA FoodData Central — DEMO_KEY works for testing, get a real one at fdc.nal.usda.gov
    USDA_API_KEY: str = ""
    USDA_BASE_URL: str = "https://api.nal.usda.gov/fdc/v1"

    # wger Exercise Database — public API, no key required
    WGER_BASE_URL: str = "https://wger.de/api/v2"

    # GitHub Personal Access Token — create at github.com/settings/tokens (repo scope)
    # Leave blank to disable github_api tool gracefully rather than crashing.
    GITHUB_TOKEN: str = ""

    # Sandboxed directory for run_terminal. Agent writes/runs code here.
    # All relative paths in run_terminal resolve inside this directory.
    WORKSPACE_DIR: str = "./workspace"

    # Playwright session cookies live here so browse_authenticated skips login on repeat visits.
    PLAYWRIGHT_STORAGE_DIR: str = "./browser_sessions"

    # Where uploaded PDFs are stored (for upload_pdf / ask_document RAG pipeline).
    UPLOADS_DIR: str = "./uploads"

    # XGBoost model .pkl files
    ML_MODELS_DIR: str = "ml_models"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        case_sensitive=True,
    )


settings = Settings()