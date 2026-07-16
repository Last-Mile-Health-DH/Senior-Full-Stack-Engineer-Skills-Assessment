from functools import lru_cache
from typing import Annotated

from dotenv import find_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openai_api_key: str
    anthropic_api_key: str | None = None

    backend_port: int = 6100
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://localhost:8000"]

    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    llm_model: str = "gpt-5.4-mini"

    chunk_breakpoint_threshold_type: str = "percentile"
    chunk_breakpoint_threshold_amount: int = 90
    semantic_chunker_embedding_model: str = "text-embedding-3-large"

    default_num_results: int = 5
    max_upload_mb: int = 25

    model_config = SettingsConfigDict(
        env_file=find_dotenv(usecwd=True),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
