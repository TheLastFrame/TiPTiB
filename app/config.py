from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TiPTiB"
    database_url: str = "sqlite:///./data/tiptib.db"
    secret_key: str = Field(default="change-me-in-production")
    environment: str = "development"
    default_currency: str = "EUR"
    default_timezone: str = "Europe/Vienna"
    session_cookie_name: str = "tiptib_session"
    session_cookie_secure: bool | None = None
    session_max_age_seconds: int = 60 * 60 * 24 * 14
    allowed_hosts: str = "*"
    allow_web_setup: bool = False
    bootstrap_username: str | None = None
    bootstrap_password: str | None = None
    scheduler_enabled: bool = True
    run_migrations_on_startup: bool = True
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 5 * 60

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TIPTIB_")

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"prod", "production"}

    @property
    def secure_session_cookie(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production

    @property
    def allowed_host_list(self) -> list[str]:
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        return hosts or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
