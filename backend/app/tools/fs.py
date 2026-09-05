"""
Filesystem tools: read_file, write_file, list_dir.  OWNER: P4.

Three of the seven.  There is no delete_file, no move, no chmod, and no path
argument anywhere that is not passed through the jail first.

These are REAL implementations in both mock and real mode - a file read is a
file read, and mocking it would hide the one thing the path jail exists to
prove.  What mock mode changes is the models and the sandbox, not the disk.
"""

from __future__ import annotations

import hashlib

from ..contracts import ErrorCode, ListDirArgs, ReadFileArgs, WriteFileArgs, WriteResult
from ..security.paths import PathEscape, to_rel
from .base import ToolContext, ToolError, media_type_for


def read_file(args: ReadFileArgs, ctx: ToolContext) -> dict:
    try:
        target = ctx.resolve(args.path)
    except PathEscape as exc:
        raise ToolError(ErrorCode.PATH_ESCAPE, str(exc), requested=args.path) from exc
    if not target.is_file():
        raise ToolError(ErrorCode.NOT_FOUND, "no such file: " + args.path, path=args.path)
    raw = target.read_bytes()[: args.max_bytes]
    try:
        text = raw.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        binary = True
    return {
        "path": to_rel(target, ctx.workspace),
        "content": text,
        "truncated": target.stat().st_size > args.max_bytes,
        "binary": binary,
        "bytes": len(raw),
    }


def write_file(args: WriteFileArgs, ctx: ToolContext) -> dict:
    """Write inside the jail.

    NOTE for the orchestrator: this tool is marked `requires_approval=True` in
    the registry.  The human sees the ACTUAL content before it is committed -
    approving a filename alone is not Layer 4.
    """
    try:
        target = ctx.resolve(args.path)
    except PathEscape as exc:
        raise ToolError(ErrorCode.PATH_ESCAPE, str(exc), requested=args.path) from exc
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = args.content.encode("utf-8")
    target.write_bytes(data)
    result = WriteResult(
        path=to_rel(target, ctx.workspace),
        bytes_written=len(data),
        created=not existed,
        sha256="sha256:" + hashlib.sha256(data).hexdigest(),
    )
    ctx.register_artifact(target, media_type_for(target), simulated=False)
    return result.model_dump()


def list_dir(args: ListDirArgs, ctx: ToolContext) -> dict:
    try:
        target = ctx.resolve(args.path)
    except PathEscape as exc:
        raise ToolError(ErrorCode.PATH_ESCAPE, str(exc), requested=args.path) from exc
    if not target.is_dir():
        raise ToolError(ErrorCode.NOT_FOUND, "no such directory: " + args.path, path=args.path)
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        entries.append(
            {
                "name": child.name,
                "path": to_rel(child, ctx.workspace),
                "is_dir": child.is_dir(),
                "size_bytes": child.stat().st_size if child.is_file() else 0,
            }
        )
    return {"path": to_rel(target, ctx.workspace), "entries": entries, "count": len(entries)}
