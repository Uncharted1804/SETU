"""
sheet_op - ONE tool, four operations.  OWNER: P6.  P4 reviews the jail and the
sandbox mount.

Why one tool and not four: the security claim is that the agent's entire
capability surface is SEVEN typed functions.  Four separate spreadsheet tools
would make it ten and the number in the pitch would be wrong.  The operations
are discriminated by a Literal and validated per-operation in
contracts.SheetOpArgs - the public interface is not `**kwargs`.

Why "spreadsheet work" is a TOOL and not an output format: R7 lists it beside
file read/write and sandboxed execution, i.e. among the things the agent calls
MID-TASK.  Producing an .xlsx at the end satisfies R9 and leaves R7 unmet.

    describe  sheet names, dims, headers, dtypes, null counts.  Called FIRST.
              Lets the model reason about a 400-row workbook without loading it
              into an 8k context.  This is the loop earning its keep on stage.
    read      headers + typed rows, truncated.
    compute   runs generated pandas/openpyxl IN THE SANDBOX against a READ-ONLY
              mount.  Returns result + script + intermediates - that is where
              "calculations with steps shown" comes from.
    write     writes a NEW file into the workspace.  NEVER overwrites an input
              (enforced in SheetOpArgs, not just by convention).

DEPENDENCY NOTE.  `compute` executes inside setu-sandbox:py311, which ships
openpyxl and numpy pinned.  python:3.11-slim does NOT, and nothing is ever
pip-installed during a task.  If the image is missing, compute returns
SANDBOX_UNAVAILABLE - it does not run on the host.
"""

from __future__ import annotations

from typing import Any

from ..contracts import ComputeResult, ErrorCode, SheetOpArgs, SheetRows, SheetSchema, WriteResult
from ..security.paths import PathEscape, to_rel
from .base import ToolContext, ToolError, media_type_for, optional_import


def _open(ctx: ToolContext, rel: str, read_only: bool = True):
    openpyxl = optional_import("openpyxl", owner="P6", purpose="spreadsheet access")
    try:
        target = ctx.resolve(rel)
    except PathEscape as exc:
        raise ToolError(ErrorCode.PATH_ESCAPE, str(exc), requested=rel) from exc
    if not target.is_file():
        raise ToolError(ErrorCode.NOT_FOUND, "no such workbook: " + rel, path=rel)
    return openpyxl.load_workbook(str(target), read_only=read_only, data_only=True), target


def _describe(args: SheetOpArgs, ctx: ToolContext) -> dict:
    """REAL implementation - describe is on the never-cut list."""
    wb, _ = _open(ctx, args.path)
    sheets: list[str] = []
    dims: dict[str, tuple[int, int]] = {}
    headers: dict[str, list[str]] = {}
    dtypes: dict[str, dict[str, str]] = {}
    nulls: dict[str, dict[str, int]] = {}
    try:
        for ws in wb.worksheets:
            name = ws.title
            sheets.append(name)
            rows = ws.max_row or 0
            cols = ws.max_column or 0
            dims[name] = (rows, cols)
            head: list[str] = []
            for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
                head = [str(c) if c is not None else "" for c in row]
                break
            headers[name] = head
            col_types: dict[str, str] = {}
            col_nulls: dict[str, int] = {}
            sampled = 0
            for row in ws.iter_rows(min_row=2, max_row=min(rows, 201), values_only=True):
                sampled += 1
                for idx, value in enumerate(row):
                    key = head[idx] if idx < len(head) and head[idx] else "col_%d" % (idx + 1)
                    if value is None or value == "":
                        col_nulls[key] = col_nulls.get(key, 0) + 1
                        continue
                    seen = type(value).__name__
                    prior = col_types.get(key)
                    # A column that mixes types is the interesting one - say so.
                    col_types[key] = seen if prior in (None, seen) else "mixed"
            dtypes[name] = col_types
            nulls[name] = col_nulls
    finally:
        wb.close()
    schema = SheetSchema(
        sheets=sheets, dims=dims, headers=headers, dtypes=dtypes, null_counts=nulls
    )
    return {"op": "describe", "path": args.path, "schema": schema.model_dump()}


def _read(args: SheetOpArgs, ctx: ToolContext) -> dict:
    wb, _ = _open(ctx, args.path)
    try:
        ws = wb[args.sheet] if args.sheet else wb.worksheets[0]
        head: list[str] = []
        rows: list[list[Any]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                head = [str(c) if c is not None else "" for c in row]
                continue
            if len(rows) >= args.max_rows:
                break
            rows.append([c for c in row])
        total = (ws.max_row or 1) - 1
    finally:
        wb.close()
    out = SheetRows(
        sheet=args.sheet or "sheet0",
        headers=head,
        rows=rows,
        truncated=total > len(rows),
        total_rows=total,
    )
    return {"op": "read", "path": args.path, **out.model_dump()}


async def _compute(args: SheetOpArgs, ctx: ToolContext) -> dict:
    """Runs generated code in the SHARED sandbox service against a read-only mount.

    This is a shared implementation service, not a tool calling a tool: sheets.py
    imports the sandbox runner directly, the same way run_python does.

    P6 TODO (acceptance: the sensor demo produces a numeric result plus the
    script and named intermediates, and the workbook mounted at /inputs is
    provably read-only - a write attempt inside the sandbox fails):
      - translate `spec` into a pandas/openpyxl script deterministically
      - capture named intermediates as JSON on stdout, not by parsing prose
    """
    from .sandbox import run_in_sandbox

    raise ToolError(
        ErrorCode.NOT_IMPLEMENTED,
        "sheet_op(compute) script generation is owned by P6. The sandbox runner "
        "it depends on is implemented (tools/sandbox.py::run_in_sandbox); what is "
        "missing is the spec -> script translation.",
        spec=args.spec,
        runner_available=bool(run_in_sandbox),
    )


def _write(args: SheetOpArgs, ctx: ToolContext) -> dict:
    """Writes a NEW workbook.  The input is never overwritten."""
    openpyxl = optional_import("openpyxl", owner="P6", purpose="spreadsheet write")
    try:
        out = ctx.resolve(args.out_path or "")
    except PathEscape as exc:
        raise ToolError(ErrorCode.PATH_ESCAPE, str(exc), requested=args.out_path) from exc
    out.parent.mkdir(parents=True, exist_ok=True)

    data = args.data or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(data.get("sheet_name", "Results"))[:31]
    if data.get("headers"):
        ws.append([str(h) for h in data["headers"]])
    for row in data.get("rows") or []:
        ws.append(list(row))
    # P6 TODO (acceptance: out-of-spec rows render red): apply args.formatting.
    wb.save(str(out))

    ref = ctx.register_artifact(out, media_type_for(out), simulated=ctx.mock)
    result = WriteResult(
        path=to_rel(out, ctx.workspace),
        bytes_written=ref.size_bytes,
        created=True,
        sha256=ref.sha256,
    )
    return {"op": "write", "artifact_id": ref.artifact_id, **result.model_dump()}


async def sheet_op(args: SheetOpArgs, ctx: ToolContext) -> dict:
    if args.op == "describe":
        return _describe(args, ctx)
    if args.op == "read":
        return _read(args, ctx)
    if args.op == "compute":
        return await _compute(args, ctx)
    return _write(args, ctx)


_ = ComputeResult  # referenced by the compute contract P6 implements against
