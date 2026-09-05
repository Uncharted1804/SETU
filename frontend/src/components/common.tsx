/** Small shared pieces.  OWNER: P5. */

import type { ReactNode } from "react";

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-edge bg-panel ${className}`}>
      <header className="flex items-center justify-between border-b border-edge px-3 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          {title}
        </h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Tag({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-edge text-muted",
    good: "bg-good/15 text-good",
    warn: "bg-warn/15 text-warn",
    bad: "bg-bad/15 text-bad",
    accent: "bg-accent/15 text-accent",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** Every simulated value on screen carries this. */
export function SimulatedTag() {
  return <Tag tone="warn">simulated</Tag>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-xs text-muted">{children}</p>;
}

export function KeyValue({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-xs">
      <span className="text-muted">{k}</span>
      <span className="font-mono text-right text-slate-300">{v}</span>
    </div>
  );
}

/**
 * Model output is rendered as PLAIN TEXT, never as HTML.  Nothing a model
 * produces is trusted to be markup, so there is no dangerouslySetInnerHTML
 * anywhere in this application.
 */
export function PlainText({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">
      {text}
    </div>
  );
}
