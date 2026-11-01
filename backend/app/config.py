from functools import lru_cache
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    app_mode: str = "synthetic"
    database_url: SecretStr
    rabbit_url: SecretStr
    session_secret: SecretStr
    internal_secret: SecretStr
    bank_write_secret: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    voyage_api_key: SecretStr = SecretStr("")
    llm_model: str = "groq/openai/gpt-oss-120b"
    llm_fallback_model: str = "groq/qwen/qwen3.8-27b"
    llm_max_tokens: int = Field(default=1024, ge=512, le=8192)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=3)
    embedding_model: str = "voyage/voyage-3.5"
    embedding_dim: int = 1024
    mcp_url: str = "http://tools:8001/mcp"
    bank_url: str = "http://bank:8002"

    @model_validator(mode="after")
    def validate_boundaries(self):
        if self.app_mode != "synthetic":
            raise ValueError("This build supports synthetic data only")
        if self.embedding_dim not in (256, 512, 1024, 2048):
            raise ValueError("Unsupported embedding dimension")
        if (
            min(
                len(self.session_secret.get_secret_value()),
                len(self.internal_secret.get_secret_value()),
            )
            < 32
        ):
            raise ValueError(
                "Session and internal secrets must be at least 32 characters"
            )
        return self


@lru_cache
def settings():
    return Settings()
