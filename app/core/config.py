from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Enterprise Knowledge Base Assistant"
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("development-only-secret-change-before-production"),
        min_length=32,
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/knowledge_base"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=20, ge=1, le=200)
    chunk_size: int = Field(default=1000, ge=100, le=10000)
    chunk_overlap: int = Field(default=150, ge=0, le=5000)

    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, ge=1, le=4096)
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    model_request_timeout_seconds: float = Field(default=60, gt=0, le=300)
    model_max_retries: int = Field(default=2, ge=0, le=5)
    model_retry_base_seconds: float = Field(default=0.5, ge=0, le=10)
    openai_embedding_send_dimensions: bool = False
    openai_chat_max_tokens: int = Field(default=1000, ge=1, le=16000)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_min_similarity: float = Field(default=0.2, ge=-1, le=1)
    rag_max_context_chars: int = Field(default=12000, ge=1000, le=100000)
    citation_excerpt_chars: int = Field(default=240, ge=50, le=1000)
    chat_rate_limit_requests: int = Field(default=20, ge=1, le=10000)
    chat_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    embedding_cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    model_input_cost_per_1m_tokens: float = Field(default=0, ge=0)
    model_output_cost_per_1m_tokens: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
