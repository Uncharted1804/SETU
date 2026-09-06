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
    <section className={`flat-panel ${className}`}>
      <header className="flex items-center justify-between border-b border-edge/60 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          {title}
        </h2>
        {right}
      </header>
      <div className="py-3">{children}</div>
    </section>
  );
}

/** A native disclosure keeps optional evidence keyboard-accessible by default. */
export function Collapsible({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <details className="group border-b border-edge/60">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 py-2.5 marker:content-none">
        <span>
          <span className="text-xs font-semibold text-slate-200">{title}</span>
          <span className="ml-2 text-[11px] text-muted">{description}</span>
        </span>
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          className="h-4 w-4 shrink-0 text-muted transition-transform group-open:rotate-180"
        >
          <path d="m7 10 5 5 5-5" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
        </svg>
      </summary>
      <div className="pb-3">{children}</div>
    </details>
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
