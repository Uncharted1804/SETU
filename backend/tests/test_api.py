"""
API, SSE and upload/download tests.  OWNER: P1.

Includes the route-ordering assertion from blueprint 0.5, which is the bug that
silently turns /api/health into index.html.
"""

from __future__ import annotations

import io
import json

import pytest


# -- health, readiness, route order -----------------------------------------


def test_health_returns_json(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["mock_mode"] is True


def test_api_health_survives_the_frontend_mount(env, tmp_path, monkeypatch):
    """Blueprint 0.5: a Mount('/') registered before the API router swallows
    /api/*.  With a real dist directory present, /api/health must still be JSON
    and / must still be index.html."""
    from fastapi.testclient import TestClient

    from app import config, main

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>SETU UI</body></html>", encoding="utf-8")

    monkeypatch.setenv("SETU_FRONTEND_DIST", str(dist))
    config.reset_caches()

    with TestClient(main.create_app()) as c:
        health = c.get("/api/health")
        assert health.status_code == 200
        assert health.headers["content-type"].startswith("application/json")
        assert health.json()["status"] == "ok"

        index = c.get("/")
        assert index.status_code == 200
        assert "SETU UI" in index.text


def test_readiness_marks_unrun_checks_as_skipped_not_passed(client):
    body = client.get("/api/ready").json()
    names = {c["name"]: c for c in body["checks"]}
    assert names["ollama_reachable"]["skipped"] is True
    assert names["ollama_reachable"]["ok"] is False
    assert names["workspace_writable"]["ok"] is True


def test_cors_is_not_installed_by_default(client):
    r = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# -- model registry ----------------------------------------------------------


def test_models_endpoint_reports_thresholds_and_never_claims_integrity(client):
    body = client.get("/api/models").json()
    assert body["thresholds"] == {"vision": 0.70, "reasoning": 0.65, "coding": 1.00}
    assert body["max_attempts"] == {"vision": 3, "reasoning": 3, "coding": 4}
    assert body["max_iterations"] == 5
    assert body["max_loaded_models"] == 1
    assert body["integrity_checked"] is False
    assert all(m["integrity_verified"] is None for m in body["models"])


def test_network_status_shape(client):
    body = client.get("/api/network-status").json()
    for key in ("loopback_active", "trusted_lan_active", "external_active", "unknown_active"):
        assert key in body
    assert body["mode"] == "single_laptop"
    assert "monitor_available" in body and "scope" in body
    assert body["negative_control"]["blocked_external_attempts"] == 0


# -- tasks and SSE -----------------------------------------------------------


def _sse_events(client, task_id, last_event_id=None):
    url = "/api/tasks/%s/stream" % task_id
    if last_event_id is not None:
        url += "?last_event_id=%d" % last_event_id
    events = []
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if events[-1]["type"] == "done":
                    break
    return events


def test_full_flagship_over_the_api_with_a_downloadable_docx(client):
    created = client.post(
        "/api/tasks",
        json={"text": "draft an approval note", "scenario": "flagship"},
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]

    # Approve everything the task asks for, driven by polling the status route.
    seen_done = False
    for _ in range(400):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            r = client.post(
                "/api/tasks/%s/approve" % task_id,
                json={"approval_id": pending["approval_id"], "approved": True},
            )
            assert r.status_code == 200
        if status["state"] in {"completed", "failed", "rejected", "needs_human_review"}:
            seen_done = True
            break
    assert seen_done, "task did not reach a terminal state"

    status = client.get("/api/tasks/%s" % task_id).json()
    assert status["state"] == "completed"

    artifacts = client.get("/api/tasks/%s/artifacts" % task_id).json()
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["name"].endswith(".docx")

    download = client.get("/api/tasks/%s/artifacts/%s" % (task_id, artifact["artifact_id"]))
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    body = download.content
    assert body[:2] == b"PK"  # a real OOXML zip container
    assert len(body) > 5000

    import docx

    document = docx.Document(io.BytesIO(body))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Approval Note" in text


def test_sse_replays_route_and_plan_for_a_late_subscriber(client):
    """The subscribe-after-create race: the browser connects after execution
    started and must still receive `route` and `plan`."""
    created = client.post(
        "/api/tasks", json={"text": "read this degraded scan", "scenario": "escalation"}
    )
    task_id = created.json()["task_id"]

    for _ in range(200):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            client.post(
                "/api/tasks/%s/approve" % task_id,
                json={"approval_id": pending["approval_id"], "approved": True},
            )
        if status["state"] in {"completed", "needs_human_review", "failed", "rejected"}:
            break

    events = _sse_events(client, task_id)
    types = [e["type"] for e in events]
    assert types[0] == "route"
    assert "plan" in types
    assert types[-1] == "done"


def test_sse_event_ids_are_monotonic(client):
    created = client.post(
        "/api/tasks", json={"text": "read this degraded scan", "scenario": "escalation"}
    )
    task_id = created.json()["task_id"]
    for _ in range(200):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            client.post("/api/tasks/%s/approve" % task_id,
                        json={"approval_id": pending["approval_id"], "approved": True})
        if status["state"] in {"completed", "needs_human_review", "failed", "rejected"}:
            break

    events = _sse_events(client, task_id)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))


