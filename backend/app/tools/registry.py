"""
The tool registry.  OWNER: P1.

EXACTLY SEVEN entries.  There is no run_bash, no HTTP tool, no email tool, no
delete_file, and no dynamic import.  These absences are the architecture, not an
oversight, and `test_registry.py` asserts the count and the exact names so a
well-meaning eighth tool cannot land unnoticed.

A registry entry is: name, description, validated argument model, handler,
result convention, and execution metadata.  The handler receives a PARSED args
model - never a raw dict - so a malformed model proposal fails validation
before any code runs.

Real vs mock handlers are chosen by `build_registry(settings)`, which is the
single place the two worlds diverge.  Everything downstream - dispatcher,
approval flow, audit, SSE - is identical in both modes.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..config import Settings
from ..contracts import (
    TOOL_ARG_MODELS,
    TOOL_NAMES,
    ErrorCode,
    StructuredError,
)
from .base import ToolContext, ToolError


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type
    handler: Callable[..., Any]
    owner: str
    #: Layer 4: the human reviews the ACTUAL content before it is committed.
    requires_approval: bool = False
    #: True when this handler can execute generated code.
    executes_code: bool = False
    #: True when the handler is a deterministic stand-in, not the real thing.
    simulated: bool = False
    #: Longest the dispatcher will wait before treating the call as failed.
    timeout_s: float = 60.0

    def json_schema(self) -> dict:
        """What a function-calling model is shown."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        names = [s.name for s in specs]
        if sorted(names) != sorted(TOOL_NAMES):
            raise RuntimeError(
                "tool registry must expose exactly the seven allowlisted tools; "
                "got %s" % names
            )
        self._specs = {s.name: s for s in specs}

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def get(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise ToolError(
                ErrorCode.INVALID_ARGS,
                "tool %r is not in the allowlist; the seven allowed tools are %s"
                % (name, ", ".join(TOOL_NAMES)),
            )
        return self._specs[name]

    @property
    def specs(self) -> list[ToolSpec]:
        return [self._specs[n] for n in TOOL_NAMES]

    def schemas(self) -> list[dict]:
        return [s.json_schema() for s in self.specs]

    def parse_args(self, name: str, raw: dict) -> Any:
        spec = self.get(name)
        try:
            return spec.args_model(**(raw or {}))
        except Exception as exc:
            raise ToolError(
                ErrorCode.INVALID_ARGS,
                "invalid arguments for %s: %s" % (name, exc),
                tool=name,
            ) from exc

    async def call(self, name: str, raw_args: dict, ctx: ToolContext) -> dict:
        """Validate then invoke.  Exceptions become ToolError for the dispatcher."""
        spec = self.get(name)
        args = self.parse_args(name, raw_args)
        result = spec.handler(args, ctx)
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=spec.timeout_s)
        if not isinstance(result, dict):
            raise ToolError(
                ErrorCode.INTERNAL,
                "tool %s returned %s; handlers must return a dict" % (name, type(result)),
            )
        result.setdefault("simulated", spec.simulated)
        return result


