from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai.embeddings import OpenAIEmbeddings
from openai import OpenAI
from sentence_transformers import SentenceTransformer

from backend.core.config import get_settings
from backend.db.pool import create_pool
from backend.db.schema import init_schema
from backend.errors import register_exception_handlers
from backend.routers import chat, documents, health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    pool = create_pool(settings.database_url)
    init_schema(pool, embedding_dim=settings.embedding_dim)

    app.state.settings = settings
    app.state.db_pool = pool
    app.state.embedder = SentenceTransformer(settings.embedding_model_name)
    app.state.openai_client = OpenAI(api_key=settings.openai_api_key)
    app.state.openai_embeddings = OpenAIEmbeddings(
        model=settings.semantic_chunker_embedding_model,
        api_key=settings.openai_api_key,
    )

    yield

    pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend", lifespan=lifespan)

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(chat.router)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
