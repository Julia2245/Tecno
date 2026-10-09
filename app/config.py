from __future__ import annotations

from functools import lru_cache
from typing import FrozenSet

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    bot_display_name: str = Field(default="", alias="BOT_DISPLAY_NAME")
    super_admins: str = Field(default="", alias="SUPER_ADMINS")
    drop_pending_updates: bool = Field(default=False, alias="DROP_PENDING_UPDATES")

    database_url: str = Field(alias="DATABASE_URL")
    pg_pool_min: int = Field(default=2, ge=1, le=100, alias="PG_POOL_MIN")
    pg_pool_max: int = Field(default=20, ge=1, le=200, alias="PG_POOL_MAX")
    pg_command_timeout: float = Field(default=15.0, gt=0, le=120, alias="PG_COMMAND_TIMEOUT")
    telegram_connection_limit: int = Field(default=100, ge=8, le=500, alias="TELEGRAM_CONNECTION_LIMIT")
    max_concurrent_updates: int = Field(default=64, ge=1, le=1000, alias="MAX_CONCURRENT_UPDATES")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    slow_update_warning_ms: float = Field(default=250.0, ge=1, alias="SLOW_UPDATE_WARNING_MS")

    @field_validator("bot_token", "database_url")
    @classmethod
    def required_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        lowered = value.lower()
        if not (lowered.startswith("postgresql://") or lowered.startswith("postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @field_validator("pg_pool_max")
    @classmethod
    def pool_bounds(cls, value: int, info):
        minimum = info.data.get("pg_pool_min")
        if minimum is not None and value < minimum:
            raise ValueError("PG_POOL_MAX must be >= PG_POOL_MIN")
        return value

    @property
    def super_admin_ids(self) -> FrozenSet[int]:
        values: set[int] = set()
        raw = self.super_admins.replace(";", ",")
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                user_id = int(item)
            except ValueError as exc:
                raise ValueError(f"Invalid SUPER_ADMINS value: {item!r}") from exc
            if user_id <= 0:
                raise ValueError("SUPER_ADMINS values must be positive Telegram IDs")
            values.add(user_id)
        return frozenset(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
