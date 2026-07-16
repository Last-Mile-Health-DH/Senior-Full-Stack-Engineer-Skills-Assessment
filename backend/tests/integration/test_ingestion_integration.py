import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

RUN_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS") == "1"
REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_PDF_PATH = REPO_ROOT / "uploads" / "Best_practices_Data_Use_Community_Health.pdf"


@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="Set RUN_INTEGRATION_TESTS=1 to run against a live Postgres+pgvector instance and a real OPENAI_API_KEY.",
)
def test_ingest_then_chat_end_to_end():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"

        with SAMPLE_PDF_PATH.open("rb") as f:
            upload_response = client.post(
                "/documents",
                files={"file": (SAMPLE_PDF_PATH.name, f, "application/pdf")},
            )
        assert upload_response.status_code == 200
        assert upload_response.json()["chunks_ingested"] > 0

        chat_response = client.post("/chat", json={"question": "What is this document about?"})
        assert chat_response.status_code == 200
        assert chat_response.json()["answer"]
