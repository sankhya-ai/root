"""The host's LLM proxy: runtimes reach the model without ever holding the key.

A runtime process is configured with ``<host>/llm/api/v1`` as its base URL and
a per-launch token as its "API key". The proxy swaps the token for the
person's real OpenRouter key and streams the reply back. Everything the
runtime sends to OpenRouter — chat completions, Jev's ``/alpha/decisions``, the
paid search plugin — is a path under ``/api/``, so one route covers it.

Why: an agent can read any file its runtime can, and in a hosted install the
key is often the operator's. With the proxy, the most an agent can learn is a
token that works only for its own session, only through this host, and only
until the runtime stops.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Callable

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

PREFIX = "/llm/api"
_FORWARD_HEADERS = ("content-type", "accept", "http-referer", "x-title", "user-agent")


@dataclass
class Grant:
    tenant_id: str
    session_id: str
    #: Returns (upstream base URL such as https://openrouter.ai/api/v1, key).
    resolve: Callable[[], tuple[str, str]]
    requests: int = 0
    #: Models OpenRouter falls back to, in order, when the chosen one fails or is down.
    fallbacks: Callable[[], list[str]] | None = None


def with_fallbacks(body: bytes, fallbacks: list[str]) -> bytes:
    """A chat request with OpenRouter's ``models`` failover list, unless it already names one."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict) or "models" in data or not data.get("model"):
        return body
    chain = [data["model"], *[m for m in fallbacks if m and m != data["model"]]]
    if len(chain) < 2:
        return body
    data["models"] = chain
    return json.dumps(data).encode()


def with_reasoning_echo(body: bytes) -> bytes:
    """A chat request in which every assistant tool call carries ``reasoning_content``.

    DeepSeek in thinking mode rejects the whole history when one lacks it ("The
    `reasoning_content` in the thinking mode must be passed back"), and a step
    that reasoned nothing stores none; an empty one is accepted.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return body
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return body
    changed = False
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "assistant" and message.get("tool_calls") and not any(k in message for k in ("reasoning_content", "reasoning", "reasoning_details")):
            message["reasoning_content"] = ""
            changed = True
    return json.dumps(data).encode() if changed else body


class LLMProxy:
    def __init__(self) -> None:
        self._grants: dict[str, Grant] = {}
        self._client: httpx.AsyncClient | None = None
        #: Set by the server once it knows its own address; None disables the proxy.
        self.base: str | None = None

    @property
    def enabled(self) -> bool:
        return self.base is not None

    def issue(self, tenant_id: str, session_id: str, resolve: Callable[[], tuple[str, str]], fallbacks: Callable[[], list[str]] | None = None) -> tuple[str, str]:
        """A (base URL, token) pair for one runtime launch."""
        assert self.base is not None
        token = f"root-{secrets.token_urlsafe(24)}"
        self._grants[token] = Grant(tenant_id, session_id, resolve, fallbacks=fallbacks)
        return f"{self.base}{PREFIX}/v1", token

    def revoke(self, token: str) -> None:
        self._grants.pop(token, None)

    def usage(self, tenant_id: str) -> int:
        return sum(g.requests for g in self._grants.values() if g.tenant_id == tenant_id)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=600, write=60, pool=20))
        return self._client

    async def forward(self, request: Request, path: str) -> Response:
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        grant = self._grants.get(token)
        if grant is None:
            return JSONResponse({"error": {"message": "Unknown or expired runtime token."}}, status_code=401)
        base, key = grant.resolve()
        if not key:
            return JSONResponse({"error": {"message": "No OpenRouter API key is configured."}}, status_code=401)
        root = base.rstrip("/").rsplit("/v1", 1)[0]
        headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_HEADERS}
        headers["authorization"] = f"Bearer {key}"
        grant.requests += 1
        body = await request.body()
        if request.method == "POST" and path.endswith("chat/completions"):
            if "openrouter.ai" not in root:
                body = with_reasoning_echo(body)
            elif grant.fallbacks is not None:
                body = with_fallbacks(body, grant.fallbacks())
        upstream = self._http().build_request(
            request.method,
            f"{root}/{path}",
            params=request.query_params,
            headers=headers,
            content=body,
        )
        response = await self._http().send(upstream, stream=True)
        passthrough = {k: v for k, v in response.headers.items() if k.lower() in ("content-type", "cache-control")}
        return StreamingResponse(
            # Decoded: content-encoding is not forwarded, so neither may compressed bytes be.
            response.aiter_bytes(),
            status_code=response.status_code,
            headers=passthrough,
            # Close the upstream response once the client has the whole body.
            background=BackgroundTask(response.aclose),
        )
