/**
 * The SSE hook.  OWNER: P5.
 *
 * Everything on screen is driven by events the backend actually emitted.  There
 * is no timer pretending work happened: if the checklist ticks, a step_done
 * arrived; if the retry badge shows "attempt 2/4", an attempt event carried it.
 *
 * Reconnection: EventSource retries on its own and sends Last-Event-ID, and the
 * backend replays from that seq.  We also pass `last_event_id` explicitly so a
 * manual reconnect resumes at the same place.  Closing the stream does not
 * cancel the task.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { EventType, SetuEvent } from "./types";

/**
 * The backend sets an SSE `event:` name on every message (it mirrors `type`, so
 * a consumer can listen per-type).  A named SSE event does NOT fire
 * `onmessage` - the browser dispatches it to a listener registered under that
 * name.  So we register one listener per type; without this the stream connects
 * and delivers nothing, which looks exactly like a broken backend.
 */
const EVENT_TYPES: EventType[] = [
  "route",
  "plan",
  "step_start",
  "token",
  "step_done",
  "attempt",
  "escalate",
  "artifact",
  "audit",
  "error",
  "state",
  "approval_request",
  "approval_resolved",
  "quarantine",
  "done",
];

export interface StreamState {
  events: SetuEvent[];
  connected: boolean;
  error: string | null;
}

export function useTaskStream(taskId: string | null) {
  const [state, setState] = useState<StreamState>({
    events: [],
    connected: false,
    error: null,
  });
  const lastSeq = useRef(0);
  const sourceRef = useRef<EventSource | null>(null);
  /** Set once `done` arrives, so the server closing a finished stream is not
   *  reported to the user as an interruption. */
  const finished = useRef(false);

  const close = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    setState((s) => ({ ...s, connected: false }));
  }, []);

  useEffect(() => {
    if (!taskId) {
      close();
      setState({ events: [], connected: false, error: null });
      lastSeq.current = 0;
      return;
    }

    lastSeq.current = 0;
    finished.current = false;
    setState({ events: [], connected: false, error: null });

    const url = `${api.streamUrl(taskId)}?last_event_id=0`;
    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => setState((s) => ({ ...s, connected: true, error: null }));

    const handle = (raw: MessageEvent) => {
      let event: SetuEvent;
      try {
        event = JSON.parse(raw.data) as SetuEvent;
      } catch {
        return;
      }
      if (event.seq <= lastSeq.current) return; // replayed duplicate
      lastSeq.current = event.seq;
      setState((s) => ({ ...s, connected: true, error: null, events: [...s.events, event] }));
      if (event.type === "done") {
        finished.current = true;
        source.close();
        sourceRef.current = null;
        setState((s) => ({ ...s, connected: false, error: null }));
      }
    };

    source.onmessage = handle; // unnamed events, if the server ever sends any
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, handle as EventListener);
    }

    source.onerror = () => {
      if (finished.current) {
        // Normal end-of-stream: the server closed after `done`.
        setState((s) => ({ ...s, connected: false, error: null }));
        return;
      }
      // EventSource reconnects by itself; surface the gap rather than hiding it.
      setState((s) => ({
        ...s,
        connected: false,
        error: "stream interrupted - reconnecting (the task keeps running)",
      }));
    };

    return () => {
      for (const type of EVENT_TYPES) {
        source.removeEventListener(type, handle as EventListener);
      }
      source.close();
      sourceRef.current = null;
    };
  }, [taskId, close]);

  return { ...state, close };
}
