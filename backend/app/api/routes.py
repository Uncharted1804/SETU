"""
All /api/* routes.  OWNER: P1.

ROUTE ORDER IS LOAD-BEARING (blueprint 0.5).  Starlette matches in registration
order, so this router must be included BEFORE `frontend/dist` is mounted at "/".
Mount first and a catch-all swallows every /api/* path, returning index.html for
/api/health.  main.py enforces the order and test_api.py asserts it.

Concrete paths, used identically by the frontend and the docs:

    GET  /api/health                     liveness, always cheap
    GET  /api/ready                      readiness checks, never claims an unrun check
    POST /api/tasks                      create + start a task
    GET  /api/tasks                      recent tasks
    GET  /api/tasks/{task_id}            task status
    GET  /api/tasks/{task_id}/stream     SSE (supports Last-Event-ID replay)
    POST /api/tasks/{task_id}/approve    approve or reject a pending approval
    POST /api/tasks/{task_id}/cancel     cancel an in-flight task
    GET  /api/tasks/{task_id}/artifacts  artifacts produced by this task
    GET  /api/tasks/{task_id}/artifacts/{artifact_id}   download (task-scoped)
    POST /api/upload                     multipart upload into the workspace
    GET  /api/network-status             the four buckets + negative control
    GET  /api/models                     the model registry as the UI renders it
    GET  /api/audit                      recent audit entries (tail)
    GET  /api/audit/verify               walk the hash chain
    GET  /api/mock/scenarios             available fixtures (mock mode only)
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..config import MAX_ATTEMPTS, MAX_ITERATIONS, THRESHOLDS, VERSION
from ..contracts import (
    ApprovalDecision,
    HealthResponse,
    ModelRegistryView,
    ReadinessCheck,
    ReadinessResponse,
    TaskCreateRequest,
    TaskCreateResponse,
)
from ..orchestration.approvals import ApprovalConflict, ApprovalGate
from ..orchestration.events import sse_payload
from ..security.paths import PathEscape, safe_storage_name
from ..service import SetuService

router = APIRouter(prefix="/api")

#: Upload cap.  A refinery scan is a few MB; anything larger is a mistake.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def _svc(request: Request) -> SetuService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="service not initialised")
    return service


# -----------------------------------------------------------------------------
# Health and readiness
# -----------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(mock_mode=_svc(request).settings.mock_mode, version=VERSION)


@router.get("/ready", response_model=ReadinessResponse)
async def ready(request: Request) -> ReadinessResponse:
    """Readiness that never reports an unrun check as a pass.

    Anything we could not actually test is returned with skipped=True, and the
    UI renders that differently from a tick.
    """
    service = _svc(request)
    settings = service.settings
    checks: list[ReadinessCheck] = []

    checks.append(
        ReadinessCheck(
            name="workspace_writable",
            ok=settings.workspace.is_dir(),
            detail=str(settings.workspace),
        )
    )
    checks.append(
        ReadinessCheck(
            name="model_registry",
            ok=bool(service.models.entries),
            detail="%d entries from config/models.yaml" % len(service.models.entries),
        )
    )
    checks.append(
        ReadinessCheck(
            name="audit_log_writable",
            ok=settings.audit_path.parent.is_dir(),
            detail=str(settings.audit_path),
        )
    )

    if settings.mock_mode:
        for name in ("ollama_reachable", "sandbox_image", "tesseract_binary", "knowledge_base"):
            checks.append(
                ReadinessCheck(
                    name=name, ok=False, skipped=True,
                    detail="not checked: mock mode does not use this component",
                )
            )
    else:
        from ..llm.ollama_client import get_client
        from ..tools.ocr import tesseract_available
        from ..tools.sandbox import image_available

        try:
            models = await get_client(settings).list_models()
            checks.append(ReadinessCheck(name="ollama_reachable", ok=True,
                                         detail="%d models installed" % len(models)))
        except Exception as exc:
            checks.append(ReadinessCheck(name="ollama_reachable", ok=False, detail=str(exc)[:300]))
        ok, detail = await image_available(settings)
        checks.append(ReadinessCheck(name="sandbox_image", ok=ok, detail=detail))
        ok, detail = tesseract_available()
        checks.append(ReadinessCheck(name="tesseract_binary", ok=ok, detail=detail))
        checks.append(
            ReadinessCheck(name="knowledge_base", ok=settings.kb_path.is_dir(),
                           detail=str(settings.kb_path))
        )

    ready_now = all(c.ok for c in checks if not c.skipped)
    return ReadinessResponse(ready=ready_now, mock_mode=settings.mock_mode, checks=checks)


# -----------------------------------------------------------------------------
# Tasks
# -----------------------------------------------------------------------------


@router.post("/tasks", response_model=TaskCreateResponse, status_code=201)
async def create_task(request: Request, body: TaskCreateRequest) -> TaskCreateResponse:
    service = _svc(request)
    if body.scenario and not service.settings.mock_mode:
        raise HTTPException(
            status_code=400,
            detail="mock scenarios cannot be requested in real mode "
                   "(SETU_MOCK_MODE=0); the request was refused rather than "
                   "silently running a fixture",
        )
    record, decision, planner = service.create_task(body)
    await service.start(record, decision, planner)
    return TaskCreateResponse(
        task_id=record.task_id,
        session_id=record.envelope.session_id,
        state=record.state,
        stream_url="/api/tasks/%s/stream" % record.task_id,
    )


@router.get("/tasks")
async def list_tasks(request: Request, limit: int = Query(default=25, ge=1, le=100)):
    service = _svc(request)
    return [r.to_status(service.max_iterations).model_dump() for r in service.store.recent(limit)]


@router.get("/tasks/{task_id}")
async def task_status(request: Request, task_id: str):
    service = _svc(request)
    record = service.store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such task")
    return record.to_status(service.max_iterations).model_dump()


@router.get("/tasks/{task_id}/stream")
async def task_stream(request: Request, task_id: str):
    """SSE.  Replays missed events, then streams live ones until `done`.

    Disconnecting does NOT cancel the task; execution continues and the events
    stay in the replay buffer for a reconnect.
    """
    service = _svc(request)
    if service.store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="no such task")

    last_id = 0
    header = request.headers.get("last-event-id")
    if header and header.isdigit():
        last_id = int(header)
    param = request.query_params.get("last_event_id")
    if param and param.isdigit():
        last_id = max(last_id, int(param))

    stream = service.bus.stream(task_id)

    async def generator():
        # We poll the subscription with a timeout rather than awaiting it
        # forever, so a client that walks away from a task parked on an
        # approval is noticed and its generator released.  Without this the
        # connection (and its task) would live until the process exits.
        source = stream.subscribe(last_event_id=last_id).__aiter__()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(source.__anext__(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # nothing yet; loop back and re-check the client
                except StopAsyncIteration:
                    break
                yield sse_payload(event)
        finally:
            await source.aclose()

    return EventSourceResponse(generator())


@router.post("/tasks/{task_id}/approve")
async def approve(request: Request, task_id: str, decision: ApprovalDecision):
    service = _svc(request)
    record = service.store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such task")
    gate = ApprovalGate(record)
    try:
        resolved = gate.resolve(decision.approval_id, decision.approved)
    except ApprovalConflict as exc:
        # 409, not 200.  A duplicate approval must not look like it worked.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "approval_id": resolved.approval_id,
        "approved": decision.approved,
        "task_id": task_id,
        "state": record.state,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel(request: Request, task_id: str):
    service = _svc(request)
    record = service.store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such task")
    cancelled = await service.cancel(record)
    return {"task_id": task_id, "cancelled": cancelled, "state": record.state}


@router.get("/tasks/{task_id}/artifacts")
async def list_artifacts(request: Request, task_id: str):
    service = _svc(request)
    record = service.store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such task")
    return [a.model_dump() for a in record.artifacts]


@router.get("/tasks/{task_id}/artifacts/{artifact_id}")
async def download_artifact(request: Request, task_id: str, artifact_id: str):
    """Task-scoped lookup by opaque id.  A client never supplies a path.

    Resolution is against THIS TASK's root, not the shared workspace, because
    `ToolContext.register_artifact` records `ref.path` relative to the task
    root. Resolving against the workspace would look up the wrong file, and
    would also mean a path recorded by one task could be reached while serving
    another.
    """
    service = _svc(request)
    ref = service.store.artifact(task_id, artifact_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="no such artifact for this task")
    try:
        from ..security.paths import jail
        from ..tools.base import task_root

        resolved = jail(ref.path, task_root(service.settings.workspace, task_id))
    except PathEscape as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=410, detail="artifact is no longer on disk")
    return FileResponse(str(resolved), media_type=ref.media_type, filename=ref.name)


# -----------------------------------------------------------------------------
# Upload
# -----------------------------------------------------------------------------


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), session_id: Optional[str] = Form(default=None)):
    """Uploads land in workspace/uploads under a SERVER-CONTROLLED name.

    The client's filename is sanitised and prefixed; it is never used as a path
    component, so an upload called "../../evil.txt" cannot escape - and the jail
    call below is the second line of defence, not the first.

    This is a STAGING area, shared across sessions and outside any task root.
    The file is not usable until a task claims it: `create_task` copies it into
    that task's own root and rewrites the path. Ownership is recorded here so
    that claim can be refused.
    """
    service = _svc(request)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds %d bytes" % MAX_UPLOAD_BYTES)

    storage_name = safe_storage_name(file.filename or "upload", prefix=secrets.token_hex(3) + "_")
    rel = "uploads/" + storage_name
    try:
        from ..security.paths import jail

        target = jail(rel, service.settings.workspace)
    except PathEscape as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    # Record who staged this. create_task refuses a file_paths entry that was
    # never staged or was staged by another session, so this is the point at
    # which session_id stops being decorative.
    service.uploads.stage(rel, session_id)
    return {
        "path": rel,
        "original_name": file.filename,
        "stored_name": storage_name,
        "size_bytes": len(raw),
        "session_id": session_id,
    }


# -----------------------------------------------------------------------------
# Proof surfaces
# -----------------------------------------------------------------------------


@router.get("/network-status")
async def network_status(request: Request):
    service = _svc(request)
    return service.monitor.sample().model_dump()


@router.get("/models", response_model=ModelRegistryView)
async def models(request: Request) -> ModelRegistryView:
    service = _svc(request)
    from ..security.integrity import annotate

    return ModelRegistryView(
        models=annotate(service.models, checked=False),
        thresholds=THRESHOLDS,
        max_attempts=MAX_ATTEMPTS,
        max_iterations=MAX_ITERATIONS,
        max_loaded_models=service.models.max_loaded_models(),
        host=service.models.host(),
        mock_mode=service.settings.mock_mode,
        integrity_checked=False,
    )


@router.get("/audit")
async def audit_tail(request: Request, limit: int = Query(default=100, ge=1, le=1000)):
    service = _svc(request)
    return {"path": str(service.audit.path), "entries": service.audit.read_all(limit=limit)}


@router.get("/audit/verify")
async def audit_verify(request: Request):
    from ..security.audit import verify_chain

    service = _svc(request)
    return verify_chain(service.audit.path).model_dump()


@router.get("/mock/scenarios")
async def mock_scenarios(request: Request):
    service = _svc(request)
    if not service.settings.mock_mode:
        return JSONResponse(
            status_code=404,
            content={"detail": "mock scenarios are unavailable in real mode"},
        )
    from ..mocks.scenarios import SCENARIOS, get_scenario

    return [
        {
            "key": key,
            "title": get_scenario(key).title,
            "description": get_scenario(key).description,
            "steps": len(get_scenario(key).initial_steps),
            "expected_state": get_scenario(key).expected_state,
        }
        for key in sorted(SCENARIOS)
    ]
