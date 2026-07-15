from __future__ import annotations

import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path


class _FakeUserSession:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def set(self, key: str, value: object) -> None:
        self.values[key] = value


class _FakeMessage:
    """Records the loading placeholder and the content it is later replaced with."""

    sent: list["_FakeMessage"] = []

    def __init__(self, content: str) -> None:
        self.content = content
        self.updates: list[str] = []

    async def send(self) -> None:
        _FakeMessage.sent.append(self)

    async def update(self) -> None:
        self.updates.append(self.content)


class _FakeStarter:
    def __init__(self, label: str, message: str, icon: str | None = None) -> None:
        self.label = label
        self.message = message
        self.icon = icon


class _FakeHTTPError(Exception):
    pass


class _FakeHTTPStatusError(_FakeHTTPError):
    def __init__(self, response: object) -> None:
        self.response = response
        super().__init__("status error")


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _FakeHTTPStatusError(self)


def _load_chat_module():
    fake_chainlit = types.SimpleNamespace(
        user_session=_FakeUserSession(),
        Message=_FakeMessage,
        Starter=_FakeStarter,
        on_chat_start=lambda func: func,
        on_message=lambda func: func,
        set_starters=lambda func: func,
    )
    sys.modules["chainlit"] = fake_chainlit
    sys.modules["httpx"] = types.SimpleNamespace(
        AsyncClient=object,
        HTTPError=_FakeHTTPError,
        HTTPStatusError=_FakeHTTPStatusError,
    )
    module_path = Path(__file__).resolve().parents[1] / "app" / "chat.py"
    module_name = f"chainlit_chat_under_test_{id(fake_chainlit)}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class ChainlitChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeMessage.sent = []

    def test_backend_presented_answer_is_rendered_with_a_reference_list(self) -> None:
        """Chainlit mirrors the backend presenter; it does not re-place citations."""
        chat = _load_chat_module()

        rendered = chat.render_answer_with_citations(
            "The child dose is 5 ml.¹ Adults receive 10 ml.²",
            [
                {"number": 1, "reference": "1. Oral Rehydration Protocol, p. 1."},
                {"number": 2, "reference": "2. Who Guidance 2024, p. 14."},
            ],
        )

        self.assertEqual(
            rendered,
            "The child dose is 5 ml.¹ Adults receive 10 ml.²\n\n"
            "**Sources**\n\n"
            "1. Oral Rehydration Protocol, p. 1.\n"
            "2. Who Guidance 2024, p. 14.",
        )

    def test_reference_falls_back_to_chunk_metadata_only(self) -> None:
        chat = _load_chat_module()

        rendered = chat.render_answer_with_citations(
            "The table shows 5 ml.¹",
            [
                {
                    "number": 1,
                    "document_title": "WHO Guidance",
                    "page_number": 7,
                    "section_path": "Dose table",
                }
            ],
        )

        self.assertIn("1. WHO Guidance, Dose table, p. 7.", rendered)

    def test_no_answer_renders_without_an_empty_reference_list(self) -> None:
        chat = _load_chat_module()

        rendered = chat.render_answer_with_citations(
            "I could not find that in the uploaded documents.",
            [],
        )

        self.assertEqual(rendered, "I could not find that in the uploaded documents.")
        self.assertNotIn("Sources", rendered)

    async def test_loading_placeholder_is_shown_then_replaced_by_the_answer(self) -> None:
        chat = _load_chat_module()

        class FakeClient:
            async def ask(self, message: str, session_id: str | None):
                return chat.BackendChatResponse(
                    session_id="00000000-0000-0000-0000-000000000001",
                    answer="The child dose is 5 ml.¹",
                    citations=[{"number": 1, "reference": "1. Oral Rehydration Protocol, p. 1."}],
                )

        chat.cl.user_session.set("backend_chat_client", FakeClient())
        await chat.handle_message(_FakeMessage("what is the child dose?"))

        placeholder = _FakeMessage.sent[-1]
        # The user sees the system working before the answer exists...
        self.assertEqual(placeholder.updates[0].count("Sources"), 1)
        self.assertIn("The child dose is 5 ml.¹", placeholder.content)
        # ...and the placeholder is replaced in place rather than left behind.
        self.assertEqual(len(placeholder.updates), 1)

    async def test_unreachable_backend_shows_a_concise_honest_error(self) -> None:
        chat = _load_chat_module()

        class FailingClient:
            async def ask(self, message: str, session_id: str | None):
                raise _FakeHTTPError("boom")

        chat.cl.user_session.set("backend_chat_client", FailingClient())
        await chat.handle_message(_FakeMessage("what is the child dose?"))

        placeholder = _FakeMessage.sent[-1]
        self.assertTrue(placeholder.content.startswith("I could not reach the chat service."))
        self.assertIn("pytest may have dropped", placeholder.content)

    def test_thinking_placeholder_is_defined(self) -> None:
        chat = _load_chat_module()

        self.assertIn("Searching your documents", chat.THINKING_MESSAGE)

    def test_upload_button_is_mounted_inside_the_composer(self) -> None:
        """The "+" sits at the bottom-left corner INSIDE the input frame, as in Next.js."""
        root = Path(__file__).resolve().parents[1]
        config = (root / ".chainlit" / "config.toml").read_text(encoding="utf-8")
        script = (root / "public" / "rag-composer-upload.js").read_text(encoding="utf-8")
        theme = (root / "public" / "rag-theme.css").read_text(encoding="utf-8")

        self.assertIn('custom_js = "/public/rag-composer-upload.js"', config)

        # Anchored to Chainlit's stable element ids, never to generated class names.
        self.assertIn("message-composer", script)
        self.assertIn("/documents", script)
        self.assertIn("rag-upload-btn", script)

        # Positioned bottom-left inside the composer frame, with room reserved so it can
        # never sit on top of the user's typed text.
        self.assertIn("#message-composer {", theme)
        self.assertIn("position: relative", theme)
        self.assertIn("#rag-upload-btn", theme)
        self.assertIn("left: 12px", theme)
        self.assertIn("bottom: 12px", theme)
        self.assertIn("padding-left: 46px", theme)

    def test_welcome_message_points_at_the_upload_page(self) -> None:
        chat = _load_chat_module()

        self.assertIn("Upload PDF", chat.WELCOME_MESSAGE)
        self.assertIn("/documents", chat.WELCOME_MESSAGE)

    def test_user_facing_copy_carries_no_retrieval_jargon(self) -> None:
        """Words like "RAG", "chunk", and "indexed" mean nothing to the people using this."""
        chat = _load_chat_module()
        root = Path(__file__).resolve().parents[1]

        jargon = re.compile(
            r"\b(RAG|chunks?|corpus|grounded|grounding|retrieval|reranker|embedding|ingestion|indexed)\b",
            re.IGNORECASE,
        )
        copy = [
            chat.WELCOME_MESSAGE,
            chat.THINKING_MESSAGE,
            (root / "chainlit.md").read_text(encoding="utf-8"),
        ]
        for text in copy:
            self.assertIsNone(jargon.search(text), f"user-facing copy contains jargon: {text}")

        config = (root / ".chainlit" / "config.toml").read_text(encoding="utf-8")
        for line in config.splitlines():
            if line.startswith(("name =", "description =")):
                self.assertIsNone(jargon.search(line), f"config copy contains jargon: {line}")

    async def test_backend_chat_client_posts_to_fastapi_chat(self) -> None:
        chat = _load_chat_module()
        seen: dict[str, object] = {}

        class FakeAsyncClient:
            def __init__(self, timeout: float) -> None:
                seen["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, url: str, json: dict[str, str], headers: dict[str, str]) -> _FakeResponse:
                seen["url"] = url
                seen["json"] = json
                seen["headers"] = headers
                return _FakeResponse(
                    200,
                    {
                        "session_id": "00000000-0000-0000-0000-000000000001",
                        "answer": "Answer",
                        "citations": [{"number": 1}],
                    },
                )

        chat.httpx.AsyncClient = FakeAsyncClient
        client = chat.BackendChatClient(
            base_url="http://backend:6100/",
            auth_token="token",
            timeout_seconds=3,
        )

        response = await client.ask("question", "00000000-0000-0000-0000-000000000002")

        self.assertEqual(seen["url"], "http://backend:6100/api/v1/chat")
        self.assertEqual(
            seen["json"],
            {
                "message": "question",
                "session_id": "00000000-0000-0000-0000-000000000002",
            },
        )
        self.assertEqual(seen["headers"], {"Accept": "application/json", "Authorization": "Bearer token"})
        self.assertEqual(response.answer, "Answer")
        self.assertEqual(response.session_id, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(response.citations, [{"number": 1}])


if __name__ == "__main__":
    unittest.main()
