"""
FastAPI application entrypoint.  OWNER: P1.

THE ORDERING THAT MUST NOT REGRESS (blueprint 0.5):

    1. apply_cors(app, settings)       middleware, off by default
    2. app.include_router(api_router)  ALL /api/* routes FIRST
    3. _mount_frontend(app)            the catch-all "/" mount LAST

Starlette matches routes in registration order.  A Mount("/") registered before
the API router swallows everything, and /api/health starts returning index.html.
`backend/tests/test_api.py::test_api_health_survives_frontend_mount` asserts the
correct behaviour with a real dist directory present.

Run it:
    # mock mode (default) - no GPU, no Ollama, no Docker
    uvicorn app.main:app --app-dir backend --port 8000

    # real mode
    SETU_MOCK_MODE=0 uvicorn app.main:app --app-dir backend --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import VERSION, get_settings
from .security.cors import apply_cors
from .service import SetuService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("setu")


def _mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Serve the built UI from the same origin as the API.

    Same scheme, same host, same port means the browser never makes a
    cross-origin request, so no CORS header is needed in the real deployment.
    """
    if not dist.is_dir():
        log.warning(
            "frontend/dist not found at %s - API only. Run `npm run build` in "
            "frontend/ before the demo; a UI change that was not rebuilt does "
            "not exist.", dist,
        )
        return False
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.service = SetuService.build(settings)
    log.info(
        "SETU %s starting | mode=%s | topology=%s | bind=%s | workspace=%s",
        VERSION,
        "MOCK" if settings.mock_mode else "REAL",
        settings.topology,
        settings.bind_host,
        settings.workspace,
    )
    if settings.mock_mode:
        log.warning(
            "MOCK MODE: agents, kb_search, run_python and sheet_op return "
            "deterministic fixtures. No model is loaded and no container is started."
        )
    try:
        yield
    finally:
        await app.state.service.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SETU",
        version=VERSION,
        description="Sovereign on-premise agentic AI workbench",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # 1. middleware
    installed, reason = apply_cors(app, settings)
    app.state.cors_installed = installed
    app.state.cors_reason = reason

    # 2. ALL /api/* routes, BEFORE any catch-all mount
    app.include_router(api_router)

    # 3. the catch-all mount, LAST
    app.state.frontend_mounted = _mount_frontend(app, settings.frontend_dist)

    return app


app = create_app()
