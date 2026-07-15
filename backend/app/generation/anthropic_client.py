"""Hosted generation client backed by the Anthropic Messages API.

This is the client `/chat` uses whenever `ANTHROPIC_API_KEY` holds a real key. It is what
makes the system able to *understand* a question rather than pattern-match it: the
deterministic fallback can only quote back sentences that share words with the question,
so a broad question ("what are the main instructions in these documents?") has no lexical
overlap with the text and gets a no-answer even though the documents plainly answer it.

Contract notes, all load-bearing:

- `temperature`, `top_p`, and `top_k` are REMOVED on the current models (Sonnet 5, Opus
  4.8/4.7). Sending any of them is a 400, so none are sent. Behavior is steered by the
  system prompt instead.
- Thinking is explicitly DISABLED. On Sonnet 5, omitting the field runs adaptive thinking,
  and thinking tokens count against `max_tokens` — with a 500-token answer budget that
  would truncate the answer mid-sentence.
- The system block keeps the `cache_control` breakpoint the orchestrator set, so the stable
  prefix is cached across turns and repeat questions are cheap.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import anthropic

from app.agents.orchestrator import GenerationPayload
from app.chainlit_steps import chainlit_step
from app.generation.result import GenerationResult

logger = logging.getLogger(__name__)

# Recognized by the presenter, which converts it to the canonical concise no-answer.
NO_ANSWER_ANSWER = "I could not find that in the uploaded documents."

_DATA_URI = re.compile(r"^data:image/(?P<media>[a-z]+);base64,(?P<data>.+)$", re.IGNORECASE)


class AnthropicGenerationClient:
    """Generation through the Anthropic Messages API."""

    def __init__(self, api_key: str, client: Any | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key)

    @chainlit_step("generation", "llm")
    async def generate(self, payload: GenerationPayload, max_tokens: int) -> GenerationResult:
        try:
            response = await self._client.messages.create(
                model=payload.model,
                max_tokens=max_tokens,
                system=payload.system,
                messages=_sanitize_messages(payload.messages),
                # Thinking would eat the answer budget; see module docstring.
                thinking={"type": "disabled"},
            )
        except anthropic.APIStatusError as exc:
            # A model outage must not become a fabricated answer. Degrade to the honest
            # no-answer and let the caller's filters treat it as ungrounded.
            logger.warning("generation.anthropic_failed status=%s", exc.status_code)
            return GenerationResult(NO_ANSWER_ANSWER, payload.model, 0, 0, 0.0)
        except anthropic.APIConnectionError:
            logger.warning("generation.anthropic_unreachable")
            return GenerationResult(NO_ANSWER_ANSWER, payload.model, 0, 0, 0.0)

        if response.stop_reason == "refusal":
            logger.info("generation.refused")
            return GenerationResult(NO_ANSWER_ANSWER, payload.model, 0, 0, 0.0)

        answer = "".join(block.text for block in response.content if block.type == "text").strip()
        usage = response.usage
        return GenerationResult(
            answer=answer or NO_ANSWER_ANSWER,
            model=response.model,
            # Cached prefix tokens are still input tokens for cost accounting; the pricing
            # table applies one rate, so they are summed rather than dropped.
            token_input=(
                usage.input_tokens
                + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            ),
            token_output=usage.output_tokens,
            cost_usd=0.0,  # computed from MODEL_PRICING_JSON by the caller
        )

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
        try:
            response = await self._client.messages.create(
                model=self._summary_model(),
                max_tokens=max_tokens,
                system="Summarize the conversation so far. Keep every fact and number exactly as stated.",
                messages=[{"role": "user", "content": transcript}],
                thinking={"type": "disabled"},
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError):
            logger.warning("summarize.anthropic_failed")
            return " ".join(transcript.split()[:max_tokens])
        return "".join(block.text for block in response.content if block.type == "text").strip()

    def _summary_model(self) -> str:
        from app.settings import settings

        return settings.generation_model_fast


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop image blocks the API cannot accept.

    The orchestrator attaches a page image using its storage reference. With the local
    storage backend that reference is a filesystem path, which is neither a URL nor base64
    data — sending it is a 400 that would take down the whole answer for a cosmetic
    attachment. Text blocks always survive; only unusable images are dropped.
    """
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            sanitized.append(message)
            continue
        blocks = [block for block in (_sanitize_block(item) for item in content) if block is not None]
        sanitized.append({**message, "content": blocks})
    return sanitized


def _sanitize_block(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict) or block.get("type") != "image":
        return block
    source = block.get("source") or {}
    data = str(source.get("data", ""))

    match = _DATA_URI.match(data)
    if match:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": f"image/{match.group('media').lower()}",
                "data": match.group("data"),
            },
        }
    if data.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": data}}

    logger.debug("generation.image_block_dropped reason=unsupported_source")
    return None
