"""Runtime settings for backend build cycles."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized environment-backed settings used by agent orchestration."""

    agent_model: str = "claude-sonnet-5"
    ingestion_agent_max_iterations_hard_ceiling: int = 320
    agent_trace_logging_enabled: bool = True
    anthropic_api_key: str = ""
    retrieval_top_k: int = 20
    hybrid_search_enabled: bool = True
    rrf_k: int = 60
    hnsw_ef_search: int = 40
    rerank_top_n: int = 5
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_provider: str = ""
    retrieval_agent_confidence_threshold: float = 0.55
    retrieval_agent_max_iterations: int = 3
    generation_model_primary: str = "claude-sonnet-5"
    generation_model_fast: str = "claude-haiku-4-5"
    exact_cache_ttl_seconds: int = 86400
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.92
    prompt_caching_enabled: bool = True
    cache_backend: str = "postgres"
    cache_eviction_cron: str = "0 * * * *"
    enable_scheduled_jobs: bool = True
    semantic_cache_max_rows: int = 5000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
