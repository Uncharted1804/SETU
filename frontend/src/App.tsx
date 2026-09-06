/** SETU conversation orchestration and durable session state. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { PlanChecklist, RouterBanner, StreamView } from "./components/task";
import {
  ActiveTask,
  AssistantTurn,
  ChatComposer,
  ConversationHeader,
  EmptyChat,
  InspectorRail,
  SessionSidebar,
  StudioLayout,
  TaskStateLine,
  TranscriptSkeleton,
  UserTurn,
  type Theme,
} from "./components/workspace";
import type { ApprovalRequest, ArtifactRef, SessionDetail, SessionSummary, TaskStatus } from "./types";
import { TERMINAL_STATES } from "./types";
import { useTaskStream } from "./useTaskStream";

function initialTheme(): Theme {
  // index.html sets this attribute synchronously, before paint, from
  // localStorage or prefers-color-scheme, so there is no flash of the wrong theme.
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [ready, setReady] = useState(false);
  const [mockMode, setMockMode] = useState<boolean | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [text, setText] = useState("");
  const [uploads, setUploads] = useState<string[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerDetached, setComposerDetached] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [decidingChoice, setDecidingChoice] = useState<"approve" | "reject" | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const previousScrollTop = useRef(0);

  const stream = useTaskStream(taskId);
  const terminal = status ? TERMINAL_STATES.includes(status.state) : false;
  const taskRunning = Boolean(taskId && (!status || !terminal));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("setu-theme", theme);
    } catch {
      // Private browsing or storage disabled: theme still applies for this load.
    }
  }, [theme]);

  useEffect(() => {
    const toggleHistory = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key !== "[" || event.metaKey || event.ctrlKey || event.altKey || target?.matches("input, textarea, select, [contenteditable='true']")) return;
      event.preventDefault();
      setHistoryCollapsed((current) => !current);
    };
    window.addEventListener("keydown", toggleHistory);
    return () => window.removeEventListener("keydown", toggleHistory);
  }, []);

  const refreshSessions = useCallback(async () => {
    const next = await api.sessions();
    setSessions(next);
  }, []);

  const loadCurrentSession = useCallback(async () => {
    const current = await api.currentSession();
    setActiveSession(current);
    if (!current) {
      setTaskId(null);
      setStatus(null);
      return;
    }
    const running = [...current.turns].reverse().find((turn) => !TERMINAL_STATES.includes(turn.state));
    setTaskId(running?.task_id ?? null);
    setStatus(running?.status ?? null);
  }, []);

  useEffect(() => {
    void Promise.all([api.health(), api.sessions(), api.currentSession()])
      .then(([health, savedSessions, current]) => {
        setMockMode(health.mock_mode);
        setSessions(savedSessions);
        setActiveSession(current);
        const running = current
          ? [...current.turns].reverse().find((turn) => !TERMINAL_STATES.includes(turn.state))
          : undefined;
        setTaskId(running?.task_id ?? null);
        setStatus(running?.status ?? null);
      })
      .catch((reason) => {
        setMockMode(null);
        setError(String(reason));
      })
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    let refreshedTerminal = false;
    const refresh = async () => {
      try {
        const next = await api.task(taskId);
        if (!alive) return;
        setStatus(next);
        if (TERMINAL_STATES.includes(next.state) && !refreshedTerminal) {
          refreshedTerminal = true;
          await Promise.all([loadCurrentSession(), refreshSessions()]);
        }
      } catch {
        // A historical task may no longer have a live SSE stream; its session snapshot remains.
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, terminal ? 2500 : 700);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [taskId, terminal, stream.events.length, loadCurrentSession, refreshSessions]);

  const submit = useCallback(async () => {
    const taskText = text.trim();
    if (!taskText || taskRunning) return;
    setError(null);
    setBusy(true);
    try {
      const created = await api.createTask(taskText, uploads);
      setText("");
      setUploads([]);
      setTaskId(created.task_id);
      setStatus(null);
      await Promise.all([loadCurrentSession(), refreshSessions()]);
      requestAnimationFrame(() => {
        const node = transcriptRef.current;
        if (node) node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
      });
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }, [text, uploads, taskRunning, loadCurrentSession, refreshSessions]);

  const upload = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const stored = await Promise.all(Array.from(files).map((file) => api.upload(file)));
      setUploads((current) => [...current, ...stored.map((item) => item.path)]);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!status?.pending_approval || status.pending_approval.decided) {
      setDecidingChoice(null);
    }
  }, [status?.pending_approval]);

  const decide = useCallback(async (approval: ApprovalRequest, approved: boolean) => {
    if (!taskId) return;
    setBusy(true);
    try {
      await api.approve(taskId, approval.approval_id, approved);
    } catch (reason) {
      setError(String(reason));
      setDecidingChoice(null);
    } finally {
      setBusy(false);
    }
  }, [taskId]);

  const beginNewSession = useCallback(async () => {
    setBusy(true);
    try {
      const fresh = await api.newSession();
      setActiveSession(fresh);
      setTaskId(null);
      setStatus(null);
      setText("");
      setUploads([]);
      setHistoryOpen(false);
      await refreshSessions();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }, [refreshSessions]);

  const selectSession = useCallback(async (sessionId: string) => {
    setBusy(true);
    try {
      const selected = await api.activateSession(sessionId);
      setActiveSession(selected);
      const running = [...selected.turns].reverse().find((turn) => !TERMINAL_STATES.includes(turn.state));
      setTaskId(running?.task_id ?? null);
      setStatus(running?.status ?? null);
      setHistoryOpen(false);
      setError(null);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }, []);

  const onTranscriptScroll = () => {
    const node = transcriptRef.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.clientHeight - node.scrollTop;
    const scrollingUp = node.scrollTop < previousScrollTop.current;
    if (distanceFromBottom < 72) setComposerDetached(false);
    else if (scrollingUp) setComposerDetached(true);
    previousScrollTop.current = node.scrollTop;
  };

  const turns = activeSession?.turns ?? [];
  const composerProps = {
    text,
    attachments: uploads,
    busy,
    disabled: taskRunning,
    error,
    detached: composerDetached,
    onTextChange: setText,
    onUpload: (files: FileList | null) => void upload(files),
    onRemoveAttachment: (path: string) => setUploads((current) => current.filter((item) => item !== path)),
    onSubmit: () => void submit(),
  };

  const artifacts = useMemo(() => {
    const collected = new Map<string, ArtifactRef>();
    for (const turn of activeSession?.turns ?? []) {
      for (const artifact of turn.status?.artifacts ?? []) collected.set(artifact.artifact_id, artifact);
    }
    for (const artifact of status?.artifacts ?? []) collected.set(artifact.artifact_id, artifact);
    return [...collected.values()];
  }, [activeSession, status]);

  return (
    <div className="app-root">
      <StudioLayout
        history={
          <SessionSidebar
            sessions={sessions}
            loading={!ready}
            activeId={activeSession?.session_id ?? null}
            busy={busy}
            collapsed={historyCollapsed}
            onNew={() => void beginNewSession()}
            onSelect={(id) => void selectSession(id)}
            onToggle={() => setHistoryCollapsed((current) => !current)}
          />
        }
        conversation={
          <>
            <ConversationHeader
              session={activeSession}
              mockMode={mockMode}
              theme={theme}
              onThemeChange={() => setTheme((current) => current === "dark" ? "light" : "dark")}
              onOpenHistory={() => setHistoryOpen(true)}
              onOpenInspector={() => setInspectorOpen(true)}
            />
            {ready && turns.length === 0 ? (
              <div className="welcome-stage">
                <EmptyChat />
                <ChatComposer {...composerProps} artifacts={artifacts} centered />
              </div>
            ) : (
              <>
                <div className="transcript" ref={transcriptRef} onScroll={onTranscriptScroll}>
                  {!ready && <TranscriptSkeleton />}
                  {turns.map((turn) => (
                    <div className="thread-pair" key={turn.task_id}>
                      <UserTurn text={turn.user_text} attachments={turn.file_paths} />
                      {turn.assistant_text && <AssistantTurn text={turn.assistant_text} />}
                      {turn.task_id === taskId && (
                        <ActiveTask>
                          <TaskStateLine status={status} terminal={terminal} onCancel={() => void api.cancel(turn.task_id)} />
                          <RouterBanner decision={status?.router_decision ?? null} />
                          <details
                            className="work-disclosure"
                            open={Boolean(status?.pending_approval && !status.pending_approval.decided) || undefined}
                          >
                            <summary>
                              <span className="disclosure-label">
                                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="m9 6 6 6-6 6" />
                                </svg>
                                Plan
                              </span>
                              {status?.pending_approval && !status.pending_approval.decided ? (
                                <div className="plan-approval-pill" onClick={(e) => e.stopPropagation()}>
                                  <button
                                    type="button"
                                    className={`pill-action pill-approve ${decidingChoice === "approve" ? "is-selected" : ""}`}
                                    disabled={busy}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDecidingChoice("approve");
                                      decide(status.pending_approval!, true);
                                    }}
                                  >
                                    Approve
                                  </button>
                                  <button
                                    type="button"
                                    className={`pill-action pill-reject ${decidingChoice === "reject" ? "is-selected" : ""}`}
                                    disabled={busy}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDecidingChoice("reject");
                                      decide(status.pending_approval!, false);
                                    }}
                                  >
                                    Reject
                                  </button>
                                </div>
                              ) : (
                                <span>{status?.plan?.steps.length ?? 0} steps</span>
                              )}
                            </summary>
                            <div className="work-disclosure-body">
                              <PlanChecklist status={status} />
                            </div>
                          </details>
                          <StreamView events={stream.events} connected={stream.connected} error={stream.error} />
                        </ActiveTask>
                      )}
                    </div>
                  ))}
                </div>
                <ChatComposer {...composerProps} artifacts={artifacts} />
              </>
            )}
          </>
        }
        inspector={<InspectorRail collapsed={inspectorCollapsed} onToggle={() => setInspectorCollapsed((current) => !current)} />}
        historyOpen={historyOpen}
        inspectorOpen={inspectorOpen}
        historyCollapsed={historyCollapsed}
        inspectorCollapsed={inspectorCollapsed}
        closePanels={() => { setHistoryOpen(false); setInspectorOpen(false); }}
      />
    </div>
  );
}
