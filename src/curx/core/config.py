from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Curx"
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8020
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://curx:curx@127.0.0.1:5433/curx"
    redis_url: str = "redis://127.0.0.1:6380/0"
    object_store_endpoint: str = "http://127.0.0.1:9010"
    object_store_access_key: str = "curx-minio"
    object_store_secret_key: str = "curx-minio-secret"
    object_store_bucket: str = "curx-sources"
    object_store_region: str = "us-east-1"
    ingestion_inline: bool = False
    ingestion_max_upload_bytes: int = 25 * 1024 * 1024
    ingestion_max_attempts: int = 3
    chunk_max_tokens: int = 600
    chunk_overlap_tokens: int = 80
    embedding_provider: str = "local"
    embedding_model_name: str = "hash-embedding-v1"
    embedding_dimension: int = 384
    embedding_batch_size: int = 64
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    session_cookie_name: str = "curx_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = 12
    auth_required: bool = True
    auth_attempt_limit: int = 5
    auth_attempt_window_seconds: int = 300
    model_provider: str = "openai"
    model_name: str = "gpt-4.1-mini"
    model_api_key: str | None = None
    model_base_url: str | None = None
    model_temperature: float = 0.2

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="CURX_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
