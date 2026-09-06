/** The SETU research-ledger shell. API and orchestration state stay in App. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import type { ArtifactRef, SessionDetail, SessionSummary, TaskStatus } from "../types";
import { AuditPanel, NetworkPanel } from "./proof";
import { Tag } from "./common";

export type Theme = "light" | "dark";

export function StudioLayout({
  history,
  conversation,
  inspector,
  historyOpen,
  inspectorOpen,
  historyCollapsed,
  inspectorCollapsed,
  closePanels,
}: {
  history: ReactNode;
  conversation: ReactNode;
  inspector: ReactNode;
  historyOpen: boolean;
  inspectorOpen: boolean;
  historyCollapsed: boolean;
  inspectorCollapsed: boolean;
  closePanels: () => void;
}) {
  return (
    <main className={`studio-grid ${historyCollapsed ? "history-collapsed" : ""} ${inspectorCollapsed ? "inspector-collapsed" : ""}`}>
      {(historyOpen || inspectorOpen) && (
        <button className="mobile-scrim" onClick={closePanels} aria-label="Close side panel" />
      )}
      <aside className={`history-rail ${historyOpen ? "is-open" : ""}`}>{history}</aside>
      <section className="conversation-pane">{conversation}</section>
      <aside className={`inspector-rail ${inspectorOpen ? "is-open" : ""}`}>{inspector}</aside>
    </main>
  );
}

export function SessionSidebar({
  sessions,
  loading,
  activeId,
  busy,
  collapsed,
  onNew,
  onSelect,
  onToggle,
}: {
  sessions: SessionSummary[];
  loading: boolean;
  activeId: string | null;
  busy: boolean;
  collapsed: boolean;
  onNew: () => void;
  onSelect: (sessionId: string) => void;
  onToggle: () => void;
}) {
  const groups = groupSessions(sessions);
  return (
    <div className="rail-inner history-inner">
      <div className="rail-compact" aria-hidden={!collapsed}>
        <button className="rail-icon" type="button" onClick={onToggle} aria-label="Expand conversation history" title="Expand history ([)">
          <HistoryIcon />
        </button>
        <button className="rail-icon rail-new" type="button" onClick={onNew} disabled={busy} aria-label="New conversation" title="New conversation">
          <PlusIcon />
        </button>
      </div>
      <div className="brand-lockup">
        <div>
          <strong>SETU</strong>
          <span>Local research</span>
        </div>
        <button className="rail-toggle" type="button" onClick={onToggle} aria-label="Collapse conversation history" title="Collapse history ([)">
          <CollapseLeftIcon />
        </button>
      </div>

      <button className="new-thread" type="button" onClick={onNew} disabled={busy}>
        <PlusIcon />
        New conversation
      </button>

      <nav className="session-index" aria-label="Conversation history">
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {[0, 1, 2].map((row) => (
              <span key={row} className="skeleton-line" style={{ height: "2.1rem" }} />
            ))}
          </div>
        )}
        {!loading && sessions.length === 0 && <p className="rail-empty">Your conversations will collect here.</p>}
        {!loading && Object.entries(groups).map(([label, items]) => (
          <section key={label} className="session-group">
            <h2>{label}</h2>
            {items.map((session) => (
              <button
                key={session.session_id}
                type="button"
                className={`session-row ${session.session_id === activeId ? "active" : ""}`}
                onClick={() => onSelect(session.session_id)}
              >
                <span className="thread-marker" aria-hidden="true" />
                <span className="session-copy">
                  <strong>{session.title}</strong>
                  <small>
                    {formatTime(session.updated_at)}, {session.turn_count} {session.turn_count === 1 ? "turn" : "turns"}
                  </small>
                </span>
              </button>
            ))}
          </section>
        ))}
      </nav>
      <p className="sovereignty-note"><LockIcon /> Stored on this machine</p>
    </div>
  );
}

export function ConversationHeader({
  session,
  mockMode,
  theme,
  onThemeChange,
  onOpenHistory,
  onOpenInspector,
}: {
  session: SessionDetail | null;
  mockMode: boolean | null;
  theme: Theme;
  onThemeChange: () => void;
  onOpenHistory: () => void;
  onOpenInspector: () => void;
}) {
  return (
    <header className="conversation-header">
      <button className="mobile-tool history-mobile-tool" onClick={onOpenHistory} aria-label="Open conversation history">
        <HistoryIcon />
      </button>
      <div className="conversation-heading">
        <h1>{session?.title ?? "Untitled thread"}</h1>
        <p>
          {session ? formatLongDate(session.updated_at) : "Local research workspace"}
          {mockMode && <span className="mock-note"> — simulated run</span>}
        </p>
      </div>
      <div className="header-actions">
        {mockMode === null && <Tag tone="bad">offline</Tag>}
        <button
          className="header-tool"
          type="button"
          onClick={onThemeChange}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} appearance`}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
        <button className="mobile-tool inspector-mobile-tool" onClick={onOpenInspector} aria-label="Open network and audit">
          <PulseIcon />
        </button>
      </div>
    </header>
  );
}

export function EmptyChat() {
  return (
    <div className="welcome">
      <h2>What can I help with?</h2>
    </div>
  );
}

export function TranscriptSkeleton() {
  return (
    <div className="empty-thread" aria-hidden="true">
      <span className="skeleton-line" style={{ display: "block", width: "60%", height: "1.75rem", marginBottom: "var(--space-4)" }} />
      <span className="skeleton-line" style={{ display: "block", width: "90%", height: "0.9rem", marginBottom: "var(--space-2)" }} />
      <span className="skeleton-line" style={{ display: "block", width: "72%", height: "0.9rem" }} />
    </div>
  );
}

export function UserTurn({ text, attachments }: { text: string; attachments: string[] }) {
  return (
    <article className="turn user-turn">
      <div className="user-bubble">
        <p>{text}</p>
        {attachments.length > 0 && (
          <ul className="inline-files">
            {attachments.map((path) => <li key={path}>{fileName(path)}</li>)}
          </ul>
        )}
      </div>
    </article>
  );
}

export function AssistantTurn({ text }: { text: string }) {
  return (
    <article className="turn assistant-turn">
      <p>{text}</p>
    </article>
  );
}

export function ActiveTask({ children }: { children: ReactNode }) {
  return <div className="active-task">{children}</div>;
}

export function TaskStateLine({
  status,
  terminal,
  onCancel,
}: {
  status: TaskStatus | null;
  terminal: boolean;
  onCancel: () => void;
}) {
  const state = status?.state ?? "preparing";
  return (
    <div className="task-state-line" aria-live="polite">
      <span className={`live-dot ${terminal ? "settled" : ""}`} />
      <strong>{terminal ? "Finished" : "Working"}</strong>
      <span className="task-state-detail">{state.replaceAll("_", " ")}</span>
      {!terminal && status && <button className="btn-ghost btn-sm" onClick={onCancel}>Cancel</button>}
    </div>
  );
}

export function ChatComposer({
  text,
  attachments,
  artifacts,
  busy,
  disabled,
  error,
  detached,
  centered = false,
  onTextChange,
  onUpload,
  onRemoveAttachment,
  onSubmit,
}: {
  text: string;
  attachments: string[];
  artifacts: ArtifactRef[];
  busy: boolean;
  disabled: boolean;
  error: string | null;
  detached: boolean;
  centered?: boolean;
  onTextChange: (text: string) => void;
  onUpload: (files: FileList | null) => void;
  onRemoveAttachment: (path: string) => void;
  onSubmit: () => void;
}) {
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!artifactsOpen) return;
    const close = (event: KeyboardEvent) => event.key === "Escape" && setArtifactsOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [artifactsOpen]);

  // Auto-grow with input size up to a limit (like Gemini / ChatGPT)
  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    const maxHeight = 160; // 10rem max limit
    const scrollH = node.scrollHeight;
    if (!text.trim()) {
      node.style.height = "26px";
      node.style.overflowY = "hidden";
    } else {
      const targetHeight = Math.min(Math.max(scrollH, 26), maxHeight);
      node.style.height = `${targetHeight}px`;
      node.style.overflowY = scrollH > maxHeight ? "auto" : "hidden";
    }
  }, [text]);

  const submitOnShortcut = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!busy && !disabled && text.trim()) onSubmit();
    }
  };

  return (
    <footer className={`composer-dock ${detached ? "detached" : ""} ${centered ? "centered" : ""}`}>
      <div className="composer-wrap">
        {artifactsOpen && (
          <div className="artifact-tray">
            <div className="artifact-heading">
              <div><strong>Artifacts</strong><span>{artifacts.length} from this thread</span></div>
              <button onClick={() => setArtifactsOpen(false)} aria-label="Close artifacts">×</button>
            </div>
            {artifacts.length === 0 ? (
              <p className="artifact-empty">Generated files will appear here.</p>
            ) : (
              <ul>
                {artifacts.map((artifact) => (
                  <li key={artifact.artifact_id}>
                    <FileIcon />
                    <span><strong>{artifact.name}</strong><small>{(artifact.size_bytes / 1024).toFixed(1)} kB</small></span>
                    <a href={api.artifactUrl(artifact.task_id, artifact.artifact_id)} download={artifact.name}>Download</a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {attachments.length > 0 && (
          <ul className="composer-files" aria-label="Files ready to send">
            {attachments.map((path) => (
              <li key={path}>
                <span>{fileName(path)}</span>
                <button onClick={() => onRemoveAttachment(path)} aria-label={`Remove ${fileName(path)}`}>×</button>
              </li>
            ))}
          </ul>
        )}

        <div className="composer-input">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            onKeyDown={submitOnShortcut}
            rows={1}
            placeholder={disabled ? "Waiting for the current run to finish…" : "Message SETU"}
            aria-label="Message SETU"
            disabled={disabled}
          />
          <div className="composer-actions">
            <label className="icon-action" title="Attach files">
              <PaperclipIcon />
              <span className="sr-only">Attach files</span>
              <input type="file" multiple onChange={(event) => onUpload(event.target.files)} />
            </label>
            <button
              className={`icon-action ${artifactsOpen ? "active" : ""}`}
              onClick={() => setArtifactsOpen((open) => !open)}
              aria-expanded={artifactsOpen}
              aria-label={`Files produced in this conversation (${artifacts.length})`}
              title="Files produced in this conversation"
            >
              <ArchiveIcon />
              {artifacts.length > 0 && <span className="artifact-count">{artifacts.length}</span>}
            </button>
            <button
              type="button"
              className="icon-action"
              onClick={() => setExpanded(true)}
              aria-label="Expand prompt editor"
              title="Expand editor (view / edit large prompt)"
            >
              <MaximizeIcon />
            </button>
            <button
              className="send-action"
              onClick={onSubmit}
              disabled={busy || disabled || !text.trim()}
              aria-label="Send message"
            >
              <ArrowIcon />
            </button>
          </div>
        </div>
        {error && <p className="composer-error">{error}</p>}
        <p className="composer-footnote">Runs locally on this machine. Nothing is sent anywhere.</p>

        {/* Modal for enlarged / expanded text editor */}
        {expanded && (
          <div className="modal-scrim" onClick={() => setExpanded(false)}>
            <div className="expanded-composer-card" onClick={(e) => e.stopPropagation()}>
              <div className="expanded-composer-header">
                <div>
                  <h3>Expanded Prompt</h3>
                  <span>{text.length} characters · {text.trim() ? text.trim().split(/\s+/).length : 0} words</span>
                </div>
                <button
                  type="button"
                  className="icon-action"
                  onClick={() => setExpanded(false)}
                  aria-label="Close expanded view"
                  title="Close expanded view"
                >
                  <MinimizeIcon />
                </button>
              </div>
              <textarea
                autoFocus
                className="expanded-composer-textarea"
                value={text}
                onChange={(e) => onTextChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    if (!busy && !disabled && text.trim()) {
                      setExpanded(false);
                      onSubmit();
                    }
                  } else if (e.key === "Escape") {
                    setExpanded(false);
                  }
                }}
                placeholder={disabled ? "Waiting for the current run to finish…" : "Type your message or prompt for SETU…"}
              />
              <div className="expanded-composer-footer">
                <span className="text-2xs text-muted">Ctrl+Enter to send · Esc to close</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setExpanded(false)}
                  >
                    Done
                  </button>
                  <button
                    type="button"
                    className="btn-primary btn-sm"
                    disabled={busy || disabled || !text.trim()}
                    onClick={() => {
                      setExpanded(false);
                      onSubmit();
                    }}
                  >
                    Send message
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </footer>
  );
}

