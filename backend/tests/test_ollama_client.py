"""
Ollama transport unit tests.  OWNER: P1.

No server, no GPU, no network - these run in ordinary mock mode, unlike
`test_ollama_live.py` which needs a live Ollama.  Everything here is driven with
synthetic httpx responses.

These cover the two defects found while exercising the transport against a real
server for the first time:

  1. Ollama's error body was discarded, so a 500 surfaced as nothing more than
     "Server error '500 Internal Server Error'".  The actual cause was in the
     body Ollama had already sent.
  2. Every HTTP failure was coded MODEL_UNAVAILABLE, which `as_error()` marks
     NOT retryable - so a transient 5xx made the orchestrator abandon a call
     that succeeded on the next attempt.

The retry decision is the one worth guarding in CI: it changes behaviour during
a demo, and it cannot be checked by a test that needs a server to be running.
"""

from __future__ import annotations

import httpx
import pytest

from app.contracts import ErrorCode
from app.llm.ollama_client import (
    OllamaError,
    _http_error_code,
    _server_said,
    _with_server_detail,
)

URL = "http://127.0.0.1:11434/api/chat"


def _status_error(status: int, body=None, text: str | None = None) -> httpx.HTTPStatusError:
    """A real httpx.HTTPStatusError with a real response attached, no server."""
    request = httpx.Request("POST", URL)
    if body is not None:
        response = httpx.Response(status, json=body, request=request)
    else:
        response = httpx.Response(status, text=text or "", request=request)
    return httpx.HTTPStatusError("HTTP %d" % status, request=request, response=response)


# -- error-code classification ----------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_side_failures_are_retryable(status):
    """A 5xx means the server is up and this attempt failed.  Try again.

    The real case: a cold load returned 500 after failing to allocate the pinned
    CUDA_Host buffer, and the identical request succeeded 11 s later.
    """
    exc = _status_error(status, {"error": "unable to allocate CUDA_Host buffer"})
    code = _http_error_code(exc)

    assert code == ErrorCode.TOOL_FAILED
    assert OllamaError(code, "boom").as_error().retryable is True


@pytest.mark.parametrize("status", [400, 404, 422])
def test_client_side_failures_are_not_retryable(status):
    """A 404 means the tag is genuinely absent.  Retrying changes nothing."""
    exc = _status_error(status, {"error": "model 'nope:999b' not found"})
    code = _http_error_code(exc)

    assert code == ErrorCode.MODEL_UNAVAILABLE
    assert OllamaError(code, "boom").as_error().retryable is False


def test_no_response_at_all_is_model_unavailable():
    """A connect error means nothing is listening - not a transient fault."""
    exc = httpx.ConnectError("connection refused", request=httpx.Request("POST", URL))

    assert _http_error_code(exc) == ErrorCode.MODEL_UNAVAILABLE


# -- server explanation surfacing -------------------------------------------


def test_server_error_body_is_extracted():
    exc = _status_error(500, {"error": "llama runner terminated"})

    assert _server_said(exc) == "llama runner terminated"


def test_non_json_body_falls_back_to_text_and_is_truncated():
    exc = _status_error(500, text="x" * 900)
    said = _server_said(exc)

    assert said.startswith("xxx")
    assert len(said) == 500, "an unbounded body would flood the audit log"


def test_missing_or_unreadable_body_yields_empty_string():
    """Must never raise: this runs inside an `except` block building an error."""
    bare = httpx.ConnectError("refused", request=httpx.Request("POST", URL))

    assert _server_said(bare) == ""
    assert _server_said(_status_error(500, text="")) == ""


def test_detail_is_appended_only_when_the_server_said_something():
    with_body = _status_error(404, {"error": "model 'nope:999b' not found"})
    without = httpx.ConnectError("refused", request=httpx.Request("POST", URL))

    assert _with_server_detail("base", with_body) == (
        "base -- server said: model 'nope:999b' not found"
    )
    assert _with_server_detail("base", without) == "base"


def test_ollama_error_carries_detail_through_to_the_structured_error():
    err = OllamaError(
        ErrorCode.TOOL_FAILED, "call failed", model="m", server_error="out of memory"
    )
    structured = err.as_error()

    assert structured.code == ErrorCode.TOOL_FAILED
    assert structured.retryable is True
    assert structured.detail["server_error"] == "out of memory"
    assert structured.detail["model"] == "m"