def _real_specs(settings: Settings) -> list[ToolSpec]:
    from . import docgen as docgen_mod
    from . import fs, kb, sheets
    from .sandbox import run_in_sandbox

    async def _run_python(args, ctx: ToolContext) -> dict:
        out = await run_in_sandbox(
            args.code, ctx.settings, timeout_s=args.timeout,
            input_paths=args.input_paths,
            # The per-task root. Without this the sandbox resolves input_paths
            # against the shared workspace, so one task could mount another's
            # files by naming them.
            workspace_root=ctx.workspace,
        )
        return out.model_dump()

    return [
        ToolSpec("kb_search", "Search the local knowledge base for relevant passages.",
                 TOOL_ARG_MODELS["kb_search"], kb.kb_search, owner="P3"),
        ToolSpec("read_file", "Read a UTF-8 file from the workspace.",
                 TOOL_ARG_MODELS["read_file"], fs.read_file, owner="P4"),
        ToolSpec("write_file", "Write a text file into the workspace.",
                 TOOL_ARG_MODELS["write_file"], fs.write_file, owner="P4",
                 requires_approval=True),
        ToolSpec("list_dir", "List the contents of a workspace directory.",
                 TOOL_ARG_MODELS["list_dir"], fs.list_dir, owner="P4"),
        ToolSpec("run_python", "Execute Python in the hardened Docker sandbox.",
                 TOOL_ARG_MODELS["run_python"], _run_python, owner="P4",
                 executes_code=True, timeout_s=90.0),
        ToolSpec("sheet_op", "Inspect, read, compute over, or write a spreadsheet.",
                 TOOL_ARG_MODELS["sheet_op"], sheets.sheet_op, owner="P6",
                 executes_code=True, timeout_s=90.0),
        ToolSpec("docgen", "Generate a docx, xlsx or pptx deliverable.",
                 TOOL_ARG_MODELS["docgen"], docgen_mod.docgen, owner="P6",
                 requires_approval=True),
    ]


def _mock_specs(settings: Settings) -> list[ToolSpec]:
    """Mock mode swaps ONLY the handlers that need a GPU, Docker, Tesseract or
    an embedding model.  Filesystem and document generation stay real: a real
    DOCX must come out of the mock flagship or the download path is untested."""
    from ..mocks import adapters
    from . import docgen as docgen_mod
    from . import fs

    real = {s.name: s for s in ()}  # placeholder to keep the shape obvious
    _ = real
    return [
        ToolSpec("kb_search", "Search the local knowledge base for relevant passages.",
                 TOOL_ARG_MODELS["kb_search"], adapters.mock_kb_search, owner="P3",
                 simulated=True),
        ToolSpec("read_file", "Read a UTF-8 file from the workspace.",
                 TOOL_ARG_MODELS["read_file"], fs.read_file, owner="P4"),
        ToolSpec("write_file", "Write a text file into the workspace.",
                 TOOL_ARG_MODELS["write_file"], fs.write_file, owner="P4",
                 requires_approval=True),
        ToolSpec("list_dir", "List the contents of a workspace directory.",
                 TOOL_ARG_MODELS["list_dir"], fs.list_dir, owner="P4"),
        ToolSpec("run_python", "Execute Python in the hardened Docker sandbox.",
                 TOOL_ARG_MODELS["run_python"], adapters.mock_run_python, owner="P4",
                 executes_code=True, simulated=True),
        ToolSpec("sheet_op", "Inspect, read, compute over, or write a spreadsheet.",
                 TOOL_ARG_MODELS["sheet_op"], adapters.mock_sheet_op, owner="P6",
                 executes_code=True, simulated=True),
        ToolSpec("docgen", "Generate a docx, xlsx or pptx deliverable.",
                 TOOL_ARG_MODELS["docgen"], docgen_mod.docgen, owner="P6",
                 requires_approval=True),
    ]


def build_registry(settings: Settings) -> ToolRegistry:
    """The one place mock and real diverge for tools."""
    return ToolRegistry(_mock_specs(settings) if settings.mock_mode else _real_specs(settings))


def error_to_structured(exc: BaseException, tool: str) -> StructuredError:
    """Any handler exception becomes an observation, never an unhandled 500."""
    if isinstance(exc, ToolError):
        return exc.as_error()
    if isinstance(exc, asyncio.TimeoutError):
        return StructuredError(
            code=ErrorCode.TOOL_FAILED,
            message="tool %s timed out" % tool,
            detail={"tool": tool},
            retryable=True,
        )
    if isinstance(exc, NotImplementedError):
        return StructuredError(
            code=ErrorCode.NOT_IMPLEMENTED,
            message=str(exc) or ("%s is not implemented yet" % tool),
            detail={"tool": tool},
            retryable=False,
        )
    return StructuredError(
        code=ErrorCode.TOOL_FAILED,
        message="%s: %s" % (type(exc).__name__, exc),
        detail={"tool": tool},
        retryable=True,
    )


_ = Optional
