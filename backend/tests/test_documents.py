import app.services.ingestion as ingestion_module
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.deps import get_db_pool, get_embedder, get_openai_embeddings, get_settings
from app.main import app
from tests.conftest import FakeConnection, FakeEmbedder, FakePool, FakeSemanticChunker


def test_upload_pdf_ingests_and_returns_chunk_count(
    client: TestClient,
    fake_embedder: FakeEmbedder,
    fake_settings: Settings,
    sample_pdf_bytes: bytes,
    monkeypatch,
):
    monkeypatch.setattr(ingestion_module, "SemanticChunker", FakeSemanticChunker)

    fake_conn = FakeConnection()
    app.dependency_overrides[get_db_pool] = lambda: FakePool(fake_conn)
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_openai_embeddings] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: fake_settings

    response = client.post(
        "/documents",
        files={"file": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_name"] == "sample.pdf"
    assert body["chunks_ingested"] == 3

    insert_calls = [call for call in fake_conn.executed if "INSERT INTO documents" in call[0]]
    assert len(insert_calls) == 3

    metadata_calls = [call for call in fake_conn.executed if "INSERT INTO document_files" in call[0]]
    assert len(metadata_calls) == 1


def test_upload_rejects_non_pdf_file(client: TestClient, fake_embedder: FakeEmbedder, fake_settings: Settings):
    app.dependency_overrides[get_db_pool] = lambda: FakePool(FakeConnection())
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_openai_embeddings] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: fake_settings

    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"just plain text", "text/plain")},
    )

    assert response.status_code == 422


def test_list_documents_returns_uploaded_files(client: TestClient, fake_settings: Settings):
    app.dependency_overrides[get_db_pool] = lambda: FakePool(FakeConnection())
    app.dependency_overrides[get_settings] = lambda: fake_settings

    response = client.get("/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["documents"][0]["doc_name"] == "Best_practices_Data_Use_Community_Health.pdf"
    assert body["documents"][0]["page_count"] == 3
    assert body["documents"][0]["file_type"] == "application/pdf"
