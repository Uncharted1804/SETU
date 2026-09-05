"""
Mock adapters.  OWNER: P1 until each owner replaces theirs.

These are the objects a teammate DELETES when their real component lands:

    MockAgent("vision")     -> agents/vision.py::VisionAgent          [P2]
    MockAgent("reasoning")  -> agents/reasoning.py::ReasoningAgent    [P3]
    MockAgent("coding")     -> agents/coding.py::CodingAgent          [P4]
    mock_kb_search          -> tools/kb.py::kb_search                 [P3]
    mock_run_python         -> tools/sandbox.py::run_in_sandbox       [P4]
    mock_sheet_op           -> tools/sheets.py::sheet_op              [P6]

They are wired in tools/registry.py::_mock_specs and agents/__init__.py, and
selected by ONE setting: SETU_MOCK_MODE.  Everything downstream of them - the
dispatcher, retry policy, approval gate, audit chain, SSE transport - is the
same code in both modes.

The scenario for a task is set once by the executor via `set_scenario()` and
read back through a ContextVar, so concurrent tasks do not read each other's
fixtures.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

from ..contracts import AgentInvocation, AgentResult, Attempt, ErrorCode, StructuredError
from ..tools.base import ToolContext, ToolError
from .scenarios import Scenario, get_scenario

#: Per-task fixture selection.  ContextVar, not a module global, so two tasks
#: running concurrently in the same process cannot cross-contaminate.
_ACTIVE: ContextVar[tuple[str, dict]] = ContextVar("setu_mock_scenario", default=("flagship", {}))

#: Simulated latency, so the UI's streaming and step transitions are visible
#: without pretending work happened.  Kept small; this is not a progress bar.
STEP_DELAY_S = 0.05


def set_scenario(key: str) -> None:
    _ACTIVE.set((key, {}))


def active_scenario() -> Scenario:
    key, _ = _ACTIVE.get()
    return get_scenario(key)


def _call_index(tool: str) -> int:
    """1-based per-tool call counter for the current task."""
    key, counters = _ACTIVE.get()
    counters = dict(counters)
    counters[tool] = counters.get(tool, 0) + 1
    _ACTIVE.set((key, counters))
    return counters[tool]


class MockAgent:
    """Deterministic stand-in for one of the three agents.

    It honours the attempt number, so the retry/confidence policy in
    orchestration/policy.py is exercised for real: attempt 1 of the coding
    scenario returns exit_code 1 and attempt 2 returns exit_code 0, and the
    policy - not the fixture - decides whether to retry.
    """

    simulated = True

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, inv: AgentInvocation) -> AgentResult:
        await asyncio.sleep(STEP_DELAY_S)
        scenario = active_scenario()
        outcome = scenario.agent_outcome(self.name, inv.attempt)
        payload = dict(outcome.payload)
        payload.setdefault("_summary", outcome.summary)
        payload["simulated"] = True
        return AgentResult(
            agent=self.name,  # type: ignore[arg-type]
            model=inv.model,
            payload=payload,
            attempts=[
                Attempt(
                    n=inv.attempt,
                    confidence=outcome.confidence,
                    failure_reason=outcome.failure_reason,
                    feedback_injected=inv.feedback,
                    duration_ms=round(STEP_DELAY_S * 1000, 1),
                )
            ],
            final_confidence=outcome.confidence,
            needs_human_review=False,
            simulated=True,
        )


async def _fixture_tool(tool: str, extra: dict) -> dict:
    await asyncio.sleep(STEP_DELAY_S)
    scenario = active_scenario()
    outcome = scenario.tool_outcome(tool, _call_index(tool))
    if outcome.error_code:
        raise ToolError(outcome.error_code, outcome.error_message or "simulated failure")
    payload = dict(outcome.payload)
    payload.update(extra)
    payload["simulated"] = True
    payload.setdefault("_summary", outcome.summary)
    return payload


async def mock_kb_search(args, ctx: ToolContext) -> dict:
    """Fixture chunks.  Labelled simulated so the UI never shows a fake citation
    as if it were retrieved from the organisation's real corpus."""
    return await _fixture_tool("kb_search", {"query": args.query})


async def mock_run_python(args, ctx: ToolContext) -> dict:
    """Simulated sandbox execution.

    It reports `sandbox_available=False` and a SIMULATED marker rather than
    claiming a container ran.  A mock that reported a real-looking exit code
    with no container behind it would be exactly the dishonest artefact the
    security story cannot afford.
    """
    payload = await _fixture_tool("run_python", {})
    payload.setdefault("code", args.code)
    payload.setdefault("stdout", "SIMULATED: no container was started.\n")
    payload.setdefault("stderr", "")
    payload.setdefault("exit_code", 0)
    payload["confidence"] = 1.0 if payload["exit_code"] == 0 else 0.0
    payload["sandbox_available"] = False
    payload["sandbox_command"] = ["<simulated - docker was not invoked>"]
    return payload


async def mock_sheet_op(args, ctx: ToolContext) -> dict:
    return await _fixture_tool("sheet_op", {"op": args.op, "path": args.path})


def refuse_in_real_mode(what: str) -> StructuredError:
    """Guard used by build_planner: fixtures never silently run in real mode."""
    return StructuredError(
        code=ErrorCode.INTERNAL,
        message="%s is a mock-mode fixture and must not run with SETU_MOCK_MODE=0" % what,
    )
