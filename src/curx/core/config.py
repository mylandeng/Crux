from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Curx"
    app_env: str = "local"
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://curx:curx@localhost:5432/curx"
    redis_url: str = "redis://localhost:6379/0"
    object_store_endpoint: str = "http://localhost:9000"
    model_provider: str = "openai"
    model_name: str = "gpt-4.1-mini"
    model_api_key: str | None = None
    model_base_url: str | None = None
    model_temperature: float = 0.2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CURX_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
