"""Dynamic, cost-optimized provider routing for the ingestion planner.

The ingestion planner must not hard-require any single vendor key: it routes through the
same cheapest-available-model policy as the other agentic tasks, and runs the deterministic
local path when nothing is configured. These tests are hermetic — no network.
"""

from __future__ import annotations

import pytest

from app.agents.ingestion_agent import (
    AnthropicMessagesClient,
    GeminiIngestionClient,
    OpenAIIngestionClient,
    default_ingestion_client,
)

REAL_GEMINI = "AQ.gemini-key-000000000000000000"
REAL_OPENAI = "sk-openai-key-0000000000000000000"
REAL_ANTHROPIC = "sk-ant-key-00000000000000000000"


@pytest.fixture(autouse=True)
def _auto_routing(monkeypatch):
    monkeypatch.setattr("app.settings.settings.model_routing", "auto")
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.settings.settings.anthropic_api_key", "", raising=False)


def test_no_key_configured_falls_back_to_deterministic() -> None:
    assert default_ingestion_client() is None


def test_only_gemini_configured_selects_gemini(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)
    client = default_ingestion_client()
    assert isinstance(client, GeminiIngestionClient)
    assert client.model == "gemini-3.1-flash-lite"


def test_only_openai_configured_selects_openai(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI)
    assert isinstance(default_ingestion_client(), OpenAIIngestionClient)


def test_only_anthropic_configured_selects_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)
    assert isinstance(default_ingestion_client(), AnthropicMessagesClient)


def test_prefers_the_cheapest_when_several_keys_are_present(monkeypatch) -> None:
    """With every provider configured, the cheapest suited model wins — Gemini flash-lite."""
    monkeypatch.setenv("GEMINI_API_KEY", REAL_GEMINI)
    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI)
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_ANTHROPIC)
    assert isinstance(default_ingestion_client(), GeminiIngestionClient)


def test_placeholder_key_is_not_treated_as_configured(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "your-gemini-api-key-here")
    assert default_ingestion_client() is None


def test_gemini_reconstructs_the_model_turn_from_prior_tool_calls() -> None:
    """The loop never records the assistant tool-call turn, so the client must rebuild it.

    Gemini rejects a functionResponse that is not preceded by the matching functionCall, so
    a bad translation would fail every multi-turn ingestion.
    """
    client = GeminiIngestionClient(REAL_GEMINI, "gemini-3.1-flash-lite")
    # Simulate that the client previously emitted a detect_structure call with this id,
    # including the Gemini 3 thought signature that must be echoed back.
    client._emitted["call_1"] = {
        "name": "detect_structure",
        "args": {"page_number": 3},
        "signature": "SIG123",
        "native_id": "call_1",
    }

    messages = [
        {"role": "user", "content": "Assess document X."},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": {"page_number": 3, "has_table": True}},
            ],
        },
    ]

    contents = client._to_contents(messages)

    assert contents[0] == {"role": "user", "parts": [{"text": "Assess document X."}]}
    # A model functionCall turn must be reconstructed before the user functionResponse turn.
    assert contents[1]["role"] == "model"
    call_part = contents[1]["parts"][0]
    assert call_part["functionCall"]["name"] == "detect_structure"
    assert call_part["functionCall"]["args"] == {"page_number": 3}
    # The thought signature and native id must be echoed back, or Gemini 3 rejects the turn.
    assert call_part["thoughtSignature"] == "SIG123"
    assert call_part["functionCall"]["id"] == "call_1"
    assert contents[2]["role"] == "user"
    fr = contents[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "detect_structure"
    assert fr["response"] == {"page_number": 3, "has_table": True}
