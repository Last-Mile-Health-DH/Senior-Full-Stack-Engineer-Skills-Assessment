"""Internal-only page-image lookup tool for final retrieval results."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tracing import traced
from app.chainlit_steps import chainlit_step
from app.retrieval.models import PageImageResult, RetrievalCandidate


@chainlit_step("fetch_page_image", "tool")
@traced(agent_name="retrieval_agent")
async def fetch_page_image(
    db: AsyncSession,
    candidate: RetrievalCandidate,
) -> PageImageResult | None:
    """Fetch page-image metadata for one final chunk.

    This is intentionally not exposed through a FastAPI route. Authorization for
    public source-page viewing is a separate future feature.
    """
    if candidate.page_number is None:
        return None
    row = (
        await db.execute(
            text(
                """
                SELECT document_id, page_number, storage_ref, has_table, has_figure
                FROM page_images
                WHERE document_id = :document_id
                  AND page_number = :page_number
                LIMIT 1
                """
            ),
            {
                "document_id": candidate.document_id,
                "page_number": candidate.page_number,
            },
        )
    ).mappings().first()
    if row is None:
        return None
    return PageImageResult(
        chunk_id=candidate.chunk_id,
        document_id=row["document_id"],
        page_number=int(row["page_number"]),
        storage_ref=str(row["storage_ref"]),
        has_table=bool(row["has_table"]),
        has_figure=bool(row["has_figure"]),
    )
