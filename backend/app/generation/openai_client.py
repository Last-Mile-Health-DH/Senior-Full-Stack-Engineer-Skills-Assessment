"""Generation through the OpenAI Chat Completions API.

The third provider behind the same `GenerationClient` protocol, so the router can pick it
on price without any call site knowing. Uses `httpx` to match the transport the rest of the
backend already uses and to avoid another dependency in the image's pip layer.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agents.orchestrator import GenerationPayload
from app.chainlit_steps import chainlit_step
from app.generation.result import GenerationResult

logger = logging.getLogger(__name__)

URL = "https://api.openai.com/v1/chat/completions"

# Recognized by the presenter, which renders it as the canonical concise no-answer.
NO_ANSWER_ANSWER = "I could not find that in the uploaded documents."


class OpenAIGenerationClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    @chainlit_step("generation", "llm")
    async def generate(self, payload: GenerationPayload, max_tokens: int) -> GenerationResult:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _system_text(payload)},
                {"role": "user", "content": _user_text(payload)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        try:
            data = await self._post(body)
        except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
            # A provider outage must never surface as a fabricated answer.
            logger.warning("generation.openai_failed error=%s", type(exc).__name__)
            return GenerationResult(NO_ANSWER_ANSWER, self._model, 0, 0, 0.0)

        choices = data.get("choices") or []
        answer = ""
        if choices:
            answer = str((choices[0].get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        return GenerationResult(
            answer=answer or NO_ANSWER_ANSWER,
            model=self._model,
            token_input=int(usage.get("prompt_tokens", 0)),
            token_output=int(usage.get("completion_tokens", 0)),
            cost_usd=0.0,  # computed from MODEL_PRICING_JSON by the caller
        )

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Summarize the conversation so far. "
                        "Keep every fact and number exactly as stated."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        try:
            data = await self._post(body)
        except (httpx.HTTPStatusError, httpx.HTTPError):
            logger.warning("summarize.openai_failed")
            return " ".join(transcript.split()[:max_tokens])
        choices = data.get("choices") or []
        if not choices:
            return " ".join(transcript.split()[:max_tokens])
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            response.raise_for_status()
            return response.json()


def _system_text(payload: GenerationPayload) -> str:
    return "\n\n".join(str(block.get("text", "")) for block in payload.system if block.get("text"))


def _user_text(payload: GenerationPayload) -> str:
    """Flatten the content blocks to text.

    Page images are dropped rather than sent: with the local storage backend their
    reference is a filesystem path, which is neither a URL nor base64 data, so including
    one would fail the whole request for a cosmetic attachment.
    """
    parts: list[str] = []
    for message in payload.messages:
        content = message.get("content")
        if not isinstance(content, list):
            parts.append(str(content))
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
    return "\n\n".join(part for part in parts if part)
