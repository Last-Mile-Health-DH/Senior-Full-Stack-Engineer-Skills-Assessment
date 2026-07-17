from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.home.routes import router as home_router
from app.documents.routes import router as documents_router
from app.scheduling.cache_scheduler import (
    start_cache_hygiene_scheduler,
    stop_cache_hygiene_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache_scheduler_task = start_cache_hygiene_scheduler()
    try:
        yield
    finally:
        await stop_cache_hygiene_scheduler(cache_scheduler_task)


app = FastAPI(lifespan=lifespan)

# Allow all origins for development; restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(home_router)
app.include_router(documents_router)
