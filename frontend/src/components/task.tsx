/**
 * Task surfaces: router banner, plan checklist with the approval gate, the live
 * stream, and artifact downloads.  OWNER: P5.
 *
 * Everything here renders backend events.  Nothing animates on a timer.
 */

import { useMemo } from "react";
import { api } from "../api";
import type {
  ArtifactRef,
  RouterDecision,
  SetuEvent,
  TaskStatus,
} from "../types";
import { Empty, Panel, PlainText, SimulatedTag } from "./common";

/** Proof of R4: the decision, the reason and the latency, above every response. */
export function RouterBanner({ decision }: { decision: RouterDecision | null }) {
  if (!decision) return <p className="route-line">Choosing a workflow…</p>;
  return (
    <p className="route-line">
      <span className="route-agent">{decision.agent}</span>
      {decision.reason}
      <span className="route-meta">{decision.rule_id}, {decision.latency_ms.toFixed(2)} ms</span>
    </p>
  );
}

export function PlanChecklist({
  status,
}: {
  status: TaskStatus | null;
}) {
  const plan = status?.plan ?? null;
  const pending = status?.pending_approval ?? null;
  const undecided = pending && !pending.decided ? pending : null;

  return (
    <div className="plan-body">
      {!plan || plan.steps.length === 0 ? (
        <p className="work-empty">No plan proposed yet.</p>
      ) : (
        <ol className="plan-steps">
          {plan.steps.map((step) => (
            <li key={`${step.n}-${step.target}`} className={`plan-step is-${step.status}`}>
              <span className="step-dot" aria-hidden="true" />
              <div>
                <p className="step-title">
                  {step.target}
                  <span className="step-status">{step.status}</span>
                </p>
                <p className="step-why">{step.why}</p>
              </div>
            </li>
          ))}
        </ol>
      )}

      {undecided && undecided.kind === "write" && (
        <div className="approval-preview">
          <p>Content to be written to {undecided.target_path}</p>
          <pre>{undecided.preview ?? "(no textual preview available)"}</pre>
        </div>
      )}
    </div>
  );
}

function eventLine(event: SetuEvent): { label: string; body: string; tone: "neutral" | "good" | "warn" | "bad" | "accent"; sim: boolean } {
  const d = event.data as Record<string, any>;
  switch (event.type) {
    case "step_start":
      return {
        label: `step ${d.step?.n} start`,
        body: `${d.step?.kind}:${d.step?.target} — ${d.step?.why}`,
        tone: "accent",
        sim: false,
      };
    case "step_done":
      return {
        label: `step ${d.step_n} done`,
        body:
          `${d.target} — ${d.summary}` +
          (typeof d.confidence === "number" ? ` (confidence ${d.confidence.toFixed(2)})` : ""),
        tone: d.ok ? "good" : "bad",
        sim: Boolean(d.simulated),
      };
    case "attempt":
      return {
        label: `attempt ${d.attempt}/${d.max_attempts}`,
        body:
          `${d.agent} confidence ${Number(d.confidence).toFixed(2)}` +
          (d.feedback_injected ? " · feeding failure back into the retry" : "") +
          (d.failure_reason ? `\n${d.failure_reason}` : ""),
        tone: d.feedback_injected ? "warn" : "neutral",
        sim: Boolean(d.simulated),
      };
    case "escalate":
      return { label: "escalated", body: String(d.reason ?? ""), tone: "bad", sim: false };
    case "error":
      return {
        label: `error ${d.code ?? ""}`,
        body: String(d.message ?? ""),
        tone: "bad",
        sim: false,
      };
    case "quarantine":
      return {
        label: "chunk quarantined",
        body: `${d?.metadata?.source_file ?? "unknown"} p.${d?.metadata?.page ?? "?"} — instruction-shaped text, surfaced and not used as context`,
        tone: "bad",
        sim: false,
      };
    case "approval_request":
      return { label: "approval requested", body: String(d.summary ?? ""), tone: "warn", sim: false };
    case "approval_resolved":
      return {
        label: "approval resolved",
        body: d.approved ? "approved by operator" : "REJECTED by operator",
        tone: d.approved ? "good" : "bad",
        sim: false,
      };
    case "route":
      return {
        label: "routed",
        body: `${d.agent} workflow selected (${d.rule_id})`,
        tone: "accent",
        sim: false,
      };
    case "plan":
      return {
        label: "plan proposed",
        body: `${(d.steps as unknown[])?.length ?? 0} steps`,
        tone: "neutral",
        sim: false,
      };
    case "artifact":
      return { label: "artifact", body: String(d.name ?? ""), tone: "good", sim: Boolean(d.simulated) };
    case "state":
      return { label: "state", body: String(d.state ?? ""), tone: "neutral", sim: false };
    case "done":
      return {
        label: "finished",
        body: `${d.state} — ${d.summary}`,
        tone: d.state === "completed" ? "good" : "warn",
        sim: Boolean(d.mock_mode),
      };
    default:
      return { label: event.type, body: "", tone: "neutral", sim: false };
  }
}

