r"""
TaskEventStream replay/live handover.  OWNER: P1.

These drive `TaskEventStream` directly - no HTTP, no TestClient, no executor.
That is the point. The end-to-end symptom is an SSE assertion in test_api.py
(`types[-1] == "done"` seeing `"step_done"`), but that test passes about 97% of
the time even on the broken code, so it cannot be trusted to guard anything.
Here the interleaving is FORCED, so the tests fail deterministically on the
unfixed implementation.

The bug they guard: `subscribe()` snapshotted history once and yielded it one
event at a time. Every `yield` suspends the generator, and the executor keeps
emitting while it is suspended. When a task finished during that replay, `done`
set `_closed`, and the `if self._closed: return` immediately after the replay
loop abandoned every event that had arrived in the meantime - `done` included.
The subscriber's last event was whatever preceded them, typically `step_done`.

This is NOT the `_finalise()` ordering bug fixed earlier. That one made a
terminal state visible before its events reached history, and its own
regression test kept passing while the full suite still failed intermittently -
which is what pointed here. See docs/DECISIONS.md D-021.
"""

from __future__ import annotations

import asyncio

import pytest

from app.orchestration.events import QUEUE_LIMIT, TaskEventStream


def _types(events):
    return [e.type for e in events]


def _seqs(events):
    return [e.seq for e in events]


async def _drain(agen, timeout=2.0):
    """Consume an async generator to exhaustion, failing loudly on a stall."""
    out = []
    while True:
        try:
            out.append(await asyncio.wait_for(agen.__anext__(), timeout=timeout))
        except StopAsyncIteration:
            return out
        except asyncio.TimeoutError:
            pytest.fail(
                "subscription stalled: no further event and no end-of-stream "
                "after %ss (delivered so far: %s)" % (timeout, _types(out))
            )


# --------------------------------------------------------------------------
# The replay/live handover
# --------------------------------------------------------------------------


def test_events_emitted_during_replay_are_still_delivered():
    """The exact interleaving behind the intermittent SSE failure.

    A late subscriber begins replaying history; the task finishes while that
    replay is suspended between yields. Everything emitted in that window must
    still reach the subscriber, `done` last.
    """

    async def scenario():
        stream = TaskEventStream("t_replay")
        for i in range(3):
            await stream.emit("step_done", {"i": i})

        agen = stream.subscribe(last_event_id=0).__aiter__()
        # Consume ONE replayed event: the generator is now parked mid-replay,
        # exactly where the SSE route leaves it between yields.
        received = [await agen.__anext__()]

        # The task finishes while the generator is suspended.
        await stream.emit("audit", {})
        await stream.emit("state", {"state": "needs_human_review"})
        await stream.emit("done", {"state": "needs_human_review"})

        received += await _drain(agen)
        return received

    received = asyncio.run(scenario())

    assert _seqs(received) == [1, 2, 3, 4, 5, 6], (
        "events emitted during replay were dropped; delivered %s" % _seqs(received)
    )
    assert _types(received)[-1] == "done", (
        "the subscriber never saw `done`; last event was %r" % _types(received)[-1]
    )


def test_a_task_that_finishes_before_the_first_yield_still_replays_fully():
    """The already-closed case: subscribe after everything, get everything."""

    async def scenario():
        stream = TaskEventStream("t_closed")
        await stream.emit("route", {})
        await stream.emit("step_done", {})
        await stream.emit("done", {})

        return await _drain(stream.subscribe(last_event_id=0).__aiter__())

    received = asyncio.run(scenario())

    assert _types(received) == ["route", "step_done", "done"]


def test_a_resuming_subscriber_gets_only_what_it_missed_including_late_events():
    """Last-Event-ID resume, with the same mid-replay finish."""

    async def scenario():
        stream = TaskEventStream("t_resume")
        for _ in range(4):
            await stream.emit("attempt", {})

        # Client already saw seq 1 and 2.
        agen = stream.subscribe(last_event_id=2).__aiter__()
        received = [await agen.__anext__()]  # seq 3, parked mid-replay
        await stream.emit("done", {})
        received += await _drain(agen)
        return received

    received = asyncio.run(scenario())

    assert _seqs(received) == [3, 4, 5], "resume dropped events: %s" % _seqs(received)
    assert _types(received)[-1] == "done"


def test_no_event_is_delivered_twice_across_the_handover():
    """The drain must not resend what the replay already yielded."""

    async def scenario():
        stream = TaskEventStream("t_dupes")
        for _ in range(3):
            await stream.emit("attempt", {})
        agen = stream.subscribe(last_event_id=0).__aiter__()
        received = [await agen.__anext__()]
        await stream.emit("attempt", {})
        await stream.emit("done", {})
        received += await _drain(agen)
        return received

    received = asyncio.run(scenario())
    seqs = _seqs(received)

    assert seqs == sorted(seqs), "events arrived out of order: %s" % seqs
    assert len(seqs) == len(set(seqs)), "an event was delivered twice: %s" % seqs


def test_live_events_after_the_handover_still_arrive():
    """The queue loop after the replay is untouched by the fix."""

    async def scenario():
        stream = TaskEventStream("t_live")
        await stream.emit("route", {})
        agen = stream.subscribe(last_event_id=0).__aiter__()
        received = [await agen.__anext__()]  # seq 1

        async def consume():
            return await _drain(agen)

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0)  # let the consumer park on queue.get()
        await stream.emit("step_start", {})
        await stream.emit("done", {})
        received += await asyncio.wait_for(task, timeout=5)
        return received

    received = asyncio.run(scenario())

    assert _types(received) == ["route", "step_start", "done"]


# --------------------------------------------------------------------------
# The end-of-stream sentinel
# --------------------------------------------------------------------------


def test_a_full_queue_still_receives_end_of_stream():
    """A backed-up subscriber must terminate, not hang.

    `emit` may drop a real event when a subscriber is too far behind - history
    is authoritative and a client resumes with Last-Event-ID. It must never
    drop the sentinel, which is the only thing that tells a subscriber parked
    on `queue.get()` that the task is over.
    """

    async def scenario():
        stream = TaskEventStream("t_full")
        agen = stream.subscribe(last_event_id=0).__aiter__()

        async def consume():
            return await _drain(agen, timeout=5.0)

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0)  # consumer parked on queue.get()

        # Overfill: far more than the subscriber can hold.
        for _ in range(QUEUE_LIMIT + 20):
            await stream.emit("attempt", {})
        await stream.emit("done", {})

        return await asyncio.wait_for(task, timeout=10)

    received = asyncio.run(scenario())

    assert _types(received)[-1] == "done", (
        "the sentinel was dropped, so the stream never ended cleanly; "
        "last delivered was %r" % (_types(received)[-1] if received else None)
    )


def test_closed_is_set_before_the_sentinel_is_delivered():
    """Ordering inside emit(): a subscriber that wakes on the sentinel and
    re-checks `closed` must see True, not a stale False."""

    async def scenario():
        stream = TaskEventStream("t_order")
        await stream.emit("done", {})
        return stream.closed

    assert asyncio.run(scenario()) is True
