from psycopg_pool import ConnectionPool

DDL_TEMPLATE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    doc_name TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector({embedding_dim}) NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_embedding_hnsw_idx
    ON documents USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS document_files (
    id SERIAL PRIMARY KEY,
    doc_name TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    page_count INTEGER,
    file_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS document_files_created_at_idx
    ON document_files (created_at DESC);
"""


def init_schema(pool: ConnectionPool, embedding_dim: int = 384) -> None:
    ddl = DDL_TEMPLATE.format(embedding_dim=embedding_dim)
    with pool.connection() as conn:
        conn.execute(ddl)
        conn.commit()


def _main() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=1, open=True)
    try:
        init_schema(pool, embedding_dim=settings.embedding_dim)
        print("Schema initialized.")
    finally:
        pool.close()


if __name__ == "__main__":
    _main()
