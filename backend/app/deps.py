from collections.abc import Generator

from fastapi import Request
from langchain_openai.embeddings import OpenAIEmbeddings
from openai import OpenAI
from psycopg_pool import ConnectionPool
from sentence_transformers import SentenceTransformer

from app.core.config import Settings
from app.rag.rag_builder import RAGPgVector


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_pool(request: Request) -> ConnectionPool:
    return request.app.state.db_pool


def get_embedder(request: Request) -> SentenceTransformer:
    return request.app.state.embedder


def get_openai_client(request: Request) -> OpenAI:
    return request.app.state.openai_client


def get_openai_embeddings(request: Request) -> OpenAIEmbeddings:
    return request.app.state.openai_embeddings


def get_rag_engine(request: Request) -> Generator[RAGPgVector, None, None]:
    pool: ConnectionPool = request.app.state.db_pool
    settings: Settings = request.app.state.settings
    with pool.connection() as conn:
        yield RAGPgVector(
            llm_client=request.app.state.openai_client,
            embedder=request.app.state.embedder,
            conn=conn,
            model=settings.llm_model,
        )
