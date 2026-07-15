from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import chainlit as cl
import httpx


DEFAULT_BACKEND_URL = "http://localhost:6100"


@dataclass(slots=True)
class BackendChatResponse:
    session_id: str | None
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    # Present when no AI model is configured: the answer was extracted from the documents
    # rather than written. Showing it is what keeps the fallback honest.
    notice: str | None = None


class BackendChatClient:
    def __init__(
        self,
        base_url: str | None = None,
        auth_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip("/")
        self.auth_token = auth_token if auth_token is not None else os.getenv("CHAINLIT_BACKEND_AUTH_TOKEN")
        self.timeout_seconds = timeout_seconds or float(os.getenv("CHAINLIT_BACKEND_TIMEOUT_SECONDS", "30"))

    async def ask(self, message: str, session_id: str | None) -> BackendChatResponse:
        payload: dict[str, str] = {"message": message}
        if session_id:
            payload["session_id"] = session_id

        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/v1/chat", json=payload, headers=headers)

        if response.status_code == 202:
            data = response.json()
            return BackendChatResponse(
                session_id=data.get("session_id") if isinstance(data, dict) else session_id,
                answer="I am still working on your last question. Please try again in a moment.",
                citations=[],
            )

        response.raise_for_status()
        data = response.json()
        status = data.get("model_status") or {}
        return BackendChatResponse(
            session_id=str(data["session_id"]),
            answer=str(data["answer"]),
            citations=list(data.get("citations") or []),
            notice=status.get("notice") if status.get("mode") == "degraded" else None,
        )


DOCUMENTS_URL = os.getenv("DOCUMENTS_URL", "http://localhost:3000/documents")

# User-facing copy: plain language only. People using this want answers from their own
# documents and do not need to know how the system finds them.
WELCOME_MESSAGE = (
    "### Ask your documents\n\n"
    "Ask a question about the documents you have uploaded. Every answer comes from those "
    "documents, and shows you the page each fact came from.\n\n"
    f"No documents yet? Use the **+ Upload PDF** button, or [add one here]({DOCUMENTS_URL})."
)

THINKING_MESSAGE = "_Searching your documents…_"

REFERENCES_HEADING = "Sources"


def render_answer_with_citations(
    answer: str,
    citations: list[dict[str, Any]],
    notice: str | None = None,
) -> str:
    """Render the answer the backend already presented, plus its reference list.

    The backend presenter owns sentence-end superscripts and the reference text, so this
    only mirrors that output. A refusal or no-answer has no citations and must not get an
    empty reference list.

    `notice` is set when no AI model is configured: the answer was extracted from the
    documents rather than written, and the user is told so above the answer.
    """
    body = answer.rstrip()
    if notice:
        body = f"> \u26a0 {notice}\n\n{body}"
    references = [
        _render_reference(citation)
        for citation in citations
        if citation.get("number") is not None
    ]
    if not references:
        return body
    notes = "\n".join(references)
    return f"{body}\n\n**{REFERENCES_HEADING}**\n\n{notes}"


def _render_reference(citation: dict[str, Any]) -> str:
    """Prefer the backend-rendered reference; fall back to chunk metadata only."""
    reference = citation.get("reference")
    if reference:
        return str(reference)
    number = int(citation["number"])
    title = str(citation.get("document_title") or "Uploaded document")
    page = citation.get("page_number")
    section = citation.get("section_path")
    parts = [title]
    if section:
        parts.append(str(section))
    if page is not None:
        parts.append(f"p. {page}")
    return f"{number}. {', '.join(parts)}."


def _chat_client() -> BackendChatClient:
    configured = cl.user_session.get("backend_chat_client")
    if configured is not None:
        return configured
    client = BackendChatClient()
    cl.user_session.set("backend_chat_client", client)
    return client


@cl.set_starters
async def starters() -> list[Any]:
    """Documented Chainlit Starter cards for the empty chat state."""
    return [
        cl.Starter(
            label="What dose is recommended?",
            message="What dose is recommended for a child?",
            icon="/public/upload-icon.svg",
        ),
        cl.Starter(
            label="Summarize my document",
            message="Summarize the main recommendation.",
            icon="/public/upload-icon.svg",
        ),
        cl.Starter(
            label="What about follow-up?",
            message="What does my document say about follow-up?",
            icon="/public/upload-icon.svg",
        ),
    ]


@cl.on_chat_start
async def start_chat() -> None:
    cl.user_session.set("backend_session_id", None)
    await cl.Message(content=WELCOME_MESSAGE).send()


@cl.on_message
async def handle_message(message: cl.Message) -> None:
    user_input = message.content.strip()
    if not user_input:
        await cl.Message(content="Please enter a question.").send()
        return

    # Send a placeholder immediately so the user sees the system working, then replace it
    # in place with the answer, an honest error, or a refusal.
    pending = cl.Message(content=THINKING_MESSAGE)
    await pending.send()

    try:
        response = await _chat_client().ask(
            user_input,
            session_id=cl.user_session.get("backend_session_id"),
        )
    except httpx.HTTPStatusError as exc:
        await _replace(pending, f"Something went wrong with that question (error {exc.response.status_code}). Please try again.")
        return
    except httpx.HTTPError:
        await _replace(
            pending,
            "I could not reach the chat service. Please check that it is running, then try again. "
            "If you just ran the test suite, ask the developer to restore the database tables that "
            "pytest may have dropped (run `alembic upgrade head` and restart the backend).",
        )
        return

    if response.session_id:
        cl.user_session.set("backend_session_id", response.session_id)
    await _replace(
        pending,
        render_answer_with_citations(response.answer, response.citations, response.notice),
    )


async def _replace(pending: Any, content: str) -> None:
    """Swap the loading placeholder for the final content."""
    pending.content = content
    await pending.update()
