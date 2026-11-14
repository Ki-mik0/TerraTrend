"""The OpenRouter HTTP client: request body, text extraction, and a refused call."""

from __future__ import annotations

import json

import httpx
import pytest

from earthtrend.api.infrastructure.shared import openrouter


def test_complete_sync_sends_bearer_and_reads_the_message(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    captured: dict = {}

    def post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": [{"type": "text", "text": "  ok  "}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(openrouter.httpx, "post", post)
    assert openrouter.complete_sync("system", "user") == "ok"
    assert captured["url"] == openrouter.URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == openrouter.DEFAULT_MODEL
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]


def test_complete_sync_refuses_an_error_status(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def post(url, headers, json, timeout):
        return httpx.Response(503, text="down", request=httpx.Request("POST", url))

    monkeypatch.setattr(openrouter.httpx, "post", post)
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.complete_sync("system", "user")


async def test_async_complete_posts_when_no_fake_is_injected(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "async"}}]}

    class FakeClient:
        def __init__(self, timeout) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", FakeClient)
    text = await openrouter.OpenRouter("k", "m").complete(system="s", user="u", max_tokens=10)
    assert text == "async"
    assert captured["body"]["max_tokens"] == 10
    assert json.dumps(captured["body"])


async def test_async_complete_raises_when_the_provider_refuses(monkeypatch) -> None:
    class FakeResponse:
        status_code = 429
        text = "slow down"

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, timeout) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", FakeClient)
    with pytest.raises(openrouter.OpenRouterError):
        await openrouter.OpenRouter("k", "m").complete(system="s", user="u")


def test_story_callback_stays_offline_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from earthtrend.api.infrastructure.analytics_bridge import _openrouter

    assert _openrouter() is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(openrouter, "complete_sync", lambda system, user: f"{system}:{user}")
    assert _openrouter()("system", "user") == "system:user"
