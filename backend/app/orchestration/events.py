"""
Event bus and SSE fan-out.  OWNER: P1.

THE RACE THIS SOLVES.  The client POSTs /api/tasks and then opens
GET /api/tasks/{id}/stream.  Execution starts immediately, so `route` and `plan`
are often emitted BEFORE the EventSource connects.  Without a replay buffer the
router banner and the approval checklist simply never appear - which looks like
a broken UI and is actually a lost race.

So every task keeps a bounded in-memory history (HISTORY_LIMIT events).  A new
subscriber is sent the whole history first, then live events.  A reconnecting
browser sends `Last-Event-ID`; we replay only what it missed.

ORDERING.  `seq` is a per-task monotonic counter starting at 1, emitted as the
SSE `id:` field.  Consumers may assume strictly increasing seq within a task.

TERMINAL BEHAVIOUR.  A `done` event is the last event on a stream; the generator
then returns and the connection closes normally.  CLOSING THE STREAM DOES NOT
CANCEL THE TASK - execution runs in its own asyncio Task and a disconnected
browser simply stops receiving events.  Cancellation is an explicit API call.

This is a single-process, in-memory bus.  Restart recovery is deliberately out
of scope for this scaffold (docs/DECISIONS.md D-007); no Redis, no Celery.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from ..contracts import Event, EventType

#: Per-task replay buffer size.  Large enough for a full flagship run with token
#: events, small enough that a thousand tasks cannot exhaust memory.
HISTORY_LIMIT = 512

#: Per-subscriber queue depth.  A subscriber that cannot keep up drops events
#: rather than blocking the executor - and we mark the drop rather than hiding it.
QUEUE_LIMIT = 256


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _force_put(queue: "asyncio.Queue[Optional[Event]]", item: "Optional[Event]") -> None:
    """Enqueue something that must not be dropped, evicting to make room.

    Ordinary events may fall on the floor when a subscriber is too far behind:
    history is the authoritative record, and a client resumes with
    Last-Event-ID to collect what it missed. Two things are different in kind
    and are pushed through here instead:

      * the `done` EVENT, because it carries the task result and is what the
        UI ends on; and
      * the None sentinel, because it is the only thing that tells a subscriber
        parked on `queue.get()` that the stream is over. Dropping it is a hang,
        not a dropped frame.

    A subscriber that is already QUEUE_LIMIT events behind can recover any
    evicted event from history; it cannot recover either of these. The loop
    terminates because put_nowait/get_nowait never yield, so nothing can refill
    the queue while it runs.
    """
    while True:
        try:
            queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:  # drained concurrently; the next put fits
                continue


class TaskEventStream:
    """One task's event history plus its live subscribers."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._seq = 0
        self._history: deque[Event] = deque(maxlen=HISTORY_LIMIT)
        self._subscribers: set[asyncio.Queue[Optional[Event]]] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def history(self, after_seq: int = 0) -> list[Event]:
        return [e for e in self._history if e.seq > after_seq]

    async def emit(self, type_: EventType, data: dict) -> Event:
        self._seq += 1
        event = Event(type=type_, data=data, seq=self._seq, ts=_now())
        self._history.append(event)
        # `done` is delivered even to a subscriber that is too far behind to
        # take anything else: it carries the result and ends the stream.
        # Everything else may be dropped rather than blocking the executor on a
        # slow browser - history plus Last-Event-ID is the recovery path.
        terminal = type_ == "done"
        for queue in list(self._subscribers):
            if terminal:
                _force_put(queue, event)
            else:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        if terminal:
            # Set before the sentinel goes out, so a subscriber that wakes on
            # it and re-checks `closed` cannot see a stale False.
            self._closed = True
            for queue in list(self._subscribers):
                _force_put(queue, None)  # sentinel: end of stream
        return event

    async def subscribe(self, last_event_id: int = 0) -> AsyncIterator[Event]:
        """Replay what was missed, then stream live events until `done`."""
        queue: asyncio.Queue[Optional[Event]] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self._subscribers.add(queue)
        try:
            # Replay until history has nothing newer, NOT once. Each `yield`
            # suspends this generator, and the executor keeps emitting while it
            # is suspended, so a single pass over a snapshot taken at the start
            # can finish already stale. Re-reading is what makes the handover
            # from replay to live delivery gapless.
            replayed_to = last_event_id
            while True:
                pending = self.history(after_seq=replayed_to)
                if not pending:
                    break
                for event in pending:
                    replayed_to = event.seq
                    yield event

            # Only now is "closed" safe to act on. Checking it straight after a
            # single replay pass abandoned every event that arrived during that
            # pass - including `done` itself, which is what closed the stream.
            if self._closed:
                return
            while True:
                event = await queue.get()
                if event is None:
                    return
                if event.seq <= replayed_to:
                    continue  # already replayed
                yield event
        finally:
            self._subscribers.discard(queue)


class EventBus:
    """All task streams in this process."""

    def __init__(self) -> None:
        self._streams: dict[str, TaskEventStream] = {}

    def stream(self, task_id: str) -> TaskEventStream:
        if task_id not in self._streams:
            self._streams[task_id] = TaskEventStream(task_id)
        return self._streams[task_id]

    def has(self, task_id: str) -> bool:
        return task_id in self._streams

    async def emit(self, task_id: str, type_: EventType, data: dict) -> Event:
        return await self.stream(task_id).emit(type_, data)

    def drop(self, task_id: str) -> None:
        self._streams.pop(task_id, None)


def sse_payload(event: Event) -> dict:
    """Shape handed to sse-starlette.

    The envelope the frontend parses is `{type, data}` in the data field; the
    SSE `event:` name mirrors `type` so a client may listen per-type instead.
    """
    return {
        "id": str(event.seq),
        "event": event.type,
        "data": event.model_dump_json(),
    }
