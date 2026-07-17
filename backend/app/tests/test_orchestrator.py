from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.agents.orchestrator import (
    RetrievalUnavailableError,
    assemble_generation_payload,
    output_filter_stub,
)
from app.retrieval.compaction import compact_chunk
from app.retrieval.models import PageImageResult, RetrievalAgentResult, RetrievalCandidate

ORCHESTRATOR_SOURCE = Path("app/agents/orchestrator.py")


def test_compact_chunk_selects_overlap_sentences() -> None:
    text = "Vaccines are stored cold. Malaria dosage is weight based. Nutrition is separate."

    compacted = compact_chunk("malaria dosage", text, max_tokens=12)

    assert compacted == "Malaria dosage is weight based."


def test_compact_chunk_restores_selected_sentences_to_document_order() -> None:
    text = "Malaria appears first. Unrelated sentence. Dosage appears later."

    compacted = compact_chunk("dosage malaria", text, max_tokens=12)

    assert compacted == "Malaria appears first. Dosage appears later."


def test_compact_chunk_zero_overlap_falls_back_to_first_tokens() -> None:
    assert compact_chunk("zebra", "one two three four", max_tokens=2) == "one two"


def test_orchestrator_import_boundary_static() -> None:
    source = ORCHESTRATOR_SOURCE.read_text()

    assert "app.retrieval.hybrid_search" not in source
    assert "app.retrieval.rerank" not in source
    assert "app.database" not in source
    assert "sqlalchemy" not in source


@pytest.mark.asyncio
async def test_multimodal_model_attaches_images() -> None:
    payload = await assemble_generation_payload(
        query="malaria dosing",
        db=object(),
        retrieval_agent=_Agent(_retrieval_with_image()),
        model="claude-sonnet-5",
    )

    content = payload.messages[0]["content"]
    assert any(block["type"] == "image" for block in content)


@pytest.mark.asyncio
async def test_non_multimodal_model_skips_images_without_failing() -> None:
    payload = await assemble_generation_payload(
        query="malaria dosing",
        db=object(),
        retrieval_agent=_Agent(_retrieval_with_image()),
        model="claude-haiku-4-5",
    )

    content = payload.messages[0]["content"]
    assert not any(block["type"] == "image" for block in content)


@pytest.mark.asyncio
async def test_generation_payload_contains_context_blocks() -> None:
    payload = await assemble_generation_payload(
        query="malaria dosing",
        db=object(),
        retrieval_agent=_Agent(_retrieval_with_image()),
        model="claude-sonnet-5",
    )

    text_blocks = [block["text"] for block in payload.messages[0]["content"] if block["type"] == "text"]
    assert any('<context source="source.pdf" page="4">' in block for block in text_blocks)
    assert text_blocks[-1] == "malaria dosing"


@pytest.mark.asyncio
async def test_retrieval_failure_surfaces_cleanly() -> None:
    with pytest.raises(RetrievalUnavailableError):
        await assemble_generation_payload(
            query="question",
            db=object(),
            retrieval_agent=_FailingAgent(),
        )


def test_output_filter_stub_is_explicit() -> None:
    source = ORCHESTRATOR_SOURCE.read_text()

    assert '# STUB: real grounding/leak/PII checks land at BC14' in source
    assert output_filter_stub("anything").status == "passed"


class _Agent:
    def __init__(self, result: RetrievalAgentResult) -> None:
        self.result = result

    async def run(self, **kwargs: object) -> RetrievalAgentResult:
        return self.result


class _FailingAgent:
    async def run(self, **kwargs: object) -> RetrievalAgentResult:
        raise RuntimeError("database down")


def _retrieval_with_image() -> RetrievalAgentResult:
    chunk_id = UUID("00000000-0000-0000-0000-000000000001")
    document_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return RetrievalAgentResult(
        chunks=[
            RetrievalCandidate(
                chunk_id=chunk_id,
                document_id=document_id,
                document_filename="source.pdf",
                document_status="indexed",
                content="Malaria dosage is weight based. Nutrition is separate.",
                page_number=4,
            )
        ],
        page_images=[
            PageImageResult(
                chunk_id=chunk_id,
                document_id=document_id,
                page_number=4,
                storage_ref="data:image/png;base64,AAAA",
                has_table=True,
            )
        ],
        top_relevance_score=0.9,
    )
