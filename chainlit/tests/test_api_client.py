import httpx
import pytest
import respx

from api_client import BACKEND_API_BASE_URL, ApiError, post_chat


@pytest.mark.asyncio
async def test_post_chat_returns_parsed_response():
    with respx.mock(base_url=BACKEND_API_BASE_URL) as mock:
        route = mock.post("/chat").mock(
            return_value=httpx.Response(
                200,
                json={"answer": "UNICEF supports health workers.", "sources": [{"doc_name": "a.pdf", "similarity": 0.9}]},
            )
        )

        result = await post_chat("What does UNICEF do?")

        assert route.called
        request_body = route.calls.last.request.content
        assert b'"question":"What does UNICEF do?"' in request_body
        assert result["answer"] == "UNICEF supports health workers."
        assert result["sources"] == [{"doc_name": "a.pdf", "similarity": 0.9}]


@pytest.mark.asyncio
async def test_post_chat_raises_api_error_with_string_detail():
    with respx.mock(base_url=BACKEND_API_BASE_URL) as mock:
        mock.post("/chat").mock(return_value=httpx.Response(422, json={"detail": "Question is required."}))

        with pytest.raises(ApiError) as exc_info:
            await post_chat("")

        assert exc_info.value.message == "Question is required."
        assert exc_info.value.status == 422


@pytest.mark.asyncio
async def test_post_chat_raises_api_error_with_array_detail():
    with respx.mock(base_url=BACKEND_API_BASE_URL) as mock:
        mock.post("/chat").mock(
            return_value=httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "question"], "msg": "field required", "type": "missing"}]},
            )
        )

        with pytest.raises(ApiError) as exc_info:
            await post_chat("")

        assert "field required" in exc_info.value.message


@pytest.mark.asyncio
async def test_post_chat_raises_generic_message_on_server_error():
    with respx.mock(base_url=BACKEND_API_BASE_URL) as mock:
        mock.post("/chat").mock(return_value=httpx.Response(502, json={"detail": "OpenAI timeout"}))

        with pytest.raises(ApiError) as exc_info:
            await post_chat("What does UNICEF do?")

        assert exc_info.value.status == 502
        assert "please try again" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_post_chat_raises_api_error_on_network_failure():
    with respx.mock(base_url=BACKEND_API_BASE_URL) as mock:
        mock.post("/chat").mock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(ApiError) as exc_info:
            await post_chat("What does UNICEF do?")

        assert exc_info.value.status == 0
