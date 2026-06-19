from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TiPTiB"
    database_url: str = "sqlite:///./data/tiptib.db"
    secret_key: str = Field(default="change-me-in-production")
    default_currency: str = "EUR"
    default_timezone: str = "Europe/Vienna"
    session_cookie_name: str = "tiptib_session"
    bootstrap_username: str | None = None
    bootstrap_password: str | None = None
    scheduler_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TIPTIB_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
