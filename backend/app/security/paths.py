"""
The path jail.  OWNER: P4.  Used by every filesystem surface in SETU.

ONE rule: the agent's writable world is exactly one directory.  Uploads,
spreadsheet inputs, generated documents and artifact downloads all resolve
through `jail()`.  There is no second code path.

Why `resolve()` after joining, not before: resolving the joined path collapses
`..` segments AND follows symlinks, so a symlink inside the workspace pointing
at C:\\Windows is caught by the same containment check that catches
`../../etc/passwd`.  Checking the raw string for ".." would not.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

from ..contracts import ErrorCode, StructuredError


class PathEscape(PermissionError):
    """Raised when a path resolves outside the workspace root."""

    def __init__(self, requested: str, message: str = "") -> None:
        self.requested = requested
        super().__init__(message or ("path escape blocked: " + requested))

    def as_error(self) -> StructuredError:
        return StructuredError(
            code=ErrorCode.PATH_ESCAPE,
            message=str(self),
            detail={"requested": self.requested},
            retryable=False,
        )


def jail(rel: str, root: Path) -> Path:
    """Resolve `rel` inside `root`, or raise PathEscape.

    Accepts only workspace-relative paths (contracts.py convention 1).  An
    absolute path, a drive letter or a UNC prefix is rejected up front - not
    because joining would be unsafe, but because accepting one would mean the
    caller's mental model is wrong.
    """
    if rel is None:
        raise PathEscape("<none>", "path is required")
    text = str(rel).strip().replace("\\", "/")
    if not text:
        text = "."
    if text.startswith("/") or text.startswith("//"):
        raise PathEscape(rel, "absolute paths are not accepted: " + str(rel))
    if re.match(r"^[A-Za-z]:", text):
        raise PathEscape(rel, "drive-qualified paths are not accepted: " + str(rel))

    root_resolved = root.resolve()
    target = (root_resolved / text).resolve()

    # is_relative_to covers the joined-and-resolved result, so both `..`
    # traversal and symlink escapes land here.
    if target != root_resolved and not target.is_relative_to(root_resolved):
        raise PathEscape(rel)
    return target


def to_rel(path: Path, root: Path) -> str:
    """Inverse of jail(): a POSIX-style workspace-relative string."""
    return path.resolve().relative_to(root.resolve()).as_posix()


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_storage_name(original: str, prefix: str = "") -> str:
    """Server-controlled storage name for an uploaded or generated file.

    The client's filename is never used as a path component.  We keep a
    sanitised stem for human recognisability and append a short content-free
    random suffix supplied by the caller via `prefix`.
    """
    name = unicodedata.normalize("NFKD", Path(str(original)).name)
    name = name.encode("ascii", "ignore").decode("ascii")
    stem = Path(name).stem or "file"
    suffix = Path(name).suffix.lower()
    stem = _SAFE.sub("_", stem)[:48].strip("._-") or "file"
    suffix = _SAFE.sub("", suffix)[:12]
    return (prefix + stem + suffix) if prefix else (stem + suffix)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def ensure_workspace(root: Path) -> Path:
    """Create the workspace and its standard subdirectories if absent."""
    root = root.resolve()
    for sub in ("", "uploads", "artifacts", "scratch"):
        (root / sub if sub else root).mkdir(parents=True, exist_ok=True)
    return root


def is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    root_resolved = root.resolve()
    return resolved == root_resolved or resolved.is_relative_to(root_resolved)


__all__ = [
    "PathEscape",
    "jail",
    "to_rel",
    "safe_storage_name",
    "sha256_file",
    "ensure_workspace",
    "is_within",
    "os",
]
