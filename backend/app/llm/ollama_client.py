"""
Thin local Ollama transport.  OWNER: P1.

This is a TRANSPORT, not an agent.  It knows about HTTP, timeouts, streaming and
the GPU lock.  It knows nothing about prompts, roles, confidence or retries -
those live in the agent modules, which is what keeps "add a model" a
configuration change.

Four properties that matter:

  1. LOOPBACK ONLY.  The endpoint is validated on construction.  There is no
     cloud fallback and no automatic model download - `ensure_model()` reports a
     missing tag, it never pulls one.  A pull during a task would be an outbound
     transfer in the middle of a sovereignty demo.
  2. ONE INFERENCE AT A TIME.  An 8 GB card holds one model.  Every request goes
     through a module-level asyncio.Semaphore(1), so a second task queues rather
     than triggering a swap storm.  Approval waiting happens OUTSIDE this lock
     (see orchestration/approvals.py) - a human thinking must never hold the GPU.
  3. EXPLICIT TIMEOUTS AND ERRORS.  Everything raises OllamaError with a code;
     nothing returns a silent empty string.
  4. ASYNC CLEANUP.  `aclose()` closes the httpx client; the app calls it on
     shutdown.

The client is constructed lazily and httpx is imported at module scope only
because it is a light dependency already required by the API layer.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

import httpx

from ..config import Settings
from ..contracts import ErrorCode, StructuredError

#: Serialises inference across the whole process.  One loaded model, one request.
_GPU_LOCK = asyncio.Semaphore(1)


class OllamaError(RuntimeError):
    def __init__(self, code: str, message: str, **detail: Any) -> None:
        self.code = code
        self.detail = detail
        super().__init__(message)

    def as_error(self) -> StructuredError:
        return StructuredError(
            code=self.code, message=str(self), detail=self.detail,
            retryable=self.code != ErrorCode.MODEL_UNAVAILABLE,
        )


def normalise_endpoint(host: str) -> str:
    """Validate loopback and return a base URL.  Raises on anything else."""
    raw = host if "//" in host else "http://" + host
    parsed = urlparse(raw)
    hostname = parsed.hostname or ""
    if hostname != "localhost":
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise OllamaError(
                ErrorCode.MODEL_UNAVAILABLE,
                "OLLAMA_HOST must be loopback; %r is not an address" % host,
            ) from exc
        if not ip.is_loopback:
            raise OllamaError(
                ErrorCode.MODEL_UNAVAILABLE,
                "refusing to talk to a non-loopback Ollama at %r" % host,
            )
    port = parsed.port or 11434
    return "http://%s:%d" % (hostname or "127.0.0.1", port)


class OllamaClient:
    """Text, vision and structured/tool transport seams over /api/chat."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = normalise_endpoint(settings.ollama_host)
        self.timeout = settings.ollama_timeout_s
        self._client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                trust_env=False,  # ignore HTTP_PROXY: loopback must stay loopback
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- readiness -----------------------------------------------------------

    async def list_models(self) -> list[str]:
        try:
            resp = await self._http().get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(
                ErrorCode.MODEL_UNAVAILABLE,
                "Ollama is not reachable at %s: %s" % (self.base_url, exc),
            ) from exc
        return [m.get("name", "") for m in resp.json().get("models", [])]

    async def ensure_model(self, tag: str) -> None:
        """Report a missing tag.  NEVER pulls - see property 1."""
        available = await self.list_models()
        if tag not in available and tag.split(":")[0] not in {a.split(":")[0] for a in available}:
            raise OllamaError(
                ErrorCode.MODEL_UNAVAILABLE,
                "model %r is not installed. Pull it AHEAD of time with "
                "scripts/01_pull_models.ps1; SETU never downloads during a task." % tag,
                model=tag, available=available,
            )

    # -- inference -----------------------------------------------------------

    async def chat(
        self,
        model: str,
        messages: list[dict],
        options: Optional[dict] = None,
        keep_alive: str = "10m",
        format_schema: Optional[dict] = None,
        tools: Optional[list[dict]] = None,
    ) -> dict:
        """One non-streaming turn.  Serialised on the GPU lock.

        `format_schema` is the structured-output seam (Ollama accepts a JSON
        schema in `format`); `tools` is the function-calling seam.  Agents pass
        them; this module does not build them.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive,
            "options": options or {},
        }
        if format_schema is not None:
            payload["format"] = format_schema
        if tools:
            payload["tools"] = tools

        async with _GPU_LOCK:
            try:
                resp = await self._http().post("/api/chat", json=payload)
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise OllamaError(
                    ErrorCode.TOOL_FAILED,
                    "Ollama timed out after %ss on %s" % (self.timeout, model),
                    model=model,
                ) from exc
            except httpx.HTTPError as exc:
                raise OllamaError(
                    ErrorCode.MODEL_UNAVAILABLE,
                    "Ollama call failed for %s: %s" % (model, exc), model=model,
                ) from exc
            return resp.json()

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        options: Optional[dict] = None,
        keep_alive: str = "10m",
    ) -> AsyncIterator[str]:
        """Token stream, for the `token` SSE event.

        P1 TODO (acceptance: tokens appear in the UI within 2 s of step_start on
        the real reasoning agent): wire this into agents/reasoning.py drafting.
        """
        import json

        payload = {
            "model": model, "messages": messages, "stream": True,
            "keep_alive": keep_alive, "options": options or {},
        }
        async with _GPU_LOCK:
            async with self._http().stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        yield piece

    async def chat_vision(
        self,
        model: str,
        prompt: str,
        image_paths: list[Path],
        options: Optional[dict] = None,
        keep_alive: str = "10m",
        format_schema: Optional[dict] = None,
    ) -> dict:
        """Image transport seam.  Images are base64'd from local disk only."""
        images = []
        for path in image_paths:
            if not path.is_file():
                raise OllamaError(
                    ErrorCode.NOT_FOUND, "image not found: %s" % path, path=str(path)
                )
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        messages = [{"role": "user", "content": prompt, "images": images}]
        return await self.chat(
            model, messages, options=options, keep_alive=keep_alive,
            format_schema=format_schema,
        )


_CLIENT: Optional[OllamaClient] = None


def get_client(settings: Settings) -> OllamaClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OllamaClient(settings)
    return _CLIENT


async def close_client() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None
