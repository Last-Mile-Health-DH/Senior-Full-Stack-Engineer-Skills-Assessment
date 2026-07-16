from fastapi.testclient import TestClient

from backend.deps import get_rag_engine
from backend.main import app
from backend.rag.rag_builder import RAGPgVector
from tests.conftest import FakeConnection, FakeEmbedder, FakeOpenAIClient


def test_chat_returns_answer_with_sources(client: TestClient, fake_embedder: FakeEmbedder):
    fake_conn = FakeConnection()
    fake_openai_client = FakeOpenAIClient(output_text="UNICEF supports frontline health workers.")

    def fake_get_rag_engine():
        return RAGPgVector(
            llm_client=fake_openai_client,
            embedder=fake_embedder,
            conn=fake_conn,
            model="test-model",
        )

    app.dependency_overrides[get_rag_engine] = fake_get_rag_engine

    response = client.post("/chat", json={"question": "What does UNICEF do?", "num_results": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "UNICEF supports frontline health workers."
    assert body["sources"] == [
        {"doc_name": "Best_practices_Data_Use_Community_Health.pdf", "similarity": 0.87},
        {"doc_name": "Best_practices_Data_Use_Community_Health.pdf", "similarity": 0.81},
    ]


def test_chat_rejects_empty_question(client: TestClient, fake_embedder: FakeEmbedder):
    fake_openai_client = FakeOpenAIClient()

    app.dependency_overrides[get_rag_engine] = lambda: RAGPgVector(
        llm_client=fake_openai_client,
        embedder=fake_embedder,
        conn=FakeConnection(),
        model="test-model",
    )

    response = client.post("/chat", json={"question": ""})

    assert response.status_code == 422
