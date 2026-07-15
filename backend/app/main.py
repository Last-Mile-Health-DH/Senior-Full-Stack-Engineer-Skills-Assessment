from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.config import router as config_router
from app.core.errors import AppError, app_error_handler
from app.generation.client import get_generation_client
from app.home.routes import router as home_router
from app.documents.routes import router as documents_router
from app.security.guardrails import (
    InputValidationMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.scheduling.cache_scheduler import start_schedulers, stop_schedulers
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the generation client once. Constructing it per request would open a new HTTP
    # client per chat turn and, worse, re-log the provider-selection warning on every call.
    app.state.generation_client = get_generation_client()
    scheduler_tasks = start_schedulers()
    try:
        yield
    finally:
        await stop_schedulers(scheduler_tasks)


app = FastAPI(lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)

# Middleware added first is innermost. UnhandledErrorMiddleware must sit INSIDE
# CORSMiddleware: an exception that escapes it would be rendered by Starlette's outermost
# error handler, which never passes back through CORS, and the browser would then report a
# phantom "No 'Access-Control-Allow-Origin' header" instead of the actual server error.
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(InputValidationMiddleware)

app.include_router(home_router)
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(documents_router)
app.include_router(chat_router)
