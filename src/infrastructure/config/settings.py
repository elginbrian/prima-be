from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings for Prima Backend"""
    # App Info
    app_name: str = "Prima Backend"
    app_version: str = "0.1.0"
    debug: bool = True
    environment: str = "development"

    # API Settings
    api_prefix: str = "/api/v1"

    # CORS Settings
    cors_origins: List[str] = [
        "http://localhost:3000",
        "https://prima-pertamina.vercel.app"
    ]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]

    # Database Settings
    database_url: str = "postgresql+asyncpg://user:pass@localhost/primadb"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # JWT Settings
    jwt_secret_key: str = "prima-secret-key-change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8001
    workers: int = 4

    # AWS S3 Storage Settings
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-southeast-1"
    s3_bucket_name: str = "prima-storage-local"
    s3_endpoint_url: str | None = None # Useful for LocalStack or MinIO if testing locally

    # AI / LLM Settings
    gemini_api_key: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
