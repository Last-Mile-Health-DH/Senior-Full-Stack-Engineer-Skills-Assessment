"""Generation through the Google Generative Language API (Gemini).

Sits alongside `AnthropicGenerationClient` behind the same `GenerationClient` protocol, so
`/chat` does not know or care which provider answered. The provider is chosen from
`GENERATION_MODEL_PRIMARY` plus whichever key is actually configured.

Raw `httpx` is used rather than a Google SDK for two reasons: it matches the transport the
ingestion agent already uses, and adding a dependency invalidates the backend image's pip
layer, which forces a ~20-minute torch reinstall on every rebuild.

The `[cite:n]` contract, the grounding filters, the presenter, and the caches are all
provider-agnostic — they operate on the answer text, not on the provider.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agents.orchestrator import GenerationPayload
from app.chainlit_steps import chainlit_step
from app.generation.result import GenerationResult

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Recognized by the presenter, which renders it as the canonical concise no-answer.
NO_ANSWER_ANSWER = "I could not find that in the uploaded documents."


class GeminiGenerationClient:
    """Grounded answer generation with a Gemini model."""

    def __init__(self, api_key: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @chainlit_step("generation", "llm")
    async def generate(self, payload: GenerationPayload, max_tokens: int) -> GenerationResult:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": _system_text(payload)}]},
            "contents": _contents(payload),
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                # Deterministic grounded extraction, not creative writing. Unlike the
                # current Claude models, Gemini still accepts temperature.
                "temperature": 0.0,
            },
        }

        try:
            data = await self._post(f"{payload.model}:generateContent", body)
        except (httpx.HTTPStatusError, httpx.HTTPError) as exc:
            # A provider outage must never surface as a fabricated answer.
            logger.warning("generation.gemini_failed error=%s", type(exc).__name__)
            return GenerationResult(NO_ANSWER_ANSWER, payload.model, 0, 0, 0.0)

        answer = _first_text(data)
        usage = data.get("usageMetadata") or {}
        return GenerationResult(
            answer=answer or NO_ANSWER_ANSWER,
            model=payload.model,
            token_input=int(usage.get("promptTokenCount", 0)),
            token_output=int(usage.get("candidatesTokenCount", 0)),
            cost_usd=0.0,  # computed from MODEL_PRICING_JSON by the caller
        )

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        from app.settings import settings

        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
        body = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Summarize the conversation so far. "
                            "Keep every fact and number exactly as stated."
                        )
                    }
                ]
            },
            "contents": [{"role": "user", "parts": [{"text": transcript}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.0},
        }
        try:
            data = await self._post(f"{settings.generation_model_fast}:generateContent", body)
        except (httpx.HTTPStatusError, httpx.HTTPError):
            logger.warning("summarize.gemini_failed")
            return " ".join(transcript.split()[:max_tokens])
        return _first_text(data) or " ".join(transcript.split()[:max_tokens])

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        # Reuse the embedding client's retry: Gemini's free tier rate-limits generation the
        # same way, and a 429 during the gold eval must back off, not fail the answer.
        from app.documents.chunking import _gemini_post_with_retry

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await _gemini_post_with_retry(
                client, f"{BASE_URL}/models/{path}", self._api_key, body
            )


def _system_text(payload: GenerationPayload) -> str:
    """Flatten the system blocks.

    The `cache_control` breakpoint the orchestrator sets is an Anthropic concept and is
    simply dropped here; Gemini caches implicitly, so there is nothing to translate it to.
    """
    return "\n\n".join(str(block.get("text", "")) for block in payload.system if block.get("text"))


def _contents(payload: GenerationPayload) -> list[dict[str, Any]]:
    """Map Messages-style content blocks onto Gemini `parts`.

    An image whose storage reference is a local filesystem path (the default local storage
    backend) is dropped rather than sent: it is neither inline data nor a URL, so including
    it would fail the whole request for a cosmetic attachment.
    """
    contents: list[dict[str, Any]] = []
    for message in payload.messages:
        raw = message.get("content")
        blocks = raw if isinstance(raw, list) else [{"type": "text", "text": str(raw)}]
        parts: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append({"text": str(block.get("text", ""))})
                continue
            if block.get("type") == "image":
                part = _image_part(block)
                if part is not None:
                    parts.append(part)
        if parts:
            contents.append({"role": "user", "parts": parts})
    return contents


def _image_part(block: dict[str, Any]) -> dict[str, Any] | None:
    source = block.get("source") or {}
    data = str(source.get("data", ""))
    if data.startswith("data:image/") and ";base64," in data:
        header, encoded = data.split(";base64,", 1)
        return {"inlineData": {"mimeType": header.removeprefix("data:"), "data": encoded}}
    logger.debug("generation.image_block_dropped reason=unsupported_source")
    return None


def _first_text(data: dict[str, Any]) -> str:
    """Read the answer, tolerating a blocked or empty candidate.

    Two things this must not get wrong:

    - A safety block returns candidates with **no `content` key at all**, so a naive
      `candidates[0]["content"]["parts"]` lookup raises and turns a refusal into a 500.
    - Gemini 3 models return reasoning as parts flagged `"thought": true`, interleaved with
      the answer. Concatenating them would splice the model's private reasoning into the
      user-facing answer — and straight past the presenter into the chat window.
    """
    for candidate in data.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            str(part.get("text", "")) for part in parts if not part.get("thought")
        ).strip()
        if text:
            return text
        if candidate.get("finishReason") in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"}:
            logger.info("generation.gemini_blocked reason=%s", candidate.get("finishReason"))
    return ""
