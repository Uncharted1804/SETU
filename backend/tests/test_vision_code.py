"""
Tests for visual coding problem solving, code deliverable artifacts, and chat formatting.
"""

from __future__ import annotations

import pytest

from app.mocks.scenarios import select_scenario


def test_select_scenario_routes_image_with_code_intent_to_vision_code():
    # An image attached with code request keywords
    assert select_scenario("solve this coding question in python", "vision", ["uploads/problem.png"]) == "vision_code"
    assert select_scenario("write python code to solve this", "vision", ["problem.jpg"]) == "vision_code"
    assert select_scenario("solve for code", "vision", ["scan.png"]) == "vision_code"
    assert select_scenario("can you write a function for this problem?", "vision", ["drawing.png"]) == "vision_code"

    # Non-code image goes to flagship
    assert select_scenario("inspect this report", "vision", ["report.pdf"]) == "flagship"


def test_vision_code_scenario_end_to_end_creates_code_artifact_and_chat_text(client):
    upload_resp = client.post(
        "/api/upload",
        files={"file": ("coding_problem.png", b"\x89PNG\r\n\x1a\nvalid_png_content", "image/png")},
    )
    assert upload_resp.status_code == 200
    uploaded_path = upload_resp.json()["path"]

    created = client.post(
        "/api/tasks",
        json={
            "text": "solve this coding question in python",
            "file_paths": [uploaded_path],
            "scenario": "vision_code",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]

    # Approve the plan and any write approval
    import time
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
        time.sleep(0.01)
    assert seen_done, "task did not reach a terminal state; last state: %s" % status.get("state")

    status = client.get("/api/tasks/%s" % task_id).json()
    assert status["state"] == "completed"

    # Verify solution.py artifact exists and is registered
    artifacts = client.get("/api/tasks/%s/artifacts" % task_id).json()
    assert len(artifacts) >= 1
    py_artifact = next((a for a in artifacts if a["name"] == "solution.py"), None)
    assert py_artifact is not None, "solution.py artifact was not registered"
    assert py_artifact["media_type"] == "text/x-python; charset=utf-8"

    # Verify download works
    download = client.get("/api/tasks/%s/artifacts/%s" % (task_id, py_artifact["artifact_id"]))
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/x-python")
    code_text = download.content.decode("utf-8")
    assert "def two_sum" in code_text

    # Verify session turn assistant_text contains copyable markdown code block
    session = client.get("/api/sessions/current").json()
    turn = next((t for t in session["turns"] if t["task_id"] == task_id), None)
    assert turn is not None
    assistant_text = turn["assistant_text"]
    assert "```python" in assistant_text
    assert "def two_sum" in assistant_text
    assert "```" in assistant_text


def test_coding_task_auto_creates_solution_artifact_if_not_explicitly_written(client):
    created = client.post(
        "/api/tasks",
        json={"text": "fix this code and run it", "scenario": "coding_retry"},
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]

    import time
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
        time.sleep(0.01)
    assert seen_done, "task did not reach terminal state"

    # Verify solution.py was automatically created and registered as artifact
    artifacts = client.get("/api/tasks/%s/artifacts" % task_id).json()
    assert any(a["name"] == "solution.py" for a in artifacts), "solution.py was not registered"
