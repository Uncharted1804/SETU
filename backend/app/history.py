"""Durable, local conversation history for SETU.

The live orchestration store remains in memory because it owns asyncio tasks,
approval futures and SSE replay.  This repository stores only serialisable chat
metadata and task snapshots so conversations survive a process restart.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .contracts import TaskResult
from .orchestration.state import TaskRecord

SESSION_ID_RE = re.compile(r"^s_[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _title(text: str) -> str:
    clean = " ".join(text.split()).strip()
    if len(clean) <= 58:
        return clean or "Untitled conversation"
    return clean[:57].rstrip() + "…"


def _assistant_text(result: TaskResult) -> str:
    """Select the most useful user-facing text without exposing raw traces."""
    code_obs = next(
        (
            o
            for o in reversed(result.observations)
            if isinstance((o.payload or {}).get("code"), str) and o.payload["code"].strip()
        ),
        None,
    )
    content_obs = next(
        (
            o
            for o in reversed(result.observations)
            if isinstance((o.payload or {}).get("content"), str) and o.payload["content"].strip()
        ),
        None,
    )
    if code_obs and content_obs:
        content = content_obs.payload["content"].strip()
        code = code_obs.payload["code"].strip()
        lang = str(code_obs.payload.get("language") or "python")
        text = f"{content}\n\n```{lang}\n{code}\n```"
        stdout = code_obs.payload.get("stdout")
        if isinstance(stdout, str) and stdout.strip():
            text += f"\n\n**Output:**\n```text\n{stdout.strip()}\n```"
        return text
    if code_obs:
        code = code_obs.payload["code"].strip()
        lang = str(code_obs.payload.get("language") or "python")
        text = f"```{lang}\n{code}\n```"
        stdout = code_obs.payload.get("stdout")
        if isinstance(stdout, str) and stdout.strip():
            text += f"\n\n**Output:**\n```text\n{stdout.strip()}\n```"
        return text
    if content_obs:
        return content_obs.payload["content"].strip()

    if result.state == "completed":
        summaries = [o.summary.strip() for o in result.observations if o.summary.strip()]
        return summaries[-1] if summaries else "Task completed."
    return result.escalation_reason or (result.error.message if result.error else result.summary)


class HistoryStore:
    """Small SQLite repository; each operation owns its connection."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialise(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                );

                CREATE TABLE IF NOT EXISTS turns (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    user_text TEXT NOT NULL,
                    file_paths_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL,
                    assistant_text TEXT,
                    status_json TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                    ON sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_turns_session_created
                    ON turns(session_id, created_at);
                """
            )
            db.execute("PRAGMA optimize")
            db.execute("PRAGMA user_version = 1")
            # Async runners cannot survive a process restart. Preserve the turn
            # and make the interruption explicit instead of leaving a chat
            # permanently stuck in a running state.
            now = _now()
            db.execute(
                """UPDATE turns
                   SET state = 'failed',
                       assistant_text = COALESCE(
                           assistant_text,
                           'This run was interrupted when SETU restarted.'
                       ),
                       updated_at = ?
                   WHERE state NOT IN ('completed', 'failed', 'rejected',
                                       'needs_human_review', 'cancelled')""",
                (now,),
            )

    def has_session(self, session_id: Optional[str]) -> bool:
        if not session_id or not SESSION_ID_RE.fullmatch(session_id):
            return False
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM sessions WHERE session_id = ? AND archived_at IS NULL",
                (session_id,),
            ).fetchone() is not None

    def create_session(self, session_id: str, title: str = "New conversation") -> dict[str, Any]:
        if not SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("session_id must be server generated")
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return self.get_session(session_id)  # type: ignore[return-value]

    def add_turn(self, record: TaskRecord) -> None:
        session_id = record.envelope.session_id
        now = record.created_at
        with self._connect() as db:
            existing = db.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, _title(record.envelope.text), now, now),
                )
            else:
                count = db.execute(
                    "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
                if count == 0:
                    db.execute(
                        "UPDATE sessions SET title = ? WHERE session_id = ?",
                        (_title(record.envelope.text), session_id),
                    )
            db.execute(
                """INSERT INTO turns(
                       task_id, session_id, user_text, file_paths_json, state,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.task_id,
                    session_id,
                    record.envelope.text,
                    json.dumps(record.envelope.file_paths),
                    record.state,
                    now,
                    now,
                ),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )

    def finalise_turn(self, record: TaskRecord, result: Optional[TaskResult]) -> None:
        status = record.to_status(max_iterations=5).model_dump(mode="json")
        result_data = result.model_dump(mode="json") if result else None
        assistant = _assistant_text(result) if result else "Task cancelled."
        now = record.updated_at or _now()
        with self._connect() as db:
            db.execute(
                """UPDATE turns
                   SET state = ?, assistant_text = ?, status_json = ?, result_json = ?, updated_at = ?
                   WHERE task_id = ?""",
                (
                    record.state,
                    assistant,
                    json.dumps(status),
                    json.dumps(result_data) if result_data else None,
                    now,
                    record.task_id,
                ),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, record.envelope.session_id),
            )

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT s.session_id, s.title, s.created_at, s.updated_at,
                          COUNT(t.task_id) AS turn_count,
                          (SELECT state FROM turns latest
                           WHERE latest.session_id = s.session_id
                           ORDER BY latest.created_at DESC LIMIT 1) AS last_state
                   FROM sessions s
                   LEFT JOIN turns t ON t.session_id = s.session_id
                   WHERE s.archived_at IS NULL
                   GROUP BY s.session_id
                   ORDER BY s.updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as db:
            session = db.execute(
                """SELECT s.session_id, s.title, s.created_at, s.updated_at,
                          COUNT(t.task_id) AS turn_count
                   FROM sessions s LEFT JOIN turns t ON t.session_id = s.session_id
                   WHERE s.session_id = ? AND s.archived_at IS NULL
                   GROUP BY s.session_id""",
                (session_id,),
            ).fetchone()
            if session is None:
                return None
            turns = db.execute(
                """SELECT task_id, user_text, file_paths_json, state, assistant_text,
                          status_json, created_at, updated_at
                   FROM turns WHERE session_id = ? ORDER BY created_at""",
                (session_id,),
            ).fetchall()
        detail = dict(session)
        detail["turns"] = [self._turn(row) for row in turns]
        return detail

    def task_status(self, task_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT status_json FROM turns WHERE task_id = ?", (task_id,)
            ).fetchone()
        if not row or not row["status_json"]:
            return None
        return json.loads(row["status_json"])

    def artifact(self, task_id: str, artifact_id: str) -> Optional[dict[str, Any]]:
        status = self.task_status(task_id)
        if not status:
            return None
        return next(
            (item for item in status.get("artifacts", []) if item.get("artifact_id") == artifact_id),
            None,
        )

    def context(self, session_id: str, max_chars: int = 6000) -> str:
        """Bounded transcript for future real-model planner integration."""
        detail = self.get_session(session_id)
        if not detail:
            return ""
        blocks: list[str] = []
        for turn in reversed(detail["turns"]):
            block = "User: %s" % turn["user_text"]
            if turn["assistant_text"]:
                block += "\nAssistant: %s" % turn["assistant_text"]
            if sum(len(item) for item in blocks) + len(block) > max_chars:
                break
            blocks.append(block)
        return "\n\n".join(reversed(blocks))

    @staticmethod
    def _turn(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "user_text": row["user_text"],
            "file_paths": json.loads(row["file_paths_json"] or "[]"),
            "state": row["state"],
            "assistant_text": row["assistant_text"],
            "status": json.loads(row["status_json"]) if row["status_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
