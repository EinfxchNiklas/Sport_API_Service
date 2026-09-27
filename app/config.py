from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://sport:sport@localhost:5432/sportdb"
    admin_api_key: str = "change-me-admin-key"
    session_secret: str = "change-me-session-secret"
    log_level: str = "INFO"
    enable_scheduler: bool = False
    openf1_base_url: str = "https://api.openf1.org/v1"
    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    tank01_key: str = ""
    tank01_host: str = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
    timezone: str = "Europe/Berlin"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        if isinstance(v, str):
            if v.startswith("postgres://"):
                return "postgresql+psycopg://" + v[len("postgres://"):]
            if v.startswith("postgresql://"):
                return "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
