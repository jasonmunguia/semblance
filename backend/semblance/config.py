import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEMBLANCE_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./semblance.db"
    alchemy_key: str = ""
    session_secret: str = "local-development-only-change-before-deploy"
    production: bool = False
    max_wallets: int = 3
    max_global_wallets: int = 3
    poll_seconds: int = 300
    scan_blocks: int = 300
    session_days: int = 30
    collector_secret: str = ""
    collector_budget_seconds: int = 45

    def validate_deployment(self):
        if self.production and (len(self.session_secret) < 32 or self.session_secret.startswith("local-")):
            raise ValueError("Production requires a random SESSION_SECRET of at least 32 characters")
        if self.production and self.database_url.startswith("sqlite"):
            raise ValueError("Production monitoring requires a persistent PostgreSQL database")


@lru_cache
def get_settings():
    settings = Settings()
    hosted_url = os.getenv("DATABASE_URL")
    if hosted_url and not os.getenv("SEMBLANCE_DATABASE_URL"):
        settings.database_url = hosted_url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    settings.validate_deployment()
    return settings
