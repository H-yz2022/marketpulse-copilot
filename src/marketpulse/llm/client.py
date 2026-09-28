"""Thin wrapper around the Anthropic Messages API.

Every LLM feature takes an optional `client` argument. In production it's
`None` and we build a real `anthropic.Anthropic` client; tests pass a fake
object with the same `.messages.create(...)` shape, so the whole suite runs
offline with no API key and no `anthropic` package required.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from marketpulse.config import settings


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM feature is used without an API key configured."""


def get_client(client: Any = None) -> Any:
    if client is not None:
        return client
    if not settings.anthropic_api_key:
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY is not set, so AI features are disabled. Add it to your .env "
            "(or the host's environment variables) and restart the server."
        )
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def response_text(message: Any) -> str:
    """Concatenate all text blocks of a Messages API response."""
    return "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text").strip()


def complete_text(system: str, prompt: str, max_tokens: int = 1024, client: Any = None) -> str:
    c = get_client(client)
    message = c.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response_text(message)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in an LLM response.

    Models occasionally wrap JSON in ```json fences or add a sentence before
    it; this strips fences and falls back to the outermost {...} span.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        value = json.loads(cleaned[start : end + 1])
        if isinstance(value, dict):
            return value
    raise ValueError("Model response did not contain a JSON object")


def complete_json(system: str, prompt: str, max_tokens: int = 1500, client: Optional[Any] = None) -> dict:
    text = complete_text(system + "\n\nRespond with a single JSON object and nothing else.", prompt, max_tokens, client)
    return parse_json_object(text)
