"""
Shared test fixtures.  OWNER: P1.

Every test runs in MOCK MODE against a temporary workspace and a temporary audit
log, so the suite needs no GPU, no Ollama, no Docker, no Tesseract and no
embedding download - and it never writes into the real data/workspace.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO_ROOT / "backend"
SCRIPTS = REPO_ROOT / "scripts"
for p in (str(BACKEND), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated settings: mock mode, temp workspace, temp audit log."""
    from app import config

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SETU_MOCK_MODE", "1")
    monkeypatch.setenv("SETU_WORKSPACE", str(workspace))
    monkeypatch.setenv("SETU_AUDIT_PATH", str(tmp_path / "logs" / "audit.jsonl"))
    monkeypatch.delenv("SETU_TRUSTED_SUBNET", raising=False)
    monkeypatch.delenv("SETU_DEV_MODE", raising=False)
    monkeypatch.delenv("SETU_DEV_ORIGINS", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    config.reset_caches()
    yield config.get_settings()
    config.reset_caches()


@pytest.fixture()
def service(env):
    from app.service import SetuService

    return SetuService.build(env)


@pytest.fixture()
def client(env):
    """TestClient with lifespan run, so app.state.service exists."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
