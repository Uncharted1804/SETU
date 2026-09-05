"""
Task lifecycle and the in-memory task store.  OWNER: P1.

Single process, single user, one dict.  Deliberately not Redis and not a
database: SETU is one operator on one workstation, and adding a broker would add
a service to the sovereignty story for no benefit.  RESTART RECOVERY IS OUT OF
SCOPE for this scaffold - if uvicorn restarts, in-flight tasks are gone.  That is
documented, not hidden (docs/DECISIONS.md D-007).

TERMINAL vs RESUMABLE (contracts.py):
  terminal   completed failed rejected needs_human_review cancelled
  resumable  awaiting_approval

A task in a terminal state never runs again.  That is the mechanism preventing a
duplicate approval from executing the same task twice.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..contracts import (
    TERMINAL_STATES,
    ApprovalRequest,
    ArtifactRef,
    Observation,
    Plan,
    RouterDecision,
    StructuredError,
    TaskEnvelope,
    TaskState,
    TaskStatus,
)


def new_task_id() -> str:
    return "t_" + secrets.token_hex(6)


def new_session_id() -> str:
    return "s_" + secrets.token_hex(6)


def new_approval_id() -> str:
    return "ap_" + secrets.token_hex(6)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class TaskRecord:
    """Everything known about one task.  Mutated only by the executor and API."""

    envelope: TaskEnvelope
    state: TaskState = "created"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    router_decision: Optional[RouterDecision] = None
    plan: Optional[Plan] = None
    observations: list[Observation] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    iterations_used: int = 0
    pending_approval: Optional[ApprovalRequest] = None
    #: Resolved by the API when a decision arrives; awaited by the executor.
    approval_future: Optional[asyncio.Future] = None
    error: Optional[StructuredError] = None
    escalation_reason: Optional[str] = None
    scenario: Optional[str] = None
    mock_mode: bool = True
    #: The asyncio task running the executor, so cancellation can reach it.
    runner: Optional[asyncio.Task] = None

    @property
    def task_id(self) -> str:
        return self.envelope.task_id

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def touch(self) -> None:
        self.updated_at = _now()

    def set_state(self, state: TaskState) -> None:
        self.state = state
        self.touch()

    def to_status(self, max_iterations: int) -> TaskStatus:
        return TaskStatus(
            task_id=self.task_id,
            session_id=self.envelope.session_id,
            state=self.state,
            created_at=self.created_at,
            updated_at=self.updated_at,
            text=self.envelope.text,
            router_decision=self.router_decision,
            plan=self.plan,
            iterations_used=self.iterations_used,
            max_iterations=max_iterations,
            pending_approval=self.pending_approval,
            artifacts=list(self.artifacts),
            error=self.error,
            mock_mode=self.mock_mode,
        )


class TaskStore:
    """In-memory, single process.  Bounded so a long demo cannot grow forever."""

    def __init__(self, limit: int = 200) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._order: list[str] = []
        self._limit = limit

    def create(self, envelope: TaskEnvelope, mock_mode: bool) -> TaskRecord:
        record = TaskRecord(envelope=envelope, mock_mode=mock_mode)
        self._tasks[record.task_id] = record
        self._order.append(record.task_id)
        while len(self._order) > self._limit:
            evicted = self._order.pop(0)
            self._tasks.pop(evicted, None)
        return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def require(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise KeyError(task_id)
        return record

    def find_by_approval(self, approval_id: str) -> Optional[TaskRecord]:
        for record in self._tasks.values():
            if record.pending_approval and record.pending_approval.approval_id == approval_id:
                return record
        return None

    def recent(self, limit: int = 25) -> list[TaskRecord]:
        return [self._tasks[t] for t in self._order[-limit:][::-1] if t in self._tasks]

    def artifact(self, task_id: str, artifact_id: str) -> Optional[ArtifactRef]:
        """Task-scoped lookup.  An artifact id from another task does not resolve."""
        record = self.get(task_id)
        if record is None:
            return None
        for ref in record.artifacts:
            if ref.artifact_id == artifact_id:
                return ref
        return None
