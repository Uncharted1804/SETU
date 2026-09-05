"""
Contract validation and the shared fixtures everybody develops against.
OWNER: P1.  Everyone's mock fixtures live here or in app/mocks/scenarios.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import contracts as C


# -- allowlists --------------------------------------------------------------


def test_exactly_seven_tools_are_declared():
    assert len(C.TOOL_NAMES) == 7
    assert set(C.TOOL_NAMES) == {
        "kb_search", "read_file", "write_file", "list_dir",
        "run_python", "sheet_op", "docgen",
    }
    assert set(C.TOOL_ARG_MODELS) == set(C.TOOL_NAMES)


def test_there_is_no_shell_or_network_tool():
    for forbidden in ("run_bash", "shell", "http_get", "send_email", "delete_file", "import_module"):
        assert forbidden not in C.TOOL_NAMES


def test_three_agents():
    assert C.AGENT_NAMES == ("vision", "reasoning", "coding")


# -- plan steps --------------------------------------------------------------


def test_plan_step_rejects_an_unallowlisted_tool():
    with pytest.raises(ValidationError):
        C.PlanStep(n=1, kind="tool", target="run_bash", why="nope")


def test_plan_step_rejects_an_unknown_agent():
    with pytest.raises(ValidationError):
        C.PlanStep(n=1, kind="agent", target="planner", why="nope")


def test_plan_step_scope_key():
    step = C.PlanStep(n=1, kind="tool", target="kb_search", why="retrieve")
    assert step.scope_key() == "tool:kb_search"


# -- conventions -------------------------------------------------------------


def test_pages_are_one_indexed():
    with pytest.raises(ValidationError):
        C.Finding(id="f", text="t", page=0, confidence=0.5,
                  source_file="a.pdf", extraction_tier="tesseract")


def test_bbox_must_be_ordered():
    with pytest.raises(ValidationError):
        C.Finding(id="f", text="t", page=1, bbox=[10, 10, 5, 5], confidence=0.5,
                  source_file="a.pdf", extraction_tier="vlm")


def test_confidence_is_bounded():
    with pytest.raises(ValidationError):
        C.VisionOutput(page_legibility=1.4, overall_confidence=0.5)


def test_attempts_are_one_indexed():
    with pytest.raises(ValidationError):
        C.Attempt(n=0, confidence=0.5)


def test_task_envelope_rejects_absolute_paths():
    for bad in ["/etc/passwd", "C:\\Windows\\win.ini", "\\\\server\\share"]:
        with pytest.raises(ValidationError):
            C.TaskEnvelope(session_id="s", task_id="t", text="hi", file_paths=[bad])


def test_terminal_and_resumable_states_are_disjoint():
    assert not (C.TERMINAL_STATES & C.RESUMABLE_STATES)


# -- coding confidence is objective -----------------------------------------


def test_coding_confidence_must_match_exit_code():
    with pytest.raises(ValidationError):
        C.CodingOutput(code="x", exit_code=1, confidence=1.0)
    with pytest.raises(ValidationError):
        C.CodingOutput(code="x", exit_code=0, confidence=0.5)
    ok = C.CodingOutput(code="x", exit_code=0, confidence=1.0)
    assert ok.confidence == 1.0


# -- sheet_op: one tool, four operations, validated per operation ------------


def test_sheet_op_describe_is_minimal():
    args = C.SheetOpArgs(op="describe", path="a.xlsx")
    assert args.op == "describe"


def test_sheet_op_describe_rejects_read_arguments():
    with pytest.raises(ValidationError):
        C.SheetOpArgs(op="describe", path="a.xlsx", sheet="Readings")


def test_sheet_op_compute_requires_a_spec():
    with pytest.raises(ValidationError):
        C.SheetOpArgs(op="compute", path="a.xlsx")
    assert C.SheetOpArgs(op="compute", path="a.xlsx", spec="mean of value").spec


def test_sheet_op_write_requires_data_and_out_path():
    with pytest.raises(ValidationError):
        C.SheetOpArgs(op="write", path="a.xlsx", data={"rows": []})
    with pytest.raises(ValidationError):
        C.SheetOpArgs(op="write", path="a.xlsx", out_path="b.xlsx")


def test_sheet_op_write_never_overwrites_its_input():
    with pytest.raises(ValidationError):
        C.SheetOpArgs(op="write", path="a.xlsx", data={"rows": []}, out_path="a.xlsx")


def test_tool_args_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        C.KbSearchArgs(query="x", kk=3)


# -- fixtures round-trip -----------------------------------------------------


def test_every_scenario_fixture_validates_against_the_contracts():
    from app.mocks import scenarios

    for finding in scenarios.FLAGSHIP_FINDINGS:
        C.Finding(**finding)
    for chunk in scenarios.FLAGSHIP_CHUNKS:
        C.Chunk(**chunk)
    C.ReasoningOutput(**scenarios.REASONING_PAYLOAD)
    C.Chunk(**scenarios.INJECTED_CHUNK)
    for key in scenarios.SCENARIOS:
        sc = scenarios.get_scenario(key)
        assert sc.initial_steps, key
        for step in sc.initial_steps:
            C.PlanStep(**step.model_dump())


def test_failure_state_fixtures():
    """Representative failure states, so nobody has to invent their own."""
    err = C.StructuredError(code=C.ErrorCode.PATH_ESCAPE, message="blocked")
    obs = C.Observation(step_n=1, kind="tool", target="read_file", ok=False,
                        summary="blocked", error=err, iteration=1)
    assert obs.error is not None and obs.ok is False

    escalated = C.AgentResult(agent="vision", model="qwen3-vl:4b", final_confidence=0.41,
                              needs_human_review=True,
                              escalation_reason="below threshold after 3 attempts")
    assert escalated.needs_human_review

    coding_fail = C.CodingOutput(code="x", exit_code=1, confidence=0.0,
                                 stderr="TypeError")
    assert coding_fail.confidence == 0.0


def test_event_envelope_shape():
    event = C.Event(type="route", data={"agent": "vision"}, seq=1, ts="now")
    dumped = event.model_dump()
    assert set(dumped) == {"type", "data", "seq", "ts"}
