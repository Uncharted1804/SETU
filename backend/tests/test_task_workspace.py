r"""
Per-task workspace isolation.  OWNER: P1.

Before this, every task shared one `workspace/` directory: one task could
`list_dir(".")` and see another's uploads and artifacts, and a path recorded by
one task resolved just as well while serving another. `ToolContext.workspace`
now points at `<workspace>/tasks/<task_id>`, and everything downstream inherits
it because every filesystem touch in every tool goes through
`ctx.resolve()` -> `jail(rel, ctx.workspace)`.

Three things are asserted here, and the third matters as much as the first two:
the isolation is real, the upload claim is checked, and the pre-existing path
jail still behaves exactly as it did. Isolation that quietly weakened traversal
protection would be a bad trade.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.contracts import TaskCreateRequest
from app.security.paths import PathEscape
from app.tools.base import ToolContext, task_root


# --------------------------------------------------------------------------
# Roots
# --------------------------------------------------------------------------


def _ctx(env, task_id, session_id="s_1"):
    return ToolContext(settings=env, task_id=task_id, session_id=session_id, mock=True)


def test_different_task_ids_resolve_to_different_roots(env):
    a = _ctx(env, "t_aaaaaa")
    b = _ctx(env, "t_bbbbbb")

    assert a.workspace != b.workspace
    assert a.workspace.name == "t_aaaaaa"
    assert b.workspace.name == "t_bbbbbb"
    # Both under the shared workspace, both under tasks/.
    assert a.workspace.parent == b.workspace.parent == env.workspace.resolve() / "tasks"


def test_the_task_root_is_not_the_shared_workspace(env):
    ctx = _ctx(env, "t_aaaaaa")

    assert ctx.workspace != env.workspace.resolve(), (
        "ToolContext.workspace still points at the shared workspace; "
        "nothing is isolated"
    )


def test_ensure_root_creates_the_directory_eagerly(env):
    ctx = _ctx(env, "t_aaaaaa")
    assert not ctx.workspace.exists()

    created = ctx.ensure_root()

    assert created.is_dir()
    assert created == ctx.workspace


def test_a_first_list_dir_succeeds_and_is_empty_before_any_write(env):
    """The reason ensure_root() is eager rather than lazy.

    A plan whose first step is list_dir(".") must get an empty listing, not an
    error about a directory that no write has created yet.
    """
    from app.tools.fs import list_dir
    from app.tools.registry import TOOL_ARG_MODELS

    ctx = _ctx(env, "t_aaaaaa")
    ctx.ensure_root()

    args = TOOL_ARG_MODELS["list_dir"](path=".")
    result = list_dir(args, ctx)

    assert result["entries"] == []


# --------------------------------------------------------------------------
# One task cannot reach another's files
# --------------------------------------------------------------------------


def test_a_task_cannot_resolve_a_path_into_another_task(env):
    """`..` out of a task root is an escape like any other."""
    a = _ctx(env, "t_aaaaaa")
    a.ensure_root()
    _ctx(env, "t_bbbbbb").ensure_root()

    for attempt in ("../t_bbbbbb/secret.txt", "../../tasks/t_bbbbbb/secret.txt", ".."):
        with pytest.raises(PathEscape):
            a.resolve(attempt)


def test_a_task_cannot_list_another_tasks_files(env):
    """The isolation property stated as the operator would experience it."""
    from app.tools.fs import list_dir, write_file
    from app.tools.registry import TOOL_ARG_MODELS

    a = _ctx(env, "t_aaaaaa")
    b = _ctx(env, "t_bbbbbb")
    a.ensure_root()
    b.ensure_root()

    write_file(TOOL_ARG_MODELS["write_file"](path="secret.txt", content="task A only"), a)

    a_entries = [e["name"] for e in list_dir(TOOL_ARG_MODELS["list_dir"](path="."), a)["entries"]]
    b_entries = [e["name"] for e in list_dir(TOOL_ARG_MODELS["list_dir"](path="."), b)["entries"]]

    assert "secret.txt" in a_entries
    assert b_entries == [], "task B can see task A's files; the roots are not isolated"


def test_a_task_cannot_read_another_tasks_file_by_name(env):
    from app.tools.fs import read_file, write_file
    from app.tools.registry import TOOL_ARG_MODELS
    from app.tools.base import ToolError

    a = _ctx(env, "t_aaaaaa")
    b = _ctx(env, "t_bbbbbb")
    a.ensure_root()
    b.ensure_root()
    write_file(TOOL_ARG_MODELS["write_file"](path="secret.txt", content="task A only"), a)

    with pytest.raises((ToolError, PathEscape, FileNotFoundError)):
        read_file(TOOL_ARG_MODELS["read_file"](path="secret.txt"), b)


# --------------------------------------------------------------------------
# The pre-existing jail is unchanged
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attempt",
    ["../secret.txt", "a/../../b", "uploads/../../outside.txt", "..", "../",
     "/etc/passwd", "C:/Windows/system32/config/sam"],
)
def test_existing_traversal_protections_still_hold(env, attempt):
    """Same cases as test_jail.py, now against a task root.

    Isolation must not have been bought by relaxing the jail.
    """
    ctx = _ctx(env, "t_aaaaaa")
    ctx.ensure_root()

    with pytest.raises(PathEscape):
        ctx.resolve(attempt)


def test_a_crafted_task_id_cannot_escape_the_workspace(env):
    """`task_id` reaches task_root() from a URL path parameter on the download
    route, so it is jailed rather than joined."""
    for bad in ("../..", "../other", "/abs", "C:/Windows"):
        with pytest.raises(PathEscape):
            task_root(env.workspace, bad)

    with pytest.raises(PathEscape):
        task_root(env.workspace, "")


def test_a_normal_relative_path_still_resolves(env):
    ctx = _ctx(env, "t_aaaaaa")
    ctx.ensure_root()

    assert ctx.resolve("uploads/report.pdf").parent == ctx.workspace / "uploads"


# --------------------------------------------------------------------------
# Staged-upload ownership
# --------------------------------------------------------------------------


def test_an_upload_staged_under_another_session_is_rejected(service, env):
    """Session A stages a file; session B may not claim it."""
    staged = env.workspace / "uploads" / "abc123_scan.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"%PDF-1.4 x")
    service.uploads.stage("uploads/abc123_scan.pdf", "session_A")

    with pytest.raises(HTTPException) as caught:
        service.create_task(
            TaskCreateRequest(
                text="read this", session_id="session_B",
                file_paths=["uploads/abc123_scan.pdf"], scenario="flagship",
            )
        )

    assert caught.value.status_code == 400
    assert "different session" in str(caught.value.detail)


def test_an_unstaged_file_path_is_rejected(service):
    """Never staged at all - refused, not silently skipped."""
    with pytest.raises(HTTPException) as caught:
        service.create_task(
            TaskCreateRequest(
                text="read this", session_id="session_A",
                file_paths=["uploads/never_staged.pdf"], scenario="flagship",
            )
        )

    assert caught.value.status_code == 400
    assert "never staged" in str(caught.value.detail)


def test_the_whole_request_is_rejected_not_just_the_bad_entry(service, env):
    """One bad path fails the task. A partially-honoured attachment list would
    give the operator a task that quietly ignored their file."""
    good = env.workspace / "uploads" / "ok.pdf"
    good.parent.mkdir(parents=True, exist_ok=True)
    good.write_bytes(b"%PDF-1.4 x")
    service.uploads.stage("uploads/ok.pdf", "session_A")

    with pytest.raises(HTTPException):
        service.create_task(
            TaskCreateRequest(
                text="read these", session_id="session_A",
                file_paths=["uploads/ok.pdf", "uploads/never_staged.pdf"],
                scenario="flagship",
            )
        )

    assert not list((env.workspace / "tasks").glob("*/uploads/ok.pdf")), (
        "a rejected request still copied a file into a task root"
    )


# --------------------------------------------------------------------------
# Materialisation and path rewriting
# --------------------------------------------------------------------------


def test_a_valid_upload_is_copied_in_and_the_path_rewritten(service, env):
    staged = env.workspace / "uploads" / "abc123_scan.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"%PDF-1.4 hello")
    service.uploads.stage("uploads/abc123_scan.pdf", "session_A")

    record, _decision, _planner = service.create_task(
        TaskCreateRequest(
            text="read this", session_id="session_A",
            file_paths=["uploads/abc123_scan.pdf"], scenario="flagship",
        )
    )

    # Rewritten to a task-relative path before the record was stored.
    assert record.envelope.file_paths == ["uploads/abc123_scan.pdf"]
    copied = task_root(env.workspace, record.task_id) / "uploads" / "abc123_scan.pdf"
    assert copied.is_file()
    assert copied.read_bytes() == b"%PDF-1.4 hello"

    # The staging copy is left alone; the task reads its own.
    assert staged.is_file()
    assert copied != staged


def test_the_rewritten_path_resolves_inside_the_task_root(service, env):
    staged = env.workspace / "uploads" / "abc123_scan.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"%PDF-1.4 hello")
    service.uploads.stage("uploads/abc123_scan.pdf", "session_A")

    record, _d, _p = service.create_task(
        TaskCreateRequest(
            text="read this", session_id="session_A",
            file_paths=["uploads/abc123_scan.pdf"], scenario="flagship",
        )
    )
    ctx = _ctx(env, record.task_id, record.envelope.session_id)

    resolved = ctx.resolve(record.envelope.file_paths[0])
    assert resolved.is_file()
    assert resolved.is_relative_to(ctx.workspace)


def test_a_generated_session_id_still_owns_its_uploads(service, env):
    """When the caller sends no session_id, one is generated - and an upload
    staged under an older session cannot be claimed by it."""
    staged = env.workspace / "uploads" / "abc123_scan.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"%PDF-1.4 x")
    service.uploads.stage("uploads/abc123_scan.pdf", "session_A")

    with pytest.raises(HTTPException) as caught:
        service.create_task(
            TaskCreateRequest(
                text="read this", file_paths=["uploads/abc123_scan.pdf"],
                scenario="flagship",
            )
        )

    assert caught.value.status_code == 400


def test_an_upload_staged_without_a_session_cannot_be_claimed(service, env):
    """POST /api/upload accepts session_id as optional. An upload with no owner
    is not claimable by anyone, rather than claimable by everyone."""
    staged = env.workspace / "uploads" / "orphan.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"%PDF-1.4 x")
    service.uploads.stage("uploads/orphan.pdf", None)

    with pytest.raises(HTTPException) as caught:
        service.create_task(
            TaskCreateRequest(
                text="read this", session_id="session_A",
                file_paths=["uploads/orphan.pdf"], scenario="flagship",
            )
        )

    assert caught.value.status_code == 400


def test_no_file_paths_is_still_a_valid_task(service):
    record, _d, _p = service.create_task(
        TaskCreateRequest(text="draft an approval note", scenario="flagship")
    )

    assert record.envelope.file_paths == []


# --------------------------------------------------------------------------
# Upload endpoint records ownership
# --------------------------------------------------------------------------


def test_the_upload_endpoint_records_the_session(client):
    r = client.post(
        "/api/upload",
        files={"file": ("scan.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"session_id": "session_A"},
    )
    assert r.status_code == 200
    rel = r.json()["path"]

    service = client.app.state.service
    staged = service.uploads.get(rel)

    assert staged is not None, "upload was not staged; session_id is still unused"
    assert staged.session_id == "session_A"
    assert staged.uploaded_at


def test_an_upload_and_task_in_the_same_session_round_trips(client):
    """The path an operator actually walks: upload, then create a task."""
    up = client.post(
        "/api/upload",
        files={"file": ("scan.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"session_id": "session_A"},
    )
    rel = up.json()["path"]

    created = client.post(
        "/api/tasks",
        json={"text": "draft an approval note", "session_id": "session_A",
              "file_paths": [rel], "scenario": "flagship"},
    )

    assert created.status_code == 201, created.text


def test_a_cross_session_task_creation_is_a_400_over_http(client):
    up = client.post(
        "/api/upload",
        files={"file": ("scan.pdf", b"%PDF-1.4 x", "application/pdf")},
        data={"session_id": "session_A"},
    )
    rel = up.json()["path"]

    created = client.post(
        "/api/tasks",
        json={"text": "draft an approval note", "session_id": "session_B",
              "file_paths": [rel], "scenario": "flagship"},
    )

    assert created.status_code == 400
    assert "different session" in created.text
