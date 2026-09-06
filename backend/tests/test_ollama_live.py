r"""
Live Ollama transport tests.  OWNER: P1.

Everything else in this suite runs in mock mode and needs no GPU.  This module
is the exception: it is the only place `llm/ollama_client.py` is exercised
against a REAL running server, which is what STATUS.md's

    "Ollama transport | REAL, untested against a live server"

was waiting on.

DOUBLE-GATED, so a mock-mode or CI run skips it cleanly rather than failing:

  1. `SETU_MOCK_MODE=0` must be set explicitly.  The default is mock mode, so
     `python -m pytest backend/tests -q` skips this file unless you opt in.
  2. Ollama must actually answer on the configured loopback host.

Run it deliberately:

    SETU_MOCK_MODE=0 python -m pytest backend/tests/test_ollama_live.py -q
    $env:SETU_MOCK_MODE=0; .\.venv\Scripts\python.exe -m pytest backend/tests -q

NO MODEL TAG APPEARS IN THIS FILE.  Tags come from the registry, which reads the
frozen `config/models.yaml` - CONTRIBUTING rule 4.1 (requirement R5).  A test
that hardcoded a tag would be the exact drift that rule exists to stop.

The third acceptance criterion for this work - a non-loopback OLLAMA_HOST still
refuses to start - is ALREADY COVERED and is deliberately not duplicated here:

  * `test_security_config.py::test_non_loopback_ollama_refuses_to_start`  (config
    layer: `get_settings()` raises ConfigError for 192.168/0.0.0.0/10.x)
  * `test_security_config.py::test_unparseable_ollama_host_refuses_to_start`
  * `test_security_config.py::test_ollama_client_endpoint_validation`  (transport
    layer: `normalise_endpoint()` raises OllamaError)

Those run in mock mode and need no server, which is where that check belongs.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------

_MOCK_MODE = os.environ.get("SETU_MOCK_MODE") != "0"


def _ollama_answers() -> bool:
    """Cheap reachability probe.  Never raises, never pulls, never blocks long."""
    try:
        import httpx

        from app import config
        from app.llm.ollama_client import normalise_endpoint

        base = normalise_endpoint(config.get_settings().ollama_host)
        resp = httpx.get(base + "/api/tags", timeout=3.0, trust_env=False)
        return resp.status_code == 200
    except Exception:
        return False


_REACHABLE = (not _MOCK_MODE) and _ollama_answers()

pytestmark = [
    pytest.mark.skipif(_MOCK_MODE, reason="live Ollama test: set SETU_MOCK_MODE=0 to run"),
    pytest.mark.skipif(
        not _REACHABLE, reason="live Ollama test: no server answering on the loopback host"
    ),
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _settings():
    from app import config

    return config.get_settings()


def _registry():
    from app import config

    return config.get_registry()


def _enabled_entries():
    return [e for e in _registry().entries if e.enabled]


def _run(body):
    """Run `body(client)` on a fresh client and event loop, always closing it.

    A new client per test on purpose: an httpx.AsyncClient is bound to the loop
    that created it, and `asyncio.run` makes a new loop each time.  This also
    keeps the module-level `get_client()` singleton out of the test path.
    """
    from app.llm.ollama_client import OllamaClient

    async def main():
        client = OllamaClient(_settings())
        try:
            return await body(client)
        finally:
            await client.aclose()

    return asyncio.run(main())


def _raw_installed_tags() -> set:
    """Ground truth straight from the server, bypassing the client entirely."""
    import httpx

    from app.llm.ollama_client import normalise_endpoint

    base = normalise_endpoint(_settings().ollama_host)
    resp = httpx.get(base + "/api/tags", timeout=10.0, trust_env=False)
    resp.raise_for_status()
    return {m["name"] for m in resp.json().get("models", [])}


# --------------------------------------------------------------------------
# Acceptance 1 - list_models() returns the installed tags
# --------------------------------------------------------------------------


def test_list_models_returns_exactly_the_installed_tags():
    """Compared against a raw /api/tags read rather than a hardcoded count.

    The handoff phrases this as "the seven installed tags", and there are seven
    on this machine today.  Asserting `== 7` would fail the moment anyone pulls
    or removes a model, and would not actually test the client - so the real
    property is asserted instead: the client reports the server's tag set,
    complete and unmangled.
    """
    tags = _run(lambda c: c.list_models())

    assert tags, "list_models() returned nothing while the server was answering"
    assert all(isinstance(t, str) and t for t in tags), "a tag came back empty or non-string"
    assert len(tags) == len(set(tags)), "list_models() returned duplicate tags"
    assert set(tags) == _raw_installed_tags()


def test_every_enabled_registry_model_is_actually_installed():
    """The frozen YAML must not promise a model this machine cannot serve.

    This is the check that would catch a benchmark gate signed off against a tag
    nobody pulled.
    """
    entries = _enabled_entries()
    assert entries, "config/models.yaml declares no enabled models"

    installed = set(_run(lambda c: c.list_models()))
    missing = sorted(e.model for e in entries if e.model not in installed)
    assert not missing, (
        "config/models.yaml enables models that are not installed: %s. "
        "SETU never pulls during a task - pull them ahead of time." % missing
    )


def test_ensure_model_accepts_installed_and_reports_missing():
    """`ensure_model()` must report, never pull (transport property 1)."""
    from app.llm.ollama_client import OllamaError

    entries = _enabled_entries()

    async def body(client):
        for entry in entries:
            await client.ensure_model(entry.model)  # must not raise

        before = set(await client.list_models())
        with pytest.raises(OllamaError) as caught:
            await client.ensure_model("setu-definitely-not-installed:0b")
        after = set(await client.list_models())
        return caught.value, before, after

    err, before, after = _run(body)

    from app.contracts import ErrorCode

    assert err.code == ErrorCode.MODEL_UNAVAILABLE
    assert after == before, "ensure_model() changed the installed set - it must never pull"


# --------------------------------------------------------------------------
# Acceptance 2 - chat() returns a real response from the planning model
# --------------------------------------------------------------------------


def test_chat_returns_a_real_response_from_the_planning_model():
    """A genuine completion, not an empty string dressed up as success.

    `think=False` is deliberate and load-bearing.  The planning model on this
    machine (reasoning-primary) is a thinking model, and with no `think` key
    Ollama leaves
    thinking ON: the whole `num_predict` budget can be spent on the reasoning
    trace, and `message.content` comes back EMPTY with `done_reason="length"`.
    That is precisely the "plausible-looking empty output" CONTRIBUTING rule 4.4
    forbids, and asserting on it without `think=False` is how this test would
    flake.  config/models.yaml already declares `thinking: false` for this entry;
    nothing reads it yet (see the P1 TODO in ollama_client.chat).
    """
    entry = _registry().resolve("planning")

    async def body(client):
        return await client.chat(
            entry.model,
            [{"role": "user", "content": "Reply with exactly the word: SETU"}],
            options={"temperature": 0.0, "num_predict": entry.max_output_tokens},
            think=False,
        )

    resp = _run(body)

    assert isinstance(resp, dict)
    assert resp.get("model") == entry.model, "a different model answered than was asked for"
    assert resp.get("done") is True

    content = (resp.get("message") or {}).get("content", "")
    assert content.strip(), (
        "chat() returned empty content (done_reason=%r) - a real response was expected"
        % resp.get("done_reason")
    )
    assert "setu" in content.lower(), (
        "model did not follow a trivial deterministic instruction; got %r" % content[:200]
    )

    # Proof the tokens were generated here rather than replayed from a fixture.
    assert resp.get("eval_count", 0) > 0
    assert resp.get("prompt_eval_count", 0) > 0


def test_chat_stream_yields_content_tokens():
    """The `token` SSE event has a real producer behind it.

    Same `think=False` reasoning as above, and it matters more here: the stream
    yields `message.content` only, so during a thinking phase it emits NOTHING.
    """
    entry = _registry().resolve("planning")

    async def body(client):
        pieces = []
        async for piece in client.chat_stream(
            entry.model,
            [{"role": "user", "content": "Reply with exactly the word: SETU"}],
            options={"temperature": 0.0, "num_predict": entry.max_output_tokens},
            think=False,
        ):
            pieces.append(piece)
        return pieces

    pieces = _run(body)

    assert pieces, "chat_stream() yielded no tokens at all"
    assert all(isinstance(p, str) and p for p in pieces)
    assert "setu" in "".join(pieces).lower()


# --------------------------------------------------------------------------
# Diagnostics - regressions on a real 500 this work uncovered
# --------------------------------------------------------------------------


def test_failure_carries_the_servers_own_explanation():
    """Ollama's error body must survive into the OllamaError.

    Not hypothetical.  Exercising this transport for the first time hit a 500 on
    a cold load of the planning model, and the client surfaced only
    `Server error '500 Internal Server Error'`.  The cause was in the discarded
    body: an out-of-memory allocating the CUDA_Host buffer - HOST RAM, not VRAM
    (Ollama disables mmap on Windows+CUDA, and this box had ~1.9 GiB free).
    Without the body that is an unexplained demo failure.
    """
    from app.llm.ollama_client import OllamaError

    async def body(client):
        with pytest.raises(OllamaError) as caught:
            await client.chat(
                "setu-definitely-not-installed:0b", [{"role": "user", "content": "hi"}]
            )
        return caught.value

    err = _run(body)

    assert "not found" in str(err).lower(), (
        "the server's explanation was dropped from the error message: %s" % err
    )
    assert err.detail.get("server_error"), "server_error missing from OllamaError.detail"


def test_stream_failure_raises_ollama_error_not_a_raw_httpx_error():
    """Transport property 3: nothing raw escapes this module.

    `chat_stream` previously called `raise_for_status()` with no handler, so a
    stream failure surfaced as `httpx.HTTPStatusError` - a leak of the transport
    layer that callers upstream have no contract for.
    """
    import httpx

    from app.llm.ollama_client import OllamaError

    async def body(client):
        try:
            async for _ in client.chat_stream(
                "setu-definitely-not-installed:0b", [{"role": "user", "content": "hi"}]
            ):
                pass
        except OllamaError as exc:
            return exc
        except httpx.HTTPError as exc:  # pragma: no cover - the regression itself
            pytest.fail("chat_stream leaked a raw httpx error: %r" % exc)
        pytest.fail("chat_stream did not raise on an unknown model")

    err = _run(body)
    assert "not found" in str(err).lower()
    assert err.detail.get("server_error")
