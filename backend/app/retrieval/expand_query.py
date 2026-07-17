"""BC9 query expansion tool for low-confidence retrieval."""

from __future__ import annotations

import json
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.agents.tracing import traced
from app.retrieval.models import QueryExpansionResult
from app.settings import settings


class ExpansionModelClient(Protocol):
    """Minimal JSON-producing model client for query expansion."""

    async def expand(self, query: str, reason: str) -> str:
        """Return strict JSON with ``subqueries`` and optional ``reason``."""


class AnthropicExpansionClient:
    """Small Anthropic Messages API adapter used outside deterministic tests."""

    async def expand(self, query: str, reason: str) -> str:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured for query expansion")

        prompt = (
            "Return only JSON matching this schema: "
            '{"subqueries":["1 to 3 short retrieval queries"],"reason":"short reason"}. '
            "Do not include markdown. Original query: "
            f"{query}\nLow-confidence reason: {reason}"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.agent_model,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()

        content = payload.get("content", [])
        if not content:
            raise RuntimeError("Query expansion response contained no content")
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text", ""))
        return str(first)


@traced(agent_name="retrieval_agent")
async def expand_query(
    query: str,
    reason: str = "",
    model_client: ExpansionModelClient | None = None,
) -> QueryExpansionResult:
    """Expand a query into 1-3 subqueries, falling back safely on malformed JSON."""
    client = model_client or AnthropicExpansionClient()
    try:
        raw = await client.expand(query=query, reason=reason)
    except Exception:
        return _fallback(query)
    return parse_expansion_response(raw, original_query=query)


def parse_expansion_response(raw: str, original_query: str) -> QueryExpansionResult:
    """Parse strict expansion JSON and fall back to the original query on errors."""
    try:
        payload = json.loads(raw)
        parsed = QueryExpansionResult.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError):
        return _fallback(original_query)

    cleaned = [item.strip() for item in parsed.subqueries if item.strip()]
    if not cleaned:
        return _fallback(original_query)
    return QueryExpansionResult(
        subqueries=cleaned[:3],
        reason=parsed.reason,
        fallback_used=False,
    )


def _fallback(query: str) -> QueryExpansionResult:
    return QueryExpansionResult(subqueries=[query], reason="fallback_to_original_query", fallback_used=True)
