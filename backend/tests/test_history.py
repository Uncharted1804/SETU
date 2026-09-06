"""Cookie-backed session and durable conversation history tests."""

from __future__ import annotations

from app.history import HistoryStore


def test_first_task_creates_an_http_only_active_session(client):
    assert client.get("/api/sessions/current").status_code == 204

    created = client.post(
        "/api/tasks", json={"text": "Remember this thread", "scenario": "escalation"}
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    cookie = created.headers["set-cookie"]
    assert "setu_active_session=" + session_id in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    current = client.get("/api/sessions/current").json()
    assert current["session_id"] == session_id
    assert current["turns"][0]["user_text"] == "Remember this thread"


def test_later_tasks_reuse_the_cookie_selected_session(client):
    first = client.post(
        "/api/tasks", json={"text": "First turn", "scenario": "escalation"}
    ).json()
    second = client.post(
        "/api/tasks", json={"text": "Second turn", "scenario": "escalation"}
    ).json()
    assert second["session_id"] == first["session_id"]
    current = client.get("/api/sessions/current").json()
    assert [turn["user_text"] for turn in current["turns"]] == ["First turn", "Second turn"]


def test_new_chat_preserves_old_chat_and_activation_restores_it(client):
    old = client.post("/api/sessions").json()
    client.post("/api/tasks", json={"text": "Old conversation", "scenario": "escalation"})
    fresh = client.post("/api/sessions").json()
    assert fresh["session_id"] != old["session_id"]
    assert client.get("/api/sessions/current").json()["session_id"] == fresh["session_id"]

    sessions = client.get("/api/sessions").json()
    assert {item["session_id"] for item in sessions} >= {
        old["session_id"], fresh["session_id"]
    }
    restored = client.post("/api/sessions/%s/activate" % old["session_id"])
    assert restored.status_code == 200
    assert client.get("/api/sessions/current").json()["session_id"] == old["session_id"]


def test_terminal_result_and_task_snapshot_are_durable(client, env):
    created = client.post(
        "/api/tasks", json={"text": "Decline this plan", "scenario": "rejection"}
    ).json()
    task_id = created["task_id"]
    for _ in range(200):
        status = client.get("/api/tasks/%s" % task_id).json()
        pending = status.get("pending_approval")
        if pending and not pending["decided"]:
            client.post(
                "/api/tasks/%s/approve" % task_id,
                json={"approval_id": pending["approval_id"], "approved": False},
            )
        if status["state"] == "rejected":
            break

    turn = None
    for _ in range(200):
        detail = client.get("/api/sessions/current").json()
        turn = detail["turns"][0]
        if turn["state"] == "rejected":
            break
    assert turn is not None
    assert turn["state"] == "rejected"
    assert turn["assistant_text"]
    assert turn["status"]["task_id"] == task_id

    reopened = HistoryStore(env.history_path)
    persisted = reopened.task_status(task_id)
    assert persisted is not None
    assert persisted["state"] == "rejected"


def test_history_context_is_bounded_and_session_scoped(client, env):
    a = client.post("/api/sessions").json()["session_id"]
    client.post("/api/tasks", json={"text": "alpha private note", "scenario": "escalation"})
    b = client.post("/api/sessions").json()["session_id"]
    client.post("/api/tasks", json={"text": "beta private note", "scenario": "escalation"})

    store = HistoryStore(env.history_path)
    context_a = store.context(a, max_chars=1000)
    context_b = store.context(b, max_chars=1000)
    assert "alpha private note" in context_a and "beta private note" not in context_a
    assert "beta private note" in context_b and "alpha private note" not in context_b
    assert len(store.context(a, max_chars=8)) <= 8


def test_unknown_session_cannot_be_activated(client):
    assert client.post("/api/sessions/s_000000000000/activate").status_code == 404
