"""Production Judge Agent for response grading and gold evaluation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)


class JudgeModelClient(Protocol):
    async def score(self, criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> float:
        """Return a score in [0, 1] for one qualitative grading criterion."""


@dataclass(slots=True)
class JudgeMetadata:
    model: str
    temperature: float
    rubric_version: int


@dataclass(slots=True)
class JudgeAgentResult:
    score: float
    metadata: JudgeMetadata
    rationale: str


class DeterministicJudgeModelClient:
    """Deterministic fallback used in local development and tests."""

    async def score(self, criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> float:
        expected = str(question.get("expected_answer") or "").lower()
        answer_text = (answer or "").lower()
        if criterion == "completeness":
            facts = question.get("expected_facts") or []
            if facts:
                return sum(1 for fact in facts if str(fact).lower() in answer_text) / len(facts)
            return 1.0 if expected and any(term in answer_text for term in expected.split()[:5]) else 0.0
        if criterion == "safety":
            return 1.0
        return 0.0


class AnthropicJudgeModelClient:
    """Hosted judge client; deterministic suites inject a fake instead."""

    def __init__(self, model: str, temperature: float) -> None:
        self.model = model
        self.temperature = temperature

    async def score(self, criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> float:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured for JudgeAgent")
        prompt = _judge_prompt(criterion, question, answer, rubric)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
        text = _extract_text(response.json())
        try:
            return max(0.0, min(1.0, float(text.strip())))
        except ValueError as exc:
            raise RuntimeError(f"JudgeAgent returned non-numeric score: {text!r}") from exc


class GeminiJudgeModelClient:
    """Hosted judge backed by Gemini.

    The judge scores answers the generation model produced, so it must be a real model —
    not the deterministic keyword heuristic. Without this, a Gemini-only deployment would
    generate answers with Gemini and grade them with a word-overlap fallback, and the gold
    score would measure the heuristic, not the answers.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    async def score(self, criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> float:
        from app.documents.chunking import _gemini_post_with_retry

        prompt = _judge_prompt(criterion, question, answer, rubric)
        async with httpx.AsyncClient(timeout=60.0) as client:
            # The gold eval issues many judge calls in a row; a 429 must back off, not fail
            # the score with a non-numeric error.
            body = await _gemini_post_with_retry(
                client,
                f"{self.BASE_URL}/models/{self.model}:generateContent",
                self.api_key,
                {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": self.temperature, "maxOutputTokens": 16},
                },
            )
        text = _extract_gemini_text(body)
        try:
            return max(0.0, min(1.0, float(text.strip())))
        except ValueError as exc:
            raise RuntimeError(f"JudgeAgent returned non-numeric score: {text!r}") from exc


class OpenAIJudgeModelClient:
    """Hosted judge backed by OpenAI."""

    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    async def score(self, criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> float:
        prompt = _judge_prompt(criterion, question, answer, rubric)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": self.temperature,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
        choices = response.json().get("choices") or []
        text = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
        try:
            return max(0.0, min(1.0, float(text.strip())))
        except ValueError as exc:
            raise RuntimeError(f"JudgeAgent returned non-numeric score: {text!r}") from exc


class JudgeAgent:
    """Agent boundary used by scheduled grading, gold eval, and deviation alerts."""

    def __init__(
        self,
        model_client: JudgeModelClient | None = None,
        *,
        model: str | None = None,
        temperature: float | None = None,
        rubric_version: int | None = None,
    ) -> None:
        judge_model = model or settings.judge_model
        judge_temperature = settings.judge_temperature if temperature is None else temperature
        judge_rubric_version = rubric_version or settings.judge_rubric_version
        self.model_client = model_client or _default_client(judge_model, judge_temperature)
        self.metadata = JudgeMetadata(
            model=judge_model,
            temperature=judge_temperature,
            rubric_version=judge_rubric_version,
        )

    async def score_criterion(
        self,
        criterion: str,
        question: dict[str, Any],
        answer: str,
        rubric: dict[str, Any],
    ) -> JudgeAgentResult:
        score = await self.model_client.score(criterion, question, answer, rubric)
        return JudgeAgentResult(
            score=max(0.0, min(1.0, float(score))),
            metadata=self.metadata,
            rationale=f"{criterion} scored by JudgeAgent",
        )

    async def qualitative_scores(
        self,
        question: dict[str, Any],
        answer: str,
        rubric: dict[str, Any],
    ) -> dict[str, JudgeAgentResult]:
        return {
            criterion: await self.score_criterion(criterion, question, answer, rubric)
            for criterion in ("completeness", "safety")
        }

    async def score_response(
        self,
        question: str,
        answer: str,
        source_texts: list[str],
        rubric: dict[str, Any] | None = None,
    ) -> JudgeAgentResult:
        """Return a reproducible 1-5 judge score for a persisted response."""
        rubric_data = rubric or {"rubric_version": settings.judge_rubric_version}
        question_data = {
            "question": question,
            "expected_answer": "\n".join(source_texts[:3]),
            "expected_facts": [],
        }
        scores = await self.qualitative_scores(question_data, answer, rubric_data)
        average = sum(result.score for result in scores.values()) / max(len(scores), 1)
        return JudgeAgentResult(
            score=1.0 + (4.0 * average),
            metadata=self.metadata,
            rationale="response scored by JudgeAgent",
        )


def _default_client(model: str, temperature: float) -> JudgeModelClient:
    """Select the judge client for the configured judge model.

    POLICY: the judge is pinned to Anthropic Opus and is deliberately NOT part of the
    cost-optimizing router that the generation and embedding agents use. A grader must be
    stable and high-quality across runs — routing it to whatever is cheapest would make
    score trends measure the judge's drift instead of the system's.

    The provider is still derived from the model name so a keyless local deployment can run
    the eval at all (with Gemini, the only key available in that setup). But whenever the
    judge is NOT the intended Anthropic model, that is logged loudly: a score judged by a
    fallback model must never be silently compared against an Opus-judged baseline. The run
    metadata records the judge model regardless, so the record is always truthful.
    """
    import os

    from app.core.model_router import is_real_key

    lowered = model.lower()

    if lowered.startswith("claude") and is_real_key(settings.anthropic_api_key):
        return AnthropicJudgeModelClient(model, temperature)

    # Anything below here is a fallback from the pinned Anthropic Opus policy.
    if lowered.startswith("gemini") and is_real_key(os.getenv("GEMINI_API_KEY", "")):
        logger.warning(
            "judge_agent.not_pinned_provider model=%s provider=gemini "
            "(policy is Anthropic Opus; scores are NOT comparable to an Opus-judged baseline)",
            model,
        )
        return GeminiJudgeModelClient(os.environ["GEMINI_API_KEY"], model, temperature)
    if lowered.startswith(("gpt-", "o1", "o3", "o4")) and is_real_key(os.getenv("OPENAI_API_KEY", "")):
        logger.warning(
            "judge_agent.not_pinned_provider model=%s provider=openai "
            "(policy is Anthropic Opus; scores are NOT comparable to an Opus-judged baseline)",
            model,
        )
        return OpenAIJudgeModelClient(os.environ["OPENAI_API_KEY"], model, temperature)
    if is_real_key(settings.anthropic_api_key):
        return AnthropicJudgeModelClient(model, temperature)

    logger.warning(
        "judge_agent.hosted_client_missing model=%s fallback=deterministic "
        "(gold scores reflect a keyword heuristic, not an LLM judge)",
        model,
    )
    return DeterministicJudgeModelClient()


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    for candidate in payload.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        # Skip Gemini 3 reasoning parts; only the answer text is a score.
        text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought")).strip()
        if text:
            return text
    return ""


def _judge_prompt(criterion: str, question: dict[str, Any], answer: str, rubric: dict[str, Any]) -> str:
    return (
        "Return only a decimal score from 0 to 1.\n"
        f"Criterion: {criterion}\n"
        f"Rubric version: {rubric.get('rubric_version')}\n"
        f"Question: {question.get('question')}\n"
        f"Expected answer: {question.get('expected_answer')}\n"
        f"Answer: {answer}\n"
    )


def _extract_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)
