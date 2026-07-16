from fastapi import APIRouter, Depends
from psycopg_pool import ConnectionPool
from sentence_transformers import SentenceTransformer

from backend.deps import get_db_pool, get_embedder
from backend.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    pool: ConnectionPool = Depends(get_db_pool),
    embedder: SentenceTransformer = Depends(get_embedder),
) -> HealthResponse:
    database_status = "ok"
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
    except Exception:
        database_status = "unavailable"

    return HealthResponse(status="ok", database=database_status, embedder_loaded=embedder is not None)
