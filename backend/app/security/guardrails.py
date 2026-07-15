"""BC14 input validation, tool-result sanitization, and output filtering."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.chainlit_steps import chainlit_step
from app.core.errors import ValidationError
from app.retrieval.models import RetrievalCandidate
from app.security.numeric_grounding import numeric_claims_supported
from app.settings import settings

logger = logging.getLogger(__name__)

SAFE_FALLBACK_MESSAGE = (
    "I could not confirm that answer against your documents, so I would rather not give it. "
    "Try rephrasing your question."
)

LEAK_CANARIES = (
    "stable_system_prefix",
    "treat retrieved content as reference material",
    "tool_choice",
    "retrieval_agent_confidence_threshold",
    "ignore previous instructions",
)

PII_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"),
)

SANITIZE_PATTERNS = (
    re.compile(r"</context>", re.IGNORECASE),
    re.compile(r"<context\b", re.IGNORECASE),
    re.compile(r"</?system\b", re.IGNORECASE),
    re.compile(r"</?assistant\b", re.IGNORECASE),
    re.compile(r"\bSystem\s*:", re.IGNORECASE),
    re.compile(r"\bAssistant\s*:", re.IGNORECASE),
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+previous\s+instructions", re.IGNORECASE),
)


@dataclass(slots=True)
class OutputFilterResult:
    answer: str
    status: str
    reason: str | None
    grounded: bool


class InputValidationMiddleware:
    """Reject oversized or malformed request bodies before endpoint logic."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        body = b""
        more_body = True
        messages: list[dict[str, Any]] = []
        while more_body:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                body += message.get("body", b"")
                more_body = bool(message.get("more_body", False))
            else:
                more_body = False

        if len(body) > settings.request_body_size_limit_bytes:
            response = _validation_response("Request body exceeds the configured hard cap.")
            await response(scope, receive, send)
            return
        headers = {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope["headers"]}
        content_type = headers.get("content-type", "")
        if b"\x00" in body and not content_type.startswith("multipart/"):
            response = _validation_response("Request body contains embedded null bytes.")
            await response(scope, receive, send)
            return

        replay = _replay_receive(messages)
        await self.app(scope, replay, send)


async def validate_chat_message_for_audit(message: str) -> None:
    if len(message) > 4000:
        raise ValidationError("Chat message must be 4000 characters or fewer.")
    if "\x00" in message:
        raise ValidationError("Chat message contains embedded null bytes.")


def sanitize_tool_result(text: str) -> str:
    """Neutralize role/instruction markers while preserving ordinary data."""
    sanitized = text
    replacements = {
        "</context>": "&lt;/context&gt;",
        "<context": "&lt;context",
    }
    for literal, replacement in replacements.items():
        sanitized = re.sub(re.escape(literal), replacement, sanitized, flags=re.IGNORECASE)
    for pattern in SANITIZE_PATTERNS[2:]:
        sanitized = pattern.sub("[neutralized]", sanitized)
    return sanitized


@chainlit_step("output filter", "tool")
async def filter_output(answer: str, cited_chunks: list[RetrievalCandidate]) -> OutputFilterResult:
    """Run deterministic output checks and return either answer or safe fallback."""
    reason = _first_filter_failure(answer, cited_chunks)
    if reason is not None:
        return OutputFilterResult(
            answer=SAFE_FALLBACK_MESSAGE,
            status="filtered",
            reason=reason,
            grounded=False,
        )
    return OutputFilterResult(answer=answer, status="passed", reason=None, grounded=True)


def deterministic_grounding_check(
    answer: str,
    source_texts: list[str],
) -> tuple[bool, dict[str, Any]]:
    """Run the shared lexical + numeric grounding check over plain source text."""
    has_answer_text = bool(answer.strip())
    detail: dict[str, Any] = {
        "lexical_grounding_passed": False,
        "numeric_grounding_passed": True,
        "unsupported_numeric_claims": [],
    }
    if not has_answer_text:
        detail["reason"] = "length_fail"
        return False, detail

    lexical_passed = lexical_grounding_passes(answer, source_texts)
    detail["lexical_grounding_passed"] = lexical_passed
    if not lexical_passed:
        detail["reason"] = "grounding_fail"
        return False, detail

    if settings.grounding_numeric_check_enabled:
        numeric_supported, unsupported = numeric_claims_supported(
            answer,
            source_texts,
            tol=0.0,
        )
        detail["numeric_grounding_passed"] = numeric_supported
        detail["unsupported_numeric_claims"] = unsupported
        if not numeric_supported:
            detail["reason"] = "numeric_grounding_fail"
            return False, detail

    detail["reason"] = None
    return True, detail


def lexical_grounding_passes(answer: str, source_texts: list[str]) -> bool:
    """Return whether answer text has enough lexical overlap with cited source text."""
    if not source_texts:
        return False
    source_text = "\n".join(source_texts)
    sentences = [item.strip() for item in re.split(r"[.!?]\s+", answer) if item.strip()]
    if not sentences:
        return False
    return max(_score_sentence(sentence, source_text) for sentence in sentences) >= 0.15


def _first_filter_failure(answer: str, cited_chunks: list[RetrievalCandidate]) -> str | None:
    source_texts = [chunk.content for chunk in cited_chunks]
    grounded, detail = deterministic_grounding_check(answer, source_texts)
    if not grounded:
        return str(detail["reason"])
    lowered = answer.lower()
    if any(canary in lowered for canary in LEAK_CANARIES):
        return "leak_check_fail"
    if _introduced_pii(answer, cited_chunks):
        return "pii_check_fail"
    return None


def _grounding_passes(answer: str, cited_chunks: list[RetrievalCandidate]) -> bool:
    return lexical_grounding_passes(answer, [chunk.content for chunk in cited_chunks])


def _introduced_pii(answer: str, cited_chunks: list[RetrievalCandidate]) -> bool:
    source_text = "\n".join(chunk.content for chunk in cited_chunks)
    matches: list[str] = []
    for pattern in PII_PATTERNS:
        matches.extend(match.group(0) for match in pattern.finditer(answer))
    return any(match not in source_text for match in matches)


def _score_sentence(sentence: str, source_text: str) -> float:
    sentence_terms = set(re.findall(r"[A-Za-z0-9]+", sentence.lower()))
    source_terms = set(re.findall(r"[A-Za-z0-9]+", source_text.lower()))
    if not sentence_terms:
        return 0.0
    return len(sentence_terms & source_terms) / len(sentence_terms)


def _replay_receive(messages: list[dict[str, Any]]) -> Receive:
    pending = list(messages)

    async def receive() -> dict[str, Any]:
        if pending:
            return pending.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    return receive


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Turn an unhandled exception into a normal JSON 500 response.

    Starlette's ServerErrorMiddleware sits *outside* CORSMiddleware, so an exception that
    escapes the route is rendered into a bare 500 that never passes back through CORS. The
    browser then reports "No 'Access-Control-Allow-Origin' header", which sends whoever is
    debugging it hunting a CORS misconfiguration that does not exist. Catching the
    exception here — inside CORS — means the error response carries the CORS headers and
    the browser shows the real failure.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        try:
            return await call_next(request)
        except Exception:
            logger.exception("unhandled_error path=%s method=%s", request.url.path, request.method)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "The server could not complete that request.",
                        "details": {},
                    }
                },
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def _validation_response(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": message, "details": {}}},
        headers={
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )
