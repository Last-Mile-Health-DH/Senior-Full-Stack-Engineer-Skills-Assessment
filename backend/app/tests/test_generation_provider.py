"""Provider selection and Anthropic request-shape coverage.

No network is used: the Anthropic client is exercised through an injected fake, so these
tests assert the request we *would* send and how we handle what comes back.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.orchestrator import GenerationPayload
from app.generation.anthropic_client import NO_ANSWER_ANSWER, AnthropicGenerationClient
from app.generation.client import DeterministicGenerationClient, get_generation_client
from app.settings import settings
from app.retrieval.models import RetrievalCandidate


class FakeMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeAnthropic:
    def __init__(self, response) -> None:
        self.messages = FakeMessages(response)


def _response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        model="claude-sonnet-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=400,
            cache_creation_input_tokens=0,
        ),
    )


def _payload(content: list | None = None) -> GenerationPayload:
    chunk = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_filename="guide.pdf",
        document_status="indexed",
        content="Child dose is 5 ml.",
        page_number=1,
    )
    return GenerationPayload(
        model="claude-sonnet-5",
        system=[{"type": "text", "text": "prefix", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content or [{"type": "text", "text": "dose?"}]}],
        source_chunk_ids=[chunk.chunk_id],
        source_chunks=[chunk],
        retrieval_mode="deterministic",
    )


def test_provider_is_chosen_from_the_configured_model(monkeypatch) -> None:
    """Switching vendors must be a config change, not a code change."""
    from app.generation.client import generation_key_name
    from app.documents.chunking import embedding_key_name

    assert generation_key_name("gemini-2.5-flash") == "GEMINI_API_KEY"
    assert generation_key_name("claude-sonnet-5") == "ANTHROPIC_API_KEY"
    assert embedding_key_name("gemini-embedding-001") == "GEMINI_API_KEY"
    assert embedding_key_name("text-embedding-3-small") == "OPENAI_API_KEY"
    assert embedding_key_name("voyage-3") == "VOYAGE_API_KEY"


def test_gemini_key_selects_the_gemini_client(monkeypatch) -> None:
    from app.generation.gemini_client import GeminiGenerationClient

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyD-realish-gemini-key-000000")

    assert isinstance(get_generation_client(), GeminiGenerationClient)


def test_openai_key_selects_the_openai_client(monkeypatch) -> None:
    from app.generation.openai_client import OpenAIGenerationClient

    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-realish-openai-key-00000")

    assert isinstance(get_generation_client(), OpenAIGenerationClient)


def test_a_blocked_gemini_candidate_does_not_crash(monkeypatch) -> None:
    """A safety block returns a candidate with no `content`.

    A naive candidates[0]["content"]["parts"] read would raise, turning a refusal into a
    500 instead of the honest no-answer.
    """
    from app.generation.gemini_client import _first_text

    assert _first_text({"candidates": [{"finishReason": "SAFETY"}]}) == ""
    assert _first_text({}) == ""
    assert _first_text(
        {"candidates": [{"content": {"parts": [{"text": "The dose is 5 ml.[cite:1]"}]}}]}
    ) == "The dose is 5 ml.[cite:1]"


def test_gemini_reasoning_parts_never_reach_the_answer() -> None:
    """Gemini 3 returns reasoning as parts flagged `thought: true`, interleaved with the answer.

    Concatenating them would splice the model's private reasoning into the user-facing
    answer and straight past the presenter into the chat window.
    """
    from app.generation.gemini_client import _first_text

    answer = _first_text(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Let me check the context for a dose...", "thought": True},
                            {"text": "The dose is 5 ml.[cite:1]"},
                        ]
                    }
                }
            ]
        }
    )

    assert answer == "The dose is 5 ml.[cite:1]"
    assert "Let me check" not in answer


def test_blank_model_pricing_falls_back_to_the_default_table() -> None:
    """Compose passes an allow-list; an unset variable arrives as an empty string.

    Treating that as "no pricing" would silently zero every cost figure in the audit log.
    """
    import app.settings as settings_module

    blank = settings_module.Settings(model_pricing_json="")
    assert blank.model_pricing["gemini-3.1-flash-lite"]["input_per_mtok"] > 0


def test_placeholder_keys_do_not_select_a_hosted_client(monkeypatch) -> None:
    """`.env.example` ships placeholder keys for every provider.

    If a placeholder counted as configured, every chat turn would fail at answer time
    instead of falling back to the local client and telling the user.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-anthropic-api-key-here")
    monkeypatch.setenv("OPENAI_API_KEY", "your-openai-api-key-here")
    monkeypatch.setenv("GEMINI_API_KEY", "your-gemini-api-key-here")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)

    assert isinstance(get_generation_client(), DeterministicGenerationClient)

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert isinstance(get_generation_client(), DeterministicGenerationClient)


