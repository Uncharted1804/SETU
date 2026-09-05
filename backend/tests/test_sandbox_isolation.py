r"""
The sandbox honours the per-task workspace root.  OWNER: P1 (the wiring).

`tools/sandbox.py` is P4's and already accepts `workspace_root`; what is tested
here is P1's side of that seam - that `registry.py::_run_python` actually passes
`ctx.workspace`, and that the result is genuine isolation rather than a
plausible-looking argument.

Two layers, because they prove different things:

  * The wiring test runs anywhere. It asserts the call site passes the per-task
    root, which is the one-line change this file exists to guard.
  * The end-to-end tests need Docker and the sandbox image, and are skipped
    cleanly without them. They start REAL containers for two tasks whose input
    files have the SAME relative name and different contents, and assert each
    container reads only its own. An argument can be passed correctly and still
    not isolate anything; only this shows that it does.

Run the end-to-end pair deliberately:

    python -m pytest backend/tests/test_sandbox_isolation.py -q
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import subprocess

import pytest

from app.security.paths import PathEscape
from app.tools.base import ToolContext

# --------------------------------------------------------------------------
# Gate
# --------------------------------------------------------------------------


def _docker_ready() -> bool:
    """Docker running AND the sandbox image present.  Never raises."""
    if shutil.which("docker") is None:
        return False
    try:
        from app import config

        image = config.get_settings().sandbox_image
        for args in (["docker", "version", "--format", "{{.Server.Version}}"],
                     ["docker", "image", "inspect", image]):
            done = subprocess.run(args, capture_output=True, timeout=20)
            if done.returncode != 0:
                return False
        return True
    except Exception:
        return False


_DOCKER = _docker_ready()

needs_docker = pytest.mark.skipif(
    not _DOCKER,
    reason="sandbox end-to-end test: needs Docker running and the sandbox image built",
)

#: Reads the mounted input and prints it, so the container's own view is the
#: evidence rather than anything the host asserts about mounts.
_READ_INPUT = (
    "import pathlib\n"
    "print('SEES:' + pathlib.Path('/inputs/data.csv').read_text().strip())\n"
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _real_settings(env):
    """run_python only exists in the REAL registry; the mock registry swaps it."""
    return dataclasses.replace(env, mock_mode=False)


def _task_with_input(settings, task_id: str, content: str) -> ToolContext:
    ctx = ToolContext(settings=settings, task_id=task_id, session_id="s_1", mock=False)
    ctx.ensure_root()
    target = ctx.workspace / "uploads" / "data.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ctx


def _run_python(ctx, input_paths, code=_READ_INPUT, timeout=15):
    from app.tools.registry import TOOL_ARG_MODELS, build_registry

    spec = build_registry(ctx.settings).get("run_python")
    args = TOOL_ARG_MODELS["run_python"](
        code=code, timeout=timeout, input_paths=list(input_paths)
    )
    return asyncio.run(spec.handler(args, ctx))


# --------------------------------------------------------------------------
# The wiring - runs everywhere, no Docker
# --------------------------------------------------------------------------


def test_run_python_passes_the_task_root_as_workspace_root(env, monkeypatch):
    """The one-line change in registry.py::_run_python, asserted directly.

    Without it, run_in_sandbox falls back to settings.workspace and resolves
    input_paths against the SHARED workspace, so one task could mount another's
    file simply by naming it.
    """
    from app.tools import sandbox
    from app.tools.registry import TOOL_ARG_MODELS, build_registry

    seen: dict = {}

    async def spy(code, settings, timeout_s=15, input_paths=None, workspace_root=None):
        seen.update(
            code=code, timeout_s=timeout_s, input_paths=input_paths,
            workspace_root=workspace_root,
        )
        from app.contracts import CodingOutput

        return CodingOutput(
            code=code, stdout="", stderr="", exit_code=0, confidence=1.0,
            duration_ms=0.0, sandbox_command=[],
        )

    # Patched before build_registry, because _real_specs imports the symbol
    # inside the factory rather than at module scope.
    monkeypatch.setattr(sandbox, "run_in_sandbox", spy)

    settings = _real_settings(env)
    ctx = ToolContext(settings=settings, task_id="t_aaaaaa", session_id="s_1", mock=False)
    spec = build_registry(settings).get("run_python")
    args = TOOL_ARG_MODELS["run_python"](
        code="print(1)", timeout=15, input_paths=["uploads/data.csv"]
    )
    asyncio.run(spec.handler(args, ctx))

    assert seen["workspace_root"] == ctx.workspace
    assert seen["workspace_root"] != settings.workspace, (
        "the sandbox was handed the shared workspace, not this task's root"
    )
    assert seen["workspace_root"].name == "t_aaaaaa"


def test_two_tasks_hand_the_sandbox_different_roots(env, monkeypatch):
    from app.tools import sandbox
    from app.tools.registry import TOOL_ARG_MODELS, build_registry

    roots: list = []

    async def spy(code, settings, timeout_s=15, input_paths=None, workspace_root=None):
        roots.append(workspace_root)
        from app.contracts import CodingOutput

        return CodingOutput(
            code=code, stdout="", stderr="", exit_code=0, confidence=1.0,
            duration_ms=0.0, sandbox_command=[],
        )

    monkeypatch.setattr(sandbox, "run_in_sandbox", spy)
    settings = _real_settings(env)
    spec = build_registry(settings).get("run_python")
    args = TOOL_ARG_MODELS["run_python"](code="print(1)", timeout=15, input_paths=[])

    for task_id in ("t_aaaaaa", "t_bbbbbb"):
        ctx = ToolContext(settings=settings, task_id=task_id, session_id="s_1", mock=False)
        asyncio.run(spec.handler(args, ctx))

    assert roots[0] != roots[1]
    assert [r.name for r in roots] == ["t_aaaaaa", "t_bbbbbb"]


def test_a_cross_task_input_path_is_refused_before_docker_is_touched(env):
    """Path resolution happens before the image probe, so an escape never runs
    a container - it raises whether or not Docker is installed."""
    settings = _real_settings(env)
    a = _task_with_input(settings, "t_aaaaaa", "ALPHA")
    _task_with_input(settings, "t_bbbbbb", "BRAVO")

    with pytest.raises(PathEscape):
        _run_python(a, ["../t_bbbbbb/uploads/data.csv"], code="print(1)")


# --------------------------------------------------------------------------
# End to end - real containers
# --------------------------------------------------------------------------


@needs_docker
def test_each_task_sandbox_reads_only_its_own_input_file(env):
    """Two tasks, the SAME input path, different contents, real containers.

    The assertion is on what the container printed, not on what the host
    intended to mount.
    """
    settings = _real_settings(env)
    a = _task_with_input(settings, "t_aaaaaa", "ALPHA-ONLY-SECRET")
    b = _task_with_input(settings, "t_bbbbbb", "BRAVO-ONLY-SECRET")

    out_a = _run_python(a, ["uploads/data.csv"])
    out_b = _run_python(b, ["uploads/data.csv"])

    assert out_a["exit_code"] == 0, out_a["stderr"]
    assert out_b["exit_code"] == 0, out_b["stderr"]

    assert "SEES:ALPHA-ONLY-SECRET" in out_a["stdout"]
    assert "SEES:BRAVO-ONLY-SECRET" in out_b["stdout"]

    # The isolation claim, stated as a leak check.
    assert "BRAVO-ONLY-SECRET" not in out_a["stdout"], "task A read task B's file"
    assert "ALPHA-ONLY-SECRET" not in out_b["stdout"], "task B read task A's file"


@needs_docker
def test_the_mounted_host_path_is_inside_the_calling_tasks_root(env):
    """Same run, checked from the host side: the -v argument must point into
    this task's directory and no other."""
    settings = _real_settings(env)
    a = _task_with_input(settings, "t_aaaaaa", "ALPHA-ONLY-SECRET")
    _task_with_input(settings, "t_bbbbbb", "BRAVO-ONLY-SECRET")

    out_a = _run_python(a, ["uploads/data.csv"])
    mounts = [str(c) for c in (out_a["sandbox_command"] or []) if "/inputs/" in str(c)]

    assert mounts, "no input mount appeared in the sandbox command"
    joined = " ".join(mounts)
    assert "t_aaaaaa" in joined
    assert "t_bbbbbb" not in joined, "the sandbox was pointed at another task's root"
    assert joined.endswith(":ro"), "input mounts must stay read-only"
