"""Provider-agnostic model routing.

One place decides, for each agent-scoped task, which provider and model to use given
whichever API keys happen to be configured. Adding a provider means adding a row to
`CATALOG` and a client behind the existing protocol — no call site changes.

Two rules:

1. **Cheapest model that is suited to the task wins.** Tasks are split by what they
   actually need. Summarizing a transcript, expanding a query, planning ingestion, and
   grading a rubric are mechanical: the cheapest small model is the right tool and paying
   Opus rates for them is waste. Answering a clinical question from source documents is
   the one task where answer quality is the product, so it gets the best-value capable
   model rather than the outright cheapest.

2. **Missing or bad keys degrade, they never crash — and the user is told.** The local
   fallbacks cannot interpret a question; they can only extract sentences that share words
   with it. That is a legitimate offline mode, but presenting its output as if a model had
   reasoned over the documents would be dishonest, so `/chat` returns a `model_status`
   the UI renders as a plain-language notice.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from app.settings import settings

logger = logging.getLogger(__name__)


class Task(str, Enum):
    """What the model is being asked to do."""

    # Answering the user's question from their documents. Quality is the product.
    CHAT = "chat"
    # Mechanical work: conversation summaries, query expansion, ingestion planning,
    # rubric grading. The cheapest small model is the correct tool here.
    FAST = "fast"


@dataclass(frozen=True, slots=True)
class ModelOption:
    provider: str
    key_name: str
    model: str
    input_per_mtok: float
    output_per_mtok: float

    @property
    def blended_cost(self) -> float:
        """Rank by a cost that reflects real traffic.

        Answers are short and prompts are long (a chat turn sends several document chunks),
        so ranking on output price alone would pick the wrong model. Input is weighted
        heavily to match that shape.
        """
        return (self.input_per_mtok * 4.0) + self.output_per_mtok


# Prices are USD per million tokens and are a routing signal, not a billing source of
# truth. Verify them at deploy time — `MODEL_PRICING_JSON` is what the audit log costs with.
CATALOG: dict[Task, list[ModelOption]] = {
    Task.CHAT: [
        ModelOption("gemini", "GEMINI_API_KEY", "gemini-3.1-flash-lite", 0.10, 0.40),
        ModelOption("openai", "OPENAI_API_KEY", "gpt-4.1-mini", 0.40, 1.60),
        ModelOption("anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-5", 3.00, 15.00),
    ],
    Task.FAST: [
        ModelOption("gemini", "GEMINI_API_KEY", "gemini-3.1-flash-lite", 0.10, 0.40),
        ModelOption("openai", "OPENAI_API_KEY", "gpt-4o-mini", 0.15, 0.60),
        ModelOption("anthropic", "ANTHROPIC_API_KEY", "claude-haiku-4-5", 1.00, 5.00),
    ],
}

EMBEDDING_CATALOG: list[ModelOption] = [
    # Dimension must equal EMBEDDING_DIM; the pgvector column is fixed-width. Gemini's
    # model is natively 3072-dim but supports Matryoshka truncation, so it can be asked for
    # exactly 1536 and fit the existing column without a migration.
    ModelOption("gemini", "GEMINI_API_KEY", "gemini-embedding-001", 0.15, 0.0),
    ModelOption("openai", "OPENAI_API_KEY", "text-embedding-3-small", 0.02, 0.0),
    ModelOption("voyage", "VOYAGE_API_KEY", "voyage-3", 0.06, 0.0),
]

_PLACEHOLDER_MARKERS = ("your-", "api-key-here", "changeme", "replace-me", "placeholder")


def is_real_key(value: str | None) -> bool:
    """Reject the placeholders that ship in `.env.example`.

    A placeholder is truthy. Without this check it selects a hosted client that then fails
    on every single call, which reads as a broken system rather than an unconfigured one.
    """
    candidate = (value or "").strip()
    if len(candidate) < 16:
        return False
    lowered = candidate.lower()
    return not any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def configured_providers() -> set[str]:
    """Providers whose key is present and is not a placeholder."""
    found: set[str] = set()
    for options in (*CATALOG.values(), EMBEDDING_CATALOG):
        for option in options:
            if is_real_key(os.getenv(option.key_name, "")):
                found.add(option.provider)
    return found


def resolve(task: Task) -> ModelOption | None:
    """Pick the cheapest configured model for a task, or None if nothing is configured.

    An explicit model pin wins over auto-routing: an operator who sets
    GENERATION_MODEL_PRIMARY has made a deliberate choice, and silently overriding it would
    be surprising.
    """
    if settings.model_routing.lower() == "manual":
        pinned = settings.generation_model_primary if task is Task.CHAT else settings.generation_model_fast
        for option in CATALOG[task]:
            if option.model == pinned and is_real_key(os.getenv(option.key_name, "")):
                return option
        # A pinned model whose key is absent is a misconfiguration, not a routing decision.
        logger.warning("model_router.pinned_model_unavailable task=%s model=%s", task.value, pinned)

    available = [
        option for option in CATALOG[task] if is_real_key(os.getenv(option.key_name, ""))
    ]
    if not available:
        return None
    return min(available, key=lambda option: option.blended_cost)


def resolve_embedding() -> ModelOption | None:
    """Pick the cheapest configured embedding model."""
    available = [
        option for option in EMBEDDING_CATALOG if is_real_key(os.getenv(option.key_name, ""))
    ]
    if not available:
        return None
    return min(available, key=lambda option: option.blended_cost)


@dataclass(frozen=True, slots=True)
class ModelStatus:
    """What the user is told about which brain answered them."""

    mode: str  # "full" | "degraded"
    provider: str | None
    model: str | None
    notice: str | None


# Plain language on purpose: this is shown in the chat window to someone who does not know
# what an embedding or a language model is, only that the answer might be worse than usual.
NO_MODEL_NOTICE = (
    "Degraded mode: no AI model is configured, so this answer was assembled by pulling "
    "sentences straight out of your documents instead of being written for you, and may be "
    "inaccurate or miss the point of your question. Ask the developer/administrator to set up "
    "an AI model API key for accurate answers."
)
NO_SEARCH_NOTICE = (
    "Degraded mode: document search is running without an embedding model, so it can only "
    "match close wording and may miss a relevant passage. Answers may be less accurate. Ask "
    "the developer/administrator to set up an embedding API key for accurate search."
)
BOTH_NOTICE = (
    "Degraded mode: no AI model or search model is configured. This answer was assembled by "
    "pulling sentences straight out of your documents, search is limited to close wording "
    "matches, and results may be inaccurate. Ask the developer/administrator to set up the "
    "AI model API key(s) for accurate answers."
)


def current_status() -> ModelStatus:
    """Describe the brain actually in use, for the chat response."""
    chat = resolve(Task.CHAT)
    embedding = resolve_embedding()

    if chat is None and embedding is None:
        return ModelStatus("degraded", None, None, BOTH_NOTICE)
    if chat is None:
        return ModelStatus("degraded", None, None, NO_MODEL_NOTICE)
    if embedding is None:
        return ModelStatus("degraded", chat.provider, chat.model, NO_SEARCH_NOTICE)
    return ModelStatus("full", chat.provider, chat.model, None)
