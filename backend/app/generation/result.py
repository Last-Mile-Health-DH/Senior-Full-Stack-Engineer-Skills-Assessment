"""Shared generation contract.

Lives apart from the clients so the deterministic client, the hosted Anthropic client, and
the factory that chooses between them can all import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agents.orchestrator import GenerationPayload


@dataclass(slots=True)
class GenerationResult:
    answer: str
    model: str
    token_input: int
    token_output: int
    cost_usd: float


class GenerationClient(Protocol):
    async def generate(self, payload: GenerationPayload, max_tokens: int) -> GenerationResult:
        ...

    async def summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        ...
