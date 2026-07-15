"""
client.py — the ONE place you bind this eval to your running backend.

The gold eval needs two things back for each question:
  1. the assistant's answer text
  2. enough lineage to grade grounding: which source documents + pages the answer cited, and the
     text of the chunks it cited (so numeric grounding can check the answer's numbers against them).

Your BC12 /chat pipeline already persists all of this: chat_messages.source_chunk_ids, and
query_audit_log.retrieved_chunk_ids. This adapter calls /chat, then reads that lineage back out of
Postgres (exactly the query_audit_log/agent_trace_log path §11.5 intends the eval to reuse).

INTEGRATOR TODO (the only wiring you must do):
  - Set GOLD_CHAT_URL / GOLD_CHAT_AUTH in your env if your endpoint differs from the defaults.
  - If your /chat response shape differs from the assumed JSON below, adjust `_parse_answer`.
  - Confirm the two SQL reads match your actual column names (they match §6 as written).
Everything else in the package is generic.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

import httpx


@dataclass
class ChatResult:
    answer: str
    cited_doc_ids: list[str] = field(default_factory=list)   # documents.id values the answer cited
    cited_docs: list[str] = field(default_factory=list)       # mapped to corpus manifest ids
    cited_pages: list[int] = field(default_factory=list)
    source_texts: list[str] = field(default_factory=list)     # text of the cited chunks
    query_audit_log_id: str | None = None
    raw: dict = field(default_factory=dict)


class ChatClient:
    def __init__(self, db_pool, http: httpx.AsyncClient | None = None):
        self.db_pool = db_pool
        self.base_url = os.environ.get("GOLD_CHAT_URL", "http://localhost:6100/api/v1/chat")
        self.auth = os.environ.get("GOLD_CHAT_AUTH")  # e.g. "Bearer <token>"; None if chat is open
        self._http = http or httpx.AsyncClient(timeout=120)
        # maps documents.filename -> corpus manifest id, built once from the manifest
        self._filename_to_corpus_id = _load_filename_map()

    async def ask(self, question: str, session_id: str | None = None) -> ChatResult:
        session_id = session_id or str(uuid.uuid4())
        headers = {"Authorization": self.auth} if self.auth else {}
        resp = await self._http.post(
            self.base_url,
            json={"query": question, "session_id": session_id},
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        answer = _parse_answer(body)

        # Read lineage back from Postgres for this session's latest turn.
        lineage = await self._fetch_lineage(session_id)
        cited_docs = [self._filename_to_corpus_id.get(fn, fn) for fn in lineage["filenames"]]
        return ChatResult(
            answer=answer,
            cited_doc_ids=lineage["doc_ids"],
            cited_docs=[d for d in cited_docs if d],
            cited_pages=lineage["pages"],
            source_texts=lineage["texts"],
            query_audit_log_id=lineage["qal_id"],
            raw=body,
        )

    async def _fetch_lineage(self, session_id: str) -> dict:
        async with self.db_pool.acquire() as conn:
            # latest assistant message for this session and its cited chunks
            row = await conn.fetchrow(
                """
                SELECT cm.id, cm.source_chunk_ids, qal.id AS qal_id
                FROM chat_messages cm
                LEFT JOIN query_audit_log qal ON qal.session_id = cm.session_id
                WHERE cm.session_id = $1 AND cm.role = 'assistant'
                ORDER BY cm.created_at DESC
                LIMIT 1
                """,
                uuid.UUID(session_id),
            )
            if not row or not row["source_chunk_ids"]:
                return {"doc_ids": [], "filenames": [], "pages": [], "texts": [], "qal_id": None}

            chunks = await conn.fetch(
                """
                SELECT c.content, c.page_number, d.id AS document_id, d.filename
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = ANY($1::uuid[])
                """,
                row["source_chunk_ids"],
            )
            return {
                "doc_ids": [str(c["document_id"]) for c in chunks],
                "filenames": [c["filename"] for c in chunks],
                "pages": [c["page_number"] for c in chunks if c["page_number"] is not None],
                "texts": [c["content"] for c in chunks],
                "qal_id": str(row["qal_id"]) if row["qal_id"] else None,
            }


def _parse_answer(body: dict) -> str:
    # Assumed shape: {"answer": "...", ...}. Adjust here if your /chat returns something else.
    for key in ("answer", "content", "message", "text"):
        if isinstance(body.get(key), str):
            return body[key]
    return str(body)


def _load_filename_map() -> dict[str, str]:
    """Map documents.filename -> corpus manifest id so grounding compares against manifest ids."""
    import yaml
    from pathlib import Path

    manifest = yaml.safe_load((Path(__file__).resolve().parent / "corpus" / "corpus_manifest.yaml").read_text())
    return {d["filename"]: d["id"] for d in manifest["documents"]}
