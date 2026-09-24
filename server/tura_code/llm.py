"""The host's own model calls: the learning reviewer and the coding-flow judge.

These are short, single-shot completions that expect JSON back — not agent
turns — so they go straight to the chat completions endpoint with the
tenant's key. ``TURA_CODE_SCRIPTED_LLM`` (a JSON object mapping a purpose such
as ``"review"`` or ``"judge"`` to a list of answers) replaces the model in
tests and offline demos, the way ``TURA_CODE_SCRIPTED_ECHO`` does for turns.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

SCRIPTED_LLM_ENV = "TURA_CODE_SCRIPTED_LLM"
_scripted_positions: dict[tuple[str, str], int] = {}


class LLMError(RuntimeError):
    pass


def _scripted(purpose: str) -> str | None:
    source = os.environ.get(SCRIPTED_LLM_ENV, "").strip()
    if not source:
        return None
    try:
        answers = json.loads(Path(source).read_text("utf-8")).get(purpose, [])
    except (OSError, ValueError, AttributeError) as error:
        raise LLMError(f"unreadable scripted answers: {error}") from error
    position = _scripted_positions.get((source, purpose), 0)
    if position >= len(answers):
        raise LLMError(f"scripted answers for {purpose!r} are exhausted")
    _scripted_positions[(source, purpose)] = position + 1
    answer = answers[position]
    return answer if isinstance(answer, str) else json.dumps(answer)


async def complete(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    purpose: str,
    max_tokens: int = 1_500,
    timeout: float = 120.0,
) -> str:
    """One completion's text. Raises ``LLMError`` on any failure."""
    scripted = _scripted(purpose)
    if scripted is not None:
        return scripted
    if not api_key:
        raise LLMError("no API key is configured")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {api_key}", "HTTP-Referer": "https://github.com/tura-learn/root", "X-Title": "root"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url.rstrip('/')}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as error:
        raise LLMError(str(error)) from error
    if response.status_code != 200:
        raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
    try:
        return str(response.json()["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, ValueError, TypeError) as error:
        raise LLMError(f"unexpected reply: {response.text[:300]}") from error


def extract_json_object(text: str) -> str:
    """The outermost JSON object in a reply that may be fenced or chatty."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the reply")
    return stripped[start : end + 1]
