"""Gemini transient-failure retry.

A free-tier 429 failed a whole document's ingestion. These prove the retry recovers from
transient rate limits and 5xx, backs off, and still surfaces a real client error.
"""

from __future__ import annotations

import httpx
import pytest

from app.documents.chunking import _gemini_post_with_retry


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = {"retry-after": retry_after} if retry_after else {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://x"), response=self)  # type: ignore[arg-type]


class _Client:
    def __init__(self, responses: list[_Resp]) -> None:
        self._responses = responses
        self.calls = 0

    async def post(self, url, headers, json):  # noqa: A002 - mirrors httpx signature
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch):
    """Make the retry's sleep a no-op so the test is fast and deterministic."""
    import asyncio

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


@pytest.mark.asyncio
async def test_recovers_from_a_transient_rate_limit() -> None:
    client = _Client([_Resp(429), _Resp(429), _Resp(200, {"embeddings": [{"values": [0.1]}]})])

    body = await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=5)

    assert client.calls == 3
    assert body["embeddings"][0]["values"] == [0.1]


@pytest.mark.asyncio
async def test_recovers_from_a_transient_server_error() -> None:
    client = _Client([_Resp(503), _Resp(200, {"ok": True})])

    body = await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=5)

    assert body == {"ok": True}


class _FlakyClient:
    """Raises a transport error the first `fail_times` calls, then returns 200.

    Models a DNS/connection blip mid-ingestion: not a status code, raised from post().
    """

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def post(self, url, headers, json):  # noqa: A002
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ConnectError("No address associated with hostname")
        return _Resp(200, {"ok": True})


@pytest.mark.asyncio
async def test_recovers_from_a_transient_network_error() -> None:
    client = _FlakyClient(fail_times=2)

    body = await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=5)

    assert client.calls == 3  # two DNS failures, then success
    assert body == {"ok": True}


@pytest.mark.asyncio
async def test_a_persistent_network_error_eventually_raises() -> None:
    client = _FlakyClient(fail_times=99)

    with pytest.raises(httpx.ConnectError):
        await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=3)

    assert client.calls == 3


@pytest.mark.asyncio
async def test_a_persistent_rate_limit_eventually_raises() -> None:
    client = _Client([_Resp(429)])

    with pytest.raises(httpx.HTTPStatusError):
        await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=3)

    assert client.calls == 3  # tried the configured number of times, then gave up


@pytest.mark.asyncio
async def test_a_real_client_error_is_not_retried() -> None:
    """A 400 is a genuine bad request, not a transient limit — fail fast, do not retry."""
    client = _Client([_Resp(400)])

    with pytest.raises(httpx.HTTPStatusError):
        await _gemini_post_with_retry(client, "http://x", "k", {}, max_attempts=5)

    assert client.calls == 1


@pytest.mark.asyncio
async def test_retry_after_header_is_honored() -> None:
    from app.documents.chunking import _retry_after_seconds

    assert _retry_after_seconds(_Resp(429, retry_after="7")) == 7.0
    assert _retry_after_seconds(_Resp(429)) is None
