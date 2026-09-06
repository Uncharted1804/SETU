"""Focused P4 tests for model-to-sandbox coding-agent integration."""

from __future__ import annotations

import pytest

from app import config
from app.agents.base import AgentContext
from app.agents.coding import CodingAgent
from app.contracts import AgentInvocation, CodingOutput, ErrorCode


class _Client:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.models: list[str] = []
        self.calls: list[dict] = []

    async def ensure_model(self, model: str) -> None:
        self.models.append(model)

    async def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        self.calls.append({"model": model, "messages": messages, **kwargs})
        return self.response


def _invocation(settings, *, attempt: int = 1, feedback: str | None = None) -> AgentInvocation:
    entry = config.get_registry().resolve_for_agent("coding")
    return AgentInvocation(
        agent="coding",
        model_id=entry.id,
        model=entry.model,
        prompt_summary="Calculate the sum and print it.",
        inputs={"prior": [{"target": "reasoning", "summary": "use integers"}]},
        attempt=attempt,
        feedback=feedback,
    )


def _agent(env, monkeypatch, response: dict) -> tuple[CodingAgent, _Client]:
    ctx = AgentContext(env, config.get_registry())
    client = _Client(response)
    monkeypatch.setattr(ctx, "client", lambda: client)
    return CodingAgent(ctx), client


@pytest.mark.asyncio
async def test_coding_agent_runs_valid_model_code_only_in_the_sandbox(env, monkeypatch):
    agent, client = _agent(env, monkeypatch, {"message": {"content": '{"code":"print(2 + 2)"}'}})
    calls: list[tuple[str, int]] = []

    async def sandbox(code, settings, timeout_s):
        calls.append((code, timeout_s))
        return CodingOutput(
            code=code,
            stdout="4\n",
            stderr="",
            exit_code=0,
            duration_ms=12.5,
            artifacts=["result.txt"],
            confidence=1.0,
            sandbox_command=["docker", "run"],
        )

    monkeypatch.setattr("app.agents.coding.run_in_sandbox", sandbox)
    result = await agent.run(_invocation(env))

    assert client.models == [config.get_registry().resolve_for_agent("coding").model]
    assert client.calls[0]["options"] == {"temperature": 0}
    assert client.calls[0]["format_schema"]
    assert calls == [("print(2 + 2)\n", env.sandbox_timeout_s)]
    assert result.final_confidence == 1.0
    assert result.payload["stdout"] == "4\n"
    assert result.payload["artifacts"] == ["result.txt"]
    assert result.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "marker"),
    [
        ("  File \"main.py\", line 1\n    if True print(1)\n            ^\nSyntaxError: invalid syntax", "syntaxerror"),
        ("Traceback (most recent call last):\n  File \"main.py\", line 1, in <module>\nZeroDivisionError", "zerodivisionerror"),
    ],
)
async def test_coding_agent_returns_sandbox_failure_evidence_for_retry(env, monkeypatch, stderr, marker):
    agent, _ = _agent(env, monkeypatch, {"message": {"content": '{"code":"1 / 0"}'}})

    async def sandbox(code, settings, timeout_s):
        return CodingOutput(
            code=code,
            stderr=stderr,
            exit_code=1,
            duration_ms=8.0,
            confidence=0.0,
        )

    monkeypatch.setattr("app.agents.coding.run_in_sandbox", sandbox)
    result = await agent.run(_invocation(env, attempt=2, feedback="previous traceback"))

    assert result.error is None
    assert result.final_confidence == 0.0
    assert result.payload["stderr"] == stderr
    assert result.attempts[0].n == 2
    assert result.attempts[0].failure_reason == "sandbox exit code 1\n" + stderr[:1200]
    assert marker in result.attempts[0].failure_reason.lower()


@pytest.mark.asyncio
async def test_coding_agent_rejects_malformed_model_output_without_sandbox(env, monkeypatch):
    agent, _ = _agent(env, monkeypatch, {"message": {"content": "```python\nprint(2 + 2)\n```"}})

    async def should_not_run(*args, **kwargs):
        raise AssertionError("malformed model output must not reach the sandbox")

    monkeypatch.setattr("app.agents.coding.run_in_sandbox", should_not_run)
    result = await agent.run(_invocation(env))

    assert result.final_confidence == 0.0
    assert result.payload == {}
    assert result.error is not None
    assert result.error.code == ErrorCode.TOOL_FAILED
    assert result.error.retryable is True
    assert "invalid coding-model output" in result.error.message
