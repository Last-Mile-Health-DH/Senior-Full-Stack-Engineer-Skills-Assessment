"""Model routing: cheapest suited provider, honest degradation."""

from __future__ import annotations

import pytest

from app.core.model_router import (
    BOTH_NOTICE,
    NO_MODEL_NOTICE,
    NO_SEARCH_NOTICE,
    Task,
    configured_providers,
    current_status,
    is_real_key,
    resolve,
    resolve_embedding,
)
from app.settings import settings

REAL_GEMINI = "AIzaSyD-real-looking-gemini-key-000"
REAL_OPENAI = "sk-proj-real-looking-openai-key-000"
REAL_ANTHROPIC = "sk-ant-api03-real-looking-key-0000"

ALL_KEYS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY")


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch):
    for name in ALL_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "model_routing", "auto")


def test_placeholders_are_not_keys() -> None:
    """A placeholder is truthy. Treating it as configured means every call fails."""
    assert is_real_key("your-anthropic-api-key-here") is False
    assert is_real_key("your-gemini-api-key-here") is False
    assert is_real_key("") is False
    assert is_real_key(None) is False
    assert is_real_key("sk-ant-") is False  # too short to be real
    assert is_real_key(REAL_ANTHROPIC) is True


def test_no_keys_means_no_provider(monkeypatch) -> None:
    assert configured_providers() == set()
    assert resolve(Task.CHAT) is None
    assert resolve_embedding() is None


def test_cheapest_configured_provider_wins(monkeypatch) -> None:
    """With everything configured, the cheapest suited model is chosen — not the priciest."""
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI)
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)

    chat = resolve(Task.CHAT)
    fast = resolve(Task.FAST)

    assert chat is not None and chat.provider == "gemini"
    assert fast is not None and fast.provider == "gemini"
    # Paying Sonnet rates to summarize a transcript would be waste.
    assert fast.blended_cost <= chat.blended_cost


def test_routing_falls_through_to_whatever_is_configured(monkeypatch) -> None:
    """Only Anthropic configured -> Anthropic answers, rather than degrading."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)

    chat = resolve(Task.CHAT)
    fast = resolve(Task.FAST)

    assert chat is not None and chat.provider == "anthropic"
    assert chat.model == "claude-sonnet-5"
    # The cheap tier is still used for mechanical work.
    assert fast is not None and fast.model == "claude-haiku-4-5"


def test_openai_only_is_a_complete_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI)

    assert resolve(Task.CHAT).provider == "openai"
    assert resolve_embedding().provider == "openai"
    assert current_status().mode == "full"


def test_manual_routing_honors_an_explicit_pin(monkeypatch) -> None:
    """An operator who pins a model made a deliberate choice; do not silently override it."""
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)
    monkeypatch.setattr(settings, "model_routing", "manual")
    monkeypatch.setattr(settings, "generation_model_primary", "claude-sonnet-5")

    chat = resolve(Task.CHAT)

    assert chat is not None and chat.model == "claude-sonnet-5"


def test_a_pinned_model_without_its_key_falls_back_to_routing(monkeypatch) -> None:
    """A pin whose key is absent is a misconfiguration, not a routing decision."""
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)
    monkeypatch.setattr(settings, "model_routing", "manual")
    monkeypatch.setattr(settings, "generation_model_primary", "claude-sonnet-5")

    chat = resolve(Task.CHAT)

    assert chat is not None and chat.provider == "gemini"


def test_no_keys_tells_the_user_plainly(monkeypatch) -> None:
    """The whole point: a degraded answer must announce itself."""
    status = current_status()

    assert status.mode == "degraded"
    assert status.notice == BOTH_NOTICE
    assert status.model is None
    # Plain language: no jargon a normal user would not understand.
    for word in ("embedding", "retrieval", "chunk", "corpus", "RAG", "vector"):
        assert word.lower() not in status.notice.lower()


def test_generation_configured_but_search_is_not(monkeypatch) -> None:
    """A key that can generate but not embed still degrades search, and says so."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)

    status = current_status()

    assert status.mode == "degraded"
    assert status.notice == NO_SEARCH_NOTICE
    assert status.provider == "anthropic"


def test_search_configured_but_generation_is_not(monkeypatch) -> None:
    """VOYAGE embeds but cannot generate: answers are extracted, and the user is told."""
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-real-looking-voyage-key-00000")

    status = current_status()

    assert status.mode == "degraded"
    assert status.notice == NO_MODEL_NOTICE


def test_fully_configured_says_nothing(monkeypatch) -> None:
    """No notice when the system is working normally — do not nag."""
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)

    status = current_status()

    assert status.mode == "full"
    assert status.notice is None
    assert status.provider == "gemini"
