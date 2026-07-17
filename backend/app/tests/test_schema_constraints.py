from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    database_url = config.get_main_option("sqlalchemy.url")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


@pytest.fixture()
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def insert_document(connection: Connection, content_hash: str = "a" * 64) -> str:
    return str(
        connection.execute(
            text(
                """
                INSERT INTO documents (filename, content_hash, page_count)
                VALUES (:filename, :content_hash, :page_count)
                RETURNING id
                """
            ),
            {"filename": "protocol.pdf", "content_hash": content_hash, "page_count": 3},
        ).scalar_one()
    )


def test_documents_content_hash_is_unique(connection: Connection) -> None:
    content_hash = "b" * 64
    insert_document(connection, content_hash)

    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            insert_document(connection, content_hash)


def test_chunks_content_tsv_is_generated_on_insert(connection: Connection) -> None:
    document_id = insert_document(connection, "c" * 64)
    chunk_id = connection.execute(
        text(
            """
            INSERT INTO chunks (
                document_id,
                chunk_index,
                content,
                content_hash,
                page_number,
                token_count,
                embedding_model
            )
            VALUES (
                :document_id,
                0,
                'malaria fever protocol and community health dosage table',
                :content_hash,
                1,
                8,
                'text-embedding-3-small'
            )
            RETURNING id
            """
        ),
        {"document_id": document_id, "content_hash": "d" * 64},
    ).scalar_one()

    generated_tsv = connection.execute(
        text("SELECT content_tsv::text FROM chunks WHERE id = :chunk_id"),
        {"chunk_id": chunk_id},
    ).scalar_one()

    assert "malaria" in generated_tsv
    assert "protocol" in generated_tsv
    assert generated_tsv != ""


def test_page_images_document_page_unique_constraint(connection: Connection) -> None:
    document_id = insert_document(connection, "e" * 64)
    connection.execute(
        text(
            """
            INSERT INTO page_images (document_id, page_number, storage_ref, has_table)
            VALUES (:document_id, 2, 'local://doc/page-2.png', true)
            """
        ),
        {"document_id": document_id},
    )

    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    """
                    INSERT INTO page_images (document_id, page_number, storage_ref, has_figure)
                    VALUES (:document_id, 2, 'local://doc/page-2-duplicate.png', true)
                    """
                ),
                {"document_id": document_id},
            )


def test_document_delete_cascades_to_chunks_and_page_images(connection: Connection) -> None:
    document_id = insert_document(connection, "f" * 64)
    connection.execute(
        text(
            """
            INSERT INTO chunks (
                document_id,
                chunk_index,
                content,
                content_hash,
                embedding_model
            )
            VALUES (:document_id, 0, 'cascade check content', :content_hash, 'text-embedding-3-small')
            """
        ),
        {"document_id": document_id, "content_hash": "g" * 64},
    )
    connection.execute(
        text(
            """
            INSERT INTO page_images (document_id, page_number, storage_ref)
            VALUES (:document_id, 1, 'local://doc/page-1.png')
            """
        ),
        {"document_id": document_id},
    )

    connection.execute(text("DELETE FROM documents WHERE id = :document_id"), {"document_id": document_id})

    chunk_count = connection.execute(
        text("SELECT count(*) FROM chunks WHERE document_id = :document_id"),
        {"document_id": document_id},
    ).scalar_one()
    page_image_count = connection.execute(
        text("SELECT count(*) FROM page_images WHERE document_id = :document_id"),
        {"document_id": document_id},
    ).scalar_one()

    assert chunk_count == 0
    assert page_image_count == 0


def test_query_audit_idempotency_key_is_unique(connection: Connection) -> None:
    idempotency_key = "session-1:1"
    connection.execute(
        text("INSERT INTO query_audit_log (idempotency_key, query) VALUES (:idempotency_key, 'first turn')"),
        {"idempotency_key": idempotency_key},
    )

    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text("INSERT INTO query_audit_log (idempotency_key, query) VALUES (:idempotency_key, 'retry')"),
                {"idempotency_key": idempotency_key},
            )


def test_agentops_summary_view_reads_empty_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        row_count = connection.execute(text("SELECT count(*) FROM agentops_summary")).scalar_one()

    assert row_count == 0
