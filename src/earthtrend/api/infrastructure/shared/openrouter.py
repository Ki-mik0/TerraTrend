"""OpenRouter chat completions. One HTTP client for the assistant and Story Lens."""

from __future__ import annotations

import os
from typing import Any

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


class OpenRouterError(Exception):
    """The provider refused the call or returned a body we cannot read."""


def model_from_env() -> str:
    return os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL


def key_from_env() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def request_body(model: str, system: str, user: str, json_schema: dict[str, Any] | None, max_tokens: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "plan", "strict": True, "schema": json_schema},
        }
    return body


def read_text(payload: dict[str, Any]) -> str:
    choice = payload["choices"][0]
    finish = choice.get("finish_reason")
    if finish in {"length", "content_filter"}:
        raise ValueError(f"model stopped: {finish}")
    content = choice["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = str(content).strip()
    if not text:
        raise ValueError("model returned no text")
    return text


class OpenRouter:
    def __init__(self, api_key: str, model: str, post=None) -> None:
        self.api_key = api_key
        self.model = model
        self._post = post

    async def complete(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 4000,
    ) -> str:
        body = request_body(self.model, system, user, json_schema, max_tokens)
        if self._post is not None:
            payload = await self._post(body)
        else:
            payload = await _post(self.api_key, body)
        return read_text(payload)


def complete_sync(system: str, user: str, *, max_tokens: int = 1200) -> str:
    key = key_from_env()
    body = request_body(model_from_env(), system, user, None, max_tokens)
    response = httpx.post(URL, headers=_headers(key), json=body, timeout=30.0)
    if response.status_code >= 400:
        raise OpenRouterError(response.text)
    return read_text(response.json())


async def _post(api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(URL, headers=_headers(api_key), json=body)
    if response.status_code >= 400:
        raise OpenRouterError(response.text)
    return response.json()


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
