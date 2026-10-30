"""Infrastructure configuration loaded from environment variables / the local .env file.

Secrets (API keys, SMTP passwords, the local API token) only ever come from the environment.
Owner preferences that change at runtime (research time, budget, risk limits, ...) live in the
database as versioned records; see ``investiq.services.preferences``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_env_file() -> str:
    return os.environ.get("INVESTIQ_ENV_FILE", str(REPO_ROOT / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INVESTIQ_",
        env_file=_default_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://investiq:investiq@127.0.0.1:5432/investiq"

    # Network exposure: loopback only by default. Never bind 0.0.0.0 without a reason.
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_token: SecretStr | None = None
    frontend_origin: str = "http://127.0.0.1:3000"

    data_dir: Path = REPO_ROOT / "data"
    backup_dir: Path = REPO_ROOT / "backups"
    outbox_dir: Path = REPO_ROOT / "outbox"
    log_level: str = "INFO"

    # External services (all optional; features degrade gracefully when absent).
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    fmp_api_key: SecretStr | None = None
    twelvedata_api_key: SecretStr | None = None
    sec_user_agent: str | None = None  # SEC EDGAR requires "Name email" in the User-Agent.

    resend_api_key: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: str | None = None

    # Backups. "local" runs pg_dump/pg_restore from PATH or pg_bin_dir; "docker" runs them inside
    # the compose database service (docker compose exec), so no client tools are needed on Windows.
    pg_tools_mode: Literal["local", "docker"] = "local"
    pg_bin_dir: Path | None = None
    docker_compose_file: Path = REPO_ROOT / "docker-compose.yml"
    docker_db_service: str = "db"

    # Synthetic fixtures are for development only and are refused in production.
    allow_synthetic_data: bool = False

    # Scheduler: run the in-process due-check loop inside the API server.
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 60

    @field_validator("api_host")
    @classmethod
    def _loopback_warning(cls, v: str) -> str:
        return v.strip()

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def secret(self, name: str) -> str | None:
        value = getattr(self, name)
        if value is None:
            return None
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
