"""
Registry allowlist tests.  OWNER: P1.

The "exactly seven tools" claim in the pitch has to be true in code, in both
mock and real mode, or it is a slide rather than an architecture.
"""

from __future__ import annotations

import pytest

from app.contracts import TOOL_NAMES
from app.tools.base import ToolContext, ToolError
from app.tools.registry import ToolRegistry, build_registry


def test_mock_registry_exposes_exactly_seven(env):
    reg = build_registry(env)
    assert [s.name for s in reg.specs] == list(TOOL_NAMES)


def test_real_registry_exposes_exactly_seven(env, monkeypatch):
    from app import config

    monkeypatch.setenv("SETU_MOCK_MODE", "0")
    config.reset_caches()
    real = config.get_settings()
    reg = build_registry(real)
    assert [s.name for s in reg.specs] == list(TOOL_NAMES)


def test_registry_refuses_an_eighth_tool(env):
    reg = build_registry(env)
    specs = reg.specs
    with pytest.raises(RuntimeError):
        ToolRegistry(specs + [specs[0]])


def test_registry_refuses_a_missing_tool(env):
    reg = build_registry(env)
    with pytest.raises(RuntimeError):
        ToolRegistry(reg.specs[:-1])


def test_unknown_tool_is_rejected(env):
    reg = build_registry(env)
    with pytest.raises(ToolError) as exc:
        reg.get("run_bash")
    assert "allowlist" in str(exc.value)


def test_every_tool_has_a_json_schema(env):
    reg = build_registry(env)
    for schema in reg.schemas():
        assert schema["name"] in TOOL_NAMES
        assert schema["description"]
        assert "properties" in schema["parameters"]


def test_arguments_are_validated_before_the_handler_runs(env):
    reg = build_registry(env)
    with pytest.raises(ToolError) as exc:
        reg.parse_args("kb_search", {"query": "x", "unexpected": 1})
    assert exc.value.code == "INVALID_ARGS"


def test_write_tools_require_approval(env):
    reg = build_registry(env)
    assert reg.get("write_file").requires_approval
    assert reg.get("docgen").requires_approval
    assert not reg.get("list_dir").requires_approval


def test_code_executing_tools_are_marked(env):
    reg = build_registry(env)
    assert reg.get("run_python").executes_code
    assert reg.get("sheet_op").executes_code


def test_every_tool_has_an_owner(env):
    reg = build_registry(env)
    for spec in reg.specs:
        assert spec.owner in {"P1", "P2", "P3", "P4", "P5", "P6"}


def test_agent_registry_matches_the_declared_agents(env):
    from app.agents import build_agents
    from app.config import get_registry

    agents = build_agents(env, get_registry())
    assert agents.names() == ["vision", "reasoning", "coding"]


def test_mock_run_python_never_claims_a_container_ran(env):
    import asyncio

    from app.contracts import RunPythonArgs

    reg = build_registry(env)
    ctx = ToolContext(settings=env, task_id="t_1", session_id="s_1")
    out = asyncio.run(reg.call("run_python", {"code": "print(1)"}, ctx))
    assert out["sandbox_available"] is False
    assert out["simulated"] is True
    _ = RunPythonArgs
