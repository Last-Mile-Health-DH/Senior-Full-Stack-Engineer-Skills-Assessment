from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_PDF_PATH = REPO_ROOT / "uploads" / "Best_practices_Data_Use_Community_Health.pdf"


class FakeEmbedder:
    def encode(self, texts):
        if isinstance(texts, str):
            return [0.1, 0.2, 0.3]
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeConnection:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "SELECT 1" in sql:
            return []
        if "SELECT" in sql and "documents" in sql:
            return [
                ("Best_practices_Data_Use_Community_Health.pdf", "UNICEF supports community health workers.", 0.87),
                ("Best_practices_Data_Use_Community_Health.pdf", "Digital tools improve last-mile data use.", 0.81),
            ]
        return []

    def transaction(self):
        return _NoopContext()

    def commit(self):
        pass


class _NoopContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakePoolConnectionContext:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def __enter__(self) -> FakeConnection:
        return self._conn

    def __exit__(self, *exc_info):
        return False


class FakePool:
    def __init__(self, conn: FakeConnection | None = None, raise_on_connect: bool = False):
        self.conn = conn or FakeConnection()
        self.raise_on_connect = raise_on_connect

    def connection(self):
        if self.raise_on_connect:
            raise RuntimeError("database unavailable")
        return FakePoolConnectionContext(self.conn)


class FakeOpenAIResponse:
    def __init__(self, output_text: str):
        self.output_text = output_text


class FakeResponses:
    def __init__(self, output_text: str):
        self._output_text = output_text

    def create(self, model, input):
        return FakeOpenAIResponse(self._output_text)


class FakeOpenAIClient:
    def __init__(self, output_text: str = "mocked answer"):
        self.responses = FakeResponses(output_text)


class FakeSemanticChunkerDocument:
    def __init__(self, page_content: str):
        self.page_content = page_content


class FakeSemanticChunker:
    """Stands in for langchain_experimental's SemanticChunker in tests, avoiding real OpenAI calls."""

    def __init__(self, embeddings, breakpoint_threshold_type, breakpoint_threshold_amount):
        self.embeddings = embeddings

    def create_documents(self, texts):
        return [
            FakeSemanticChunkerDocument("First chunk of the document."),
            FakeSemanticChunkerDocument("Second chunk of the document."),
            FakeSemanticChunkerDocument("Third chunk of the document."),
        ]


@pytest.fixture
def fake_settings() -> Settings:
    return Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        openai_api_key="test-key",
        max_upload_mb=25,
        chunk_breakpoint_threshold_type="percentile",
        chunk_breakpoint_threshold_amount=90,
    )


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_openai_client() -> FakeOpenAIClient:
    return FakeOpenAIClient()


@pytest.fixture
def client() -> Iterator[TestClient]:
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return SAMPLE_PDF_PATH.read_bytes()
