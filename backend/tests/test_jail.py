"""
Path jail tests.  OWNER: P4.

The four-second demo that answers the objection every PSU judge forms within
four seconds of seeing an autonomous agent with file access.
"""

from __future__ import annotations

import os

import pytest

from app.security.paths import PathEscape, ensure_workspace, jail, safe_storage_name, to_rel


@pytest.fixture()
def root(tmp_path):
    return ensure_workspace(tmp_path / "workspace")


def test_a_normal_relative_path_resolves(root):
    target = jail("uploads/report.pdf", root)
    assert target.parent == (root / "uploads")


def test_dot_resolves_to_the_root(root):
    assert jail(".", root) == root.resolve()


def test_traversal_is_blocked(root):
    with pytest.raises(PathEscape):
        jail("../../etc/passwd", root)


@pytest.mark.parametrize(
    "bad",
    ["../secret.txt", "a/../../b", "uploads/../../outside.txt", "..", "../"],
)
def test_every_traversal_shape_is_blocked(root, bad):
    with pytest.raises(PathEscape):
        jail(bad, root)


def test_backslash_traversal_is_blocked(root):
    with pytest.raises(PathEscape):
        jail("..\\..\\windows\\win.ini", root)


def test_absolute_paths_are_rejected(root):
    for bad in ["/etc/passwd", "C:\\Windows\\win.ini", "//server/share"]:
        with pytest.raises(PathEscape):
            jail(bad, root)


def test_resolved_symlink_escape_is_blocked(root, tmp_path):
    """resolve() is called AFTER joining, so a symlink pointing outside the
    workspace is caught by the same containment check as `..`."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified", encoding="utf-8")
    link = root / "escape"
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this platform")
    with pytest.raises(PathEscape):
        jail("escape/secret.txt", root)


def test_to_rel_is_the_inverse(root):
    target = jail("artifacts/note.docx", root)
    assert to_rel(target, root) == "artifacts/note.docx"


def test_storage_names_are_server_controlled():
    """A client filename is never used as a path component."""
    assert "/" not in safe_storage_name("../../evil.txt")
    assert "\\" not in safe_storage_name("..\\..\\evil.txt")
    assert safe_storage_name("../../evil.txt").endswith(".txt")
    assert safe_storage_name("réport final.pdf").endswith(".pdf")
    assert " " not in safe_storage_name("réport final.pdf")


def test_storage_name_prefix_is_applied():
    name = safe_storage_name("scan.pdf", prefix="abc123_")
    assert name.startswith("abc123_")


# -- the same jail governs the tools ----------------------------------------


def test_read_file_tool_blocks_escape(env):
    from app.contracts import ReadFileArgs
    from app.tools.base import ToolContext, ToolError
    from app.tools.fs import read_file

    ctx = ToolContext(settings=env, task_id="t_1", session_id="s_1")
    with pytest.raises(ToolError) as exc:
        read_file(ReadFileArgs(path="../../etc/passwd"), ctx)
    assert exc.value.code == "PATH_ESCAPE"


def test_write_file_tool_blocks_escape(env):
    from app.contracts import WriteFileArgs
    from app.tools.base import ToolContext, ToolError
    from app.tools.fs import write_file

    ctx = ToolContext(settings=env, task_id="t_1", session_id="s_1")
    with pytest.raises(ToolError) as exc:
        write_file(WriteFileArgs(path="../escape.txt", content="x"), ctx)
    assert exc.value.code == "PATH_ESCAPE"


def test_write_then_read_round_trip(env):
    from app.contracts import ReadFileArgs, WriteFileArgs
    from app.tools.base import ToolContext
    from app.tools.fs import read_file, write_file

    ctx = ToolContext(settings=env, task_id="t_1", session_id="s_1")
    result = write_file(WriteFileArgs(path="notes/a.txt", content="hello"), ctx)
    assert result["created"] is True
    assert read_file(ReadFileArgs(path="notes/a.txt"), ctx)["content"] == "hello"
