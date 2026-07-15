"""Injectable generation client used by `/chat` and deterministic tests."""

from __future__ import annotations

import logging
import os
import re

from app.agents.orchestrator import GenerationPayload
from app.chainlit_steps import chainlit_step
from app.core.model_router import ModelOption, Task, resolve
from app.generation.result import GenerationClient, GenerationResult
from app.settings import settings

logger = logging.getLogger(__name__)

# Re-exported so existing imports of GenerationResult/GenerationClient keep working.
__all__ = [
    "DeterministicGenerationClient",
    "GenerationClient",
    "GenerationResult",
    "Task",
    "get_generation_client",
    "routed_model",
]

# The presenter recognizes this wording as a no-answer and returns the canonical
# concise message, so the deterministic client never invents unsupported content.
NO_ANSWER_ANSWER = "I could not find that in the uploaded documents."

MAX_CITED_BLOCKS = 3
MAX_SENTENCE_WORDS = 45

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from",
        "how", "in", "is", "it", "of", "on", "or", "that", "the", "to", "what", "when",
        "which", "who", "why", "with",
    }
)


def generation_key_name(model: str) -> str:
    """Which provider key a given generation model needs."""
    lowered = model.lower()
    if lowered.startswith("gemini"):
        return "GEMINI_API_KEY"
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return "OPENAI_API_KEY"
    return "ANTHROPIC_API_KEY"


def build_client(option: ModelOption) -> GenerationClient:
    """Construct the client for a routed provider."""
    api_key = os.getenv(option.key_name, "")
    if option.provider == "gemini":
        from app.generation.gemini_client import GeminiGenerationClient

        return GeminiGenerationClient(api_key=api_key)
    if option.provider == "openai":
        from app.generation.openai_client import OpenAIGenerationClient

        return OpenAIGenerationClient(api_key=api_key, model=option.model)

    from app.generation.anthropic_client import AnthropicGenerationClient

    return AnthropicGenerationClient(api_key=api_key)


def get_generation_client(task: Task = Task.CHAT) -> GenerationClient:
    """Route to the cheapest configured provider for the task; degrade if there is none.

    The deterministic client cannot interpret a question — it can only extract sentences
    that share words with it. That is a legitimate offline mode, but it is NOT the product,
    which is why `/chat` returns a `model_status` telling the user plainly when they are on
    it rather than letting them judge the system on a path they did not know they were on.
    """
    option = resolve(task)
    if option is None:
        logger.warning(
            "generation.no_provider_configured task=%s fallback=deterministic "
            "(answers are extracted, not generated)",
            task.value,
        )
        return DeterministicGenerationClient()

    logger.info(
        "generation.routed task=%s provider=%s model=%s",
        task.value,
        option.provider,
        option.model,
    )
    return build_client(option)


def routed_model(task: Task = Task.CHAT) -> str:
    """The model name the router picked, for payload assembly and cost accounting."""
    option = resolve(task)
    if option is not None:
        return option.model
    return settings.generation_model_primary


class DeterministicGenerationClient:
    """Local deterministic fallback that never calls a hosted LLM.

    It obeys the same citation contract as a hosted model: it quotes the
    context sentences that best match the question and marks each one with the
    `[cite:n]` id of the block it came from. It never opens with a document
    name and never emits a number the context does not contain.
    """

    @chainlit_step("generation", "llm")
    async def generate(self, payload: GenerationPayload, max_tokens: int) -> GenerationResult:
        context_text = _payload_text(payload)
        answer = _compose_grounded_answer(payload)
        return GenerationResult(
            answer=answer,
            model=payload.model,
            token_input=_count_tokens(context_text),
            token_output=min(_count_tokens(answer), max_tokens),
            cost_usd=0.0,
        )

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        text = " ".join(item["content"] for item in messages)
        return " ".join(text.split()[:max_tokens])


def _compose_grounded_answer(payload: GenerationPayload) -> str:
    """Quote the best-matching context sentence per block, cited by block id."""
    if not payload.source_chunks:
        return NO_ANSWER_ANSWER

    query_terms = _terms(_query_text(payload))
    sentences: list[str] = []
    for block_id, chunk in enumerate(payload.source_chunks[:MAX_CITED_BLOCKS], start=1):
        sentence = _best_sentence(chunk.content, query_terms)
        if sentence is None:
            continue
        sentences.append(f"{sentence}[cite:{block_id}]")
    if not sentences:
        return NO_ANSWER_ANSWER
    return " ".join(sentences)


def _best_sentence(content: str, query_terms: set[str]) -> str | None:
    """Pick the context sentence with the most query-term overlap.

    Returns None when no sentence speaks to the question at all. Without this, retrieval's
    nearest-neighbour result is always quoted back, so an off-corpus question ("snake bite")
    gets a confident, correctly-cited answer about something else entirely. Lexical
    grounding cannot catch that: the sentence really is verbatim from a source.
    """
    candidates = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", content) if part.strip()]
    if not candidates or not query_terms:
        return None

    # One shared generic word is not relevance. "What treats a snake bite?" shares
    # "treat" with a malaria chunk, which is enough to quote it back with a citation.
    # A question with several content words must match on more than one of them.
    minimum_overlap = 2 if len(query_terms) >= 3 else 1
    scored = max(candidates, key=lambda sentence: len(_terms(sentence) & query_terms))
    if len(_terms(scored) & query_terms) < minimum_overlap:
        return None
    trimmed = " ".join(scored.split()[:MAX_SENTENCE_WORDS])
    if not trimmed:
        return None
    if trimmed[0].islower():
        trimmed = trimmed[0].upper() + trimmed[1:]
    if trimmed[-1] not in ".!?":
        trimmed = f"{trimmed}."
    return trimmed


def _query_text(payload: GenerationPayload) -> str:
    """The question is appended last to the user content blocks."""
    for message in reversed(payload.messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))
    return ""


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.lower()) if term not in _STOPWORDS}


def _payload_text(payload: GenerationPayload) -> str:
    parts: list[str] = []
    for block in payload.system:
        parts.append(str(block.get("text", "")))
    for message in payload.messages:
        content = message.get("content", [])
        if isinstance(content, list):
            parts.extend(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return "\n".join(parts)


def _count_tokens(text: str) -> int:
    return len(text.split())
