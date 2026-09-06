/**
 * Task surfaces: router banner, plan checklist with the approval gate, the live
 * stream, and artifact downloads.  OWNER: P5.
 *
 * Everything here renders backend events.  Nothing animates on a timer.
 */

import { useMemo } from "react";
import { api } from "../api";
import type {
  ApprovalRequest,
  ArtifactRef,
  RouterDecision,
  SetuEvent,
  TaskStatus,
} from "../types";
import { Empty, Panel, PlainText, SimulatedTag, Tag } from "./common";

/** Proof of R4: the decision, the reason and the latency, above every response. */
export function RouterBanner({ decision }: { decision: RouterDecision | null }) {
  if (!decision) {
    return (
      <div className="route-line text-xs text-muted">
        no routing decision yet
      </div>
    );
  }
  return (
    <div className="route-line">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="text-muted">workflow selected</span>
        <Tag tone="accent">{decision.agent}</Tag>
        <span className="text-muted">·</span>
        <span className="text-slate-300">{decision.reason}</span>
        <span className="text-muted">·</span>
        <span className="font-mono text-muted">{decision.rule_id}</span>
        <span className="text-muted">·</span>
        <span className="font-mono text-muted">{decision.latency_ms.toFixed(2)} ms</span>
      </div>
    </div>
  );
}

const STATUS_TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "accent"> = {
  pending: "neutral",
  running: "accent",
  done: "good",
  failed: "bad",
  skipped: "warn",
};

export function PlanChecklist({
  status,
  onDecision,
  busy,
}: {
  status: TaskStatus | null;
  onDecision: (approval: ApprovalRequest, approved: boolean) => void;
  busy: boolean;
}) {
  const plan = status?.plan ?? null;
  const pending = status?.pending_approval ?? null;
  const undecided = pending && !pending.decided ? pending : null;

  return (
    <Panel
      title="Plan"
      right={
        status ? (
          <span className="font-mono text-[10px] text-muted">
            iteration {status.iterations_used}/{status.max_iterations}
            {plan && plan.revisions > 0 ? ` · ${plan.revisions} revision(s)` : ""}
          </span>
        ) : undefined
      }
    >
      {!plan || plan.steps.length === 0 ? (
        <Empty>no plan proposed yet</Empty>
      ) : (
        <ol className="space-y-1">
          {plan.steps.map((step) => (
            <li
              key={`${step.n}-${step.target}`}
              className="flex items-start gap-2 rounded border border-edge/60 px-2 py-1.5"
            >
              <span className="mt-0.5 font-mono text-[10px] text-muted">{step.n}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-200">
                    {step.kind === "agent" ? "agent" : "tool"}:{step.target}
                  </span>
                  <Tag tone={STATUS_TONE[step.status] ?? "neutral"}>{step.status}</Tag>
                </div>
                <p className="mt-0.5 text-[11px] text-muted">{step.why}</p>
              </div>
            </li>
          ))}
        </ol>
      )}

      {undecided && (
        <div className="mt-3 rounded border border-warn/50 bg-warn/5 p-3">
          <div className="flex items-center gap-2">
            <Tag tone="warn">
              {undecided.kind === "write" ? "write approval" : "approval required"}
            </Tag>
            <span className="text-xs text-slate-300">{undecided.summary}</span>
          </div>

          {undecided.kind === "write" && (
            <div className="mt-2">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">
                content to be committed to {undecided.target_path}
              </p>
              <pre className="max-h-52 overflow-auto rounded bg-ink p-2 font-mono text-[11px] text-slate-300">
                {undecided.preview ?? "(no textual preview available)"}
              </pre>
            </div>
          )}

          <div className="mt-3 flex gap-2">
            <button
              disabled={busy}
              onClick={() => onDecision(undecided, true)}
              className="rounded bg-good/20 px-3 py-1 text-xs font-medium text-good hover:bg-good/30 disabled:opacity-40"
            >
              Approve
            </button>
            <button
              disabled={busy}
              onClick={() => onDecision(undecided, false)}
              className="rounded bg-bad/20 px-3 py-1 text-xs font-medium text-bad hover:bg-bad/30 disabled:opacity-40"
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </Panel>
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

  return (
    <Panel
      title="Execution"
      right={
        <span className="text-[10px] text-muted">
          {connected ? "streaming" : "not connected"} · {events.length} events
        </span>
      }
    >
      {error && (
        <p className="mb-2 rounded border border-warn/40 bg-warn/5 px-2 py-1 text-[11px] text-warn">
          {error}
        </p>
      )}
      {visible.length === 0 ? (
        <Empty>submit a task to see live execution</Empty>
      ) : (
        <ul className="space-y-1">
          {visible.map((event) => {
            const line = eventLine(event);
            return (
              <li key={event.seq} className="flex gap-2 border-b border-edge/40 py-1 last:border-0">
                <span className="w-8 shrink-0 font-mono text-[10px] text-muted">
                  {event.seq}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Tag tone={line.tone}>{line.label}</Tag>
                    {line.sim && <SimulatedTag />}
                  </div>
                  {line.body && (
                    <p className="mt-0.5 whitespace-pre-wrap break-words text-[11px] text-slate-300">
                      {line.body}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {tokens && (
        <div className="mt-3 rounded border border-edge bg-ink p-2">
          <PlainText text={tokens} />
        </div>
      )}
    </Panel>
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
                  <span className="truncate font-mono text-xs text-slate-200">{a.name}</span>
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