export function StreamView({
  events,
  connected,
  error,
}: {
  events: SetuEvent[];
  connected: boolean;
  error: string | null;
}) {
  const visible = useMemo(
    () => events.filter((e) => e.type !== "audit" && e.type !== "token"),
    [events],
  );
  const tokens = useMemo(
    () => events.filter((e) => e.type === "token").map((e) => String(e.data.text ?? "")).join(""),
    [events],
  );

  const isReconnecting = !connected && Boolean(error && error.includes("reconnecting"));
  const realError = error && !error.includes("reconnecting") ? error : null;

  return (
    <details className="work-disclosure" open>
      <summary>
        <span className="disclosure-label">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="m9 6 6 6-6 6" />
          </svg>
          Activity
        </span>
        <span className="activity-summary-meta">
          {isReconnecting && (
            <span className="reconnecting-spinner" title="Stream reconnecting in background (task continues running)">
              <svg className="spinner-icon" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            </span>
          )}
          <span>{visible.length} steps</span>
        </span>
      </summary>
      <div className="work-disclosure-body">
        {realError && <p className="work-note">{realError}</p>}
        {visible.length === 0 ? (
          <p className="work-empty">Nothing has run yet.</p>
        ) : (
          <ul className="stream-list">
            {visible.map((event) => {
              const line = eventLine(event);
              return (
                <li key={event.seq} className={`stream-row tone-${line.tone}`}>
                  <span className="stream-dot" aria-hidden="true" />
                  <div>
                    <p className="stream-label">
                      {line.label}
                      {line.sim && <span className="stream-sim">simulated</span>}
                    </p>
                    {line.body && <p className="stream-body">{line.body}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {tokens && (
          <div className="stream-tokens">
            <PlainText text={tokens} />
          </div>
        )}
      </div>
    </details>
  );
}

export function Artifacts({
  taskId,
  artifacts,
}: {
  taskId: string | null;
  artifacts: ArtifactRef[];
}) {
  return (
    <Panel title="Artifacts">
      {artifacts.length === 0 || !taskId ? (
        <Empty>no files produced yet</Empty>
      ) : (
        <ul className="space-y-1">
          {artifacts.map((a) => (
            <li
              key={a.artifact_id}
              className="flex items-center justify-between gap-2 rounded border border-edge/60 px-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs text-slate-900 dark:text-slate-100">{a.name}</span>
                  {a.simulated && <SimulatedTag />}
                </div>
                <p className="truncate font-mono text-[10px] text-muted">
                  {(a.size_bytes / 1024).toFixed(1)} kB · {a.sha256.slice(0, 22)}…
                </p>
              </div>
              <a
                href={api.artifactUrl(taskId, a.artifact_id)}
                download={a.name}
                className="shrink-0 rounded bg-accent/20 px-2 py-1 text-[11px] font-medium text-accent hover:bg-accent/30"
              >
                Download
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
