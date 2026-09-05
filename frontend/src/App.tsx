/**
 * SETU workbench.  OWNER: P5.
 *
 * Layout: prompt + execution on the left, proof surfaces on the right.  The
 * MOCK MODE banner is unmissable when the backend is running fixtures, because
 * a demo that cannot tell simulated output from real output is worse than no
 * demo.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AuditPanel, ModelRegistryPanel, NetworkPanel } from "./components/proof";
import { Artifacts, PlanChecklist, RouterBanner, StreamView } from "./components/task";
import { Panel, Tag } from "./components/common";
import type { ApprovalRequest, MockScenario, TaskStatus } from "./types";
import { TERMINAL_STATES } from "./types";
import { useTaskStream } from "./useTaskStream";

export default function App() {
  const [mockMode, setMockMode] = useState<boolean | null>(null);
  const [version, setVersion] = useState("");
  const [scenarios, setScenarios] = useState<MockScenario[]>([]);
  const [scenario, setScenario] = useState<string>("");

  const [text, setText] = useState("Draft an approval note from this inspection report.");
  const [uploads, setUploads] = useState<string[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stream = useTaskStream(taskId);

  useEffect(() => {
    void api
      .health()
      .then((h) => {
        setMockMode(h.mock_mode);
        setVersion(h.version);
        if (h.mock_mode) void api.scenarios().then(setScenarios).catch(() => setScenarios([]));
      })
      .catch(() => setMockMode(null));
  }, []);

  /** Status is refreshed on every event, so the checklist and approvals follow
   *  the backend rather than a local guess about what happened. */
  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    const refresh = async () => {
      try {
        const next = await api.task(taskId);
        if (alive) setStatus(next);
      } catch {
        /* task list is bounded; a dropped task simply stops updating */
      }
    };
    void refresh();
    const timer = setInterval(refresh, 700);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [taskId, stream.events.length]);

  const submit = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const created = await api.createTask(text, uploads, scenario || undefined);
      setTaskId(created.task_id);
      setStatus(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [text, uploads, scenario]);

  const onUpload = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const stored: string[] = [];
      for (const file of Array.from(files)) {
        const result = await api.upload(file);
        stored.push(result.path);
      }
      setUploads((prev) => [...prev, ...stored]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const decide = useCallback(
    async (approval: ApprovalRequest, approved: boolean) => {
      if (!taskId) return;
      setBusy(true);
      try {
        await api.approve(taskId, approval.approval_id, approved);
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [taskId],
  );

  const terminal = status ? TERMINAL_STATES.includes(status.state) : false;

  return (
    <div className="min-h-full">
      {mockMode && (
        <div className="border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-center text-xs font-semibold tracking-wide text-warn">
          MOCK MODE — agents, retrieval and sandbox execution return deterministic
          fixtures. No model is loaded and no container is started.
        </div>
      )}

      <header className="flex items-center justify-between border-b border-edge px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold tracking-tight text-slate-100">SETU</h1>
          <span className="text-xs text-muted">
            sovereign on-premise agentic workbench
          </span>
        </div>
        <div className="flex items-center gap-2">
          {mockMode === false && <Tag tone="good">real mode</Tag>}
          {mockMode === null && <Tag tone="bad">backend unreachable</Tag>}
          <span className="font-mono text-[10px] text-muted">{version}</span>
        </div>
      </header>

      <main className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-3">
          <Panel title="Task">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              className="w-full resize-y rounded border border-edge bg-ink px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-accent"
              placeholder="Describe the task…"
            />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label className="cursor-pointer rounded border border-edge px-2 py-1 text-xs text-slate-300 hover:border-accent">
                Attach file
                <input
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => void onUpload(e.target.files)}
                />
              </label>

              {scenarios.length > 0 && (
                <select
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value)}
                  className="rounded border border-edge bg-ink px-2 py-1 text-xs text-slate-300"
                >
                  <option value="">scenario: auto-select</option>
                  {scenarios.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.key} — {s.title}
                    </option>
                  ))}
                </select>
              )}

              <button
                onClick={() => void submit()}
                disabled={busy || !text.trim()}
                className="rounded bg-accent/20 px-3 py-1 text-xs font-medium text-accent hover:bg-accent/30 disabled:opacity-40"
              >
                Run
              </button>

              {taskId && !terminal && (
                <button
                  onClick={() => void api.cancel(taskId)}
                  className="rounded border border-edge px-2 py-1 text-xs text-muted hover:border-bad hover:text-bad"
                >
                  Cancel
                </button>
              )}

              {status && (
                <Tag
                  tone={
                    status.state === "completed"
                      ? "good"
                      : status.state === "needs_human_review" || status.state === "rejected"
                        ? "warn"
                        : status.state === "failed"
                          ? "bad"
                          : "accent"
                  }
                >
                  {status.state}
                </Tag>
              )}
            </div>

            {uploads.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {uploads.map((path) => (
                  <li key={path} className="font-mono text-[10px] text-muted">
                    {path}
                  </li>
                ))}
              </ul>
            )}

            {error && <p className="mt-2 text-xs text-bad">{error}</p>}
          </Panel>

          <RouterBanner decision={status?.router_decision ?? null} />

          {status?.state === "needs_human_review" && (
            <div className="rounded-lg border border-bad/50 bg-bad/5 px-3 py-2 text-xs text-bad">
              Needs human review — the system did not finalise this task. A person makes
              the call.
            </div>
          )}

          <PlanChecklist status={status} onDecision={decide} busy={busy} />
          <StreamView events={stream.events} connected={stream.connected} error={stream.error} />
          <Artifacts taskId={taskId} artifacts={status?.artifacts ?? []} />
        </div>

        <div className="space-y-3">
          <NetworkPanel />
          <ModelRegistryPanel />
          <AuditPanel />
        </div>
      </main>
    </div>
  );
}