@pytest.mark.asyncio
async def test_request_omits_parameters_the_current_models_reject() -> None:
    """`temperature`/`top_p`/`top_k` are removed on Sonnet 5 and Opus 4.8 — sending any is a 400.

    Thinking is disabled deliberately: on Sonnet 5, omitting it runs adaptive thinking, and
    thinking tokens count against max_tokens, which would truncate a 500-token answer.
    """
    fake = FakeAnthropic(_response("The child dose is 5 ml.[cite:1]"))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    await client.generate(_payload(), max_tokens=500)

    sent = fake.messages.kwargs
    assert "temperature" not in sent
    assert "top_p" not in sent
    assert "top_k" not in sent
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["max_tokens"] == 500
    assert sent["model"] == "claude-sonnet-5"
    # The cache breakpoint the orchestrator set must survive to the API.
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_cached_prefix_tokens_are_still_counted_for_cost() -> None:
    fake = FakeAnthropic(_response("The child dose is 5 ml.[cite:1]"))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    result = await client.generate(_payload(), max_tokens=500)

    # 100 uncached + 400 cache-read: dropping the cached half would under-report spend.
    assert result.token_input == 500
    assert result.token_output == 20
    assert result.answer == "The child dose is 5 ml.[cite:1]"


@pytest.mark.asyncio
async def test_a_refusal_becomes_an_honest_no_answer() -> None:
    fake = FakeAnthropic(_response("", stop_reason="refusal"))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    result = await client.generate(_payload(), max_tokens=500)

    assert result.answer == NO_ANSWER_ANSWER


@pytest.mark.asyncio
async def test_a_provider_outage_never_becomes_a_fabricated_answer() -> None:
    import anthropic

    fake = FakeAnthropic(anthropic.APIConnectionError(request=None))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    result = await client.generate(_payload(), max_tokens=500)

    # Degrades to the no-answer, which the presenter renders as the concise refusal.
    assert result.answer == NO_ANSWER_ANSWER
    assert result.token_input == 0


@pytest.mark.asyncio
async def test_an_unusable_page_image_is_dropped_rather_than_failing_the_answer() -> None:
    """With local storage a page image is a filesystem path, not a URL or base64 blob.

    Sending it is a 400 that would take down the entire answer for a cosmetic attachment.
    """
    fake = FakeAnthropic(_response("The child dose is 5 ml.[cite:1]"))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    await client.generate(
        _payload(
            [
                {"type": "text", "text": "context"},
                {"type": "image", "source": {"type": "url", "data": "/var/lib/pages/p1.png"}},
                {"type": "text", "text": "dose?"},
            ]
        ),
        max_tokens=500,
    )

    blocks = fake.messages.kwargs["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["text", "text"]


@pytest.mark.asyncio
async def test_a_data_uri_page_image_is_converted_to_a_base64_block() -> None:
    fake = FakeAnthropic(_response("ok[cite:1]"))
    client = AnthropicGenerationClient(api_key="sk-test", client=fake)

    await client.generate(
        _payload(
            [
                {
                    "type": "image",
                    "source": {"type": "base64", "data": "data:image/png;base64,AAAB"},
                },
                {"type": "text", "text": "dose?"},
            ]
        ),
        max_tokens=500,
    )

    image = fake.messages.kwargs["messages"][0]["content"][0]
    assert image["source"] == {"type": "base64", "media_type": "image/png", "data": "AAAB"}
