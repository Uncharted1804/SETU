"""
Coding agent.  OWNER: P4.

It turns a coding step into one structured local-model request and one hardened
Docker execution.  The P1 orchestrator owns retries, approvals and escalation;
this module only reports evidence from its single attempt.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..contracts import AgentInvocation, AgentResult, Attempt, CodingOutput, ErrorCode, StructuredError
from ..tools.sandbox import run_in_sandbox
from .base import AgentContext


class _GeneratedPython(BaseModel):
    """The only model-produced shape accepted before the sandbox boundary."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100_000)


class _ModelOutputError(ValueError):
    pass


def _normalise_code(code: str) -> str:
    """Accept a fenced Python value, but never execute or compile it on the host."""
    text = code.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[0].strip().lower() not in {"```", "```python", "```py"}:
            raise _ModelOutputError("code fence must be plain, python, or py")
        text = "\n".join(lines[1:-1]).strip()
    if not text:
        raise _ModelOutputError("generated code is empty")
    return text + "\n"


def _generated_code(response: dict) -> str:
    """Validate Ollama's structured response without interpreting model prose."""
    try:
        content = response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise _ModelOutputError("response has no message.content string") from exc
    if not isinstance(content, str):
        raise _ModelOutputError("response message.content is not a string")
    try:
        generated = _GeneratedPython.model_validate_json(content)
    except ValidationError as exc:
        raise _ModelOutputError("response is not a valid generated-Python object") from exc
    return _normalise_code(generated.code)


def _messages(inv: AgentInvocation) -> list[dict[str, str]]:
    task = {
        "task": inv.prompt_summary,
        "inputs": inv.inputs,
        "attempt": inv.attempt,
        "feedback": inv.feedback,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are SETU's coding agent. Produce one self-contained Python solution. "
                "Return only a JSON object with exactly one key, `code`. The value must be "
                "Python source. Do not claim execution results; SETU will run the code in "
                "its hardened Docker sandbox."
            ),
        },
        {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
    ]


def _model_failure(inv: AgentInvocation, model: str, message: str, **detail: object) -> AgentResult:
    error = StructuredError(
        code=ErrorCode.TOOL_FAILED,
        message=message,
        detail={"model": model, "attempt": inv.attempt, **detail},
        retryable=True,
    )
    return AgentResult(
        agent="coding",
        model=model,
        payload={},
        attempts=[Attempt(n=inv.attempt, confidence=0.0, failure_reason=message)],
        final_confidence=0.0,
        error=error,
    )


class CodingAgent:
    name = "coding"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        entry = self.ctx.model_for("coding")
        client = self.ctx.client()
        await client.ensure_model(entry.model)
        try:
            response = await client.chat(
                entry.model,
                _messages(inv),
                options={"temperature": 0},
                format_schema=_GeneratedPython.model_json_schema(),
            )
            code = _generated_code(response)
        except _ModelOutputError as exc:
            return _model_failure(inv, entry.model, "invalid coding-model output: " + str(exc))

        output = await run_in_sandbox(
            code, self.ctx.settings, timeout_s=self.ctx.settings.sandbox_timeout_s
        )
        failure_reason = None
        if output.exit_code != 0:
            failure_reason = "sandbox exit code %s\n%s" % (output.exit_code, output.stderr[:1200])
        return AgentResult(
            agent="coding",
            model=entry.model,
            payload=output.model_dump(),
            attempts=[
                Attempt(
                    n=inv.attempt,
                    confidence=output.confidence,
                    failure_reason=failure_reason,
                    duration_ms=output.duration_ms,
                )
            ],
            final_confidence=output.confidence,
        )