export function InspectorRail({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <div className="rail-inner inspector-inner">
      <div className="proof-compact" aria-hidden={!collapsed}>
        <button className="rail-icon" type="button" onClick={onToggle} aria-label="Expand proof panel" title="Expand proof panel">
          <ProofIcon />
        </button>
      </div>
      <div className="inspector-title">
        <span>Proof</span><small>Local session</small>
        <button className="rail-toggle" type="button" onClick={onToggle} aria-label="Collapse proof panel" title="Collapse proof panel">
          <CollapseRightIcon />
        </button>
      </div>
      <details open>
        <summary><span><PulseIcon /> Network posture</span><ChevronIcon /></summary>
        <div className="inspector-content"><NetworkPanel /></div>
      </details>
      <details>
        <summary><span><AuditIcon /> Audit trail</span><ChevronIcon /></summary>
        <div className="inspector-content"><AuditPanel /></div>
      </details>
    </div>
  );
}

function groupSessions(sessions: SessionSummary[]): Record<string, SessionSummary[]> {
  const groups: Record<string, SessionSummary[]> = {};
  const now = new Date();
  for (const session of sessions) {
    const date = new Date(session.updated_at);
    const days = Math.floor((startOfDay(now).getTime() - startOfDay(date).getTime()) / 86_400_000);
    const label = days === 0 ? "Today" : days === 1 ? "Yesterday" : days < 7 ? "Previous seven days" : "Earlier";
    (groups[label] ??= []).push(session);
  }
  return groups;
}