def test_sse_resumes_from_last_event_id(client):
    created = client.post(
        "/api/tasks", json={"text": "read this degraded scan", "scenario": "escalation"}
    )
    task_id = created.json()["task_id"]
    for _ in range(200):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            client.post("/api/tasks/%s/approve" % task_id,
                        json={"approval_id": pending["approval_id"], "approved": True})
        if status["state"] in {"completed", "needs_human_review", "failed", "rejected"}:
            break

    everything = _sse_events(client, task_id)
    resumed = _sse_events(client, task_id, last_event_id=3)
    assert [e["seq"] for e in resumed] == [e["seq"] for e in everything if e["seq"] > 3]


def test_closing_the_stream_does_not_cancel_the_task(client):
    created = client.post("/api/tasks", json={"text": "draft an approval note",
                                              "scenario": "flagship"})
    task_id = created.json()["task_id"]
    with client.stream("GET", "/api/tasks/%s/stream" % task_id) as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                break  # disconnect immediately
    status = client.get("/api/tasks/%s" % task_id).json()
    assert status["state"] != "cancelled"


def test_duplicate_approval_returns_409(client):
    created = client.post("/api/tasks", json={"text": "draft an approval note",
                                              "scenario": "flagship"})
    task_id = created.json()["task_id"]
    approval_id = None
    for _ in range(200):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            approval_id = pending["approval_id"]
            break
    assert approval_id
    first = client.post("/api/tasks/%s/approve" % task_id,
                        json={"approval_id": approval_id, "approved": True})
    assert first.status_code == 200
    second = client.post("/api/tasks/%s/approve" % task_id,
                         json={"approval_id": approval_id, "approved": True})
    assert second.status_code == 409


def test_unknown_task_is_404(client):
    assert client.get("/api/tasks/t_nope").status_code == 404
    assert client.get("/api/tasks/t_nope/stream").status_code == 404


# -- uploads and downloads ---------------------------------------------------


def test_upload_uses_a_server_controlled_name(client):
    r = client.post("/api/upload", files={"file": ("../../evil.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["path"].startswith("uploads/")
    assert ".." not in body["path"]
    assert "/" not in body["stored_name"] and "\\" not in body["stored_name"]


def test_upload_lands_inside_the_workspace(client, env):
    r = client.post("/api/upload", files={"file": ("scan.pdf", b"%PDF-1.4 x", "application/pdf")})
    stored = env.workspace / r.json()["path"]
    assert stored.is_file()
    assert stored.resolve().is_relative_to(env.workspace.resolve())


def test_artifact_download_is_task_scoped(client):
    """An artifact id from one task does not resolve under another task."""
    a = client.post("/api/tasks", json={"text": "draft an approval note",
                                        "scenario": "flagship"}).json()["task_id"]
    for _ in range(400):
        status = client.get("/api/tasks/%s" % a).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            client.post("/api/tasks/%s/approve" % a,
                        json={"approval_id": pending["approval_id"], "approved": True})
        if status["state"] == "completed":
            break
    artifact_id = client.get("/api/tasks/%s/artifacts" % a).json()[0]["artifact_id"]

    b = client.post("/api/tasks", json={"text": "hello", "scenario": "escalation"}).json()["task_id"]
    assert client.get("/api/tasks/%s/artifacts/%s" % (b, artifact_id)).status_code == 404


def test_download_rejects_a_path_shaped_artifact_id(client):
    a = client.post("/api/tasks", json={"text": "hello", "scenario": "escalation"}).json()["task_id"]
    r = client.get("/api/tasks/%s/artifacts/..%%2F..%%2Fetc%%2Fpasswd" % a)
    assert r.status_code in (403, 404)


# -- audit -------------------------------------------------------------------


def test_audit_endpoints(client):
    client.post("/api/tasks", json={"text": "hello", "scenario": "escalation"})
    tail = client.get("/api/audit").json()
    assert tail["entries"]
    verify = client.get("/api/audit/verify").json()
    assert verify["ok"] is True


# -- mock-mode boundaries ----------------------------------------------------


def test_mock_scenarios_are_listed_in_mock_mode(client):
    body = client.get("/api/mock/scenarios").json()
    keys = {s["key"] for s in body}
    assert {"flagship", "coding_retry", "escalation", "rejection",
            "observation_branch", "injection"} <= keys


def test_a_scenario_cannot_be_requested_in_real_mode(env, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import config, main

    monkeypatch.setenv("SETU_MOCK_MODE", "0")
    config.reset_caches()
    with TestClient(main.create_app()) as c:
        r = c.post("/api/tasks", json={"text": "hi", "scenario": "flagship"})
        assert r.status_code == 400
        assert "mock" in r.json()["detail"].lower()
    config.reset_caches()


def test_mock_scenarios_route_is_absent_in_real_mode(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app import config, main

    monkeypatch.setenv("SETU_MOCK_MODE", "0")
    config.reset_caches()
    with TestClient(main.create_app()) as c:
        assert c.get("/api/mock/scenarios").status_code == 404
    config.reset_caches()
