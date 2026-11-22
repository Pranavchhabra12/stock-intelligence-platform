"""Application settings, read from environment variables (and a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.database.urls import normalize_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "dev", "prod", "test"] = "local"
    log_level: str = "INFO"

    # SecretStr keeps the password out of logs and reprs.
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # Comma-separated in the environment, e.g. "http://localhost:3000,https://example.vercel.app"
    cors_allowed_origins: str = "http://localhost:3000"
    api_rate_limit_per_minute: int = Field(default=60, ge=0)
    admin_api_token: SecretStr | None = None
    # Shared with the website's server so its page renders aren't rate limited as one client.
    internal_api_key: SecretStr | None = None

    # Phase 2: market data. Providers are tried in this order for prices.
    market_data_providers: str = "yfinance,upstox,eodhd"
    eodhd_api_key: SecretStr | None = None
    # IndianAPI.in: company results (quarterly and annual). Optional; Yahoo is used without it.
    indianapi_key: SecretStr | None = None
    price_backfill_years: int = Field(default=5, ge=1, le=20)

    # Phase 4: AI analysis. Without a key, analysis is skipped and everything else still works.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_max_requests_per_run: int = Field(default=40, ge=1, le=500)

    # Companies followed daily and included in Power BI; visitors can add up to this many.
    max_tracked_companies: int = Field(default=25, ge=1, le=500)

    # Phase 5: on-demand refresh jobs
    refresh_cooldown_minutes: int = Field(default=15, ge=0, le=1440)   # reuse a refresh this recent
    max_active_jobs: int = Field(default=3, ge=1, le=20)               # across all companies
    job_stale_minutes: int = Field(default=45, ge=5, le=1440)          # a job running longer is marked failed

    @property
    def market_data_provider_codes(self) -> list[str]:
        return [c.strip() for c in self.market_data_providers.split(",") if c.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url.get_secret_value())

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
