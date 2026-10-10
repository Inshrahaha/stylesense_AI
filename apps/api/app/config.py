"""
StyleSenseAI — Application Configuration

All config is loaded from environment variables via pydantic-settings.
No hard-coded URLs, keys, or model names.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # --- Application ---
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_secret_key: str = "CHANGE_ME_TO_A_RANDOM_64_CHAR_HEX_STRING"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- Database ---
    database_url: str = "postgresql+asyncpg://stylesense:stylesense_dev@localhost:5432/stylesense"
    database_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth / JWT ---
    jwt_secret_key: str = "CHANGE_ME_TO_A_RANDOM_64_CHAR_HEX_STRING"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # --- Encryption ---
    master_encryption_key: str = "CHANGE_ME_TO_A_BASE64_ENCODED_32_BYTE_KEY"

    # --- Provider Selection ---
    llm_provider: Literal["claude", "mock"] = "mock"
    classifier_provider: Literal["local", "claude", "auto"] = "local"
    embedding_provider: Literal["fashionclip", "mock"] = "mock"
    suggestion_provider: Literal["local", "live", "auto"] = "local"
    storage_provider: Literal["s3", "localfs"] = "localfs"
    jobs_eager: bool = True

    # --- S3 / MinIO ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "stylesense"
    s3_region: str = "us-east-1"

    # --- LocalFS Storage ---
    local_storage_path: str = "./storage"

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # --- Live Search ---
    search_api_key: str = ""
    search_api_base_url: str = ""

    # --- ClamAV ---
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_enabled: bool = False

    # --- Rate Limiting ---
    rate_limit_login_per_minute: int = 5
    rate_limit_upload_per_minute: int = 10
    rate_limit_llm_per_minute: int = 20

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Logging ---
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            import json
            parsed = json.loads(v)
            if not isinstance(parsed, list) or any(not isinstance(origin, str) for origin in parsed):
                raise ValueError("cors_origins must be a JSON list of strings")
            return parsed
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """Return a synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
