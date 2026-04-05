# core/config.py — single source of truth for all environment variables
# Import anywhere: from core.config import settings
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    API_KEY: str

    # Database
    DATABASE_URL: str
    REDIS_URL: str

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # AI APIs
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"

    # Market data
    YFINANCE_DELAY_MINUTES: int = 15

    # Wallet defaults
    DEFAULT_INITIAL_CAPITAL: float = 10000.0
    DEFAULT_MONTHLY_TOPUP: float = 1000.0
    MAX_DAILY_LOSS_PCT: float = 0.02
    DAILY_PROFIT_TARGET_PCT: float = 0.015
    INTRADAY_ALLOCATION_PCT: float = 0.25
    POSITIONAL_ALLOCATION_PCT: float = 0.75

    # Report schedule (IST, 24hr)
    MORNING_REPORT_HOUR: int = 8
    MORNING_REPORT_MINUTE: int = 30
    EVENING_REPORT_HOUR: int = 15
    EVENING_REPORT_MINUTE: int = 30

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
