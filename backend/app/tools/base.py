"""
Shared plumbing for the seven tools.  OWNER: P1 (the context shape), tool
authors own their handlers.

A tool is a typed Python function.  It is invoked by the MODEL's proposal but
DISPATCHED by the orchestrator - never by another tool.  Tools therefore do not
look up the registry and do not call each other.  Shared implementation
SERVICES are fine and expected: sheet_op("compute") uses the same sandbox runner
that backs run_python, because that is one implementation, not a tool calling a
tool.

WORKSPACE ISOLATION.  `ToolContext.workspace` is the root of ONE TASK
(`<workspace>/tasks/<task_id>`), not the shared workspace.  Every filesystem
touch in every tool goes through `ctx.resolve()` -> `jail(rel, ctx.workspace)`,
so this single property is what stops one task reading or listing another's
files.  Two consequences worth knowing before you change anything here:

  * Artifact paths recorded by `register_artifact` are relative to the TASK
    root, so the download route must resolve against the same root.
  * Uploads are copied into the task root by `service.create_task` and the
    envelope's paths are rewritten before the task is stored, so an agent or
    tool only ever sees a task-relative path.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import Settings
from ..contracts import ArtifactRef, ErrorCode, StructuredError
from ..security.paths import PathEscape, jail, safe_storage_name, to_rel


def task_root(workspace: Path, task_id: str) -> Path:
    """The per-task filesystem root: `<workspace>/tasks/<task_id>`.

    One definition, used by ToolContext, by the executor's eager mkdir and by
    the artifact download route, so the three cannot drift apart.

    `task_id` reaches this from a URL path parameter on the download route, so
    it is validated as a SINGLE path component rather than merely jailed.
    `jail()` on its own is not enough here: "tasks/../other" resolves to
    `<workspace>/other`, which is still inside the workspace, so jail would
    allow it - escaping tasks/ and letting a crafted id aim a task root at the
    shared uploads/ staging area. The jail call stays as the second line of
    defence.
    """
    text = str(task_id).strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise PathEscape(
            task_id, "task_id must be a single path component, got %r" % (task_id,)
        )
    return jail("tasks/" + text, workspace)


class ToolError(Exception):
    """Raised inside a handler.  The dispatcher converts it to an observation."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)

    def as_error(self) -> StructuredError:
        return StructuredError(
            code=self.code,
            message=self.message,
            detail=self.detail,
            retryable=self.code in {ErrorCode.TOOL_FAILED, ErrorCode.SANDBOX_TIMEOUT},
        )


@dataclass
class ToolContext:
    """Everything a handler is allowed to know about the run.

    Deliberately NOT included: the plan, the registry, the event bus.  A tool
    that could see the plan would be tempted to change it.
    """

    settings: Settings
    task_id: str
    session_id: str
    #: Called by a handler that produced a file.  The orchestrator turns these
    #: into `artifact` events and download links.
    artifacts: list[ArtifactRef] = field(default_factory=list)
    #: Set by the executor so a handler can label simulated output.
    mock: bool = True

    @property
    def workspace(self) -> Path:
        """THIS TASK's root, not the shared workspace.

        Moving this one property is what isolates tasks from each other: every
        tool path resolves through `resolve()` below, and `jail` confines each
        one to whatever this returns.
        """
        return task_root(self.settings.workspace, self.task_id)

    def ensure_root(self) -> Path:
        """Create this task's root now, rather than on the first write.

        The executor calls this before the first step runs so that a plan
        opening with `list_dir(".")` gets an empty listing instead of failing on
        a directory nothing has created yet.
        """
        root = self.workspace
        root.mkdir(parents=True, exist_ok=True)
        return root

    def resolve(self, rel: str) -> Path:
        """Every filesystem touch in every tool goes through here."""
        return jail(rel, self.workspace)

    def new_artifact_name(self, original: str) -> str:
        return safe_storage_name(original, prefix=secrets.token_hex(3) + "_")

    def register_artifact(self, path: Path, media_type: str, simulated: bool = False) -> ArtifactRef:
        data = path.read_bytes()
        ref = ArtifactRef(
            artifact_id="a_" + secrets.token_hex(6),
            task_id=self.task_id,
            name=path.name,
            path=to_rel(path, self.workspace),
            media_type=media_type,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            simulated=simulated,
        )
        self.artifacts.append(ref)
        return ref


#: A handler takes validated args plus the context and returns a JSON-able dict.
Handler = Callable[[Any, ToolContext], dict]


MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".csv": "text/csv",
}


def media_type_for(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def truncate(text: str, limit: int = 400) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def optional_import(module: str, owner: str, purpose: str):
    """Import a heavyweight dependency LAZILY, with a useful failure.

    Nothing heavy is imported at module scope anywhere in the tool layer, so
    mock mode starts without chromadb, torch, pymupdf or docker present.
    """
    try:
        import importlib

        return importlib.import_module(module)
    except ImportError as exc:
        raise ToolError(
            ErrorCode.NOT_IMPLEMENTED,
            "%s requires %r (%s). Install it or run in mock mode "
            "(SETU_MOCK_MODE=1). Owner: %s." % (purpose, module, exc, owner),
        ) from exc
