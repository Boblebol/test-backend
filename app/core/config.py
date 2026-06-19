from functools import lru_cache

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: AnyUrl = "postgresql+psycopg://primmo:primmo@postgres:5432/primmo"
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "http://minio:9000"
    minio_public_endpoint: str | None = None
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "primmo-documents"
    minio_region: str = "us-east-1"
    max_upload_size_bytes: int = 20 * 1024 * 1024
    upload_url_expires_seconds: int = 300
    jwt_secret: str = "local-dev-secret-change-me-32-bytes"
    jwt_expires_minutes: int = 60
    partner_hmac_secret: str = "local-partner-secret-change-me"
    app_env: str = "local"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
