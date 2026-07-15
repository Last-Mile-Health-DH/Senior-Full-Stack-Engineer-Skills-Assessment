"""Gold-standard chat adapter bound to the repo's `/chat` and SQLAlchemy stack."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session


@dataclass(slots=True)
class ChatResult:
    answer: str
    cited_doc_ids: list[str] = field(default_factory=list)
    cited_docs: list[str] = field(default_factory=list)
    cited_pages: list[int] = field(default_factory=list)
    source_texts: list[str] = field(default_factory=list)
    query_audit_log_id: str | None = None
    raw: dict = field(default_factory=dict)


class ChatClient:
    """Thin adapter used by the gold eval runner.

    Tests can inject an `httpx.AsyncClient` with an ASGI transport or pass a
    fake object implementing `ask`.
    """

    def __init__(self, db: AsyncSession | None = None, http: httpx.AsyncClient | None = None) -> None:
        self.db = db
        self.base_url = os.environ.get("GOLD_CHAT_URL", "http://localhost:6100/api/v1/chat")
        self.auth = os.environ.get("GOLD_CHAT_AUTH")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=120.0)
        self._filename_to_corpus_id = _load_filename_map()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def ask(self, question: str, session_id: str | None = None) -> ChatResult:
        session_id = session_id or str(uuid4())
        headers = {"Authorization": self.auth} if self.auth else {}
        response = await self._http.post(
            self.base_url,
            json={"message": question, "session_id": session_id},
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        if self.db is None:
            async with async_session() as db:
                lineage = await self._fetch_lineage(db, UUID(session_id), body)
        else:
            lineage = await self._fetch_lineage(self.db, UUID(session_id), body)
        # Grounding must be measured against what the answer actually CITED, not everything
        # retrieval happened to fetch. A refusal retrieves chunks (top-k always returns
        # something) but cites none; scoring it on retrieved chunks would wrongly read as
        # "cited a document" and fail every correct decline. The `citations` array is the
        # cited set; `source_texts` stays the retrieved text (used only for the numeric
        # fabrication check, where more context is a safe over-approximation).
        citations = body.get("citations") or []
        cited_filenames = [str(c.get("document_filename")) for c in citations if c.get("document_filename")]
        cited_docs = [self._filename_to_corpus_id.get(fn, fn) for fn in cited_filenames]
        cited_pages = [int(c["page_number"]) for c in citations if c.get("page_number") is not None]
        return ChatResult(
            answer=_parse_answer(body),
            cited_doc_ids=[str(c.get("document_id")) for c in citations if c.get("document_id")],
            cited_docs=[doc for doc in cited_docs if doc],
            cited_pages=cited_pages,
            source_texts=lineage["texts"],
            query_audit_log_id=lineage["qal_id"],
            raw=body,
        )

    async def _fetch_lineage(self, db: AsyncSession, session_id: UUID, body: dict) -> dict[str, list[str] | list[int] | str | None]:
        audit_id = body.get("query_audit_log_id")
        source_chunk_ids = body.get("source_chunk_ids") or []
        if not source_chunk_ids and audit_id:
            row = (
                await db.execute(
                    text("SELECT retrieved_chunk_ids FROM query_audit_log WHERE id = :id"),
                    {"id": UUID(str(audit_id))},
                )
            ).mappings().first()
            source_chunk_ids = list(row["retrieved_chunk_ids"] or []) if row else []

        if not source_chunk_ids:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT source_chunk_ids
                        FROM chat_messages
                        WHERE session_id = :session_id
                          AND role = 'assistant'
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"session_id": session_id},
                )
            ).mappings().first()
            source_chunk_ids = list(row["source_chunk_ids"] or []) if row else []

        if not source_chunk_ids:
            return {"doc_ids": [], "filenames": [], "pages": [], "texts": [], "qal_id": str(audit_id) if audit_id else None}

        chunks = (
            await db.execute(
                text(
                    """
                    SELECT c.content, c.page_number, d.id AS document_id, d.filename
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.id = ANY(CAST(:chunk_ids AS uuid[]))
                    """
                ),
                {"chunk_ids": [UUID(str(chunk_id)) for chunk_id in source_chunk_ids]},
            )
        ).mappings().all()
        return {
            "doc_ids": [str(chunk["document_id"]) for chunk in chunks],
            "filenames": [str(chunk["filename"]) for chunk in chunks],
            "pages": [int(chunk["page_number"]) for chunk in chunks if chunk["page_number"] is not None],
            "texts": [str(chunk["content"]) for chunk in chunks],
            "qal_id": str(audit_id) if audit_id else None,
        }


def _parse_answer(body: dict) -> str:
    for key in ("answer", "content", "message", "text"):
        if isinstance(body.get(key), str):
            return str(body[key])
    return str(body)


def _load_filename_map() -> dict[str, str]:
    manifest_path = Path(__file__).resolve().parent / "corpus" / "corpus_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    return {doc["filename"]: doc["id"] for doc in manifest["documents"]}
