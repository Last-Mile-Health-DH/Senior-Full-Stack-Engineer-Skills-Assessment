from fastapi.testclient import TestClient

from backend.deps import get_db_pool, get_embedder
from backend.main import app
from tests.conftest import FakeConnection, FakeEmbedder, FakePool


def test_health_ok(client: TestClient, fake_embedder: FakeEmbedder):
    app.dependency_overrides[get_db_pool] = lambda: FakePool(FakeConnection())
    app.dependency_overrides[get_embedder] = lambda: fake_embedder

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": "ok", "embedder_loaded": True}


def test_health_reports_database_unavailable(client: TestClient, fake_embedder: FakeEmbedder):
    app.dependency_overrides[get_db_pool] = lambda: FakePool(raise_on_connect=True)
    app.dependency_overrides[get_embedder] = lambda: fake_embedder

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "unavailable"
