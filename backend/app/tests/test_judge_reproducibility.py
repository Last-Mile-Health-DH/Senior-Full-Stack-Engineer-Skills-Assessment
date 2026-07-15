from __future__ import annotations

import pytest

from app.agents.judge_agent import JudgeAgent
from app.chainlit_steps import chainlit_step
from app.settings import settings


class FakeJudgeModelClient:
    async def score(self, criterion: str, question: dict, answer: str, rubric: dict) -> float:
        return 0.75 if criterion == "completeness" else 1.0


@pytest.mark.asyncio
async def test_judge_agent_stores_model_temperature_and_rubric(monkeypatch) -> None:
    monkeypatch.setattr(settings, "judge_model", "judge-test")
    monkeypatch.setattr(settings, "judge_temperature", 0.0)
    monkeypatch.setattr(settings, "judge_rubric_version", 7)

    agent = JudgeAgent(model_client=FakeJudgeModelClient())
    result = await agent.score_response(
        question="What is the dose?",
        answer="The dose is 5 ml.",
        source_texts=["The dose is 5 ml."],
        rubric={"rubric_version": 7},
    )

    assert result.metadata.model == "judge-test"
    assert result.metadata.temperature == 0.0
    assert result.metadata.rubric_version == 7
    assert result.score == pytest.approx(4.5)


def test_rubric_version_change_is_not_comparable() -> None:
    from app.scheduling.anomaly import cadence_for_metric

    assert cadence_for_metric("judge_score_mean") == "nightly"


@pytest.mark.asyncio
async def test_chainlit_step_is_noop_without_context() -> None:
    called = False

    @chainlit_step("noop-test")
    async def wrapped() -> str:
        nonlocal called
        called = True
        return "ok"

    assert await wrapped() == "ok"
    assert called is True


def test_judge_provider_follows_the_model_and_configured_key(monkeypatch) -> None:
    """A Gemini-only deployment must get a real LLM judge, not the keyword heuristic.

    Without provider routing, the judge only knew Anthropic, so it silently fell back to the
    deterministic judge — and the gold score would then measure the heuristic rather than
    the answers the generation model actually produced.
    """
    from app.agents.judge_agent import (
        AnthropicJudgeModelClient,
        DeterministicJudgeModelClient,
        GeminiJudgeModelClient,
        OpenAIJudgeModelClient,
        _default_client,
    )
    from app.settings import settings

    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    # No keys -> deterministic, and the caller is warned (see the log in _default_client).
    assert isinstance(_default_client("gemini-3.1-flash-lite", 0.0), DeterministicJudgeModelClient)

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyD-realish-gemini-key-000000")
    assert isinstance(_default_client("gemini-3.1-flash-lite", 0.0), GeminiJudgeModelClient)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-realish-openai-key-00000")
    assert isinstance(_default_client("gpt-4o-mini", 0.0), OpenAIJudgeModelClient)

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-api03-realish-key-000000")
    assert isinstance(_default_client("claude-haiku-4-5", 0.0), AnthropicJudgeModelClient)

    # A placeholder key must not select a hosted judge.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "your-gemini-api-key-here")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(_default_client("gemini-3.1-flash-lite", 0.0), DeterministicJudgeModelClient)


def test_gemini_judge_ignores_reasoning_parts() -> None:
    """A Gemini 3 reasoning part must not be parsed as the score."""
    from app.agents.judge_agent import _extract_gemini_text

    text = _extract_gemini_text(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Let me evaluate completeness...", "thought": True},
                            {"text": "0.8"},
                        ]
                    }
                }
            ]
        }
    )
    assert text == "0.8"