function startOfDay(date: Date) { return new Date(date.getFullYear(), date.getMonth(), date.getDate()); }
function formatTime(value: string) { return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value)); }
function formatLongDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function fileName(path: string) { return path.split("/").pop() ?? path; }

function Svg({ children }: { children: ReactNode }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
}
function PlusIcon() { return <Svg><path d="M12 5v14M5 12h14" /></Svg>; }
function LockIcon() { return <Svg><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></Svg>; }
function HistoryIcon() { return <Svg><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></Svg>; }
function CollapseLeftIcon() { return <Svg><path d="M15 18l-6-6 6-6" /><path d="M20 5v14" /></Svg>; }
function CollapseRightIcon() { return <Svg><path d="m9 18 6-6-6-6" /><path d="M4 5v14" /></Svg>; }
function ProofIcon() { return <Svg><path d="M12 3 4 6v5c0 5.1 3.4 8.5 8 10 4.6-1.5 8-4.9 8-10V6z" /><path d="m9 12 2 2 4-4" /></Svg>; }
function PulseIcon() { return <Svg><path d="M3 12h4l2-6 4 12 2-6h6" /></Svg>; }
function AuditIcon() { return <Svg><path d="M7 3h10v4H7zM5 5H3v16h18V5h-2M7 12h10M7 16h7" /></Svg>; }
function ChevronIcon() { return <Svg><path d="m7 10 5 5 5-5" /></Svg>; }
function SunIcon() { return <Svg><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Svg>; }
function MoonIcon() { return <Svg><path d="M20.8 15.2A8.5 8.5 0 0 1 8.8 3.2a8.5 8.5 0 1 0 12 12Z" /></Svg>; }
function PaperclipIcon() { return <Svg><path d="m20.5 11.5-8.8 8.8a6 6 0 0 1-8.5-8.5l9.5-9.5a4 4 0 1 1 5.7 5.7l-9.5 9.5a2 2 0 1 1-2.8-2.8l8.8-8.8" /></Svg>; }
function ArchiveIcon() { return <Svg><path d="M4 7h16v13H4zM3 3h18v4H3zM9 11h6" /></Svg>; }
function FileIcon() { return <Svg><path d="M6 2h8l4 4v16H6zM14 2v5h5" /></Svg>; }
function ArrowIcon() { return <Svg><path d="m5 12 7-7 7 7M12 5v14" /></Svg>; }
function MaximizeIcon() { return <Svg><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></Svg>; }
function MinimizeIcon() { return <Svg><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" /></Svg>; }
